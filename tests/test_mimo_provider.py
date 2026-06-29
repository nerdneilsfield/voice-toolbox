from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.mimo import (
    ASR_TIMEOUT_SECONDS,
    GENERATION_TIMEOUT_SECONDS,
    MAX_BASE64_AUDIO_SIZE,
    RATE_LIMIT_BACKOFF_SECONDS,
    TTS_TIMEOUT_SECONDS,
    MimoProvider,
    _audio_file_to_data_url,
)


class FakeChatCompletions:
    def __init__(self, completion: object | list[object]) -> None:
        self.responses = completion if isinstance(completion, list) else [completion]
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, completion: object | list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletions(completion))


@pytest.fixture
def mimo_provider(tmp_path: Path) -> MimoProvider:
    return MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeClient(_tts_completion()),
    )


def test_provider_generation_timeout_defaults_to_300_seconds() -> None:
    assert GENERATION_TIMEOUT_SECONDS == 300.0
    assert TTS_TIMEOUT_SECONDS == GENERATION_TIMEOUT_SECONDS
    assert ASR_TIMEOUT_SECONDS == GENERATION_TIMEOUT_SECONDS


def test_operation_ids_are_unique_under_threaded_access(tmp_path: Path) -> None:
    provider = MimoProvider(
        api_key="secret", artifact_root=tmp_path, client=FakeClient(_tts_completion())
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        operation_ids = list(executor.map(provider._next_operation_id, ["tts"] * 100))

    assert len(operation_ids) == len(set(operation_ids))


def _tts_completion(payload: bytes = b"WAV") -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    audio=SimpleNamespace(data=base64.b64encode(payload).decode("ascii"))
                )
            )
        ]
    )


def _asr_completion(text: str = "hello transcript") -> object:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _api_request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _rate_limit_error() -> RateLimitError:
    request = _api_request()
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _api_status_error(status_code: int) -> APIStatusError:
    request = _api_request()
    response = httpx.Response(status_code, request=request)
    return APIStatusError("status failed", response=response, body=None)


def test_builtin_tts_places_tags_in_assistant_content(mimo_provider: MimoProvider) -> None:
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        text="(唱歌)啦啦啦[叹气]",
        style_instruction="Use a bright singing style.",
        voice_id="冰糖",
    )

    body = mimo_provider._build_tts_body(request)

    assert body["model"] == "mimo-v2.5-tts"
    assert body["messages"] == [
        {"role": "user", "content": "Use a bright singing style."},
        {"role": "assistant", "content": "(唱歌)啦啦啦[叹气]"},
    ]
    assert body["audio"] == {"voice": "冰糖", "format": "wav"}


def test_mimo_tts_provider_options_passthrough(tmp_path: Path) -> None:
    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeClient(_tts_completion()),
    )
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="冰糖",
        provider_options={"stream": False, "audio_sample_rate": 24000},
    )

    body = provider._build_tts_body(request)

    assert body["stream"] is False
    assert body["audio"]["sample_rate"] == 24000


def test_design_optimized_preview_omits_assistant_message_when_text_missing(
    mimo_provider: MimoProvider,
) -> None:
    request = TTSRequest(
        mode=TTSMode.DESIGN,
        voice_description="Warm alto voice with gentle pacing.",
        optimize_text_preview=True,
    )

    body = mimo_provider._build_tts_body(request)

    assert body["model"] == "mimo-v2.5-tts-voicedesign"
    assert body["messages"] == [{"role": "user", "content": "Warm alto voice with gentle pacing."}]
    assert body["audio"] == {"format": "wav", "optimize_text_preview": True}
    assert all(message["role"] != "assistant" for message in body["messages"])


def test_clone_builds_data_url_and_never_metadata_payload(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"clone audio")
    expected_payload = base64.b64encode(b"clone audio").decode("ascii")
    request = TTSRequest(
        mode=TTSMode.CLONE,
        text="hello",
        style_instruction="calm",
        clone_sample_path=sample,
        clone_mime_type="audio/wav",
        consent_confirmed=True,
    )

    client = FakeClient(_tts_completion())
    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )
    body = provider._build_tts_body(request)

    assert body["model"] == "mimo-v2.5-tts-voiceclone"
    assert body["audio"] == {
        "voice": f"data:audio/wav;base64,{expected_payload}",
        "format": "wav",
    }

    artifact = provider.synthesize(request)
    sidecar = artifact.path.with_suffix(".json").read_text(encoding="utf-8")

    assert client.chat.completions.calls[0]["timeout"] == GENERATION_TIMEOUT_SECONDS
    assert artifact.metadata["uploaded_file_suffix"] == ".wav"
    assert "uploaded_file_name" not in artifact.metadata
    assert artifact.metadata["uploaded_file_mime_type"] == "audio/wav"
    assert artifact.metadata["base64_size"] == len(expected_payload)
    assert "clone audio" not in sidecar
    assert expected_payload not in sidecar
    assert "data:audio/wav;base64" not in sidecar
    assert "audio" not in artifact.metadata
    assert "voice" not in artifact.metadata


def test_clone_rejects_unsupported_mime_before_data_url(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"clone audio")
    request = TTSRequest(
        mode=TTSMode.CLONE,
        text="hello",
        clone_sample_path=sample,
        clone_mime_type="audio/ogg",
        consent_confirmed=True,
    )

    with pytest.raises(ProviderError, match="MIME"):
        provider = MimoProvider(
            api_key="secret",
            artifact_root=tmp_path,
            client=FakeClient(_tts_completion()),
        )
        provider._build_tts_body(request)


def test_clone_rejects_unsupported_suffix_before_reading_file(tmp_path: Path) -> None:
    missing_flac = tmp_path / "missing.flac"
    request = TTSRequest(
        mode=TTSMode.CLONE,
        text="hello",
        clone_sample_path=missing_flac,
        clone_mime_type="audio/wav",
        consent_confirmed=True,
    )

    with pytest.raises(ProviderError, match="suffix"):
        provider = MimoProvider(
            api_key="secret",
            artifact_root=tmp_path,
            client=FakeClient(_tts_completion()),
        )
        provider._build_tts_body(request)


def test_asr_uses_chat_completions_input_audio_and_extra_body(tmp_path: Path) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"asr audio")
    data_url, raw_size, base64_size = _audio_file_to_data_url(audio, "audio/wav")
    request = ASRRequest(
        audio_path=audio,
        mime_type="audio/wav",
        raw_byte_size=raw_size,
        base64_size=base64_size,
        language="zh",
        provider_options={"asr_temperature": 0},
    )

    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeClient(_asr_completion()),
    )
    body = provider._build_asr_body(request, data_url)

    assert body == {
        "model": "mimo-v2.5-asr",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }
                ],
            }
        ],
        "_extra_body": {"asr_options": {"language": "zh", "temperature": 0}},
    }

    client = FakeClient(_asr_completion("你好"))
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=client)
    artifact = provider.transcribe(request)

    assert client.chat.completions.calls == [
        {
            "model": "mimo-v2.5-asr",
            "messages": body["messages"],
            "extra_body": {"asr_options": {"language": "zh", "temperature": 0}},
            "timeout": GENERATION_TIMEOUT_SECONDS,
        }
    ]
    assert artifact.path.read_text(encoding="utf-8") == "你好"


def test_non_text_asr_transcript_raises_provider_error(tmp_path: Path) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"asr audio")
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content={"text": "hello"}))]
    )
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=FakeClient(completion))
    request = ASRRequest(
        audio_path=audio,
        mime_type="audio/wav",
        raw_byte_size=len(b"asr audio"),
        base64_size=len(base64.b64encode(b"asr audio").decode("ascii")),
    )

    with pytest.raises(ProviderError, match="not text"):
        provider.transcribe(request)


def test_bearer_auth_client_is_created_from_api_key(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def client_factory(**kwargs: object) -> FakeClient:
        captured.update(kwargs)
        return FakeClient(_tts_completion())

    MimoProvider(
        api_key="mimo-key",
        base_url="https://example.test/v1",
        artifact_root=tmp_path,
        client_factory=client_factory,
    )

    assert captured == {
        "api_key": "mimo-key",
        "base_url": "https://example.test/v1",
        "max_retries": 0,
    }


def test_api_connection_error_is_not_retried(tmp_path: Path) -> None:
    error = APIConnectionError(request=_api_request())
    client = FakeClient(error)
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=client)
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="connection failed"):
        provider.synthesize(request)

    assert len(client.chat.completions.calls) == 1


def test_rate_limit_error_retries_once(tmp_path: Path) -> None:
    sleep_calls: list[float] = []
    client = FakeClient([_rate_limit_error(), _tts_completion(b"OK")])
    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
        sleep_func=sleep_calls.append,
    )
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    artifact = provider.synthesize(request)

    assert len(client.chat.completions.calls) == 2
    assert sleep_calls == [RATE_LIMIT_BACKOFF_SECONDS]
    assert artifact.path.read_bytes() == b"OK"


def test_rate_limit_error_retries_once_then_provider_error(tmp_path: Path) -> None:
    sleep_calls: list[float] = []
    client = FakeClient([_rate_limit_error(), _rate_limit_error()])
    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
        sleep_func=sleep_calls.append,
    )
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="rate limit"):
        provider.synthesize(request)

    assert len(client.chat.completions.calls) == 2
    assert sleep_calls == [RATE_LIMIT_BACKOFF_SECONDS]


def test_api_timeout_error_is_not_retried(tmp_path: Path) -> None:
    client = FakeClient(APITimeoutError(_api_request()))
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=client)
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="timed out"):
        provider.synthesize(request)

    assert len(client.chat.completions.calls) == 1


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "authentication failed"),
        (500, "status 500"),
    ],
)
def test_api_status_errors_are_provider_errors_without_retry(
    tmp_path: Path,
    status_code: int,
    message: str,
) -> None:
    client = FakeClient(_api_status_error(status_code))
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=client)
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match=message):
        provider.synthesize(request)

    assert len(client.chat.completions.calls) == 1


def test_malformed_audio_payload_raises_provider_error(tmp_path: Path) -> None:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(audio=SimpleNamespace(data="not-base64")))]
    )
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=FakeClient(completion))
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="valid base64"):
        provider.synthesize(request)


def test_missing_audio_payload_raises_provider_error(tmp_path: Path) -> None:
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())])
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=FakeClient(completion))
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="missing audio data"):
        provider.synthesize(request)


def test_non_string_audio_payload_raises_provider_error(tmp_path: Path) -> None:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(audio=SimpleNamespace(data=123)))]
    )
    provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=FakeClient(completion))
    request = TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia")

    with pytest.raises(ProviderError, match="audio data is not text"):
        provider.synthesize(request)


def test_model_resolution_explicit_request_model_wins(tmp_path: Path) -> None:
    explicit = TTSRequest(
        mode=TTSMode.BUILTIN,
        model="mimo-v2.5-tts",
        text="hello",
        voice_id="Mia",
    )
    design = TTSRequest(
        mode=TTSMode.DESIGN,
        voice_description="clear voice",
        optimize_text_preview=True,
    )
    clone_sample = tmp_path / "sample.wav"
    clone_sample.write_bytes(b"x")
    clone = TTSRequest(
        mode=TTSMode.CLONE,
        text="hello",
        clone_sample_path=clone_sample,
        clone_mime_type="audio/wav",
        consent_confirmed=True,
        clone_raw_byte_size=1,
        clone_base64_size=4,
    )

    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeClient(_tts_completion()),
    )

    assert provider._build_tts_body(explicit)["model"] == "mimo-v2.5-tts"
    assert provider._build_tts_body(design)["model"] == "mimo-v2.5-tts-voicedesign"
    assert provider._build_tts_body(clone)["model"] == "mimo-v2.5-tts-voiceclone"


def test_unsupported_explicit_model_is_rejected(mimo_provider: MimoProvider) -> None:
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        model="gpt-4",
        text="hello",
        voice_id="Mia",
    )

    with pytest.raises(ProviderError, match="unsupported MiMo model"):
        mimo_provider._build_tts_body(request)


def test_clone_and_asr_base64_size_max_10_mib(tmp_path: Path) -> None:
    clone_sample = tmp_path / "sample.wav"
    clone_sample.write_bytes(b"x")
    clone_request = TTSRequest(
        mode=TTSMode.CLONE,
        text="hello",
        clone_sample_path=clone_sample,
        clone_mime_type="audio/wav",
        clone_base64_size=MAX_BASE64_AUDIO_SIZE + 1,
        consent_confirmed=True,
    )
    asr_request = ASRRequest(
        audio_path=clone_sample,
        mime_type="audio/wav",
        raw_byte_size=1,
        base64_size=MAX_BASE64_AUDIO_SIZE + 1,
    )

    with pytest.raises(ProviderError, match="base64"):
        provider = MimoProvider(
            api_key="secret",
            artifact_root=tmp_path,
            client=FakeClient(_tts_completion()),
        )
        provider._build_tts_body(clone_request)
    provider = MimoProvider(
        api_key="secret",
        artifact_root=tmp_path,
        client=FakeClient(_asr_completion()),
    )
    with pytest.raises(ProviderError, match="base64"):
        provider.transcribe(asr_request)


def test_tts_output_format_stays_wav_only() -> None:
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="Mia",
        output_format="mp3",
    )
    provider = MimoProvider(
        api_key="secret",
        client=FakeClient(_tts_completion()),
    )

    with pytest.raises(ProviderError, match="output format must be wav"):
        provider._build_tts_body(request)
