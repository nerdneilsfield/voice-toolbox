from __future__ import annotations

import base64
import gzip
import hashlib
import json
import struct
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import DEFAULT_VOLCENGINE_BASE_URL, make_default_volcengine_provider_config
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
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment

TTS_RESOURCE_ID = "seed-tts-2.0"
ASR_RESOURCE_ID = "volc.seedasr.sauc.duration"
REQUEST_TIMEOUT_SECONDS = 300.0
DEFAULT_ASR_SEGMENT_MS = 200


class VolcengineHTTPClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def synthesize(self, body: Mapping[str, object], *, timeout: float) -> Iterable[dict[str, Any]]:
        request = urllib.request.Request(
            f"{self._base_url}/tts/unidirectional",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self._api_key,
                "X-Api-Resource-Id": TTS_RESOURCE_ID,
                "X-Api-Request-Id": str(uuid4()),
                "X-Control-Require-Usage-Tokens-Return": "*",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for raw_line in response:
                    if raw_line.strip():
                        yield json.loads(raw_line)
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                _http_error_message(exc.code),
                provider_id="volcengine",
                operation="tts",
                status_code=exc.code,
                metadata={"x_tt_logid": exc.headers.get("X-Tt-Logid", "")},
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("volcengine TTS connection failed") from exc


class VolcengineASRClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def transcribe(
        self,
        audio: bytes,
        *,
        options: Mapping[str, object],
        timeout: float,
    ) -> list[dict[str, Any]]:
        try:
            import websocket
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ProviderError("websocket-client is required for volcengine ASR") from exc

        connect_id = str(uuid4())
        headers = [
            f"X-Api-Key: {self._api_key}",
            f"X-Api-Resource-Id: {ASR_RESOURCE_ID}",
            f"X-Api-Request-Id: {connect_id}",
            f"X-Api-Connect-Id: {connect_id}",
        ]
        url = f"{self._base_url.replace('https://', 'wss://', 1)}/sauc/bigmodel_async"
        connection = websocket.create_connection(url, header=headers, timeout=timeout)
        responses: list[dict[str, Any]] = []
        try:
            sequence = 1
            connection.send_binary(_full_asr_request(sequence, options))
            initial = _parse_asr_response(connection.recv())
            if initial:
                responses.append(initial)
            segment_bytes = 16000 * 2 * DEFAULT_ASR_SEGMENT_MS // 1000
            chunks = [audio[index : index + segment_bytes] for index in range(0, len(audio), segment_bytes)]
            for index, chunk in enumerate(chunks):
                sequence += 1
                connection.send_binary(
                    _audio_asr_request(sequence, chunk, is_last=index == len(chunks) - 1)
                )
            while True:
                parsed = _parse_asr_response(connection.recv())
                if parsed:
                    responses.append(parsed)
                    if parsed.get("_last") or parsed.get("code", 0):
                        break
        finally:
            connection.close()
        return responses


class _MissingCredentialsClient:
    def __init__(self, api_key_env: str, *, provider_id: str) -> None:
        self._api_key_env = api_key_env
        self._provider_id = provider_id

    def _raise(self) -> None:
        raise ProviderError(
            f"{self._api_key_env} is required for provider {self._provider_id}; "
            "set it in environment or .env"
        )

    def synthesize(self, *_: object, **__: object) -> Iterable[dict[str, Any]]:
        self._raise()
        return []

    def transcribe(self, *_: object, **__: object) -> list[dict[str, Any]]:
        self._raise()
        return []


class VolcengineProvider:
    id = "volcengine"
    name = "Volcengine Speech"

    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
        tts_client: Any | None = None,
        asr_client: Any | None = None,
        tts_client_factory: Callable[..., Any] = VolcengineHTTPClient,
        asr_client_factory: Callable[..., Any] = VolcengineASRClient,
    ) -> None:
        resolved = config or make_default_volcengine_provider_config(
            base_url=base_url or DEFAULT_VOLCENGINE_BASE_URL
        )
        if base_url is not None:
            resolved = ConfiguredProvider.model_validate(
                {**resolved.model_dump(), "base_url": base_url}
            )
        if resolved.base_url is None or resolved.api_key_env is None:
            raise ProviderError(f"provider {resolved.id} requires base_url and api_key_env")
        self._config = resolved
        self.id = resolved.id
        self.name = resolved.name
        self._models_by_id = {model.id: model for model in resolved.models}
        self._default_models = resolved.default_models or ProviderDefaultModels()
        if tts_client is not None:
            self._tts_client = tts_client
        elif api_key:
            self._tts_client = tts_client_factory(api_key=api_key, base_url=resolved.base_url)
        else:
            self._tts_client = _MissingCredentialsClient(resolved.api_key_env, provider_id=self.id)
        if asr_client is not None:
            self._asr_client = asr_client
        elif api_key:
            self._asr_client = asr_client_factory(api_key=api_key, base_url=resolved.base_url)
        else:
            self._asr_client = _MissingCredentialsClient(resolved.api_key_env, provider_id=self.id)
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._operation_lock = threading.Lock()
        self._closed = False
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            if artifact_root is None:
                self._temp_dir = tempfile.TemporaryDirectory()
                artifact_root = self._temp_dir.name
            self._artifact_root = Path(artifact_root)
            self._artifact_store = ArtifactStore(self._artifact_root)

    def capabilities(self) -> set[str]:
        return {model.capability for model in self._config.models if model.capability is not None}

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

    def __enter__(self) -> VolcengineProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self._ensure_open()
        model = self._resolve_tts_model(request)
        if request.mode != TTSMode.BUILTIN:
            raise UnsupportedCapability("volcengine provider supports builtin TTS only")
        if not request.voice_id:
            raise ProviderError("volcengine TTS requires voice_id")
        if request.output_format not in {"wav", "mp3"}:
            raise ProviderError("volcengine TTS output format must be wav or mp3")
        params: dict[str, object] = {
            "text": request.text,
            "speaker": request.voice_id,
            "audio_params": {"format": request.output_format, "sample_rate": 24000},
        }
        _apply_options(params, request.provider_options, protected={"text", "speaker", "audio_params"})
        audio = bytearray()
        for event in self._tts_client.synthesize(
            {"req_params": params}, timeout=REQUEST_TIMEOUT_SECONDS
        ):
            code = event.get("code", 0)
            if code not in {0, 20000000}:
                raise ProviderError(f"volcengine TTS failed with code {code}")
            encoded = event.get("data")
            if encoded:
                try:
                    audio.extend(base64.b64decode(encoded, validate=True))
                except (ValueError, TypeError) as exc:
                    raise ProviderError("volcengine TTS returned invalid base64 audio") from exc
        if not audio:
            raise ProviderError("volcengine TTS response audio is empty")
        suffix = f".{request.output_format}"
        mime_type = "audio/mpeg" if request.output_format == "mp3" else "audio/wav"
        return ProviderAudioResult(audio=bytes(audio), mime_type=mime_type, suffix=suffix, model=model)

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        operation_id = self._next_operation_id("tts")
        started_at = datetime.now(UTC)
        result = self.synthesize_bytes(request)
        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=result.audio,
            mime_type=result.mime_type,
            suffix=result.suffix,
            metadata={
                **dict(artifact_metadata or {}),
                "model": result.model,
                "operation": "tts",
                "output_format": request.output_format,
                "provider_id": self.id,
                "source_text_length": len(request.text or ""),
                "tts_mode": request.mode.value,
                "voice_id": request.voice_id,
            },
        )
        self._record(operation_id, "tts", started_at, artifact.id)
        return artifact

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        self._ensure_open()
        self._resolve_asr_model(request)
        options: dict[str, object] = {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": False,
        }
        _apply_options(options, request.provider_options, protected={"model_name"})
        responses = self._asr_client.transcribe(
            request.audio_path.read_bytes(), options=options, timeout=REQUEST_TIMEOUT_SECONDS
        )
        return _extract_transcript(responses)

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
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
                **request.artifact_metadata,
                "language": request.language,
                "model": self._resolve_asr_model(request),
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name_hash": hashlib.sha256(
                    request.audio_path.name.encode("utf-8")
                ).hexdigest()[:12],
                "uploaded_file_suffix": request.audio_path.suffix,
            },
        )
        self._record(operation_id, "asr", started_at, artifact.id)
        return artifact

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        return self._resolve_model(
            request.model or self._default_models.tts_builtin, TTS_MODE_CAPABILITIES[request.mode]
        )

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        return self._resolve_model(request.model or self._default_models.asr, ASR_CAPABILITY)

    def _resolve_model(self, model: str | None, capability: str) -> str:
        if model is None:
            raise ProviderError(f"volcengine provider {self.id} has no default {capability} model")
        info = self._models_by_id.get(model)
        if info is None or info.capability != capability:
            raise ProviderError(f"unsupported Volcengine model for {capability}: {model}")
        expected = TTS_RESOURCE_ID if capability == "tts.builtin" else ASR_RESOURCE_ID
        if model != expected:
            raise ProviderError(f"Volcengine {capability} Resource-Id must be {expected}")
        return model

    def _next_operation_id(self, operation: str) -> str:
        with self._operation_lock:
            self._operation_counter += 1
            counter = self._operation_counter
        return f"volcengine-{self._operation_prefix}-{operation}-{counter}"

    def _record(self, operation_id: str, operation: str, started_at: datetime, artifact_id: str) -> None:
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation=operation,
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact_id],
            )
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("volcengine provider is closed")


def _apply_options(target: dict[str, object], options: Mapping[str, object], *, protected: set[str]) -> None:
    for key, value in options.items():
        if key in protected:
            raise ProviderError(f"provider option {key} cannot override core request field")
        target[key] = value


def _full_asr_request(sequence: int, options: Mapping[str, object]) -> bytes:
    payload = {
        "user": {"uid": "voice-toolbox"},
        "audio": {"format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": dict(options),
    }
    return _asr_frame(0b0001, 0b0001, sequence, json.dumps(payload).encode("utf-8"))


def _audio_asr_request(sequence: int, audio: bytes, *, is_last: bool) -> bytes:
    return _asr_frame(0b0010, 0b0011 if is_last else 0b0001, -sequence if is_last else sequence, audio)


def _asr_frame(message_type: int, flags: int, sequence: int, payload: bytes) -> bytes:
    compressed = gzip.compress(payload)
    header = bytes([(0b0001 << 4) | 1, (message_type << 4) | flags, (0b0001 << 4) | 0b0001, 0])
    return header + struct.pack(">iI", sequence, len(compressed)) + compressed


def _parse_asr_response(message: Any) -> dict[str, Any]:
    if not isinstance(message, bytes) or len(message) < 4:
        raise ProviderError("volcengine ASR returned invalid WebSocket message")
    header_size = (message[0] & 0x0F) * 4
    message_type = message[1] >> 4
    flags = message[1] & 0x0F
    compression = message[2] & 0x0F
    payload = message[header_size:]
    if flags & 0x01:
        payload = payload[4:]
    if flags & 0x04:
        payload = payload[4:]
    code = 0
    if message_type == 0b1001:
        payload = payload[4:]
    elif message_type == 0b1111:
        code = struct.unpack(">i", payload[:4])[0]
        payload = payload[8:]
    if compression == 0b0001 and payload:
        payload = gzip.decompress(payload)
    result = json.loads(payload.decode("utf-8")) if payload else {}
    if not isinstance(result, dict):
        raise ProviderError("volcengine ASR response payload must be an object")
    result["_last"] = bool(flags & 0x02)
    if code:
        result["code"] = code
    return result


def _extract_transcript(responses: Iterable[Mapping[str, Any]]) -> TranscriptPayload:
    latest: Mapping[str, Any] = {}
    for response in responses:
        if response.get("code", 0):
            raise ProviderError(f"volcengine ASR failed with code {response['code']}")
        candidate = response.get("result")
        if isinstance(candidate, Mapping):
            latest = candidate
        elif "text" in response:
            latest = response
    text = latest.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("volcengine ASR response transcript is empty")
    segments: list[TranscriptSegment] = []
    utterances = latest.get("utterances", [])
    if isinstance(utterances, list):
        for utterance in utterances:
            if not isinstance(utterance, Mapping) or not isinstance(utterance.get("text"), str):
                continue
            start = utterance.get("start_time")
            end = utterance.get("end_time")
            segments.append(
                TranscriptSegment(
                    text=utterance["text"],
                    start_seconds=float(start) / 1000 if isinstance(start, int | float) else None,
                    end_seconds=float(end) / 1000 if isinstance(end, int | float) else None,
                )
            )
    return TranscriptPayload(text=text, segments=segments)


def _http_error_message(status: int) -> str:
    if status in {401, 403}:
        return "volcengine API authentication failed; verify dedicated Agent Plan API key"
    if status == 429:
        return "volcengine API quota exceeded; enable overage post-payment or retry later"
    return f"volcengine API request failed with status {status}"
