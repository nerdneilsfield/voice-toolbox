from __future__ import annotations

import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from voice_toolbox.artifacts import ArtifactStore
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


class FakeProvider:
    id = "fake"
    name = "Fake Provider"

    def __init__(
        self,
        *,
        capabilities: set[str] | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
    ) -> None:
        self._capabilities = (
            {"tts.builtin", "tts.design", "tts.clone", ASR_CAPABILITY}
            if capabilities is None
            else set(capabilities)
        )
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._closed = False
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
        return set(self._capabilities)

    def list_models(self) -> list[ModelInfo]:
        models = [
            ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
            ModelInfo(id="fake-design", name="Fake Voice Design", capability="tts.design"),
            ModelInfo(id="fake-clone", name="Fake Voice Clone", capability="tts.clone"),
            ModelInfo(id="fake-asr", name="Fake ASR", capability=ASR_CAPABILITY),
        ]
        return [model for model in models if model.capability in self._capabilities]

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id="Mia", name="Mia", language="en", gender="female"),
            VoiceInfo(id="Chen", name="Chen", language="zh", gender="male"),
        ]

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def close(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
        self._closed = True

    def __enter__(self) -> FakeProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

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
        metadata = {
            "model": request.model or "fake-tts",
            "operation": "tts",
            "output_format": request.output_format,
            "provider_id": self.id,
            "source_text_length": len(request.text or ""),
            "tts_mode": request.mode.value,
            "voice_id": request.voice_id,
            **dict(artifact_metadata or {}),
        }
        if request.voice_description:
            metadata["voice_description_length"] = len(request.voice_description)
        if request.style_instruction:
            metadata["style_instruction_length"] = len(request.style_instruction)
        if request.clone_reference_text:
            metadata["clone_reference_text_length"] = len(request.clone_reference_text)
        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=result.audio,
            mime_type=result.mime_type,
            suffix=result.suffix,
            metadata=metadata,
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
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in self._capabilities:
            raise UnsupportedCapability(f"fake provider does not support capability: {capability}")
        return ProviderAudioResult(
            audio=self._audio_bytes(request),
            mime_type="audio/wav",
            suffix=".wav",
            model=request.model or "fake-tts",
        )

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        self._ensure_open()
        if ASR_CAPABILITY not in self._capabilities:
            raise UnsupportedCapability(
                f"fake provider does not support capability: {ASR_CAPABILITY}"
            )

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
                "model": request.model or "fake-asr",
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
        if ASR_CAPABILITY not in self._capabilities:
            raise UnsupportedCapability(
                f"fake provider does not support capability: {ASR_CAPABILITY}"
            )
        return TranscriptPayload(text="fake transcript")

    def _audio_bytes(self, request: TTSRequest) -> bytes:
        if request.mode == TTSMode.BUILTIN:
            return f"FAKE_WAV:{request.text}:{request.voice_id}".encode()
        if request.mode == TTSMode.DESIGN:
            return f"FAKE_WAV:{request.text or ''}:{request.voice_description}".encode()
        return f"FAKE_WAV:{request.text}:{request.clone_mime_type}".encode()

    def _next_operation_id(self, operation: str) -> str:
        self._operation_counter += 1
        return f"fake-{self._operation_prefix}-{operation}-{self._operation_counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("fake provider is closed")


def _file_name_hash(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:12]
