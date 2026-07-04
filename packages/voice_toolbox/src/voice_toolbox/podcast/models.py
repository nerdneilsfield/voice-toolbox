from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PodcastScriptFormat = Literal["auto", "speaker_colon", "markdown", "json", "yaml"]
ResolvedPodcastScriptFormat = Literal["speaker_colon", "markdown", "json", "yaml"]


class PodcastSpeaker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class PodcastSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str
    speaker_name: str
    text: str
    pause_after_ms: int | None = Field(default=None, ge=0)
    source_line: int | None = Field(default=None, ge=1)


class PodcastScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speakers: list[PodcastSpeaker]
    segments: list[PodcastSegment]
    source_format: ResolvedPodcastScriptFormat


class PodcastManifestSpeaker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    voice_id: str
    voice_name: str | None = None


class PodcastManifestSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    speaker_id: str
    speaker_name: str
    voice_id: str
    text: str
    source_line: int | None = None
    pause_after_ms: int = Field(ge=0)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    audio_duration_ms: int | None = Field(default=None, ge=0)


class PodcastManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    provider_id: str
    model: str | None = None
    mode: Literal["builtin"] = "builtin"
    default_pause_ms: int = Field(ge=0)
    speakers: list[PodcastManifestSpeaker]
    segments: list[PodcastManifestSegment]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
