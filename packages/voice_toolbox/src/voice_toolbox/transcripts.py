from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker: str | None = None

    @field_validator("text", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("segment text is required")
        return stripped

    @field_validator("speaker", mode="after")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_timestamps(self) -> TranscriptSegment:
        has_start = self.start_seconds is not None
        has_end = self.end_seconds is not None
        if has_start != has_end:
            raise ValueError("segment timestamps require start_seconds and end_seconds")
        if has_start and self.end_seconds is not None and self.start_seconds is not None:
            if self.end_seconds < self.start_seconds:
                raise ValueError("segment end_seconds must be greater than start_seconds")
        return self


class TranscriptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)

    @field_validator("text", mode="after")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @property
    def has_segments(self) -> bool:
        return bool(self.segments)

    @property
    def has_complete_timestamps(self) -> bool:
        return (
            bool(self.segments)
            and all(
                segment.start_seconds is not None and segment.end_seconds is not None
                for segment in self.segments
            )
            and self._segments_cover_text()
        )

    @property
    def has_complete_speakers(self) -> bool:
        return bool(self.segments) and all(segment.speaker for segment in self.segments)

    @property
    def download_formats(self) -> list[str]:
        formats = ["txt", "json"]
        if self.has_complete_timestamps:
            formats.extend(["srt", "vtt"])
        return formats

    def _segments_cover_text(self) -> bool:
        segment_text = " ".join(segment.text for segment in self.segments)
        return _compact_text(segment_text) == _compact_text(self.text)


def render_txt(
    payload: TranscriptPayload,
    *,
    timestamps: bool = False,
    speakers: bool = False,
) -> str:
    if not timestamps and not speakers:
        return payload.text
    if timestamps and not payload.has_complete_timestamps:
        raise ValueError("timestamped TXT requires complete timestamps")
    if speakers and not payload.has_complete_speakers:
        raise ValueError("speaker TXT requires complete speaker labels")
    lines: list[str] = []
    for segment in payload.segments:
        prefixes: list[str] = []
        if timestamps:
            prefixes.append(
                f"[{format_txt_timestamp(segment.start_seconds)} - "
                f"{format_txt_timestamp(segment.end_seconds)}]"
            )
        if speakers:
            prefixes.append(f"{segment.speaker}:")
        prefix = " ".join(prefixes)
        lines.append(f"{prefix} {segment.text}" if prefix else segment.text)
    return "\n".join(lines)


def render_srt(payload: TranscriptPayload) -> str:
    _require_complete_timestamps(payload, "SRT")
    blocks: list[str] = []
    for index, segment in enumerate(payload.segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    (
                        f"{format_srt_timestamp(segment.start_seconds)} --> "
                        f"{format_srt_timestamp(segment.end_seconds)}"
                    ),
                    segment.text,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def render_vtt(payload: TranscriptPayload) -> str:
    _require_complete_timestamps(payload, "VTT")
    blocks: list[str] = ["WEBVTT"]
    for segment in payload.segments:
        blocks.append(
            "\n".join(
                [
                    (
                        f"{format_vtt_timestamp(segment.start_seconds)} --> "
                        f"{format_vtt_timestamp(segment.end_seconds)}"
                    ),
                    segment.text,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def render_json(payload: TranscriptPayload) -> dict[str, object]:
    return payload.model_dump(mode="json", exclude_none=True)


def format_txt_timestamp(seconds: float | None) -> str:
    return _format_caption_timestamp(seconds, decimal=".")


def format_srt_timestamp(seconds: float | None) -> str:
    return _format_caption_timestamp(seconds, decimal=",")


def format_vtt_timestamp(seconds: float | None) -> str:
    return _format_caption_timestamp(seconds, decimal=".")


def _format_caption_timestamp(seconds: float | None, *, decimal: str) -> str:
    total_ms = _total_milliseconds(seconds)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}{decimal}{milliseconds:03d}"


def _total_milliseconds(seconds: float | None) -> int:
    if seconds is None:
        raise ValueError("timestamp is required")
    return max(0, round(seconds * 1000))


def _require_complete_timestamps(payload: TranscriptPayload, format_name: str) -> None:
    if not payload.has_complete_timestamps:
        raise ValueError(f"{format_name} rendering requires complete timestamps")


def _compact_text(value: str) -> str:
    return re.sub(r"[ \t\r\n\f\v]+", " ", value).strip()
