from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voice_toolbox.models import AudioArtifact, OperationResult, TranscriptArtifact
from voice_toolbox.storage import MetadataStore

ALLOWED_METADATA_KEYS = {
    "base64_size",
    "capability",
    "chunking_audio_durations_ms",
    "chunking_chunk_count",
    "chunking_dedupe_removed_chars",
    "chunking_enabled",
    "chunking_max_chars",
    "chunking_mode",
    "chunking_operation",
    "chunking_overlap_ms",
    "chunking_repeated_leading_audio_tags",
    "chunking_silence_ms",
    "chunking_strategy",
    "chunking_target_seconds",
    "chunking_text_lengths",
    "chunking_transcript_lengths",
    "consent_confirmed",
    "input_length",
    "language",
    "mime_type",
    "model",
    "normalization_changed",
    "normalization_ignored_options",
    "normalization_input_format",
    "normalization_input_length",
    "normalization_normalizer_id",
    "normalization_output_format",
    "normalization_output_length",
    "operation",
    "output_length",
    "output_format",
    "provider_id",
    "provider_option_keys",
    "provider_option_safe_values",
    "raw_byte_size",
    "source_file_name_hash",
    "source_file_suffix",
    "source_kind",
    "source_text_raw_char_count",
    "transcript_download_formats",
    "transcript_has_speakers",
    "transcript_has_timestamps",
    "transcript_segment_count",
    "tts_mode",
    "uploaded_file_mime_type",
    "uploaded_file_name_hash",
    "uploaded_file_suffix",
    "uploaded_text_file_name_hash",
    "uploaded_text_file_size_bytes",
    "uploaded_text_file_suffix",
    "voice_id",
}
LENGTH_METADATA_KEYS = {
    "clone_reference_text",
    "source_text",
    "source_text_preview",
    "style_instruction",
    "voice_description",
}
SAFE_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}

    for key, value in metadata.items():
        if key in LENGTH_METADATA_KEYS:
            redacted[f"{key}_length"] = len(str(value)) if value is not None else 0
            continue
        if key in ALLOWED_METADATA_KEYS:
            redacted[key] = value

    return redacted


class ArtifactStore:
    def __init__(self, root: Path | str, metadata_store: MetadataStore | None = None) -> None:
        self.root = Path(root)
        self._metadata_store = metadata_store or MetadataStore(
            self.root / "data" / "voice_toolbox.sqlite"
        )

    def write_audio(
        self,
        *,
        operation_id: str,
        provider_id: str,
        operation: str,
        audio: bytes,
        mime_type: str = "audio/wav",
        suffix: str = ".wav",
        metadata: dict[str, Any] | None = None,
    ) -> AudioArtifact:
        self._validate_operation_id(operation_id)
        if not suffix.startswith(".") or "/" in suffix:
            raise ValueError("audio suffix must be a file extension")
        path = self._artifact_dir() / f"{operation_id}{suffix}"
        self._ensure_sidecar_available(path)
        with path.open("xb") as audio_file:
            audio_file.write(audio)
        path.chmod(0o600)
        artifact = AudioArtifact(
            id=operation_id,
            provider_id=provider_id,
            operation=operation,
            path=path,
            mime_type=mime_type,
            metadata=redact_metadata(metadata or {}),
        )
        self._write_sidecar(artifact)
        self._metadata_store.insert_artifact(artifact)
        return artifact

    def write_transcript(
        self,
        *,
        operation_id: str,
        provider_id: str,
        operation: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> TranscriptArtifact:
        self._validate_operation_id(operation_id)
        path = self._artifact_dir() / f"{operation_id}.txt"
        self._ensure_sidecar_available(path)
        with path.open("x", encoding="utf-8") as transcript_file:
            transcript_file.write(text)
        path.chmod(0o600)
        artifact = TranscriptArtifact(
            id=operation_id,
            provider_id=provider_id,
            operation=operation,
            path=path,
            mime_type="text/plain; charset=utf-8",
            metadata=redact_metadata(metadata or {}),
        )
        self._write_sidecar(artifact)
        self._metadata_store.insert_artifact(artifact)
        return artifact

    def record_operation(self, operation: OperationResult) -> None:
        self._metadata_store.insert_operation(operation)

    def _artifact_dir(self) -> Path:
        path = self.root / "data" / "artifacts" / datetime.now(UTC).strftime("%Y%m%d")
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
        return path

    def _validate_operation_id(self, operation_id: str) -> None:
        if not SAFE_OPERATION_ID_PATTERN.fullmatch(operation_id):
            raise ValueError(
                "operation_id must contain only letters, numbers, underscores, or hyphens"
            )

    def _ensure_sidecar_available(self, artifact_path: Path) -> None:
        sidecar_path = artifact_path.with_suffix(".json")
        if sidecar_path.exists():
            raise FileExistsError(f"artifact sidecar already exists: {sidecar_path}")

    def _write_sidecar(self, artifact: AudioArtifact | TranscriptArtifact) -> None:
        sidecar_path = artifact.path.with_suffix(".json")
        if sidecar_path.exists():
            raise FileExistsError(f"artifact sidecar already exists: {sidecar_path}")
        payload = artifact.model_dump(mode="json", exclude={"path"})
        with sidecar_path.open("x", encoding="utf-8") as sidecar_file:
            sidecar_file.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        sidecar_path.chmod(0o600)
