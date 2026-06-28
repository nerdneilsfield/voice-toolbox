from __future__ import annotations

import base64
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

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import (
    DEFAULT_OPENROUTER_BASE_URL,
    make_default_openrouter_provider_config,
)
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    OperationResult,
    OperationStatus,
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
OPENROUTER_TTS_RESPONSE_FORMAT = "mp3"


@dataclass(frozen=True)
class OpenRouterHTTPResponse:
    status_code: int
    content: bytes
    headers: Mapping[str, str]


class OpenRouterProvider:
    id = "openrouter"
    name = "OpenRouter"

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
        resolved_config = config or make_default_openrouter_provider_config(
            base_url=base_url or DEFAULT_OPENROUTER_BASE_URL
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
            factory = client_factory or OpenRouterHTTPClient
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

    def __enter__(self) -> OpenRouterProvider:
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
        return {
            "model": self._resolve_tts_model(request),
            "input": request.text,
            "voice": request.voice_id,
            "response_format": OPENROUTER_TTS_RESPONSE_FORMAT,
        }

    def _build_asr_body(self, request: ASRRequest) -> dict[str, Any]:
        model = self._resolve_asr_model(request)
        self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
        body: dict[str, Any] = {
            "model": model,
            "input_audio": {
                "data": base64.b64encode(request.audio_path.read_bytes()).decode("ascii"),
                "format": _audio_format_from_mime(request.mime_type),
            },
        }
        if request.language != "auto":
            body["language"] = request.language
        return body

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        self._ensure_open()
        self._ensure_tts_capability(request)
        operation_id = self._next_operation_id("tts")
        started_at = datetime.now(UTC)
        body = self._build_tts_body(request)
        response = self._post_json("/audio/speech", body, timeout=TTS_TIMEOUT_SECONDS)
        if not response.content:
            raise ProviderError("openrouter TTS response audio is empty")

        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=response.content,
            mime_type="audio/mpeg",
            suffix=".mp3",
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

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        self._ensure_open()
        operation_id = self._next_operation_id("asr")
        started_at = datetime.now(UTC)
        body = self._build_asr_body(request)
        response = self._post_json(
            "/audio/transcriptions",
            body,
            timeout=ASR_TIMEOUT_SECONDS,
        )
        transcript = _extract_transcript(response)

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
    ) -> OpenRouterHTTPResponse:
        for attempt in range(2):
            try:
                response = self._client.post_json(path, body, timeout=timeout)
            except TimeoutError as exc:
                raise ProviderError("openrouter API request timed out") from exc
            except (OSError, urllib.error.URLError) as exc:
                raise ProviderError("openrouter API connection failed") from exc
            if response.status_code == 429 and attempt == 0:
                self._sleep_func(RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if response.status_code == 429:
                raise ProviderError("openrouter API rate limit exceeded")
            if response.status_code >= 400:
                raise ProviderError(_http_error_message(response))
            return response
        raise ProviderError("openrouter API request failed")

    def _ensure_tts_capability(self, request: TTSRequest) -> None:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in self.capabilities():
            raise UnsupportedCapability(
                f"openrouter provider does not support capability: {capability}"
            )

    def _validate_tts_request(self, request: TTSRequest) -> None:
        if request.mode != TTSMode.BUILTIN:
            raise UnsupportedCapability(
                f"openrouter provider does not support TTS mode: {request.mode}"
            )
        if not request.voice_id:
            raise ProviderError("openrouter TTS requires voice_id")

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        model = request.model or self._default_models.tts_builtin
        if model is None:
            raise ProviderError(f"openrouter provider {self.id} has no default TTS model")
        self._validate_model_id(model, expected_capability=TTS_MODE_CAPABILITIES[request.mode])
        return model

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        model = request.model or self._default_models.asr
        if model is None:
            raise ProviderError(f"openrouter provider {self.id} has no default ASR model")
        return model

    def _validate_model_id(self, model: str, *, expected_capability: str | None = None) -> None:
        model_info = self._models_by_id.get(model)
        if model_info is None:
            raise ProviderError(f"unsupported OpenRouter model: {model}")
        if expected_capability is not None and model_info.capability != expected_capability:
            raise ProviderError(f"unsupported OpenRouter model for {expected_capability}: {model}")

    def _next_operation_id(self, operation: str) -> str:
        with self._operation_counter_lock:
            self._operation_counter += 1
            counter = self._operation_counter
        return f"{self.id}-{self._operation_prefix}-{operation}-{counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("openrouter provider is closed")


class OpenRouterHTTPClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float,
    ) -> OpenRouterHTTPResponse:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return OpenRouterHTTPResponse(
                    status_code=response.status,
                    content=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return OpenRouterHTTPResponse(
                status_code=exc.code,
                content=exc.read(),
                headers=dict(exc.headers.items()),
            )


class _MissingCredentialsClient:
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self._api_key_env = api_key_env
        self._provider_id = provider_id

    def post_json(self, *_: Any, **__: Any) -> OpenRouterHTTPResponse:
        raise ProviderError(
            f"{self._api_key_env} is required for provider {self._provider_id}; "
            "set it in environment or .env"
        )


def _audio_format_from_mime(mime_type: str) -> str:
    if mime_type == "audio/wav":
        return "wav"
    if mime_type in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    raise ProviderError(f"unsupported OpenRouter audio MIME type: {mime_type}")


def _extract_transcript(response: OpenRouterHTTPResponse) -> str:
    try:
        payload = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("openrouter STT response is not valid JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        return payload["text"]
    raise ProviderError("openrouter STT response is missing transcript text")


def _http_error_message(response: OpenRouterHTTPResponse) -> str:
    if response.status_code in {401, 403}:
        return "openrouter API authentication failed"
    if response.status_code == 402:
        return "openrouter API payment required or credits exhausted"
    return f"openrouter API request failed with status {response.status_code}"


def _tts_metadata(
    request: TTSRequest,
    body: dict[str, Any],
    *,
    provider_id: str,
) -> dict[str, Any]:
    return {
        "model": body["model"],
        "operation": "tts",
        "output_format": body["response_format"],
        "provider_id": provider_id,
        "source_text": request.text,
        "style_instruction": request.style_instruction,
        "tts_mode": request.mode.value,
        "voice_id": request.voice_id,
    }
