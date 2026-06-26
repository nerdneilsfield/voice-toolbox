from pathlib import Path

import pytest

from voice_toolbox.providers import FakeProvider, ProviderRegistry
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest


def test_registry_blocks_unsupported_tts_mode() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])
    request = TTSRequest(
        provider_id="fake",
        mode=TTSMode.DESIGN,
        voice_description="warm voice",
        optimize_text_preview=True,
    )

    with pytest.raises(UnsupportedCapability):
        registry.ensure_tts_capability("fake", request)


def test_registry_allows_supported_tts_mode() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])
    request = TTSRequest(
        provider_id="fake",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="Mia",
    )

    provider = registry.ensure_tts_capability("fake", request)

    assert provider.id == "fake"


def test_registry_blocks_unsupported_asr() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])

    with pytest.raises(UnsupportedCapability):
        registry.ensure_asr_capability("fake")


def test_fake_provider_accepts_empty_capabilities() -> None:
    provider = FakeProvider(capabilities=set())
    registry = ProviderRegistry([provider])
    request = TTSRequest(
        provider_id="fake",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="Mia",
    )

    assert provider.capabilities() == set()
    with pytest.raises(UnsupportedCapability):
        registry.ensure_tts_capability("fake", request)
    with pytest.raises(UnsupportedCapability):
        registry.ensure_asr_capability("fake")


def test_fake_provider_models_follow_capabilities() -> None:
    assert FakeProvider(capabilities=set()).list_models() == []
    assert {model.capability for model in FakeProvider().list_models()} == {
        "asr",
        "tts.builtin",
        "tts.clone",
        "tts.design",
    }


def test_registry_raises_for_unknown_provider() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])
    request = TTSRequest(
        provider_id="missing",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="Mia",
    )

    with pytest.raises(ProviderError, match="unknown provider"):
        registry.ensure_tts_capability("missing", request)


def test_fake_provider_returns_deterministic_artifacts(tmp_path: Path) -> None:
    provider = FakeProvider(capabilities={"tts.builtin", "asr"}, artifact_root=tmp_path)
    tts_request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")
    asr_request = ASRRequest(
        audio_path=tmp_path / "input.wav",
        mime_type="audio/wav",
        raw_byte_size=10,
        base64_size=16,
    )

    audio = provider.synthesize(tts_request)
    transcript = provider.transcribe(asr_request)

    assert audio.id == "fake-tts-1"
    assert audio.provider_id == "fake"
    assert audio.path.read_bytes() == b"FAKE_WAV:hello:Mia"
    assert transcript.id == "fake-asr-2"
    assert transcript.provider_id == "fake"
    assert transcript.path.read_text(encoding="utf-8") == "fake transcript"


def test_fake_provider_repeated_artifacts_do_not_collide(tmp_path: Path) -> None:
    provider = FakeProvider(capabilities={"tts.builtin", "asr"}, artifact_root=tmp_path)
    tts_request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")
    asr_request = ASRRequest(
        audio_path=tmp_path / "input.wav",
        mime_type="audio/wav",
        raw_byte_size=10,
        base64_size=16,
    )

    first_audio = provider.synthesize(tts_request)
    second_audio = provider.synthesize(tts_request)
    first_transcript = provider.transcribe(asr_request)
    second_transcript = provider.transcribe(asr_request)

    assert first_audio.id == "fake-tts-1"
    assert second_audio.id == "fake-tts-2"
    assert first_transcript.id == "fake-asr-3"
    assert second_transcript.id == "fake-asr-4"
    assert len({first_audio.path, second_audio.path, first_transcript.path, second_transcript.path}) == 4


def test_fake_provider_closes_implicit_temp_root() -> None:
    provider = FakeProvider()
    artifact_root = provider.artifact_root

    assert artifact_root.exists()
    provider.close()

    assert not artifact_root.exists()
