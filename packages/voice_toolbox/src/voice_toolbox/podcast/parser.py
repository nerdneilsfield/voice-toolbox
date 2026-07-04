from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any, Literal, cast

import yaml

from voice_toolbox.podcast.models import (
    PodcastScript,
    PodcastScriptFormat,
    PodcastSegment,
    PodcastSpeaker,
    ResolvedPodcastScriptFormat,
)

MAX_PODCAST_SEGMENTS = 200
PAUSE_PATTERN = re.compile(r"\[pause:(\d+)\]\s*$")
STANDALONE_PAUSE_PATTERN = re.compile(r"^\s*\[pause:(\d+)\]\s*$")
SPEAKER_COLON_PATTERN = re.compile(r"^\s*([^:\n]{1,80}):\s*(.*?)\s*$")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", flags=re.MULTILINE)
SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


class PodcastParseError(ValueError):
    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


def parse_podcast_script(
    script: str,
    *,
    script_format: PodcastScriptFormat = "auto",
    default_pause_ms: int = 350,
) -> PodcastScript:
    text = script.strip()
    if not text:
        raise PodcastParseError("podcast script is required")
    if default_pause_ms < 0:
        raise PodcastParseError("default_pause_ms must be non-negative")
    resolved = _resolve_format(text, script_format)
    if resolved == "speaker_colon":
        return _parse_speaker_colon(text, default_pause_ms=default_pause_ms)
    if resolved == "markdown":
        return _parse_markdown(text, default_pause_ms=default_pause_ms)
    return _parse_structured(text, source_format=resolved, default_pause_ms=default_pause_ms)


def _resolve_format(script: str, requested: PodcastScriptFormat) -> ResolvedPodcastScriptFormat:
    if requested != "auto":
        return requested
    stripped = script.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if HEADING_PATTERN.search(script):
        return "markdown"
    if re.search(r"^\s*lines\s*:", script, flags=re.MULTILINE):
        return "yaml"
    return "speaker_colon"


def _parse_pause(text: str, *, line: int | None) -> tuple[str, int | None]:
    if "[pause:" in text and not PAUSE_PATTERN.search(text):
        raise PodcastParseError("invalid pause directive", line=line)
    match = PAUSE_PATTERN.search(text)
    if not match:
        return text.strip(), None
    return text[: match.start()].strip(), int(match.group(1))


def _standalone_pause_ms(text: str, *, line: int) -> int | None:
    match = STANDALONE_PAUSE_PATTERN.match(text)
    if match:
        return int(match.group(1))
    if text.strip().startswith("[pause:"):
        raise PodcastParseError("invalid pause directive", line=line)
    return None


def _apply_pause_to_previous(
    rows: list[tuple[str, str, int | None, int | None]],
    pause_ms: int,
    *,
    line: int,
) -> None:
    if not rows:
        raise PodcastParseError("pause directive requires a preceding segment", line=line)
    speaker, text, _previous_pause, source_line = rows[-1]
    rows[-1] = (speaker, text, pause_ms, source_line)


def _speaker_id(name: str, existing: set[str]) -> str:
    base = SLUG_PATTERN.sub("-", name.strip()).strip("-_").lower() or "speaker"
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}-{index}"
        index += 1
    existing.add(candidate)
    return candidate


def _build_script(
    rows: Iterable[tuple[str, str, int | None, int | None]],
    *,
    source_format: ResolvedPodcastScriptFormat,
    default_pause_ms: int,
) -> PodcastScript:
    speakers: OrderedDict[str, PodcastSpeaker] = OrderedDict()
    used_ids: set[str] = set()
    segments: list[PodcastSegment] = []
    for speaker_name, raw_text, explicit_pause, line in rows:
        name = speaker_name.strip()
        if not name:
            raise PodcastParseError("speaker name is required", line=line)
        if name not in speakers:
            speakers[name] = PodcastSpeaker(id=_speaker_id(name, used_ids), name=name)
        text = raw_text.strip()
        if not text:
            continue
        speaker = speakers[name]
        segments.append(
            PodcastSegment(
                speaker_id=speaker.id,
                speaker_name=speaker.name,
                text=text,
                pause_after_ms=explicit_pause if explicit_pause is not None else default_pause_ms,
                source_line=line,
            )
        )
    if not segments:
        raise PodcastParseError("podcast script has no speakable segments")
    if len(segments) > MAX_PODCAST_SEGMENTS:
        raise PodcastParseError(f"podcast script has more than {MAX_PODCAST_SEGMENTS} segments")
    return PodcastScript(
        speakers=list(speakers.values()),
        segments=segments,
        source_format=source_format,
    )


def _parse_speaker_colon(script: str, *, default_pause_ms: int) -> PodcastScript:
    rows: list[tuple[str, str, int | None, int | None]] = []
    for line_no, line in enumerate(script.splitlines(), start=1):
        if not line.strip():
            continue
        standalone_pause = _standalone_pause_ms(line, line=line_no)
        if standalone_pause is not None:
            _apply_pause_to_previous(rows, standalone_pause, line=line_no)
            continue
        match = SPEAKER_COLON_PATTERN.match(line)
        if not match:
            raise PodcastParseError("expected 'Speaker: text'", line=line_no)
        segment_text, pause = _parse_pause(match.group(2), line=line_no)
        rows.append((match.group(1), segment_text, pause, line_no))
    return _build_script(rows, source_format="speaker_colon", default_pause_ms=default_pause_ms)


def _parse_markdown(script: str, *, default_pause_ms: int) -> PodcastScript:
    rows: list[tuple[str, str, int | None, int | None]] = []
    current_speaker: str | None = None
    paragraph: list[str] = []
    paragraph_line: int | None = None

    def flush() -> None:
        nonlocal paragraph, paragraph_line
        if current_speaker is None or not paragraph:
            paragraph = []
            paragraph_line = None
            return
        raw = " ".join(part.strip() for part in paragraph).strip()
        text, pause = _parse_pause(raw, line=paragraph_line)
        rows.append((current_speaker, text, pause, paragraph_line))
        paragraph = []
        paragraph_line = None

    for line_no, line in enumerate(script.splitlines(), start=1):
        heading = HEADING_PATTERN.match(line)
        if heading:
            flush()
            current_speaker = heading.group(1).strip()
            continue
        standalone_pause = _standalone_pause_ms(line, line=line_no)
        if standalone_pause is not None:
            flush()
            _apply_pause_to_previous(rows, standalone_pause, line=line_no)
            continue
        if current_speaker is None:
            if line.strip():
                raise PodcastParseError(
                    "markdown podcast text must follow a speaker heading",
                    line=line_no,
                )
            continue
        if not line.strip():
            flush()
            continue
        if paragraph_line is None:
            paragraph_line = line_no
        paragraph.append(line)
    flush()
    return _build_script(rows, source_format="markdown", default_pause_ms=default_pause_ms)


def _parse_structured(
    script: str,
    *,
    source_format: Literal["json", "yaml"],
    default_pause_ms: int,
) -> PodcastScript:
    try:
        data = json.loads(script) if source_format == "json" else yaml.safe_load(script)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise PodcastParseError(f"invalid {source_format} podcast script") from exc
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise PodcastParseError(f"{source_format} podcast script requires a lines list")
    rows: list[tuple[str, str, int | None, int | None]] = []
    for index, item in enumerate(cast(list[Any], data["lines"]), start=1):
        if not isinstance(item, dict):
            raise PodcastParseError("line item must be an object")
        speaker = item.get("speaker")
        text = item.get("text")
        if not isinstance(speaker, str) or not isinstance(text, str):
            raise PodcastParseError("line item requires speaker and text")
        pause_value = item.get("pause_after_ms")
        if pause_value is not None and (not isinstance(pause_value, int) or pause_value < 0):
            raise PodcastParseError("pause_after_ms must be a non-negative integer")
        rows.append((speaker, text, pause_value, index))
    return _build_script(rows, source_format=source_format, default_pause_ms=default_pause_ms)
