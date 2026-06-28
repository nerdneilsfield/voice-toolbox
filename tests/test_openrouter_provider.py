from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from voice_toolbox.config import AppConfig
from voice_toolbox.defaults import make_default_openrouter_provider_config
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.openrouter import (
    OPENROUTER_TTS_RESPONSE_FORMAT,
    OpenRouterHTTPResponse,
    OpenRouterProvider,
)


class FakeOpenRouterClient:
    def __init__(self, responses: list[OpenRouterHTTPResponse] | OpenRouterHTTPResponse) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[dict[str, object]] = []

    def post_json(
        self,
        path: str,
        body: dict[str, object],
        *,
        timeout: float,
    ) -> OpenRouterHTTPResponse:
        self.calls.append({"path": path, "body": body, "timeout": timeout})
        return self.responses.pop(0)


def _response(content: bytes, *, status_code: int = 200) -> OpenRouterHTTPResponse:
    return OpenRouterHTTPResponse(status_code=status_code, content=content, headers={})


def test_openrouter_builtin_tts_posts_audio_speech_and_writes_mp3(tmp_path: Path) -> None:
    client = FakeOpenRouterClient(_response(b"MP3DATA"))
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = TTSRequest(
        provider_id="openrouter",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="alloy",
    )

    artifact = provider.synthesize(request)

    assert artifact.path.name.endswith(".mp3")
    assert artifact.path.read_bytes() == b"MP3DATA"
    assert artifact.mime_type == "audio/mpeg"
    assert artifact.metadata["model"] == "openai/gpt-4o-mini-tts-2025-12-15"
    assert artifact.metadata["output_format"] == "mp3"
    assert client.calls == [
        {
            "path": "/audio/speech",
            "body": {
                "model": "openai/gpt-4o-mini-tts-2025-12-15",
                "input": "hello",
                "voice": "alloy",
                "response_format": OPENROUTER_TTS_RESPONSE_FORMAT,
            },
            "timeout": 300.0,
        }
    ]


def test_openrouter_rejects_design_and_clone_modes(tmp_path: Path) -> None:
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(_response(b"")),
    )

    with pytest.raises(UnsupportedCapability):
        provider.synthesize(
            TTSRequest(
                provider_id="openrouter",
                mode=TTSMode.DESIGN,
                voice_description="warm",
                optimize_text_preview=True,
            )
        )


def test_openrouter_asr_posts_base64_input_audio_and_writes_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"RIFF0000WAVEfmt ")
    client = FakeOpenRouterClient(_response(json.dumps({"text": "hello"}).encode()))
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = ASRRequest(
        provider_id="openrouter",
        audio_path=audio_path,
        mime_type="audio/wav",
        raw_byte_size=16,
        base64_size=24,
        language="en",
    )

    artifact = provider.transcribe(request)

    assert artifact.path.read_text(encoding="utf-8") == "hello"
    assert artifact.metadata["model"] == "openai/whisper-1"
    assert client.calls == [
        {
            "path": "/audio/transcriptions",
            "body": {
                "model": "openai/whisper-1",
                "input_audio": {
                    "data": base64.b64encode(b"RIFF0000WAVEfmt ").decode("ascii"),
                    "format": "wav",
                },
                "language": "en",
            },
            "timeout": 300.0,
        }
    ]


def test_openrouter_asr_omits_auto_language(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech.mp3"
    audio_path.write_bytes(b"ID3audio")
    client = FakeOpenRouterClient(_response(json.dumps({"text": "hello"}).encode()))
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    request = ASRRequest(
        provider_id="openrouter",
        audio_path=audio_path,
        mime_type="audio/mpeg",
        raw_byte_size=8,
        base64_size=12,
        language="auto",
    )

    provider.transcribe(request)

    body = client.calls[0]["body"]
    assert isinstance(body, dict)
    assert body["input_audio"] == {
        "data": base64.b64encode(b"ID3audio").decode("ascii"),
        "format": "mp3",
    }
    assert "language" not in body


def test_openrouter_rate_limit_and_payment_messages(tmp_path: Path) -> None:
    request = TTSRequest(
        provider_id="openrouter",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="alloy",
    )
    rate_limited = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(
            [_response(b"", status_code=429), _response(b"", status_code=429)]
        ),
        sleep_func=lambda _: None,
    )
    payment_required = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(_response(b"", status_code=402)),
    )

    with pytest.raises(ProviderError, match="rate limit"):
        rate_limited.synthesize(request)
    with pytest.raises(ProviderError, match="payment|required|credits"):
        payment_required.synthesize(request)


def test_build_provider_registry_creates_openrouter_provider(tmp_path: Path) -> None:
    config = AppConfig(config_path=None, providers=[make_default_openrouter_provider_config()])

    registry = build_provider_registry(
        config=config,
        artifact_root=tmp_path,
        env_values={"OPENROUTER_API_KEY": "openrouter-key"},
    )

    provider = registry.get("openrouter")
    assert isinstance(provider, OpenRouterProvider)
    assert provider.id == "openrouter"
