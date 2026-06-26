from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voice_toolbox.models import AudioArtifact, TranscriptArtifact

ALLOWED_METADATA_KEYS = {
    "base64_size",
    "consent_confirmed",
    "language",
    "model",
    "operation",
    "output_format",
    "provider_id",
    "raw_byte_size",
    "tts_mode",
    "uploaded_file_mime_type",
    "uploaded_file_name",
    "voice_id",
}
LENGTH_METADATA_KEYS = {"source_text", "style_instruction", "voice_description"}
SAFE_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}

    for key, value in metadata.items():
        if key in LENGTH_METADATA_KEYS:
            redacted[f"{key}_length"] = len(value) if value is not None else 0
            continue
        if key in ALLOWED_METADATA_KEYS:
            redacted[key] = value

    return redacted


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write_audio(
        self,
        *,
        operation_id: str,
        provider_id: str,
        operation: str,
        audio: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> AudioArtifact:
        self._validate_operation_id(operation_id)
        path = self._artifact_dir() / f"{operation_id}.wav"
        self._ensure_available(path)
        path.write_bytes(audio)
        artifact = AudioArtifact(
            id=operation_id,
            provider_id=provider_id,
            operation=operation,
            path=path,
            mime_type="audio/wav",
            metadata=redact_metadata(metadata or {}),
        )
        self._write_sidecar(artifact)
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
        self._ensure_available(path)
        path.write_text(text, encoding="utf-8")
        artifact = TranscriptArtifact(
            id=operation_id,
            provider_id=provider_id,
            operation=operation,
            path=path,
            mime_type="text/plain; charset=utf-8",
            metadata=redact_metadata(metadata or {}),
        )
        self._write_sidecar(artifact)
        return artifact

    def _artifact_dir(self) -> Path:
        path = self.root / "data" / "artifacts" / datetime.now(UTC).strftime("%Y%m%d")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _validate_operation_id(self, operation_id: str) -> None:
        if not SAFE_OPERATION_ID_PATTERN.fullmatch(operation_id):
            raise ValueError("operation_id must contain only letters, numbers, underscores, or hyphens")

    def _ensure_available(self, artifact_path: Path) -> None:
        sidecar_path = artifact_path.with_suffix(".json")
        if artifact_path.exists():
            raise FileExistsError(f"artifact already exists: {artifact_path}")
        if sidecar_path.exists():
            raise FileExistsError(f"artifact sidecar already exists: {sidecar_path}")

    def _write_sidecar(self, artifact: AudioArtifact | TranscriptArtifact) -> None:
        sidecar_path = artifact.path.with_suffix(".json")
        if sidecar_path.exists():
            raise FileExistsError(f"artifact sidecar already exists: {sidecar_path}")
        payload = artifact.model_dump(mode="json")
        sidecar_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
