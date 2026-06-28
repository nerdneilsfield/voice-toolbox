from __future__ import annotations

import base64
import json
from pathlib import Path

import msgpack
import pytest

from voice_toolbox.config import AppConfig
from voice_toolbox.defaults import make_default_fish_audio_provider_config
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.fish_audio import (
    FISH_DESIGN_REFERENCE_TEXT_MAX_CHARS,
    FishAudioProvider,
    FishHTTPResponse,
)


class FakeFishClient:
    def __init__(self, responses: list[FishHTTPResponse] | FishHTTPResponse) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
        msgpack_body: dict[str, object] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        fields: dict[str, str],
        timeout: float,
    ) -> FishHTTPResponse:
        self.calls.append(
            {
                "path": path,
                "headers": headers,
                "json_body": json_body,
                "msgpack_body": msgpack_body,
                "files": files,
                "fields": fields,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def _response(content: bytes, *, status_code: int = 200) -> FishHTTPResponse:
    return FishHTTPResponse(status_code=status_code, content=content, headers={})


def test_fish_builtin_tts_posts_json_and_writes_audio(tmp_path: Path) -> None:
    client = FakeFishClient(_response(b"WAVDATA"))
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = TTSRequest(
        provider_id="fish-audio",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="e58b0d7efca34eb38d5c4985e378abcb",
    )

    artifact = provider.synthesize(request)

    assert artifact.path.read_bytes() == b"WAVDATA"
    assert artifact.provider_id == "fish-audio"
    assert artifact.metadata["model"] == "s1"
    assert client.calls == [
        {
            "path": "/v1/tts",
            "headers": {"model": "s1"},
            "json_body": {
                "text": "hello",
                "format": "wav",
                "reference_id": "e58b0d7efca34eb38d5c4985e378abcb",
                "normalize": True,
            },
            "msgpack_body": None,
            "files": None,
            "fields": {},
            "timeout": 300.0,
        }
    ]


def test_fish_voice_design_decodes_first_audio_candidate(tmp_path: Path) -> None:
    audio = base64.b64encode(b"DESIGNED").decode("ascii")
    client = FakeFishClient(_response(json.dumps({"voices": [{"audio": audio}]}).encode()))
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = TTSRequest(
        provider_id="fish-audio",
        mode=TTSMode.DESIGN,
        voice_description="warm narrator",
        text="short preview",
    )

    artifact = provider.synthesize(request)

    assert artifact.path.read_bytes() == b"DESIGNED"
    assert artifact.metadata["model"] == "s1"
    assert client.calls[0]["path"] == "/v1/voice-design"
    assert client.calls[0]["headers"] == {"model": "s1"}
    assert client.calls[0]["json_body"] == {
        "instruction": "warm narrator",
        "reference_text": "short preview",
    }


def test_fish_voice_design_accepts_data_uri_payload(tmp_path: Path) -> None:
    audio = base64.b64encode(b"DESIGNED").decode("ascii")
    client = FakeFishClient(
        _response(json.dumps({"data": f"data:audio/wav;base64,{audio}"}).encode())
    )
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )

    artifact = provider.synthesize(
        TTSRequest(
            provider_id="fish-audio",
            mode=TTSMode.DESIGN,
            voice_description="warm narrator",
            optimize_text_preview=True,
        )
    )

    assert artifact.path.read_bytes() == b"DESIGNED"


def test_fish_clone_tts_posts_msgpack_references_and_writes_audio(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")
    client = FakeFishClient(_response(b"CLONED"))
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = TTSRequest(
        provider_id="fish-audio",
        mode=TTSMode.CLONE,
        text="target text",
        clone_sample_path=sample,
        clone_mime_type="audio/wav",
        clone_reference_text="sample transcript",
        clone_raw_byte_size=16,
        clone_base64_size=24,
        consent_confirmed=True,
    )

    artifact = provider.synthesize(request)

    assert artifact.path.read_bytes() == b"CLONED"
    assert artifact.metadata["model"] == "s1"
    assert artifact.metadata["clone_reference_text_length"] == len("sample transcript")
    assert client.calls[0]["path"] == "/v1/tts"
    assert client.calls[0]["headers"] == {"model": "s1"}
    assert client.calls[0]["json_body"] is None
    payload = client.calls[0]["msgpack_body"]
    assert isinstance(payload, dict)
    assert payload == {
        "text": "target text",
        "format": "wav",
        "normalize": True,
        "references": [{"audio": b"RIFF0000WAVEfmt ", "text": "sample transcript"}],
    }
    packed, content_type = msgpack.packb(payload, use_bin_type=True), "application/msgpack"
    assert msgpack.unpackb(packed, raw=False)["references"][0]["audio"] == b"RIFF0000WAVEfmt "
    assert content_type == "application/msgpack"


def test_fish_clone_requires_reference_text(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeFishClient(_response(b"")),
    )
    request = TTSRequest(
        provider_id="fish-audio",
        mode=TTSMode.CLONE,
        text="target text",
        clone_sample_path=sample,
        clone_mime_type="audio/wav",
        clone_raw_byte_size=16,
        clone_base64_size=24,
        consent_confirmed=True,
    )

    with pytest.raises(ProviderError, match="clone_reference_text"):
        provider.synthesize(request)


def test_fish_voice_design_rejects_long_reference_text(tmp_path: Path) -> None:
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeFishClient(_response(b"")),
    )
    request = TTSRequest(
        provider_id="fish-audio",
        mode=TTSMode.DESIGN,
        voice_description="warm narrator",
        text="x" * (FISH_DESIGN_REFERENCE_TEXT_MAX_CHARS + 1),
    )

    with pytest.raises(ProviderError, match="150"):
        provider.synthesize(request)


def test_fish_asr_posts_multipart_and_writes_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"RIFF0000WAVEfmt ")
    client = FakeFishClient(_response(json.dumps({"text": "hello"}).encode()))
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = ASRRequest(
        provider_id="fish-audio",
        audio_path=audio_path,
        mime_type="audio/wav",
        raw_byte_size=16,
        base64_size=24,
        language="en",
    )

    artifact = provider.transcribe(request)

    assert artifact.path.read_text(encoding="utf-8") == "hello"
    assert artifact.metadata["model"] == "fish-audio-asr"
    assert client.calls == [
        {
            "path": "/v1/asr",
            "headers": {},
            "json_body": None,
            "msgpack_body": None,
            "files": {"audio": ("speech.wav", b"RIFF0000WAVEfmt ", "audio/wav")},
            "fields": {"language": "en"},
            "timeout": 300.0,
        }
    ]


def test_fish_provider_has_clone_capability(tmp_path: Path) -> None:
    provider = FishAudioProvider(
        config=make_default_fish_audio_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeFishClient(_response(b"")),
    )

    assert provider.capabilities() == {
        "tts.builtin",
        "tts.design",
        "tts.clone",
        "asr.transcribe",
    }


def test_build_provider_registry_creates_fish_audio_provider(tmp_path: Path) -> None:
    config = AppConfig(
        config_path=None,
        providers=[make_default_fish_audio_provider_config()],
    )

    registry = build_provider_registry(
        config=config,
        artifact_root=tmp_path,
        env_values={"FISH_AUDIO_API_KEY": "fish-key"},
    )

    provider = registry.get("fish-audio")
    assert isinstance(provider, FishAudioProvider)
    assert provider.id == "fish-audio"
