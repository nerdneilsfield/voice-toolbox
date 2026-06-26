from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voice_toolbox.models import AudioArtifact, TranscriptArtifact

SENSITIVE_METADATA_KEYS = {
    "api_key",
    "audio_bytes",
    "base64",
    "base64_payload",
    "data_url",
    "raw_audio",
}
LENGTH_METADATA_KEYS = {"source_text", "style_instruction", "voice_description"}


def redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}

    for key, value in metadata.items():
        if key in SENSITIVE_METADATA_KEYS:
            continue
        if key in LENGTH_METADATA_KEYS:
            redacted[f"{key}_length"] = len(value) if value is not None else 0
            continue
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
        path = self._artifact_dir() / f"{operation_id}.wav"
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
        path = self._artifact_dir() / f"{operation_id}.txt"
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

    def _write_sidecar(self, artifact: AudioArtifact | TranscriptArtifact) -> None:
        sidecar_path = artifact.path.with_suffix(".json")
        payload = artifact.model_dump(mode="json")
        sidecar_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
