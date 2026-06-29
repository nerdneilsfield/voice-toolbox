from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from voice_toolbox.config import AppConfig
from voice_toolbox.defaults import make_default_openrouter_provider_config
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.openrouter import (
    OPENROUTER_TTS_RESPONSE_FORMAT,
    OPENROUTER_REFERER_HEADER,
    OPENROUTER_TITLE_HEADER,
    OpenRouterHTTPClient,
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


def test_openrouter_tts_sends_style_instruction_as_openai_options(tmp_path: Path) -> None:
    client = FakeOpenRouterClient(_response(b"MP3DATA"))
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )

    provider.synthesize(
        TTSRequest(
            provider_id="openrouter",
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="alloy",
            style_instruction="warm and concise",
        )
    )

    body = client.calls[0]["body"]
    assert isinstance(body, dict)
    assert body["provider"] == {"options": {"openai": {"instructions": "warm and concise"}}}


def test_openrouter_tts_provider_options_passthrough(tmp_path: Path) -> None:
    client = FakeOpenRouterClient(_response(b"MP3DATA"))
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )

    provider.synthesize(
        TTSRequest(
            provider_id="openrouter",
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="alloy",
            provider_options={"instructions": "clear voice", "speed": 1.1},
        )
    )

    body = client.calls[0]["body"]
    assert isinstance(body, dict)
    assert body["speed"] == 1.1
    assert body["provider"] == {"options": {"openai": {"instructions": "clear voice"}}}


def test_openrouter_base_url_override_is_revalidated(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="base_url"):
        OpenRouterProvider(
            config=make_default_openrouter_provider_config(),
            api_key="secret",
            base_url="http://user:pass@example.test/v1?key=1",
            artifact_root=tmp_path,
        )


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
        provider_options={"prompt": "domain words"},
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
                "prompt": "domain words",
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


def test_openrouter_rate_limit_uses_retry_after_and_payment_messages(tmp_path: Path) -> None:
    sleeps: list[float] = []
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
            [
                OpenRouterHTTPResponse(
                    status_code=429,
                    content=b"",
                    headers={"Retry-After": "1.5"},
                ),
                _response(b"", status_code=429),
            ]
        ),
        sleep_func=sleeps.append,
    )
    payment_required = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(_response(b"", status_code=402)),
    )

    with pytest.raises(ProviderError, match="rate limit"):
        rate_limited.synthesize(request)
    assert sleeps == [1.5]
    with pytest.raises(ProviderError, match="payment|required|credits"):
        payment_required.synthesize(request)


def test_openrouter_refuses_redirect_responses(tmp_path: Path) -> None:
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(
            OpenRouterHTTPResponse(status_code=302, content=b"", headers={"Location": "x"})
        ),
    )

    with pytest.raises(ProviderError, match="redirect refused"):
        provider.synthesize(
            TTSRequest(
                provider_id="openrouter",
                mode=TTSMode.BUILTIN,
                text="hello",
                voice_id="alloy",
            )
        )


def test_openrouter_transcribe_rejects_invalid_json(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"RIFF0000WAVEfmt ")
    provider = OpenRouterProvider(
        config=make_default_openrouter_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeOpenRouterClient(_response(b"not-json")),
    )

    with pytest.raises(ProviderError, match="valid JSON"):
        provider.transcribe(
            ASRRequest(
                provider_id="openrouter",
                audio_path=audio_path,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
            )
        )


def test_openrouter_http_client_sets_headers_and_disables_redirects(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRawResponse:
        status = 200
        headers = {"Content-Type": "audio/mpeg"}

        def __enter__(self) -> FakeRawResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b"MP3"

    class FakeOpener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> FakeRawResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeRawResponse()

    def fake_build_opener(*handlers: object) -> FakeOpener:
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    response = OpenRouterHTTPClient(
        api_key="secret", base_url="https://openrouter.ai/api/v1"
    ).post_json(
        "/audio/speech",
        {"model": "m", "input": "hi", "voice": "alloy"},
        timeout=12.0,
    )

    request = captured["request"]
    assert isinstance(request, urllib.request.Request)
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer secret"
    assert headers["content-type"] == "application/json"
    assert headers["http-referer"] == OPENROUTER_REFERER_HEADER
    assert headers["x-title"] == OPENROUTER_TITLE_HEADER
    assert captured["timeout"] == 12.0
    handlers = captured["handlers"]
    assert isinstance(handlers, tuple)
    assert any(handler.__class__.__name__ == "_NoRedirectHandler" for handler in handlers)
    assert response.content == b"MP3"


def test_openrouter_http_client_returns_http_errors(monkeypatch) -> None:
    class FakeOpener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> None:
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs={},
                fp=BytesIO(b"nope"),
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: FakeOpener())

    response = OpenRouterHTTPClient(
        api_key="secret", base_url="https://openrouter.ai/api/v1"
    ).post_json(
        "/audio/speech",
        {"model": "m", "input": "hi", "voice": "alloy"},
        timeout=12.0,
    )

    assert response.status_code == 401
    assert response.content == b"nope"


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
