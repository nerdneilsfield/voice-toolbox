from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TTSOutputFormat = Literal["wav", "mp3"]
ProviderOptionType = Literal[
    "boolean",
    "integer",
    "number",
    "string",
    "text",
    "select",
    "multiselect",
]
ProviderOptionScalar = bool | int | float | str
ProviderOptionValue = ProviderOptionScalar | list[str] | None
OPTION_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SHARED_PROVIDER_OPTION_KEYS = {
    "audio_path",
    "base64_size",
    "chunk_max_chars",
    "chunk_overlap_ms",
    "chunk_seconds",
    "chunk_silence_ms",
    "chunking_mode",
    "clone_base64_size",
    "clone_mime_type",
    "clone_raw_byte_size",
    "clone_reference_text",
    "clone_sample_path",
    "consent_confirmed",
    "language",
    "mime_type",
    "model",
    "optimize_text_preview",
    "output_format",
    "provider_id",
    "provider_options",
    "raw_byte_size",
    "style_instruction",
    "text",
    "text_file",
    "text_format",
    "transcript_speakers",
    "transcript_timestamps",
    "voice_description",
    "voice_id",
}


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


class TranscriptCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamps: bool = False
    speakers: bool = False
    segments: bool = False


class ProviderOptionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    description: str | None = None


class _ProviderOptionValidationMixin:
    key: str
    capability: str
    type: ProviderOptionType | None
    default: ProviderOptionValue
    choices: list[ProviderOptionChoice] | None
    min_value: float | None
    max_value: float | None
    required: bool | None
    enabled: bool | None

    @model_validator(mode="after")
    def validate_option_schema(self):
        if self.key in SHARED_PROVIDER_OPTION_KEYS:
            raise ValueError(f"provider option key {self.key!r} collides with shared field")
        choices = self.choices or []
        choice_values = {choice.value for choice in choices}
        option_type = self.type
        if option_type in {"select", "multiselect"} and not choices:
            raise ValueError(f"{option_type} provider option requires choices")
        if self.default is not None:
            if self.required is True:
                raise ValueError("required provider option cannot define a default")
            if option_type == "select" and self.default not in choice_values:
                raise ValueError("select default must be one of choices")
            if option_type == "multiselect":
                if not isinstance(self.default, list) or not all(
                    isinstance(item, str) for item in self.default
                ):
                    raise ValueError("multiselect default must be a list of strings")
                if any(item not in choice_values for item in self.default):
                    raise ValueError("multiselect default must be one of choices")
            if option_type in {"integer", "number"}:
                if isinstance(self.default, bool) or not isinstance(self.default, int | float):
                    raise ValueError(f"{option_type} default must be numeric")
                numeric_default = float(self.default)
                if self.min_value is not None and numeric_default < self.min_value:
                    raise ValueError("numeric default is below min_value")
                if self.max_value is not None and numeric_default > self.max_value:
                    raise ValueError("numeric default is above max_value")
        return self


class ProviderOptionSpec(_ProviderOptionValidationMixin, BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=OPTION_KEY_PATTERN)
    label: str
    type: ProviderOptionType
    capability: str
    description: str | None = None
    default: ProviderOptionValue = None
    choices: list[ProviderOptionChoice] = Field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    placeholder: str | None = None
    required: bool = False
    advanced: bool = True
    provider_specific: bool = True
    safe_metadata: bool = False
    enabled: bool = True


class ProviderOptionOverride(_ProviderOptionValidationMixin, BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=OPTION_KEY_PATTERN)
    capability: str
    label: str | None = None
    type: ProviderOptionType | None = None
    description: str | None = None
    default: ProviderOptionValue = None
    choices: list[ProviderOptionChoice] | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    placeholder: str | None = None
    required: bool | None = None
    advanced: bool | None = None
    provider_specific: bool | None = None
    safe_metadata: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_disabled_override(self) -> ProviderOptionOverride:
        if self.enabled is False:
            allowed = {"key", "capability", "enabled"}
            extras = self.model_fields_set - allowed
            if extras:
                raise ValueError(
                    "enabled=false provider option override may only set key, "
                    "capability, and enabled"
                )
        return self


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    capability: str | None = None
    note: str | None = None
    options: list[ProviderOptionSpec | ProviderOptionOverride] = Field(default_factory=list)
    transcript_capabilities: TranscriptCapabilities | None = None

    @field_validator("options", mode="before")
    @classmethod
    def parse_model_options_as_overrides(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        parsed: list[ProviderOptionOverride | ProviderOptionSpec] = []
        for item in value:
            if isinstance(item, ProviderOptionOverride | ProviderOptionSpec):
                parsed.append(item)
            else:
                parsed.append(ProviderOptionOverride.model_validate(item))
        return parsed


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
    provider_options: dict[str, object] = Field(default_factory=dict)

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
    provider_options: dict[str, object] = Field(default_factory=dict)

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


class ProviderAudioResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    audio: bytes
    mime_type: str
    suffix: str
    model: str | None = None
