from __future__ import annotations

from pathlib import Path

import pytest

from voice_toolbox.config import (
    ConfigError,
    load_app_config,
    mask_api_key_preview,
    preview_config_path,
    replay_config_warnings,
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
    assert provider.default_models.tts_builtin == "s1"
    assert provider.default_models.tts_design == "s1-design"
    assert provider.default_models.tts_clone == "s1-clone"
    assert provider.default_models.asr == "fish-audio-asr"
    assert {model.capability for model in provider.models} == {
        "tts.builtin",
        "tts.design",
        "tts.clone",
        "asr.transcribe",
    }
    assert provider.default_voice == "e58b0d7efca34eb38d5c4985e378abcb"
