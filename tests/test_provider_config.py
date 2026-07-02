from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from voice_toolbox.config import AppConfig, ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ASRRequest, ModelInfo, TTSMode, TTSRequest, VoiceInfo
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.mimo import MIMO_MODELS, MIMO_VOICES, MimoProvider


def _completion() -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(audio=SimpleNamespace(data="V0FW")))]
    )


class RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return _completion()


def _provider_config() -> ConfiguredProvider:
    return ConfiguredProvider(
        id="mimo-sgp",
        type="mimo",
        name="MiMo SGP",
        base_url="https://sgp.example/v1",
        api_key_env="MIMO_SGP_API_KEY",
        default_voice="Mia",
        default_models=ProviderDefaultModels(tts_builtin="custom-tts", asr="custom-asr"),
        models=[
            ModelInfo(id="custom-tts", name="Custom TTS", capability="tts.builtin"),
            ModelInfo(id="custom-asr", name="Custom ASR", capability="asr.transcribe"),
        ],
        voices=[VoiceInfo(id="Mia", name="Mia", language="en", gender="female")],
    )


def test_mimo_provider_uses_configured_identity_models_and_voices(tmp_path: Path) -> None:
    provider = MimoProvider(config=_provider_config(), api_key="secret", artifact_root=tmp_path)

    assert provider.id == "mimo-sgp"
    assert provider.name == "MiMo SGP"
    assert provider.capabilities() == {"tts.builtin", "asr.transcribe"}
    assert [model.id for model in provider.list_models()] == ["custom-tts", "custom-asr"]
    assert [voice.id for voice in provider.list_voices()] == ["Mia"]


def test_mimo_provider_resolves_configured_default_tts_model(tmp_path: Path) -> None:
    completions = RecordingCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = MimoProvider(
        config=_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )

    provider.synthesize(TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia"))

    assert completions.calls[0]["model"] == "custom-tts"


def test_mimo_provider_keeps_base_url_test_seam(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=RecordingCompletions()))

    MimoProvider(
        api_key="secret",
        base_url="https://override.test/v1",
        artifact_root=tmp_path,
        client_factory=factory,
    )

    assert captured["base_url"] == "https://override.test/v1"


def test_mimo_provider_validates_base_url_override_with_config(tmp_path: Path) -> None:
    client = SimpleNamespace(chat=SimpleNamespace(completions=RecordingCompletions()))

    with pytest.raises(ValueError, match="base_url must be an https URL"):
        MimoProvider(
            config=_provider_config(),
            base_url="http://bad.example",
            artifact_root=tmp_path,
            client=client,
        )


def test_defaults_reexport_for_existing_tests() -> None:
    assert {model.id for model in MIMO_MODELS} >= {"mimo-v2.5-tts", "mimo-v2.5-asr"}
    assert {voice.id for voice in MIMO_VOICES} >= {"mimo_default", "Mia"}


def test_asr_model_can_be_omitted(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")
    request = ASRRequest(
        model=None,
        audio_path=audio,
        mime_type="audio/wav",
        raw_byte_size=16,
        base64_size=24,
    )

    assert request.model is None


def test_build_provider_registry_uses_config_and_env_values(tmp_path: Path) -> None:
    registry = build_provider_registry(
        config=AppConfig(config_path=None, providers=[_provider_config()]),
        artifact_root=tmp_path,
        env_values={"MIMO_SGP_API_KEY": "secret"},
    )

    provider = registry.get("mimo-sgp")

    assert isinstance(provider, MimoProvider)
    assert provider.id == "mimo-sgp"
