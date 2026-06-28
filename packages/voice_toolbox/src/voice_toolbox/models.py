from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TTSOutputFormat = Literal["wav", "mp3"]


class TTSMode(StrEnum):
    BUILTIN = "builtin"
    DESIGN = "design"
    CLONE = "clone"


class ArtifactKind(StrEnum):
    AUDIO = "audio"
    TRANSCRIPT = "transcript"


class OperationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderConfig(BaseModel):
    """Legacy single-provider settings view; prefer AppConfig for new code."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = "mimo"
    base_url: str = "https://api.xiaomimimo.com/v1"
    api_key_env: str = "MIMO_API_KEY"
    default_output_format: Literal["wav"] = "wav"
    api_host: str = "127.0.0.1"
    api_port: int = 8000


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    capability: str | None = None
    note: str | None = None


class VoiceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    note: str | None = None


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = "mimo"
    mode: TTSMode
    model: str | None = None
    text: str | None = None
    style_instruction: str | None = None
    output_format: TTSOutputFormat = "wav"
    voice_id: str | None = None
    voice_description: str | None = None
    optimize_text_preview: bool = False
    clone_sample_path: Path | None = None
    clone_mime_type: str | None = None
    clone_raw_byte_size: int | None = Field(default=None, ge=0)
    clone_base64_size: int | None = Field(default=None, ge=0)
    clone_reference_text: str | None = None
    consent_confirmed: bool = False

    @field_validator(
        "provider_id",
        "model",
        "text",
        "style_instruction",
        "voice_id",
        "voice_description",
        "clone_mime_type",
        "clone_reference_text",
        mode="after",
    )
    @classmethod
    def strip_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> TTSRequest:
        if self.mode == TTSMode.BUILTIN:
            if not self.text:
                raise ValueError("builtin mode requires text")
            if not self.voice_id:
                raise ValueError("builtin mode requires voice_id")

        if self.mode == TTSMode.DESIGN:
            if not self.voice_description:
                raise ValueError("design mode requires voice_description")
            if not self.optimize_text_preview and not self.text:
                raise ValueError("design mode requires text unless optimize_text_preview is true")

        if self.mode == TTSMode.CLONE:
            if not self.text:
                raise ValueError("clone mode requires text")
            if self.clone_sample_path is None:
                raise ValueError("clone mode requires clone_sample_path")
            if not self.clone_mime_type:
                raise ValueError("clone mode requires clone_mime_type")
            if not self.consent_confirmed:
                raise ValueError("clone mode requires consent_confirmed")

        return self


class ASRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = "mimo"
    model: str | None = None
    audio_path: Path
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp3"]
    raw_byte_size: int = Field(ge=0)
    base64_size: int = Field(ge=0)
    language: Literal["auto", "zh", "en"] = "auto"

    @field_validator("provider_id", "model", mode="after")
    @classmethod
    def strip_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ArtifactKind
    provider_id: str
    operation: str
    path: Path
    mime_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AudioArtifact(Artifact):
    kind: Literal[ArtifactKind.AUDIO] = ArtifactKind.AUDIO


class TranscriptArtifact(Artifact):
    kind: Literal[ArtifactKind.TRANSCRIPT] = ArtifactKind.TRANSCRIPT


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    operation: str
    status: OperationStatus
    started_at: datetime
    finished_at: datetime
    artifact_ids: list[str] = Field(default_factory=list)
    error_summary: str | None = None
