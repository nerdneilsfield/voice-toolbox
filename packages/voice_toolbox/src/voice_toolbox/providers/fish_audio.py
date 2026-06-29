from __future__ import annotations

import base64
import binascii
import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

import msgpack

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import (
    DEFAULT_FISH_AUDIO_BASE_URL,
    make_default_fish_audio_provider_config,
)
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TTSMode,
    TTSRequest,
    TranscriptArtifact,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES

GENERATION_TIMEOUT_SECONDS = 300.0
TTS_TIMEOUT_SECONDS = GENERATION_TIMEOUT_SECONDS
ASR_TIMEOUT_SECONDS = GENERATION_TIMEOUT_SECONDS
RATE_LIMIT_BACKOFF_SECONDS = 0.25
FISH_DESIGN_REFERENCE_TEXT_MAX_CHARS = 150
FISH_VOICE_DESIGN_MODEL = "voice-design-1"


@dataclass(frozen=True)
class FishHTTPResponse:
    status_code: int
    content: bytes
    headers: Mapping[str, str]


class FishAudioProvider:
    id = "fish-audio"
    name = "Fish Audio"

    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved_config = config or make_default_fish_audio_provider_config(
            base_url=base_url or DEFAULT_FISH_AUDIO_BASE_URL
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
            factory = client_factory or FishHTTPClient
            self._client = factory(api_key=api_key, base_url=resolved_config.base_url)
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

    def __enter__(self) -> FishAudioProvider:
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
        model = self._resolve_tts_model(request)
        if request.mode == TTSMode.BUILTIN:
            return {
                "model": _fish_api_model_id(model),
                "json": {
                    "text": request.text,
                    "format": request.output_format,
                    "reference_id": request.voice_id,
                    "normalize": True,
                },
            }
        if request.mode == TTSMode.DESIGN:
            body: dict[str, Any] = {"instruction": request.voice_description}
            if request.text:
                if len(request.text) > FISH_DESIGN_REFERENCE_TEXT_MAX_CHARS:
                    raise ProviderError("fish_audio voice design reference_text exceeds 150 chars")
                body["reference_text"] = request.text
            return {"model": FISH_VOICE_DESIGN_MODEL, "json": body}
        if request.mode == TTSMode.CLONE:
            self._validate_clone_request(request)
            if request.clone_sample_path is None:
                raise ProviderError("fish_audio clone mode requires clone sample path")
            return {
                "model": _fish_api_model_id(model),
                "msgpack": {
                    "text": request.text,
                    "format": request.output_format,
                    "normalize": True,
                    "references": [
                        {
                            "audio": request.clone_sample_path.read_bytes(),
                            "text": request.clone_reference_text,
                        }
                    ],
                },
            }
        raise UnsupportedCapability(
            f"fish_audio provider does not support TTS mode: {request.mode}"
        )

    def _build_asr_request(self, request: ASRRequest) -> dict[str, Any]:
        model = self._resolve_asr_model(request)
        self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
        return {
            "model": model,
            "files": {
                "audio": (
                    request.audio_path.name,
                    request.audio_path.read_bytes(),
                    request.mime_type,
                )
            },
            "fields": {"language": request.language} if request.language != "auto" else {},
        }

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
        if request.mode == TTSMode.DESIGN:
            response = self._post_json(
                "/v1/voice-design",
                body["json"],
                timeout=TTS_TIMEOUT_SECONDS,
                model=body["model"],
            )
            audio = _extract_design_audio(response)
        elif request.mode == TTSMode.CLONE:
            response = self._post_msgpack(
                "/v1/tts",
                body["msgpack"],
                timeout=TTS_TIMEOUT_SECONDS,
                model=body["model"],
            )
            audio = response.content
        else:
            response = self._post_json(
                "/v1/tts",
                body["json"],
                timeout=TTS_TIMEOUT_SECONDS,
                model=body["model"],
            )
            audio = response.content
        if not audio:
            raise ProviderError("fish_audio response audio is empty")
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
        body = self._build_asr_request(request)
        response = self._post_multipart(
            "/v1/asr",
            files=body["files"],
            fields=body["fields"],
            timeout=ASR_TIMEOUT_SECONDS,
        )
        transcript = _extract_asr_text(response)

        artifact = self._artifact_store.write_transcript(
            operation_id=operation_id,
            provider_id=self.id,
            operation="asr",
            text=transcript,
            metadata={
                "base64_size": request.base64_size,
                "language": request.language,
                "model": body["model"],
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name": request.audio_path.name,
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

    def _post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float,
        model: str,
    ) -> FishHTTPResponse:
        return self._post_with_errors(
            path,
            json_body=body,
            headers={"model": model},
            timeout=timeout,
        )

    def _post_msgpack(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float,
        model: str,
    ) -> FishHTTPResponse:
        return self._post_with_errors(
            path,
            msgpack_body=body,
            headers={"model": model},
            timeout=timeout,
        )

    def _post_multipart(
        self,
        path: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        fields: dict[str, str],
        timeout: float,
    ) -> FishHTTPResponse:
        return self._post_with_errors(path, files=files, fields=fields, timeout=timeout)

    def _post_with_errors(
        self,
        path: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        msgpack_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        fields: dict[str, str] | None = None,
    ) -> FishHTTPResponse:
        for attempt in range(2):
            try:
                response = self._client.post(
                    path,
                    headers=headers or {},
                    json_body=json_body,
                    msgpack_body=msgpack_body,
                    files=files,
                    fields=fields or {},
                    timeout=timeout,
                )
            except TimeoutError as exc:
                raise ProviderError("fish_audio API request timed out") from exc
            except (OSError, urllib.error.URLError) as exc:
                raise ProviderError("fish_audio API connection failed") from exc
            if response.status_code == 429 and attempt == 0:
                self._sleep_func(RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if response.status_code == 429:
                raise ProviderError("fish_audio API rate limit exceeded")
            if response.status_code >= 400:
                raise ProviderError(_http_error_message(response))
            return response
        raise ProviderError("fish_audio API rate limit exceeded")

    def _ensure_tts_capability(self, request: TTSRequest) -> None:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in self.capabilities():
            raise UnsupportedCapability(
                f"fish_audio provider does not support capability: {capability}"
            )

    def _validate_tts_request(self, request: TTSRequest) -> None:
        if request.output_format != "wav":
            raise ProviderError("fish_audio TTS output format must be wav")

    def _validate_clone_request(self, request: TTSRequest) -> None:
        if request.clone_sample_path is None or request.clone_mime_type is None:
            raise ProviderError("fish_audio clone mode requires clone sample path and MIME type")
        if not request.clone_reference_text:
            raise ProviderError("fish_audio clone mode requires clone_reference_text")

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        model = request.model or self._default_tts_model(request.mode)
        self._validate_model_id(model, expected_capability=capability)
        return model

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        model = request.model or self._default_models.asr
        if model is None:
            raise ProviderError(f"fish_audio provider {self.id} has no default ASR model")
        return model

    def _default_tts_model(self, mode: TTSMode) -> str:
        default_by_mode = {
            TTSMode.BUILTIN: self._default_models.tts_builtin,
            TTSMode.DESIGN: self._default_models.tts_design,
            TTSMode.CLONE: self._default_models.tts_clone,
        }
        model = default_by_mode[mode]
        if model is None:
            raise ProviderError(
                f"fish_audio provider {self.id} has no default TTS model for {mode}"
            )
        return model

    def _validate_model_id(self, model: str, *, expected_capability: str | None = None) -> None:
        model_info = self._models_by_id.get(model)
        if model_info is None:
            raise ProviderError(f"unsupported Fish Audio model: {model}")
        if expected_capability is not None and model_info.capability != expected_capability:
            raise ProviderError(f"unsupported Fish Audio model for {expected_capability}: {model}")

    def _next_operation_id(self, operation: str) -> str:
        with self._operation_counter_lock:
            self._operation_counter += 1
            counter = self._operation_counter
        return f"{self.id}-{self._operation_prefix}-{operation}-{counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("fish_audio provider is closed")


class FishHTTPClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        msgpack_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        fields: dict[str, str] | None = None,
        timeout: float,
    ) -> FishHTTPResponse:
        request_headers = {
            "Authorization": f"Bearer {self._api_key}",
            **dict(headers or {}),
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif msgpack_body is not None:
            data = msgpack.packb(msgpack_body, use_bin_type=True)
            request_headers["Content-Type"] = "application/msgpack"
        elif files is not None:
            data, content_type = _encode_multipart(fields or {}, files)
            request_headers["Content-Type"] = content_type
        else:
            data = b""
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=data,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return FishHTTPResponse(
                    status_code=response.status,
                    content=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return FishHTTPResponse(
                status_code=exc.code,
                content=exc.read(),
                headers=dict(exc.headers.items()),
            )


class _MissingCredentialsClient:
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self._api_key_env = api_key_env
        self._provider_id = provider_id

    def post(self, *_: Any, **__: Any) -> FishHTTPResponse:
        raise ProviderError(
            f"{self._api_key_env} is required for provider {self._provider_id}; "
            "set it in environment or .env"
        )


def _fish_api_model_id(model: str) -> str:
    if model in {"s1-design", "s1-clone"}:
        return "s1"
    return model


def _encode_multipart(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"voice-toolbox-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, content, mime_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _extract_design_audio(response: FishHTTPResponse) -> bytes:
    payload = _json_response(response)
    for candidate in _walk_audio_candidates(payload):
        audio = _decode_audio_base64(candidate)
        if audio:
            return audio
    raise ProviderError("fish_audio voice design response is missing audio")


def _walk_audio_candidates(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key in ("audio", "audio_base64", "audio_data", "data"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                found.append(candidate)
        for key in ("voices", "audios", "candidates", "results", "data"):
            nested = value.get(key)
            if nested is not None:
                found.extend(_walk_audio_candidates(nested))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_audio_candidates(item))
    return found


def _decode_audio_base64(value: str) -> bytes | None:
    payload = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None


def _extract_asr_text(response: FishHTTPResponse) -> str:
    payload = _json_response(response)
    if isinstance(payload, dict):
        for key in ("text", "transcript", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    if isinstance(payload, str):
        return payload
    raise ProviderError("fish_audio ASR response is missing transcript text")


def _json_response(response: FishHTTPResponse) -> Any:
    try:
        return json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("fish_audio response is not valid JSON") from exc


def _http_error_message(response: FishHTTPResponse) -> str:
    if response.status_code in {401, 403}:
        return "fish_audio API authentication failed"
    if response.status_code == 402:
        return "fish_audio API payment required or credits exhausted"
    return f"fish_audio API request failed with status {response.status_code}"


def _tts_metadata(
    request: TTSRequest,
    body: dict[str, Any],
    *,
    provider_id: str,
) -> dict[str, Any]:
    return {
        "model": body["model"],
        "operation": "tts",
        "output_format": request.output_format,
        "provider_id": provider_id,
        "source_text": request.text,
        "style_instruction": request.style_instruction,
        "tts_mode": request.mode.value,
        "voice_description": request.voice_description,
        "clone_reference_text": request.clone_reference_text,
        "voice_id": request.voice_id,
    }
