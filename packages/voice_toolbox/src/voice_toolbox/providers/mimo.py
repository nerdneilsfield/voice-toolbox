from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tempfile
import threading
import time
from collections.abc import Callable
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox import defaults as _defaults
from voice_toolbox.defaults import (
    DEFAULT_MIMO_BASE_URL,
    make_default_mimo_provider_config,
)
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES
from voice_toolbox.transcripts import TranscriptPayload

MIMO_MODELS = _defaults.MIMO_MODELS
MIMO_VOICES = _defaults.MIMO_VOICES
MAX_BASE64_AUDIO_SIZE = 10 * 1024 * 1024
GENERATION_TIMEOUT_SECONDS = 300.0
TTS_TIMEOUT_SECONDS = GENERATION_TIMEOUT_SECONDS
ASR_TIMEOUT_SECONDS = GENERATION_TIMEOUT_SECONDS
RATE_LIMIT_BACKOFF_SECONDS = 0.25
CLONE_MIME_SUFFIXES = {
    "audio/wav": {".wav"},
    "audio/mpeg": {".mp3"},
    "audio/mp3": {".mp3"},
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
        config: ConfiguredProvider | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
        client: Any | None = None,
        client_factory: Callable[..., Any] = OpenAI,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved_config = config or make_default_mimo_provider_config(
            base_url=base_url or DEFAULT_MIMO_BASE_URL
        )
        if base_url is not None:
            resolved_config = resolved_config.model_copy(update={"base_url": base_url})

        self._config = resolved_config
        self.id = resolved_config.id
        self.name = resolved_config.name
        self._models_by_id = {model.id: model for model in resolved_config.models}
        self._default_models = resolved_config.default_models or ProviderDefaultModels()

        if client is not None:
            self._client = client
        elif api_key:
            self._client = client_factory(
                api_key=api_key,
                base_url=resolved_config.base_url,
                max_retries=0,
            )
        else:
            self._client = _MissingCredentialsClient(
                resolved_config.api_key_env,
                provider_id=resolved_config.id,
            )
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._operation_counter_lock = threading.Lock()
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
        capabilities: set[str] = set()
        for model in self._config.models:
            if model.capability is not None:
                capabilities.add(model.capability)
        return capabilities

    def list_models(self) -> list[ModelInfo]:
        return [model.model_copy() for model in self._config.models]

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in self._config.voices]

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

    def _build_tts_body(self, request: TTSRequest) -> dict[str, Any]:
        self._validate_tts_request(request)
        audio: dict[str, Any] = {"format": request.output_format}
        body: dict[str, Any] = {
            "model": self._resolve_tts_model(request),
            "messages": [],
            "audio": audio,
        }
        messages = body["messages"]

        if request.mode == TTSMode.BUILTIN:
            if request.style_instruction:
                messages.append({"role": "user", "content": request.style_instruction})
            messages.append({"role": "assistant", "content": request.text})
            audio["voice"] = request.voice_id
            _apply_mimo_provider_options(body, audio, request.provider_options)
            return body

        if request.mode == TTSMode.DESIGN:
            messages.append({"role": "user", "content": request.voice_description})
            if request.text:
                messages.append({"role": "assistant", "content": request.text})
            audio["optimize_text_preview"] = request.optimize_text_preview
            _apply_mimo_provider_options(body, audio, request.provider_options)
            return body

        if request.mode == TTSMode.CLONE:
            self._validate_clone_audio_input(request)
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
            _apply_mimo_provider_options(body, audio, request.provider_options)
            return body

        raise UnsupportedCapability(f"mimo provider does not support TTS mode: {request.mode}")

    def _build_asr_body(self, request: ASRRequest, audio_data_url: str) -> dict[str, Any]:
        model = self._resolve_asr_model(request)
        self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
        _validate_base64_size(request.base64_size)
        body: dict[str, Any] = {
            "model": model,
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
        asr_options: dict[str, object] = {"language": request.language}
        for key, value in request.provider_options.items():
            if key == "language":
                raise ProviderError("provider option language cannot override ASR language")
            if key.startswith("asr_"):
                asr_options[key.removeprefix("asr_")] = value
                continue
            if key in {"model", "messages"}:
                raise ProviderError(f"provider option {key} cannot override core ASR field")
            body[key] = value
        body["_extra_body"] = {"asr_options": asr_options}
        return body

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        self._ensure_open()
        operation_id = self._next_operation_id("tts")
        started_at = datetime.now(UTC)
        result = self.synthesize_bytes(request)
        body = self._build_tts_body(request)
        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=result.audio,
            mime_type=result.mime_type,
            suffix=result.suffix,
            metadata={
                **dict(artifact_metadata or {}),
                **_tts_metadata(request, body, provider_id=self.id),
            },
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="tts",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self._ensure_open()
        self._ensure_tts_capability(request)
        body = self._build_tts_body(request)
        completion = self._create_completion(body, timeout=TTS_TIMEOUT_SECONDS)
        audio_payload = _message_audio_data(completion)
        try:
            audio = base64.b64decode(audio_payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError("mimo response audio data is not valid base64") from exc
        return ProviderAudioResult(
            audio=audio,
            mime_type="audio/wav",
            suffix=".wav",
            model=body.get("model") if isinstance(body.get("model"), str) else None,
        )

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        self._ensure_open()
        operation_id = self._next_operation_id("asr")
        started_at = datetime.now(UTC)
        payload = self.transcribe_payload(request)
        artifact = self._artifact_store.write_transcript(
            operation_id=operation_id,
            provider_id=self.id,
            operation="asr",
            text=payload.text,
            payload=payload,
            metadata={
                "base64_size": request.base64_size,
                "language": request.language,
                "model": self._resolve_asr_model(request),
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name_hash": _file_name_hash(request.audio_path.name),
                "uploaded_file_suffix": request.audio_path.suffix,
            },
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="asr",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        self._ensure_open()
        _validate_base64_size(request.base64_size)
        audio_data_url, _raw_size, _base64_size = _audio_file_to_data_url(
            request.audio_path,
            request.mime_type,
        )
        body = self._build_asr_body(request, audio_data_url)
        extra_body = body.pop("_extra_body", None)
        completion = self._create_completion(
            body,
            timeout=ASR_TIMEOUT_SECONDS,
            extra_body=extra_body if isinstance(extra_body, dict) else None,
        )
        return TranscriptPayload(text=_message_content(completion))

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

    def _validate_tts_request(self, request: TTSRequest) -> None:
        if request.output_format != "wav":
            raise ProviderError("mimo TTS output format must be wav")

    def _validate_clone_audio_input(self, request: TTSRequest) -> None:
        if request.clone_sample_path is None or request.clone_mime_type is None:
            raise ProviderError("clone mode requires clone sample path and MIME type")
        allowed_suffixes = CLONE_MIME_SUFFIXES.get(request.clone_mime_type)
        if allowed_suffixes is None:
            raise ProviderError(
                "mimo clone sample MIME type must be audio/wav, audio/mpeg, or audio/mp3"
            )
        suffix = request.clone_sample_path.suffix.lower()
        if suffix not in allowed_suffixes:
            expected = ", ".join(sorted(allowed_suffixes))
            raise ProviderError(
                f"mimo clone sample suffix must be {expected} for {request.clone_mime_type}"
            )

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        model = request.model or self._default_tts_model(request.mode)
        self._validate_model_id(model, expected_capability=capability)
        return model

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        model = request.model or self._default_models.asr
        if model is None:
            raise ProviderError(f"mimo provider {self.id} has no default ASR model")
        return model

    def _default_tts_model(self, mode: TTSMode) -> str:
        default_by_mode = {
            TTSMode.BUILTIN: self._default_models.tts_builtin,
            TTSMode.DESIGN: self._default_models.tts_design,
            TTSMode.CLONE: self._default_models.tts_clone,
        }
        model = default_by_mode[mode]
        if model is None:
            raise ProviderError(f"mimo provider {self.id} has no default TTS model for {mode}")
        return model

    def _validate_model_id(self, model: str, *, expected_capability: str | None = None) -> None:
        model_info = self._models_by_id.get(model)
        if model_info is None:
            raise ProviderError(f"unsupported MiMo model: {model}")
        if expected_capability is not None and model_info.capability != expected_capability:
            raise ProviderError(f"unsupported MiMo model for {expected_capability}: {model}")

    def _next_operation_id(self, operation: str) -> str:
        with self._operation_counter_lock:
            self._operation_counter += 1
            counter = self._operation_counter
        return f"mimo-{self._operation_prefix}-{operation}-{counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("mimo provider is closed")


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
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self.chat = _MissingCredentialsChat(api_key_env, provider_id=provider_id)


class _MissingCredentialsChat:
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self.completions = _MissingCredentialsCompletions(api_key_env, provider_id=provider_id)


class _MissingCredentialsCompletions:
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self._api_key_env = api_key_env
        self._provider_id = provider_id

    def create(self, **_: Any) -> Any:
        raise ProviderError(
            f"{self._api_key_env} is required for provider {self._provider_id}; "
            "set it in environment or .env"
        )


def _tts_metadata(
    request: TTSRequest,
    body: dict[str, Any],
    *,
    provider_id: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "model": body["model"],
        "operation": "tts",
        "output_format": request.output_format,
        "provider_id": provider_id,
        "clone_reference_text": request.clone_reference_text,
        "source_text": request.text,
        "style_instruction": request.style_instruction,
        "tts_mode": request.mode.value,
        "voice_description": request.voice_description,
        "voice_id": request.voice_id,
    }
    if request.mode == TTSMode.CLONE:
        if request.clone_sample_path is not None:
            metadata["uploaded_file_name_hash"] = _file_name_hash(request.clone_sample_path.name)
            metadata["uploaded_file_suffix"] = request.clone_sample_path.suffix
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


def _apply_mimo_provider_options(
    body: dict[str, Any],
    audio: dict[str, Any],
    options: Mapping[str, object],
) -> None:
    for key, value in options.items():
        if key.startswith("audio_"):
            audio_key = key.removeprefix("audio_")
            if audio_key in {"format", "voice"}:
                raise ProviderError(f"provider option {key} cannot override core audio field")
            audio[audio_key] = value
            continue
        if key in {"model", "messages", "audio"}:
            raise ProviderError(f"provider option {key} cannot override core request field")
        body[key] = value


def _file_name_hash(filename: str) -> str:
    return hashlib.sha256(filename.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
