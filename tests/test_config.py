from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from voice_toolbox.config import (
    ConfigError,
    load_app_config,
    mask_api_key_preview,
    preview_config_path,
    replay_config_warnings,
)
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import MLX_AUDIO_MODEL_ALIASES
from voice_toolbox.models import (
    ModelInfo,
    ProviderOptionOverride,
    ProviderOptionSpec,
    VoiceInfo,
)


def test_loads_builtin_default_without_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOICE_TOOLBOX_CONFIG", raising=False)

    config = load_app_config()

    assert config.config_path is None
    assert config.api.host == "127.0.0.1"
    assert config.api.port == 8000
    assert [provider.id for provider in config.providers] == ["mimo"]
    assert config.providers[0].base_url == "https://api.xiaomimimo.com/v1"


def test_explicit_missing_config_path_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.toml"
    monkeypatch.setenv("VOICE_TOOLBOX_CONFIG", str(missing))

    with pytest.raises(ConfigError, match="VOICE_TOOLBOX_CONFIG"):
        load_app_config()


def test_toml_with_empty_providers_falls_back_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIMO_BASE_URL", "https://ignored.example/v1")
    path = tmp_path / "voice_toolbox.toml"
    path.write_text("providers = []\n", encoding="utf-8")

    config = load_app_config(path)

    assert [provider.id for provider in config.providers] == ["mimo"]
    assert "providers is empty" in caplog.text
    assert "ignored env var MIMO_BASE_URL" in caplog.text


def test_configured_provider_overrides_models_and_voices(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[api]
host = "127.0.0.1"
port = 9001

[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"
default_voice = "Mia"

[providers.default_models]
tts_builtin = "custom-tts"

[[providers.models]]
id = "custom-tts"
name = "Custom TTS"
capability = "tts.builtin"

[[providers.voices]]
id = "Mia"
name = "Mia"
language = "en"
gender = "female"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)

    provider = config.providers[0]
    assert provider.id == "mimo-lite"
    assert provider.default_models is not None
    assert provider.default_models.tts_builtin == "custom-tts"
    assert provider.default_models.tts_design is None
    assert [model.id for model in provider.models] == ["custom-tts"]
    assert [voice.id for voice in provider.voices] == ["Mia"]


def test_legacy_env_applies_only_without_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MIMO_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("VOICE_TOOLBOX_API_HOST", "127.0.0.2")
    monkeypatch.setenv("VOICE_TOOLBOX_API_PORT", "9002")

    fallback = load_app_config()

    assert fallback.providers[0].base_url == "https://env.example/v1"
    assert fallback.api.host == "127.0.0.2"
    assert fallback.api.port == 9002

    path = tmp_path / "voice_toolbox.toml"
    path.write_text("[api]\nhost = '127.0.0.1'\nport = 8000\n", encoding="utf-8")
    active = load_app_config(path)

    assert active.providers[0].base_url == "https://api.xiaomimimo.com/v1"
    assert "ignored env var MIMO_BASE_URL" in caplog.text


def test_config_warnings_can_be_replayed_without_duplicate_load_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text("[api]\nhost = '127.0.0.1'\n", encoding="utf-8")
    env = {"MIMO_BASE_URL": "https://env.example/v1"}

    config = load_app_config(path, env_values=env, emit_warnings=False)
    assert caplog.text == ""

    replay_config_warnings(config, env)

    assert caplog.text.count("providers is empty") == 1
    assert caplog.text.count("ignored env var MIMO_BASE_URL") == 1


def test_masked_key_preview_short_boundaries() -> None:
    assert mask_api_key_preview(None, trusted_local=True) is None
    assert mask_api_key_preview("tp-1234", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-123456", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-12345678", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=True) == "tp-...abcd"
    assert mask_api_key_preview("abcdef123456", trusted_local=True) == "...3456"
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=False) == "configured"


def test_config_path_preview() -> None:
    assert preview_config_path(None) == "built-in default"
    assert preview_config_path(Path("/Users/example/voice-toolbox/voice_toolbox.toml")) == (
        "voice-toolbox/voice_toolbox.toml"
    )
    assert preview_config_path(Path("voice_toolbox.toml")) == "voice_toolbox.toml"


def test_validation_rejects_bad_defaults(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://example.test/v1"
api_key_env = "BAD_KEY"
default_voice = "missing"

[providers.default_models]
tts_builtin = "asr-only"

[[providers.models]]
id = "asr-only"
name = "ASR"
capability = "asr.transcribe"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="default_voice|capability"):
        load_app_config(path)


def test_fill_defaults_validation_errors_are_config_errors(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://example.test/v1"
api_key_env = "BAD_KEY"

[[providers.models]]
id = "broken"
name = "Broken"
capability = 123
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_app_config(path)


def test_fallback_bad_env_port_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOICE_TOOLBOX_API_PORT", "not-a-port")

    with pytest.raises(ConfigError, match="not-a-port"):
        load_app_config()


def test_api_port_range_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text("[api]\nport = 70000\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="65535|less than or equal"):
        load_app_config(path)


def test_provider_string_fields_reject_empty_values(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = ""
type = "mimo"
name = ""
base_url = ""
api_key_env = ""
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="at least 1 character"):
        load_app_config(path)


def test_config_rejects_extra_keys_and_insecure_base_url(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[api]
host = "127.0.0.1"
extra = "nope"

[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "http://user:pass@example.test/v1"
api_key_env = "BAD_KEY"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Extra inputs|https"):
        load_app_config(path)


def test_config_error_does_not_echo_secret_base_url(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://user:secret@example.test/v1?token=secret"
api_key_env = "BAD_KEY"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_app_config(path)

    message = str(exc_info.value)
    assert "secret" not in message
    assert "input_value" not in message


def test_config_rejects_model_and_voice_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://example.test/v1"
api_key_env = "BAD_KEY"

[[providers.models]]
id = "m"
name = "M"
capability = "tts.builtin"
extra = "nope"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Extra inputs"):
        load_app_config(path)


def test_config_rejects_base_url_query_and_fragment(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://example.test/v1?token=x#frag"
api_key_env = "BAD_KEY"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="query or fragment"):
        load_app_config(path)


def test_load_app_config_uses_explicit_env_path(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.custom"
    env_path.write_text("MIMO_BASE_URL=https://custom-env.example/v1\n", encoding="utf-8")

    config = load_app_config(env_path=env_path)

    assert config.providers[0].base_url == "https://custom-env.example/v1"


def test_explicit_env_path_does_not_read_cwd_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "voice_toolbox.toml").write_text(
        """
[[providers]]
id = "mimo"
type = "mimo"
name = "MiMo"
base_url = "https://toml.example/v1"
api_key_env = "MIMO_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env.custom"
    env_path.write_text("MIMO_BASE_URL=https://env-path.example/v1\n", encoding="utf-8")

    config = load_app_config(env_path=env_path)

    assert config.providers[0].base_url == "https://env-path.example/v1"


def test_partial_model_fallback_does_not_add_absent_capabilities(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"

[[providers.models]]
id = "custom-tts"
name = "Custom TTS"
capability = "tts.builtin"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    defaults = config.providers[0].default_models

    assert defaults is not None
    assert defaults.tts_builtin == "custom-tts"
    assert defaults.tts_design is None
    assert defaults.tts_clone is None
    assert defaults.asr is None


def test_fish_audio_provider_fills_builtin_defaults(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "fish"
type = "fish_audio"
name = "Fish Audio"
base_url = "https://api.fish.audio"
api_key_env = "FISH_AUDIO_API_KEY"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    provider = config.providers[0]

    assert provider.type == "fish_audio"
    assert provider.default_models is not None
    assert provider.default_models.tts_builtin == "s2.1-pro-free"
    assert provider.default_models.tts_design == "s1-design"
    assert provider.default_models.tts_clone == "s1-clone"
    assert provider.default_models.asr == "fish-audio-asr"
    builtin_models = [m.id for m in provider.models if m.capability == "tts.builtin"]
    clone_models = [m.id for m in provider.models if m.capability == "tts.clone"]
    assert builtin_models == ["s2.1-pro-free", "s2.1-pro", "s2-pro", "s1"]
    assert clone_models == ["s1-clone", "s2.1-pro-clone", "s2-pro-clone"]
    assert {model.capability for model in provider.models} == {
        "tts.builtin",
        "tts.design",
        "tts.clone",
        "asr.transcribe",
    }
    assert provider.default_voice == "e58b0d7efca34eb38d5c4985e378abcb"


def test_openrouter_provider_fills_builtin_defaults(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "openrouter"
type = "openrouter"
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    provider = config.providers[0]

    assert provider.type == "openrouter"
    assert provider.default_models is not None
    assert provider.default_models.tts_builtin == "openai/gpt-4o-mini-tts-2025-12-15"
    assert provider.default_models.tts_design is None
    assert provider.default_models.tts_clone is None
    assert provider.default_models.asr == "openai/whisper-1"
    assert {model.capability for model in provider.models} == {
        "tts.builtin",
        "asr.transcribe",
    }
    assert provider.default_voice == "alloy"


def test_chunking_config_parses_and_validates_cross_field_rules(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[chunking.tts]
mode = "force"
max_chars = 1000
max_chunks = 3
max_text_file_bytes = 4096
silence_ms = 250
repeat_leading_audio_tags = false

[chunking.asr]
mode = "auto"
target_seconds = 20
overlap_ms = 900
max_chunks = 4
max_upload_mb = 10
browser_upload = false
session_ttl_seconds = 120
dedupe_min_chars = 5
dedupe_max_chars = 50

[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)

    assert config.chunking.tts.mode == "force"
    assert config.chunking.tts.max_chars == 1000
    assert config.chunking.tts.repeat_leading_audio_tags is False
    assert config.chunking.asr.browser_upload is False
    assert config.chunking.asr.dedupe_min_chars == 5

    bad_dedupe = path.with_name("bad-dedupe.toml")
    bad_dedupe.write_text(
        """
[chunking.asr]
dedupe_min_chars = 80
dedupe_max_chars = 40

[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="dedupe_min_chars"):
        load_app_config(bad_dedupe)

    bad_overlap = path.with_name("bad-overlap.toml")
    bad_overlap.write_text(
        """
[chunking.asr]
target_seconds = 20
overlap_ms = 10000

[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="overlap_ms"):
        load_app_config(bad_overlap)


def test_config_parses_provider_specs_and_model_overrides(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "tenant-mimo"
type = "mimo"
name = "Tenant MiMo"
base_url = "https://example.test/v1"
api_key_env = "TENANT_MIMO_KEY"

[[providers.options]]
key = "speed"
label = "Speed"
type = "number"
capability = "tts.builtin"
default = 1.0
min_value = 0.5
max_value = 2.0

[[providers.models]]
id = "custom-tts"
name = "Custom TTS"
capability = "tts.builtin"

[[providers.models.options]]
key = "speed"
capability = "tts.builtin"
max_value = 1.5

[[providers.models]]
id = "custom-asr"
name = "Custom ASR"
capability = "asr.transcribe"

[providers.models.transcript_capabilities]
timestamps = true
speakers = false
segments = true
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    provider = config.providers[0]

    assert provider.id == "tenant-mimo"
    assert provider.type == "mimo"
    assert isinstance(provider.options[0], ProviderOptionSpec)
    assert isinstance(provider.models[0].options[0], ProviderOptionOverride)
    assert provider.models[0].options[0].label is None
    assert provider.models[0].options[0].max_value == 1.5
    assert provider.models[1].transcript_capabilities is not None
    assert provider.models[1].transcript_capabilities.timestamps is True


def test_config_rejects_invalid_provider_type_even_when_id_matches(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "mimo"
type = "not_mimo"
name = "Bad"
base_url = "https://example.test/v1"
api_key_env = "BAD_KEY"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="mimo|fish_audio|openrouter"):
        load_app_config(path)


def test_mac_extra_installs_mlx_audio_without_model_specific_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    mac_deps = pyproject["project"]["optional-dependencies"]["mac"]
    joined = "\n".join(mac_deps)

    assert mac_deps == [
        "mlx-audio[tts,stt]>=0.4.4 ; "
        "sys_platform == 'darwin' and platform_machine == 'arm64'"
    ]
    assert "misaki" not in joined
    assert "nagisa" not in joined
    assert "soynlp" not in joined
    assert "onnx" not in joined


def test_mlx_audio_provider_accepts_local_credentials_none() -> None:
    provider = ConfiguredProvider(
        id="mlx-audio",
        type="mlx_audio",
        name="MLX Audio",
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=ProviderDefaultModels(
            tts_builtin="qwen3-tts-0.6b-base",
            tts_clone="qwen3-tts-0.6b-base-clone",
            asr="mlx-community/Qwen3-ASR-0.6B-8bit",
        ),
        models=[
            ModelInfo(id="qwen3-tts-0.6b-base", name="Qwen3 TTS", capability="tts.builtin"),
            ModelInfo(
                id="qwen3-tts-0.6b-base-clone",
                name="Qwen3 TTS Clone",
                capability="tts.clone",
            ),
            ModelInfo(
                id="mlx-community/Qwen3-ASR-0.6B-8bit",
                name="Qwen3 ASR",
                capability="asr.transcribe",
            ),
        ],
        voices=[VoiceInfo(id="Ryan", name="Ryan", language="en", gender="male")],
    )

    assert provider.base_url is None
    assert provider.api_key_env is None


def test_mlx_audio_provider_rejects_local_url_and_key_env() -> None:
    with pytest.raises(ValueError, match="base_url is not used by local provider type mlx_audio"):
        ConfiguredProvider(
            id="mlx-audio",
            type="mlx_audio",
            name="MLX Audio",
            base_url="https://localhost.example",
            api_key_env=None,
        )

    with pytest.raises(ValueError, match="api_key_env is not used by local provider type mlx_audio"):
        ConfiguredProvider(
            id="mlx-audio",
            type="mlx_audio",
            name="MLX Audio",
            base_url=None,
            api_key_env="MLX_AUDIO_API_KEY",
        )


def test_network_provider_still_requires_url_and_key_env() -> None:
    network_provider_base_urls = {
        "mimo": "https://api.xiaomimimo.com/v1",
        "fish_audio": "https://api.fish.audio",
        "openrouter": "https://openrouter.ai/api/v1",
    }

    provider = ConfiguredProvider(
        id="mimo",
        type="mimo",
        name="MiMo",
        base_url=network_provider_base_urls["mimo"],
        api_key_env="  MIMO_API_KEY  ",
    )
    assert provider.api_key_env == "MIMO_API_KEY"

    for provider_type, base_url in network_provider_base_urls.items():
        with pytest.raises(ValueError, match="base_url is required"):
            ConfiguredProvider(
                id=provider_type,
                type=provider_type,
                name=provider_type,
                base_url=None,
                api_key_env="MIMO_API_KEY",
            )

        with pytest.raises(ValueError, match="api_key_env is required"):
            ConfiguredProvider(
                id=provider_type,
                type=provider_type,
                name=provider_type,
                base_url=base_url,
                api_key_env=None,
            )

        for api_key_env in ("", "   "):
            with pytest.raises(ValueError, match="api_key_env must not be empty"):
                ConfiguredProvider(
                    id=provider_type,
                    type=provider_type,
                    name=provider_type,
                    base_url=base_url,
                    api_key_env=api_key_env,
                )


def test_mlx_audio_toml_gets_default_models_and_voices(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    provider = config.providers[0]

    assert provider.default_models is not None
    assert provider.base_url is None
    assert provider.api_key_env is None
    assert provider.default_models.tts_builtin == "qwen3-tts-0.6b-base"
    assert provider.default_models.tts_clone == "qwen3-tts-0.6b-base-clone"
    assert provider.default_models.asr == "mlx-community/Qwen3-ASR-0.6B-8bit"
    assert MLX_AUDIO_MODEL_ALIASES == {
        "qwen3-tts-0.6b-base": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
        "qwen3-tts-0.6b-base-clone": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
        "qwen3-tts-1.7b-base-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        "longcat-audiodit-1b": "mlx-community/LongCat-AudioDiT-1B-bf16",
        "ming-omni-tts-16.8b-a3b": "mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
        "higgs-audio-v3-tts-4b": "bosonai/higgs-audio-v3-tts-4b",
    }

    model_ids = {model.id for model in provider.models}
    assert model_ids >= {
        "qwen3-tts-0.6b-base",
        "qwen3-tts-0.6b-base-clone",
        "qwen3-tts-1.7b-base-8bit",
        "longcat-audiodit-1b",
        "ming-omni-tts-16.8b-a3b",
        "higgs-audio-v3-tts-4b",
        "mlx-community/Qwen3-ASR-0.6B-8bit",
    }
    voice_ids = {voice.id for voice in provider.voices}
    assert voice_ids >= {"Ryan", "Aiden", "Vivian", "Serena", "default"}
    option_keys = {option.key for option in provider.options}
    assert option_keys >= {"lang_code", "temperature", "speed"}
    ming = next(model for model in provider.models if model.id == "ming-omni-tts-16.8b-a3b")
    assert ming.note is not None
    assert "onnx" in ming.note
    assert "safetensors" in ming.note
