from __future__ import annotations

import base64
import binascii
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES
from voice_toolbox.settings import get_mimo_api_key, load_settings

MAX_BASE64_AUDIO_SIZE = 10 * 1024 * 1024
TTS_TIMEOUT_SECONDS = 60.0
ASR_TIMEOUT_SECONDS = 90.0
RATE_LIMIT_BACKOFF_SECONDS = 0.25
CLONE_MIME_SUFFIXES = {
    "audio/wav": {".wav"},
    "audio/mpeg": {".mp3"},
    "audio/mp3": {".mp3"},
}

MIMO_MODELS = [
    {"id": "mimo-v2.5-tts", "capability": "tts.builtin"},
    {"id": "mimo-v2.5-tts-voicedesign", "capability": "tts.design"},
    {"id": "mimo-v2.5-tts-voiceclone", "capability": "tts.clone"},
    {"id": "mimo-v2.5-asr", "capability": "asr.transcribe"},
]

MIMO_VOICES = [
    {"id": "mimo_default", "name": "MiMo-默认", "note": "cluster-dependent"},
    {"id": "冰糖", "name": "冰糖", "language": "zh", "gender": "female"},
    {"id": "茉莉", "name": "茉莉", "language": "zh", "gender": "female"},
    {"id": "苏打", "name": "苏打", "language": "zh", "gender": "male"},
    {"id": "白桦", "name": "白桦", "language": "zh", "gender": "male"},
    {"id": "Mia", "name": "Mia", "language": "en", "gender": "female"},
    {"id": "Chloe", "name": "Chloe", "language": "en", "gender": "female"},
    {"id": "Milo", "name": "Milo", "language": "en", "gender": "male"},
    {"id": "Dean", "name": "Dean", "language": "en", "gender": "male"},
]

_TTS_MODEL_BY_MODE = {
    TTSMode.BUILTIN: "mimo-v2.5-tts",
    TTSMode.DESIGN: "mimo-v2.5-tts-voicedesign",
    TTSMode.CLONE: "mimo-v2.5-tts-voiceclone",
}

_MODEL_NAMES = {
    "mimo-v2.5-tts": "MiMo TTS",
    "mimo-v2.5-tts-voicedesign": "MiMo Voice Design",
    "mimo-v2.5-tts-voiceclone": "MiMo Voice Clone",
    "mimo-v2.5-asr": "MiMo ASR",
}


def _build_tts_body(request: TTSRequest) -> dict[str, Any]:
    _validate_tts_request(request)
    audio: dict[str, Any] = {"format": request.output_format}
    body: dict[str, Any] = {
        "model": _resolve_tts_model(request),
        "messages": [],
        "audio": audio,
    }
    messages = body["messages"]

    if request.mode == TTSMode.BUILTIN:
        if request.style_instruction:
            messages.append({"role": "user", "content": request.style_instruction})
        messages.append({"role": "assistant", "content": request.text})
        audio["voice"] = request.voice_id
        return body

    if request.mode == TTSMode.DESIGN:
        messages.append({"role": "user", "content": request.voice_description})
        if request.text:
            messages.append({"role": "assistant", "content": request.text})
        audio["optimize_text_preview"] = request.optimize_text_preview
        return body

    if request.mode == TTSMode.CLONE:
        _validate_clone_audio_input(request)
        if request.clone_base64_size is not None:
            _validate_base64_size(request.clone_base64_size)
        if request.style_instruction:
            messages.append({"role": "user", "content": request.style_instruction})
        messages.append({"role": "assistant", "content": request.text})
        if request.clone_sample_path is None or request.clone_mime_type is None:
            raise ProviderError("clone mode requires clone sample path and MIME type")
        audio_data_url, _, _ = _audio_file_to_data_url(
            request.clone_sample_path,
            request.clone_mime_type,
        )
        audio["voice"] = audio_data_url
        return body

    raise UnsupportedCapability(f"mimo provider does not support TTS mode: {request.mode}")


def _build_asr_body(request: ASRRequest, audio_data_url: str) -> dict[str, Any]:
    _validate_base64_size(request.base64_size)
    return {
        "model": request.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_data_url},
                    }
                ],
            }
        ],
    }


def _audio_file_to_data_url(path: Path, mime_type: str) -> tuple[str, int, int]:
    raw_audio = path.read_bytes()
    raw_size = len(raw_audio)
    base64_audio = base64.b64encode(raw_audio).decode("ascii")
    base64_size = len(base64_audio)
    _validate_base64_size(base64_size)
    return f"data:{mime_type};base64,{base64_audio}", raw_size, base64_size


class MimoProvider:
    id = "mimo"
    name = "MiMo"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
        env_path: Path | str | None = None,
        client: Any | None = None,
        client_factory: Callable[..., Any] = OpenAI,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = load_settings(env_path)
        resolved_api_key = api_key if api_key is not None else get_mimo_api_key(env_path)
        resolved_base_url = base_url if base_url is not None else settings.base_url

        if client is not None:
            self._client = client
        elif resolved_api_key:
            self._client = client_factory(
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                max_retries=0,
            )
        else:
            self._client = _MissingCredentialsClient()
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._closed = False
        self._sleep_func = sleep_func
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            if artifact_root is None:
                self._temp_dir = tempfile.TemporaryDirectory()
                root = Path(self._temp_dir.name)
            else:
                root = Path(artifact_root)
            self._artifact_root = root
            self._artifact_store = ArtifactStore(root)

    def capabilities(self) -> set[str]:
        return {"tts.builtin", "tts.design", "tts.clone", ASR_CAPABILITY}

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=model["id"],
                name=_MODEL_NAMES[model["id"]],
                capability=model["capability"],
            )
            for model in MIMO_MODELS
        ]

    def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(**voice) for voice in MIMO_VOICES]

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def close(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
        self._closed = True

    def __enter__(self) -> MimoProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def synthesize(self, request: TTSRequest) -> AudioArtifact:
        self._ensure_open()
        self._ensure_tts_capability(request)
        body = _build_tts_body(request)
        completion = self._create_completion(body, timeout=TTS_TIMEOUT_SECONDS)
        audio_payload = _message_audio_data(completion)

        try:
            audio = base64.b64decode(audio_payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError("mimo response audio data is not valid base64") from exc

        return self._artifact_store.write_audio(
            operation_id=self._next_operation_id("tts"),
            provider_id=self.id,
            operation="tts",
            audio=audio,
            metadata=_tts_metadata(request, body),
        )

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        self._ensure_open()
        _validate_base64_size(request.base64_size)
        audio_data_url, raw_size, base64_size = _audio_file_to_data_url(
            request.audio_path,
            request.mime_type,
        )
        body = _build_asr_body(request, audio_data_url)
        completion = self._create_completion(
            body,
            timeout=ASR_TIMEOUT_SECONDS,
            extra_body={"asr_options": {"language": request.language}},
        )
        transcript = _message_content(completion)

        return self._artifact_store.write_transcript(
            operation_id=self._next_operation_id("asr"),
            provider_id=self.id,
            operation="asr",
            text=transcript,
            metadata={
                "base64_size": base64_size,
                "language": request.language,
                "model": request.model,
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": raw_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name": request.audio_path.name,
            },
        )

    def _create_completion(
        self,
        body: dict[str, Any],
        *,
        timeout: float,
        extra_body: dict[str, Any] | None = None,
    ) -> Any:
        kwargs = {**body, "timeout": timeout}
        if extra_body is not None:
            kwargs["extra_body"] = extra_body

        for attempt in range(2):
            try:
                return self._client.chat.completions.create(**kwargs)
            except RateLimitError as exc:
                if attempt == 0:
                    self._sleep_func(RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                raise ProviderError("mimo API rate limit exceeded") from exc
            except APITimeoutError as exc:
                raise ProviderError("mimo API request timed out") from exc
            except APIConnectionError as exc:
                raise ProviderError("mimo API connection failed") from exc
            except APIStatusError as exc:
                raise ProviderError(_api_status_error_message(exc)) from exc
        raise ProviderError("mimo API request failed")

    def _ensure_tts_capability(self, request: TTSRequest) -> None:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in self.capabilities():
            raise UnsupportedCapability(f"mimo provider does not support capability: {capability}")

    def _next_operation_id(self, operation: str) -> str:
        self._operation_counter += 1
        return f"mimo-{self._operation_prefix}-{operation}-{self._operation_counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("mimo provider is closed")


def _validate_tts_request(request: TTSRequest) -> None:
    if request.output_format != "wav":
        raise ProviderError("mimo TTS output format must be wav")


def _validate_clone_audio_input(request: TTSRequest) -> None:
    if request.clone_sample_path is None or request.clone_mime_type is None:
        raise ProviderError("clone mode requires clone sample path and MIME type")
    allowed_suffixes = CLONE_MIME_SUFFIXES.get(request.clone_mime_type)
    if allowed_suffixes is None:
        raise ProviderError("mimo clone sample MIME type must be audio/wav, audio/mpeg, or audio/mp3")
    suffix = request.clone_sample_path.suffix.lower()
    if suffix not in allowed_suffixes:
        expected = ", ".join(sorted(allowed_suffixes))
        raise ProviderError(
            f"mimo clone sample suffix must be {expected} for {request.clone_mime_type}"
        )


def _validate_base64_size(base64_size: int) -> None:
    if base64_size > MAX_BASE64_AUDIO_SIZE:
        raise ProviderError("mimo audio base64 payload exceeds 10 MiB")


def _api_status_error_message(exc: APIStatusError) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return "mimo API authentication failed"
    if status_code is not None:
        return f"mimo API request failed with status {status_code}"
    return "mimo API request failed"


def _resolve_tts_model(request: TTSRequest) -> str:
    return request.model or _TTS_MODEL_BY_MODE[request.mode]


def _message_audio_data(completion: Any) -> str:
    try:
        message = _get_value(_get_value(completion, "choices")[0], "message")
        audio = _get_value(message, "audio")
        data = _get_value(audio, "data")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderError("mimo response is missing audio data") from exc
    if not isinstance(data, str):
        raise ProviderError("mimo response audio data is not text")
    return data


def _message_content(completion: Any) -> str:
    try:
        message = _get_value(_get_value(completion, "choices")[0], "message")
        content = _get_value(message, "content")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderError("mimo response is missing transcript content") from exc
    if not isinstance(content, str):
        raise ProviderError("mimo transcript content is not text")
    return content


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value[key]
    return getattr(value, key)


class _MissingCredentialsClient:
    def __init__(self) -> None:
        self.chat = _MissingCredentialsChat()


class _MissingCredentialsChat:
    def __init__(self) -> None:
        self.completions = _MissingCredentialsCompletions()


class _MissingCredentialsCompletions:
    def create(self, **_: Any) -> Any:
        raise ProviderError("MIMO_API_KEY is required for provider mimo")


def _tts_metadata(request: TTSRequest, body: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "model": body["model"],
        "operation": "tts",
        "output_format": request.output_format,
        "provider_id": "mimo",
        "source_text": request.text,
        "style_instruction": request.style_instruction,
        "tts_mode": request.mode.value,
        "voice_description": request.voice_description,
        "voice_id": request.voice_id,
    }
    if request.mode == TTSMode.CLONE:
        if request.clone_sample_path is not None:
            metadata["uploaded_file_name"] = request.clone_sample_path.name
        metadata.update(
            {
                "base64_size": _clone_base64_size(request),
                "consent_confirmed": request.consent_confirmed,
                "raw_byte_size": _clone_raw_size(request),
                "uploaded_file_mime_type": request.clone_mime_type,
            }
        )
    return metadata


def _clone_raw_size(request: TTSRequest) -> int | None:
    if request.clone_raw_byte_size is not None:
        return request.clone_raw_byte_size
    if request.clone_sample_path is None:
        return None
    return os.path.getsize(request.clone_sample_path)


def _clone_base64_size(request: TTSRequest) -> int | None:
    if request.clone_base64_size is not None:
        return request.clone_base64_size
    if request.clone_sample_path is None:
        return None
    raw_size = os.path.getsize(request.clone_sample_path)
    return ((raw_size + 2) // 3) * 4
