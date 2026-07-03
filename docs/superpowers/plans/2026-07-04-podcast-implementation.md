# Podcast Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Podcast workspace that parses multi-speaker scripts, maps speakers to built-in voices, generates each segment as TTS, and merges the segments into one audio artifact with a timing manifest.

**Architecture:** Add a focused `voice_toolbox.podcast` package for parsing, manifest models, job state, and audio assembly. The FastAPI app owns the in-process podcast job store and exposes job create/poll/cancel endpoints. The web app adds a third `podcast` tab with Split Compose UI and uses polling to display progress.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pydub, PyYAML, pytest, React, TypeScript, Vitest.

---

## File Structure

- Create `packages/voice_toolbox/src/voice_toolbox/podcast/__init__.py`: package exports.
- Create `packages/voice_toolbox/src/voice_toolbox/podcast/parser.py`: script parsing and parser errors.
- Create `packages/voice_toolbox/src/voice_toolbox/podcast/models.py`: parsed script, job status, and manifest Pydantic models.
- Create `packages/voice_toolbox/src/voice_toolbox/podcast/audio.py`: per-segment audio concat with per-segment pauses and duration metadata.
- Create `packages/voice_toolbox/src/voice_toolbox/podcast/jobs.py`: in-memory job store, cancellation flags, bounded TTL cleanup.
- Modify `pyproject.toml` and `uv.lock`: make `pyyaml` a direct runtime dependency.
- Modify `packages/voice_toolbox/src/voice_toolbox/artifacts.py`: allow podcast-safe metadata keys.
- Modify `apps/api/src/voice_toolbox_api/main.py`: add podcast endpoints, app state job store, job runner, manifest sidecar read/write helpers.
- Modify `tests/test_api.py`: podcast route and job tests.
- Create `tests/test_podcast_parser.py`: parser tests.
- Create `tests/test_podcast_audio.py`: per-segment pause and duration tests.
- Modify `apps/web/src/api.ts`: podcast API client types/functions.
- Modify `apps/web/src/api.test.ts`: podcast API client tests.
- Modify `apps/web/src/App.tsx`: add podcast state, tab routing, history behavior.
- Modify `apps/web/src/components/Sidebar.tsx`: add Podcast nav item.
- Create `apps/web/src/components/PodcastWorkspace.tsx`: Split Compose UI, local parse preview, speaker voice mapping, submit/polling.
- Create `apps/web/src/lib/podcastScript.ts`: client-side parser preview mirroring backend subset.
- Create `apps/web/src/lib/podcastScript.test.ts`: parser preview tests.
- Modify `apps/web/src/components/HistoryPanel.tsx`: podcast title formatting.
- Modify `apps/web/src/i18n/dictionaries.ts`: add Podcast labels.
- Modify `apps/web/src/styles.css`: Split Compose layout and podcast card styling.
- Modify `README.md`: document Podcast usage and supported script formats.

## Task 1: Parser Models And Script Parser

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/podcast/__init__.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/podcast/models.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/podcast/parser.py`
- Create: `tests/test_podcast_parser.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add failing parser tests**

Create `tests/test_podcast_parser.py`:

```python
from __future__ import annotations

import pytest

from voice_toolbox.podcast.parser import PodcastParseError, parse_podcast_script


def test_parse_speaker_colon_preserves_speakers_and_pause() -> None:
    script = "Alice: Hello there [pause:800]\nBob: General Kenobi"

    parsed = parse_podcast_script(script, script_format="speaker_colon", default_pause_ms=350)

    assert [speaker.name for speaker in parsed.speakers] == ["Alice", "Bob"]
    assert [(segment.speaker_name, segment.text, segment.pause_after_ms) for segment in parsed.segments] == [
        ("Alice", "Hello there", 800),
        ("Bob", "General Kenobi", 350),
    ]
    assert parsed.segments[0].source_line == 1


def test_parse_markdown_headings_split_paragraphs() -> None:
    script = "### Alice\nHello.\n\nSecond paragraph.\n### Bob\nReply."

    parsed = parse_podcast_script(script, script_format="markdown", default_pause_ms=250)

    assert [speaker.name for speaker in parsed.speakers] == ["Alice", "Bob"]
    assert [segment.text for segment in parsed.segments] == ["Hello.", "Second paragraph.", "Reply."]
    assert parsed.segments[2].speaker_name == "Bob"


def test_parse_json_and_yaml_lines() -> None:
    json_parsed = parse_podcast_script(
        '{"lines":[{"speaker":"Alice","text":"JSON line"}]}',
        script_format="json",
        default_pause_ms=200,
    )
    yaml_parsed = parse_podcast_script(
        "lines:\n  - speaker: Bob\n    text: YAML line\n",
        script_format="yaml",
        default_pause_ms=200,
    )

    assert json_parsed.segments[0].text == "JSON line"
    assert yaml_parsed.segments[0].speaker_name == "Bob"


def test_parse_auto_detects_structured_and_markdown() -> None:
    assert parse_podcast_script('{"lines":[{"speaker":"A","text":"x"}]}').source_format == "json"
    assert parse_podcast_script("### A\nx").source_format == "markdown"
    assert parse_podcast_script("A: x").source_format == "speaker_colon"


def test_parse_errors_include_line_number() -> None:
    with pytest.raises(PodcastParseError) as exc:
        parse_podcast_script("Alice: hello [pause:nope]", script_format="speaker_colon")

    assert exc.value.line == 1
    assert "pause" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
rtk uv run pytest tests/test_podcast_parser.py -q
```

Expected: import failure for `voice_toolbox.podcast`.

- [ ] **Step 3: Add PyYAML direct dependency**

Modify `pyproject.toml` runtime dependencies:

```toml
dependencies = [
  "fastapi>=0.115",
  "loguru>=0.7",
  "msgpack>=1.2.1",
  "openai>=1.0",
  "pydub>=0.25",
  "pydantic>=2.0",
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
  "python-multipart>=0.0.18",
  "typer>=0.12",
  "uvicorn>=0.30",
  "audioop-lts>=0.2.2 ; python_full_version >= '3.13'",
]
```

Run:

```bash
rtk uv lock
```

Expected: `uv.lock` updates or stays semantically equivalent with `pyyaml` present.

- [ ] **Step 4: Add parser models**

Create `packages/voice_toolbox/src/voice_toolbox/podcast/models.py`:

```python
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
```

- [ ] **Step 5: Add parser implementation**

Create `packages/voice_toolbox/src/voice_toolbox/podcast/parser.py` with these public names:

```python
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
SPEAKER_COLON_PATTERN = re.compile(r"^\s*([^:\n]{1,80}):\s*(.*?)\s*$")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$")
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
```

Implement helper functions in same file:

```python
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
    speakers: "OrderedDict[str, PodcastSpeaker]" = OrderedDict()
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
```

Add parsers in same file:

```python
def _parse_speaker_colon(script: str, *, default_pause_ms: int) -> PodcastScript:
    rows: list[tuple[str, str, int | None, int | None]] = []
    for line_no, line in enumerate(script.splitlines(), start=1):
        if not line.strip():
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
        if current_speaker is None:
            if line.strip():
                raise PodcastParseError("markdown podcast text must follow a speaker heading", line=line_no)
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
```

- [ ] **Step 6: Export package names**

Create `packages/voice_toolbox/src/voice_toolbox/podcast/__init__.py`:

```python
from voice_toolbox.podcast.models import PodcastManifest, PodcastScript, PodcastSegment, PodcastSpeaker
from voice_toolbox.podcast.parser import MAX_PODCAST_SEGMENTS, PodcastParseError, parse_podcast_script

__all__ = [
    "MAX_PODCAST_SEGMENTS",
    "PodcastManifest",
    "PodcastParseError",
    "PodcastScript",
    "PodcastSegment",
    "PodcastSpeaker",
    "parse_podcast_script",
]
```

- [ ] **Step 7: Run parser tests**

Run:

```bash
rtk uv run pytest tests/test_podcast_parser.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Run lint for touched Python files**

Run:

```bash
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/podcast tests/test_podcast_parser.py
rtk uv run ruff format --check packages/voice_toolbox/src/voice_toolbox/podcast tests/test_podcast_parser.py
```

Expected: no errors.

- [ ] **Step 9: Commit Task 1**

Run:

```bash
rtk git add pyproject.toml uv.lock packages/voice_toolbox/src/voice_toolbox/podcast tests/test_podcast_parser.py
rtk git commit -m "feat(podcast): parse multi-speaker scripts"
```

## Task 2: Podcast Audio Merge And Manifest Persistence

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/podcast/audio.py`
- Create: `tests/test_podcast_audio.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/artifacts.py`

- [ ] **Step 1: Add failing audio merge tests**

Create `tests/test_podcast_audio.py`:

```python
from __future__ import annotations

import io
import wave

from pydub import AudioSegment

from voice_toolbox.models import ProviderAudioResult
from voice_toolbox.podcast.audio import PodcastAudioSegment, merge_podcast_audio


def _wav_silence(duration_ms: int) -> bytes:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def test_merge_podcast_audio_uses_per_segment_pauses() -> None:
    merged = merge_podcast_audio(
        [
            PodcastAudioSegment(
                result=ProviderAudioResult(audio=_wav_silence(100), mime_type="audio/wav", suffix=".wav"),
                pause_after_ms=30,
            ),
            PodcastAudioSegment(
                result=ProviderAudioResult(audio=_wav_silence(120), mime_type="audio/wav", suffix=".wav"),
                pause_after_ms=90,
            ),
        ],
        output_format="wav",
    )

    audio = AudioSegment.from_file(io.BytesIO(merged.audio.audio), format="wav")

    assert 245 <= len(audio) <= 265
    assert [segment.audio_duration_ms for segment in merged.segments] == [100, 120]
    assert merged.segments[0].start_ms == 0
    assert 95 <= (merged.segments[0].end_ms or 0) <= 105
    assert 125 <= (merged.segments[1].start_ms or 0) <= 135


def test_merge_podcast_audio_omits_timing_for_unreadable_audio() -> None:
    merged = merge_podcast_audio(
        [
            PodcastAudioSegment(
                result=ProviderAudioResult(audio=b"not-audio", mime_type="audio/mpeg", suffix=".mp3"),
                pause_after_ms=10,
            )
        ],
        output_format="mp3",
    )

    assert merged.segments[0].start_ms is None
    assert merged.segments[0].end_ms is None
    assert merged.segments[0].audio_duration_ms is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
rtk uv run pytest tests/test_podcast_audio.py -q
```

Expected: import failure for `voice_toolbox.podcast.audio`.

- [ ] **Step 3: Implement podcast audio merge**

Create `packages/voice_toolbox/src/voice_toolbox/podcast/audio.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment

from voice_toolbox.audio_conversion import DownloadAudioFormat
from voice_toolbox.chunking.audio import decode_audio_result, export_audio_segment
from voice_toolbox.models import ProviderAudioResult


@dataclass(frozen=True)
class PodcastAudioSegment:
    result: ProviderAudioResult
    pause_after_ms: int


@dataclass(frozen=True)
class PodcastAudioTiming:
    start_ms: int | None
    end_ms: int | None
    audio_duration_ms: int | None


@dataclass(frozen=True)
class PodcastAudioMergeResult:
    audio: ProviderAudioResult
    segments: list[PodcastAudioTiming]


def merge_podcast_audio(
    segments: list[PodcastAudioSegment],
    *,
    output_format: DownloadAudioFormat,
) -> PodcastAudioMergeResult:
    rendered = AudioSegment.silent(duration=0)
    cursor_ms = 0
    timings: list[PodcastAudioTiming] = []
    all_decoded = True
    for index, segment in enumerate(segments):
        try:
            audio = decode_audio_result(segment.result)
        except Exception:
            all_decoded = False
            timings.append(PodcastAudioTiming(start_ms=None, end_ms=None, audio_duration_ms=None))
            continue
        start_ms = cursor_ms if all_decoded else None
        rendered += audio
        cursor_ms += len(audio)
        end_ms = cursor_ms if all_decoded else None
        timings.append(
            PodcastAudioTiming(
                start_ms=start_ms,
                end_ms=end_ms,
                audio_duration_ms=len(audio),
            )
        )
        if index < len(segments) - 1 and segment.pause_after_ms > 0:
            rendered += AudioSegment.silent(duration=segment.pause_after_ms)
            cursor_ms += segment.pause_after_ms
    if not segments:
        audio_result = export_audio_segment(AudioSegment.silent(duration=0), output_format=output_format)
    elif all_decoded:
        audio_result = export_audio_segment(rendered, output_format=output_format)
    else:
        audio_result = segments[0].result
    return PodcastAudioMergeResult(audio=audio_result, segments=timings)
```

- [ ] **Step 4: Extend artifact metadata allowlist**

Modify `ALLOWED_METADATA_KEYS` in `packages/voice_toolbox/src/voice_toolbox/artifacts.py`:

```python
    "podcast_default_pause_ms",
    "podcast_manifest_sidecar",
    "podcast_manifest_version",
    "podcast_mode",
    "podcast_segment_count",
    "podcast_speaker_count",
    "podcast_speakers",
    "podcast_voice_ids",
```

Keep full segment text out of metadata.

- [ ] **Step 5: Run audio tests**

Run:

```bash
rtk uv run pytest tests/test_podcast_audio.py tests/test_artifacts.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run lint**

Run:

```bash
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/podcast/audio.py packages/voice_toolbox/src/voice_toolbox/artifacts.py tests/test_podcast_audio.py
rtk uv run ruff format --check packages/voice_toolbox/src/voice_toolbox/podcast/audio.py packages/voice_toolbox/src/voice_toolbox/artifacts.py tests/test_podcast_audio.py
```

Expected: no errors.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/podcast/audio.py packages/voice_toolbox/src/voice_toolbox/artifacts.py tests/test_podcast_audio.py
rtk git commit -m "feat(podcast): merge spoken segments"
```

## Task 3: Backend Podcast Jobs And API

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/podcast/jobs.py`
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_api.py`:

```python
def test_podcast_job_generates_audio_and_manifest(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "model": "fake-tts",
            "script": "Alice: Hello\nBob: Hi [pause:25]",
            "script_format": "speaker_colon",
            "default_pause_ms": "40",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] in {"queued", "running", "completed"}
    job = client.get(f"/v1/podcast/jobs/{payload['job_id']}").json()
    assert job["status"] == "completed"
    assert job["artifact"]["operation"] == "podcast"
    assert job["artifact"]["metadata"]["podcast_segment_count"] == 2
    assert [request.voice_id for request in provider.tts_requests] == ["Mia", "Dean"]

    artifact_id = job["artifact"]["id"]
    sidecar = next((tmp_path / "data" / "artifacts").glob(f"*/{artifact_id}.podcast.json"))
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    assert manifest["segments"][0]["speaker_name"] == "Alice"
    assert manifest["segments"][1]["pause_after_ms"] == 25


def test_podcast_job_rejects_missing_voice_mapping(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello\nBob: Hi",
            "speaker_voices": json.dumps({"alice": "Mia"}),
        },
    )

    assert response.status_code == 422
    assert "Bob" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_records_provider_failure(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)
    provider.tts_error_after_calls = 2

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello\nBob: Hi",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )
    job = client.get(f"/v1/podcast/jobs/{created.json()['job_id']}").json()

    assert job["status"] == "failed"
    assert job["failed_segment"]["index"] == 1
    assert "chunk failed" in job["error_summary"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
rtk uv run pytest tests/test_api.py -q -k podcast
```

Expected: 404 for `/v1/podcast/jobs`.

- [ ] **Step 3: Add job models/store**

Create `packages/voice_toolbox/src/voice_toolbox/podcast/jobs.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from voice_toolbox.models import AudioArtifact


class PodcastFailedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    speaker: str


class PodcastJobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    current_segment: int = 0
    total_segments: int = 0
    current_speaker: str | None = None
    current_text_preview: str | None = None
    artifact: AudioArtifact | None = None
    error_summary: str | None = None
    failed_segment: PodcastFailedSegment | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PodcastJobStore:
    def __init__(self, *, ttl_seconds: int = 3600, max_jobs: int = 100) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self.max_jobs = max_jobs
        self._jobs: dict[str, PodcastJobStatus] = {}
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def create(self) -> PodcastJobStatus:
        with self._lock:
            self.cleanup()
            job = PodcastJobStatus(job_id=f"podcast-{uuid4().hex}", status="queued")
            self._jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> PodcastJobStatus | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> PodcastJobStatus:
        with self._lock:
            current = self._jobs[job_id]
            updated = current.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
            self._jobs[job_id] = updated
            return updated

    def cancel(self, job_id: str) -> PodcastJobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            self._cancelled.add(job_id)
            if job.status == "queued":
                job = job.model_copy(update={"status": "cancelled", "updated_at": datetime.now(UTC)})
                self._jobs[job_id] = job
            return job

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def cleanup(self) -> None:
        now = datetime.now(UTC)
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - job.updated_at > self.ttl
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)
            self._cancelled.discard(job_id)
        while len(self._jobs) > self.max_jobs:
            oldest = min(self._jobs.values(), key=lambda job: job.updated_at)
            self._jobs.pop(oldest.job_id, None)
            self._cancelled.discard(oldest.job_id)
```

- [ ] **Step 4: Register job store in app state**

Modify `create_app()` in `apps/api/src/voice_toolbox_api/main.py` after ASR store setup:

```python
from voice_toolbox.podcast.audio import PodcastAudioSegment, merge_podcast_audio
from voice_toolbox.podcast.jobs import PodcastFailedSegment, PodcastJobStatus, PodcastJobStore
from voice_toolbox.podcast.models import (
    PodcastManifest,
    PodcastManifestSegment,
    PodcastManifestSpeaker,
    PodcastScriptFormat,
)
from voice_toolbox.podcast.parser import MAX_PODCAST_SEGMENTS, PodcastParseError, parse_podcast_script
```

```python
    app.state.podcast_jobs = PodcastJobStore()
```

- [ ] **Step 5: Add endpoint skeleton**

Add inside `create_app()` before artifact routes:

```python
    @app.post("/v1/podcast/jobs")
    def create_podcast_job(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        model: Annotated[str | None, Form()] = None,
        script: Annotated[str, Form()] = "",
        script_format: Annotated[PodcastScriptFormat, Form()] = "auto",
        default_pause_ms: Annotated[int, Form()] = 350,
        speaker_voices: Annotated[str, Form()] = "{}",
        provider_options: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
    ) -> dict[str, Any]:
        job = http_request.app.state.podcast_jobs.create()
        _run_podcast_job_sync(
            http_request=http_request,
            job_id=job.job_id,
            provider_id=provider_id,
            model=model,
            script=script,
            script_format=script_format,
            default_pause_ms=default_pause_ms,
            speaker_voices=speaker_voices,
            provider_options=provider_options,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
        )
        return _podcast_job_payload(http_request.app.state.podcast_jobs.get(job.job_id))

    @app.get("/v1/podcast/jobs/{job_id}")
    def get_podcast_job(job_id: str, http_request: Request) -> dict[str, Any]:
        job = http_request.app.state.podcast_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="podcast job not found")
        return _podcast_job_payload(job)

    @app.delete("/v1/podcast/jobs/{job_id}")
    def cancel_podcast_job(job_id: str, http_request: Request) -> dict[str, Any]:
        job = http_request.app.state.podcast_jobs.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="podcast job not found")
        return _podcast_job_payload(job)
```

This is synchronous for deterministic tests; background execution can be added by wrapping `_run_podcast_job_sync` in FastAPI `BackgroundTasks` after tests cover state.

- [ ] **Step 6: Add job runner helpers**

Add module-level helpers in `apps/api/src/voice_toolbox_api/main.py`:

```python
def _podcast_job_payload(job: PodcastJobStatus | None) -> dict[str, Any]:
    if job is None:
        raise HTTPException(status_code=404, detail="podcast job not found")
    payload = job.model_dump(mode="json", exclude={"artifact"})
    payload["artifact"] = _safe_artifact_payload(job.artifact) if job.artifact is not None else None
    return payload


def _parse_speaker_voices(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="speaker_voices must be JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="speaker_voices must be an object")
    voices: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=422, detail="speaker_voices values must be non-empty strings")
        voices[key.strip()] = value.strip()
    return voices
```

Add `_run_podcast_job_sync(...)` with the exact signature from Step 5. The body should:

```python
    store: PodcastJobStore = http_request.app.state.podcast_jobs
    provider_registry = _registry_from_request(http_request)
    config = _config_from_request(http_request)
    started_at = datetime.now(UTC)
    try:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        provider = _get_provider(provider_registry, provider_id)
        _ensure_model_allowed(provider, model, expected_capability="tts.builtin")
        parsed = parse_podcast_script(
            script,
            script_format=script_format,
            default_pause_ms=default_pause_ms,
        )
        voices_by_key = _parse_speaker_voices(speaker_voices)
        validated_options, option_metadata = _validate_tts_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            capability="tts.builtin",
            raw_provider_options=provider_options,
        )
        missing = [
            speaker.name
            for speaker in parsed.speakers
            if speaker.id not in voices_by_key and speaker.name not in voices_by_key
        ]
        if missing:
            raise HTTPException(status_code=422, detail=f"missing voice mapping for: {', '.join(missing)}")
        store.update(job_id, status="running", total_segments=len(parsed.segments))
        audio_segments: list[PodcastAudioSegment] = []
        manifest_segments: list[PodcastManifestSegment] = []
        voice_lookup = {voice.id: voice.name for voice in provider.list_voices()}
        speaker_voice_ids = {
            speaker.id: voices_by_key.get(speaker.id) or voices_by_key[speaker.name]
            for speaker in parsed.speakers
        }
        for index, segment in enumerate(parsed.segments):
            if store.is_cancelled(job_id):
                store.update(job_id, status="cancelled")
                return
            voice_id = speaker_voice_ids[segment.speaker_id]
            store.update(
                job_id,
                current_segment=index + 1,
                current_speaker=segment.speaker_name,
                current_text_preview=_preview_text(segment.text, 80),
            )
            prepared = _prepare_tts_or_422(
                raw_text=TextSource(text=segment.text, metadata={"source_kind": "inline"}),
                text_format=None,
                config=config,
                chunking_mode=chunking_mode,
                chunk_max_chars=chunk_max_chars,
                chunk_silence_ms=chunk_silence_ms,
                fields={
                    "provider_id": provider_id,
                    "mode": TTSMode.BUILTIN,
                    "model": model,
                    "voice_id": voice_id,
                    "provider_options": validated_options,
                },
                artifact_metadata=option_metadata,
            )
            result = _synthesize_prepared_segment(provider, prepared)
            audio_segments.append(
                PodcastAudioSegment(
                    result=result,
                    pause_after_ms=segment.pause_after_ms or default_pause_ms,
                )
            )
            manifest_segments.append(
                PodcastManifestSegment(
                    index=index,
                    speaker_id=segment.speaker_id,
                    speaker_name=segment.speaker_name,
                    voice_id=voice_id,
                    text=segment.text,
                    source_line=segment.source_line,
                    pause_after_ms=segment.pause_after_ms or default_pause_ms,
                )
            )
        merged = merge_podcast_audio(audio_segments, output_format="wav")
        for segment, timing in zip(manifest_segments, merged.segments, strict=True):
            segment.start_ms = timing.start_ms
            segment.end_ms = timing.end_ms
            segment.audio_duration_ms = timing.audio_duration_ms
        manifest = PodcastManifest(
            provider_id=provider_id,
            model=model,
            default_pause_ms=default_pause_ms,
            speakers=[
                PodcastManifestSpeaker(
                    id=speaker.id,
                    name=speaker.name,
                    voice_id=speaker_voice_ids[speaker.id],
                    voice_name=voice_lookup.get(speaker_voice_ids[speaker.id]),
                )
                for speaker in parsed.speakers
            ],
            segments=manifest_segments,
        )
        operation_id = job_id
        artifact = ArtifactStore(http_request.app.state.artifact_root).write_audio(
            operation_id=operation_id,
            provider_id=provider_id,
            operation="podcast",
            audio=merged.audio.audio,
            mime_type=merged.audio.mime_type,
            suffix=merged.audio.suffix,
            metadata={
                **dict(option_metadata),
                "operation": "podcast",
                "model": model,
                "source_text": script,
                "source_text_preview": _preview_text(script),
                "podcast_mode": "builtin",
                "podcast_default_pause_ms": default_pause_ms,
                "podcast_manifest_version": 1,
                "podcast_manifest_sidecar": True,
                "podcast_speaker_count": len(parsed.speakers),
                "podcast_segment_count": len(parsed.segments),
                "podcast_speakers": [speaker.name for speaker in parsed.speakers],
                "podcast_voice_ids": list(speaker_voice_ids.values()),
            },
        )
        _write_podcast_manifest(artifact.path, manifest)
        ArtifactStore(http_request.app.state.artifact_root).record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="podcast",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        store.update(job_id, status="completed", artifact=artifact)
    except HTTPException:
        raise
    except PodcastParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        store.update(
            job_id,
            status="failed",
            error_summary=str(exc),
            failed_segment=PodcastFailedSegment(
                index=max(0, (store.get(job_id).current_segment if store.get(job_id) else 1) - 1),
                speaker=(store.get(job_id).current_speaker if store.get(job_id) else "") or "",
            ),
        )
```

Add `_synthesize_prepared_segment` and `_write_podcast_manifest`:

```python
def _synthesize_prepared_segment(provider: Any, prepared: PreparedTTSRequest) -> ProviderAudioResult:
    if len(prepared.chunks) == 1:
        return provider.synthesize_bytes(prepared.chunks[0])
    results = [provider.synthesize_bytes(chunk) for chunk in prepared.chunks]
    return merge_audio_results(
        results,
        silence_ms=int(prepared.artifact_metadata.get("chunking_silence_ms", 120)),
        output_format="wav",
    )


def _write_podcast_manifest(audio_path: Path, manifest: PodcastManifest) -> None:
    manifest_path = audio_path.with_suffix(".podcast.json")
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
```

- [ ] **Step 7: Run focused API tests**

Run:

```bash
rtk uv run pytest tests/test_api.py -q -k podcast
```

Expected: all podcast API tests pass.

- [ ] **Step 8: Run broader backend tests**

Run:

```bash
rtk uv run pytest tests/test_podcast_parser.py tests/test_podcast_audio.py tests/test_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Run lint**

Run:

```bash
rtk uv run ruff check apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests/test_api.py
rtk uv run ruff format --check apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests/test_api.py
```

Expected: no errors.

- [ ] **Step 10: Commit Task 3**

Run:

```bash
rtk git add apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests/test_api.py
rtk git commit -m "feat(api): add podcast jobs"
```

## Task 4: First Adversarial Review After Tasks 1-3

**Files:**
- Review: `git diff HEAD~3..HEAD`
- Modify: files named by review findings

- [ ] **Step 1: Dispatch adversarial review**

Use subagent reviewer with this prompt:

```text
Review current branch diff HEAD~3..HEAD for podcast parser/audio/API.
Prioritize runtime crashes, API contract bugs, missing tests, privacy leaks, and flaky job state.
Use caveman-review format: location, severity, problem, fix.
Do not praise. Do not summarize obvious changes.
```

- [ ] **Step 2: Verify findings manually**

For every Critical/Risk item, inspect the referenced file and decide whether it is real. Record rejected findings in the final task note with the reason.

- [ ] **Step 3: Fix real findings**

Apply fixes in the smallest affected files. Add or update regression tests for every Critical finding.

- [ ] **Step 4: Run backend verification**

Run:

```bash
rtk uv run pytest tests/test_podcast_parser.py tests/test_podcast_audio.py tests/test_api.py -q
rtk uv run ruff check apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests/test_podcast_parser.py tests/test_podcast_audio.py tests/test_api.py
rtk uv run ruff format --check apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests/test_podcast_parser.py tests/test_podcast_audio.py tests/test_api.py
```

Expected: all pass.

- [ ] **Step 5: Commit review fixes**

If fixes were made:

```bash
rtk git add apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/podcast tests
rtk git commit -m "fix(podcast): address backend review"
```

If no fixes were needed, do not create an empty commit.

## Task 5: Web API Client And Client Parser Preview

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/api.test.ts`
- Create: `apps/web/src/lib/podcastScript.ts`
- Create: `apps/web/src/lib/podcastScript.test.ts`

- [ ] **Step 1: Add failing web API tests**

Append to `apps/web/src/api.test.ts` imports:

```ts
import { createPodcastJob, getPodcastJob } from "./api";
```

Append tests:

```ts
it("creates podcast jobs with speaker voices JSON", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ job_id: "podcast-1", status: "queued" }), {
      headers: { "content-type": "application/json" },
    }),
  );

  await createPodcastJob({
    providerId: "mimo",
    model: "fake-tts",
    script: "Alice: hello",
    scriptFormat: "speaker_colon",
    defaultPauseMs: 350,
    speakerVoices: { alice: "Mia" },
  });

  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/v1/podcast/jobs");
  const body = init?.body as FormData;
  expect(body.get("provider_id")).toBe("mimo");
  expect(body.get("speaker_voices")).toBe(JSON.stringify({ alice: "Mia" }));
});

it("fetches podcast job status", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ job_id: "podcast-1", status: "completed" }), {
      headers: { "content-type": "application/json" },
    }),
  );

  await getPodcastJob("podcast/1");

  expect(globalThis.fetch).toHaveBeenCalledWith("/v1/podcast/jobs/podcast%2F1");
});
```

- [ ] **Step 2: Add failing client parser tests**

Create `apps/web/src/lib/podcastScript.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parsePodcastScriptPreview } from "./podcastScript";

describe("podcast script preview parser", () => {
  it("parses speaker lines with pause overrides", () => {
    const parsed = parsePodcastScriptPreview("Alice: Hi [pause:800]\nBob: Yo", "speaker_colon", 350);

    expect(parsed.speakers.map((speaker) => speaker.name)).toEqual(["Alice", "Bob"]);
    expect(parsed.segments[0]).toMatchObject({ speakerName: "Alice", text: "Hi", pauseAfterMs: 800 });
  });

  it("reports invalid lines", () => {
    const parsed = parsePodcastScriptPreview("not valid", "speaker_colon", 350);

    expect(parsed.errors[0].line).toBe(1);
  });
});
```

- [ ] **Step 3: Run web tests to verify failure**

Run:

```bash
rtk npm --prefix apps/web test -- api.test.ts podcastScript.test.ts
```

Expected: missing exports/imports.

- [ ] **Step 4: Implement API client types/functions**

Modify `apps/web/src/api.ts`:

```ts
export type PodcastScriptFormat = "auto" | "speaker_colon" | "markdown" | "json" | "yaml";

export type PodcastJobStatus = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  current_segment?: number;
  total_segments?: number;
  current_speaker?: string | null;
  current_text_preview?: string | null;
  artifact?: Artifact | null;
  error_summary?: string | null;
  failed_segment?: { index: number; speaker: string } | null;
};

export type PodcastJobCreate = {
  providerId: string;
  model?: string | null;
  script: string;
  scriptFormat: PodcastScriptFormat;
  defaultPauseMs: number;
  speakerVoices: Record<string, string>;
  providerOptions?: Record<string, unknown>;
  chunkingMode?: ChunkingMode;
  chunkMaxChars?: number;
  chunkSilenceMs?: number;
};
```

Add functions:

```ts
export function createPodcastJob(form: PodcastJobCreate): Promise<PodcastJobStatus> {
  const body = new FormData();
  body.set("provider_id", form.providerId);
  appendOptional(body, "model", form.model);
  body.set("script", form.script);
  body.set("script_format", form.scriptFormat);
  body.set("default_pause_ms", String(form.defaultPauseMs));
  body.set("speaker_voices", JSON.stringify(form.speakerVoices));
  appendProviderOptions(body, form.providerOptions);
  appendChunking(body, form);
  return requestForm("/v1/podcast/jobs", body);
}

export function getPodcastJob(jobId: string): Promise<PodcastJobStatus> {
  return requestJson(`/v1/podcast/jobs/${encodeURIComponent(jobId)}`);
}

export function cancelPodcastJob(jobId: string): Promise<PodcastJobStatus> {
  return requestJson(`/v1/podcast/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}
```

- [ ] **Step 5: Implement client preview parser**

Create `apps/web/src/lib/podcastScript.ts`:

```ts
import type { PodcastScriptFormat } from "../api";

export type PodcastPreviewSpeaker = { id: string; name: string };
export type PodcastPreviewSegment = {
  speakerId: string;
  speakerName: string;
  text: string;
  pauseAfterMs: number;
  line: number;
};
export type PodcastPreviewError = { line?: number; message: string };
export type PodcastPreview = {
  speakers: PodcastPreviewSpeaker[];
  segments: PodcastPreviewSegment[];
  errors: PodcastPreviewError[];
};

const speakerLinePattern = /^\s*([^:\n]{1,80}):\s*(.*?)\s*$/;
const pausePattern = /\[pause:(\d+)\]\s*$/;

export function parsePodcastScriptPreview(
  script: string,
  format: PodcastScriptFormat,
  defaultPauseMs: number,
): PodcastPreview {
  const resolved = format === "auto" ? "speaker_colon" : format;
  if (resolved !== "speaker_colon") {
    return { speakers: [], segments: [], errors: [{ message: "Preview currently supports speaker lines" }] };
  }
  const speakers = new Map<string, PodcastPreviewSpeaker>();
  const usedSpeakerIds = new Set<string>();
  const segments: PodcastPreviewSegment[] = [];
  const errors: PodcastPreviewError[] = [];
  for (const [offset, line] of script.split(/\r?\n/).entries()) {
    const lineNo = offset + 1;
    if (!line.trim()) continue;
    const match = speakerLinePattern.exec(line);
    if (!match) {
      errors.push({ line: lineNo, message: "Expected Speaker: text" });
      continue;
    }
    const name = match[1].trim();
    if (!speakers.has(name)) speakers.set(name, { id: slugSpeaker(name, usedSpeakerIds), name });
    const parsedText = parsePause(match[2], defaultPauseMs);
    if (parsedText.error) {
      errors.push({ line: lineNo, message: parsedText.error });
      continue;
    }
    if (!parsedText.text) continue;
    const speaker = speakers.get(name)!;
    segments.push({
      speakerId: speaker.id,
      speakerName: speaker.name,
      text: parsedText.text,
      pauseAfterMs: parsedText.pauseAfterMs,
      line: lineNo,
    });
  }
  return { speakers: Array.from(speakers.values()), segments, errors };
}

function parsePause(raw: string, defaultPauseMs: number): { text: string; pauseAfterMs: number; error?: string } {
  if (raw.includes("[pause:") && !pausePattern.test(raw)) {
    return { text: raw.trim(), pauseAfterMs: defaultPauseMs, error: "Invalid pause directive" };
  }
  const match = pausePattern.exec(raw);
  if (!match) return { text: raw.trim(), pauseAfterMs: defaultPauseMs };
  return { text: raw.slice(0, match.index).trim(), pauseAfterMs: Number(match[1]) };
}

function slugSpeaker(name: string, existing: Set<string>): string {
  const base = name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "speaker";
  let candidate = base;
  let index = 2;
  while (existing.has(candidate)) {
    candidate = `${base}-${index}`;
    index += 1;
  }
  return candidate;
}
```

- [ ] **Step 6: Run web API/parser tests**

Run:

```bash
rtk npm --prefix apps/web test -- api.test.ts podcastScript.test.ts
```

Expected: tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
rtk git add apps/web/src/api.ts apps/web/src/api.test.ts apps/web/src/lib/podcastScript.ts apps/web/src/lib/podcastScript.test.ts
rtk git commit -m "feat(web): add podcast API client"
```

## Task 6: Podcast Workspace UI

**Files:**
- Create: `apps/web/src/components/PodcastWorkspace.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/Sidebar.tsx`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/src/i18n/dictionaries.ts`

- [ ] **Step 1: Add Podcast nav types**

Modify `apps/web/src/App.tsx`:

```ts
type MainTab = "tts" | "asr" | "podcast";
```

Add state:

```ts
const [podcastArtifact, setPodcastArtifact] = useState<Artifact | null>(null);
const [podcastState, setPodcastState] = useState<"idle" | "loading" | "error">("idle");
```

In provider switch cleanup:

```ts
setPodcastArtifact(null);
setPodcastState("idle");
```

- [ ] **Step 2: Update Sidebar**

Modify `apps/web/src/components/Sidebar.tsx`:

```ts
type MainTab = "tts" | "asr" | "podcast";
```

Add a Podcast section button after TTS and before ASR:

```tsx
<div>
  <div className="sidebar-section">{t("nav.podcastSection")}</div>
  <button
    className={["nav-item", tab === "podcast" ? "active" : ""].filter(Boolean).join(" ")}
    type="button"
    disabled={!supportsCapability("tts.builtin")}
    onClick={() => onTabChange("podcast")}
  >
    <span>🎧</span>
    <span>{t("nav.podcast")}</span>
  </button>
</div>
```

- [ ] **Step 3: Add i18n strings**

Modify `apps/web/src/i18n/dictionaries.ts`. Add these keys to `en`:

```ts
"nav.podcastSection": "Podcast",
"nav.podcast": "Podcast",
"podcast.script": "Podcast script",
"podcast.scriptFormat": "Script format",
"podcast.parsePreview": "Parse preview",
"podcast.speakers": "Speakers",
"podcast.defaultPause": "Default pause",
"podcast.generate": "Generate podcast",
"podcast.generating": "Generating podcast...",
"podcast.progress": "{current} / {total} · {speaker}",
"podcast.missingVoice": "Choose a voice for every speaker.",
"podcast.noSegments": "No speakable segments parsed.",
```

Add matching keys to `zh`:

```ts
"nav.podcastSection": "播客",
"nav.podcast": "播客",
"podcast.script": "播客脚本",
"podcast.scriptFormat": "脚本格式",
"podcast.parsePreview": "解析预览",
"podcast.speakers": "说话人",
"podcast.defaultPause": "默认停顿",
"podcast.generate": "生成播客",
"podcast.generating": "播客生成中…",
"podcast.progress": "{current} / {total} · {speaker}",
"podcast.missingVoice": "请为每个说话人选择音色。",
"podcast.noSegments": "未解析出可合成的片段。",
```

- [ ] **Step 4: Add PodcastWorkspace component**

Create `apps/web/src/components/PodcastWorkspace.tsx`:

```tsx
import { type FormEvent, useEffect, useMemo, useState } from "react";
import type { Artifact, PodcastJobStatus, PodcastScriptFormat, Provider } from "../api";
import { createPodcastJob, getPodcastJob } from "../api";
import { useI18n } from "../i18n";
import { parsePodcastScriptPreview } from "../lib/podcastScript";
import { Notice } from "./Primitives";
import { ScriptField } from "./ScriptField";

type PodcastWorkspaceProps = {
  provider: Provider | null;
  providerId: string;
  model: string | null;
  onModelChange: (value: string) => void;
  voices: { id: string; name: string; note?: string | null }[];
  onResult: (artifact: Artifact | null) => void;
};

export function PodcastWorkspace({
  provider,
  providerId,
  model,
  onModelChange,
  voices,
  onResult,
}: PodcastWorkspaceProps) {
  const { t } = useI18n();
  const [script, setScript] = useState("Alice: Welcome to the show.\nBob: Glad to be here.");
  const [scriptFormat, setScriptFormat] = useState<PodcastScriptFormat>("speaker_colon");
  const [defaultPauseMs, setDefaultPauseMs] = useState(350);
  const [speakerVoices, setSpeakerVoices] = useState<Record<string, string>>({});
  const [job, setJob] = useState<PodcastJobStatus | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  const parsed = useMemo(
    () => parsePodcastScriptPreview(script, scriptFormat, defaultPauseMs),
    [script, scriptFormat, defaultPauseMs],
  );
  const models = provider?.models.filter((item) => item.capability === "tts.builtin") ?? [];
  const selectedModel = model || models[0]?.id || "";
  const missingVoice = parsed.speakers.some((speaker) => !speakerVoices[speaker.id]);
  const canSubmit =
    Boolean(provider && selectedModel && parsed.segments.length > 0 && parsed.errors.length === 0 && !missingVoice);

  useEffect(() => {
    setSpeakerVoices((current) => {
      const next: Record<string, string> = {};
      for (const speaker of parsed.speakers) {
        next[speaker.id] = current[speaker.id] ?? voices[0]?.id ?? "";
      }
      return next;
    });
  }, [parsed.speakers, voices]);

  useEffect(() => {
    if (!job || job.status !== "queued" && job.status !== "running") return;
    const timer = window.setInterval(async () => {
      const next = await getPodcastJob(job.job_id);
      setJob(next);
      if (next.status === "completed" && next.artifact) {
        onResult(next.artifact);
        setState("idle");
      }
      if (next.status === "failed") {
        setError(next.error_summary ?? "Podcast generation failed");
        setState("error");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job, onResult]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setState("loading");
    try {
      const created = await createPodcastJob({
        providerId,
        model: selectedModel,
        script,
        scriptFormat,
        defaultPauseMs,
        speakerVoices,
      });
      setJob(created);
      if (created.status === "completed" && created.artifact) {
        onResult(created.artifact);
        setState("idle");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Podcast generation failed");
      setState("error");
    }
  }

  return (
    <form className="canvas podcast-canvas" onSubmit={submit}>
      <div className="podcast-compose">
        <section className="card podcast-script-card">
          <div className="card-header">
            <span className="card-label">{t("podcast.script")}</span>
            <select value={scriptFormat} onChange={(event) => setScriptFormat(event.target.value as PodcastScriptFormat)}>
              <option value="auto">Auto</option>
              <option value="speaker_colon">Speaker lines</option>
              <option value="markdown">Markdown</option>
              <option value="json">JSON</option>
              <option value="yaml">YAML</option>
            </select>
          </div>
          <ScriptField label={t("podcast.script")} value={script} onChange={setScript} importable required />
          <div className="podcast-preview-list">
            {parsed.errors.map((item, index) => (
              <Notice key={index} variant="error">
                {item.line ? `L${item.line}: ` : ""}{item.message}
              </Notice>
            ))}
            {parsed.segments.slice(0, 20).map((segment, index) => (
              <div key={`${segment.line}-${index}`} className="podcast-segment-row">
                <span>{segment.speakerName}</span>
                <span>{segment.text}</span>
                <span>{segment.pauseAfterMs} ms</span>
              </div>
            ))}
          </div>
        </section>
        <section className="card podcast-speakers-card">
          <div className="card-header">
            <span className="card-label">{t("podcast.speakers")}</span>
          </div>
          <label className="field">
            <span className="field-title">{t("tts.model")}</span>
            <select value={selectedModel} onChange={(event) => onModelChange(event.target.value)}>
              {models.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-title">{t("podcast.defaultPause")}</span>
            <input type="number" min={0} value={defaultPauseMs} onChange={(event) => setDefaultPauseMs(Number(event.target.value))} />
          </label>
          {parsed.speakers.map((speaker) => (
            <label key={speaker.id} className="field">
              <span className="field-title">{speaker.name}</span>
              <select
                value={speakerVoices[speaker.id] ?? ""}
                onChange={(event) => setSpeakerVoices((current) => ({ ...current, [speaker.id]: event.target.value }))}
              >
                <option value="">{t("tts.voice")}</option>
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>{voice.name || voice.id}</option>
                ))}
              </select>
            </label>
          ))}
          {missingVoice ? <Notice variant="error">{t("podcast.missingVoice")}</Notice> : null}
          {job ? <p className="field-hint">{job.current_segment ?? 0} / {job.total_segments ?? 0} · {job.current_speaker ?? ""}</p> : null}
        </section>
      </div>
      <div className="card action-card">
        {error ? <Notice variant="error">{error}</Notice> : null}
        <button className="primary-action" type="submit" disabled={state === "loading" || !canSubmit}>
          {state === "loading" ? t("podcast.generating") : t("podcast.generate")}
        </button>
      </div>
    </form>
  );
}
```

The existing `ScriptField` accepts `label`, `value`, `onChange`, `importable`, and `required`; keep those props exactly.

- [ ] **Step 5: Wire PodcastWorkspace in App**

Import `PodcastWorkspace` in `apps/web/src/App.tsx`.

Add render branch:

```tsx
{tab === "tts" ? (
  <TtsWorkspace ... />
) : tab === "podcast" ? (
  <PodcastWorkspace
    provider={selectedProvider}
    providerId={selectedProviderId}
    model={selection.models.builtin}
    onModelChange={(value) => selection.setModel("builtin", value)}
    voices={ttsVoices}
    onResult={(artifact) => {
      setPodcastArtifact(artifact);
      setPodcastState("idle");
      void refreshHistory();
    }}
  />
) : (
  <AsrWorkspace ... />
)}
```

Output panel:

```tsx
{tab === "podcast" && (podcastArtifact || podcastState === "loading") ? (
  <ResultPanel artifact={podcastArtifact} state={podcastState} />
) : null}
```

History selection:

```ts
if (artifact.kind === "audio" && artifact.operation === "podcast") {
  setPodcastArtifact(artifact);
  setPodcastState("idle");
  setTab("podcast");
  return;
}
```

- [ ] **Step 6: Add responsive CSS**

Modify `apps/web/src/styles.css`:

```css
.podcast-compose {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.85fr);
  gap: 18px;
  align-items: start;
}

.podcast-script-card,
.podcast-speakers-card {
  min-width: 0;
}

.podcast-preview-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.podcast-segment-row {
  display: grid;
  grid-template-columns: minmax(72px, 0.25fr) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
}

@media (max-width: 980px) {
  .podcast-compose {
    grid-template-columns: 1fr;
  }
}
```

Use the existing border token present in `apps/web/src/styles.css`. If the file has no `--border` token, use the same border color used by `.card`.

- [ ] **Step 7: Run web tests/build**

Run:

```bash
rtk npm --prefix apps/web test
rtk npm --prefix apps/web run build
```

Expected: tests and build pass.

- [ ] **Step 8: Browser visual verification**

Use in-app browser at `http://127.0.0.1:5173/`.

Check:

- Podcast tab visible.
- Split Compose columns align on desktop width.
- Single column on narrow width.
- Speaker cards appear after sample script.
- Generate disabled if a speaker voice is empty.

- [ ] **Step 9: Commit Task 6**

Run:

```bash
rtk git add apps/web/src
rtk git commit -m "feat(web): add podcast workspace"
```

## Task 7: History, Docs, And End-To-End Polish

**Files:**
- Modify: `apps/web/src/components/HistoryPanel.tsx`
- Create: `apps/web/src/components/HistoryPanel.test.ts`
- Modify: `README.md`

- [ ] **Step 1: Export history title helper and add failing test**

Modify `apps/web/src/components/HistoryPanel.tsx`:

```ts
export function formatHistoryTitle(
  artifact: Artifact,
  t: (key: TranslationKey, values?: Record<string, string | number>) => string,
): string {
```

Create `apps/web/src/components/HistoryPanel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Artifact } from "../api";
import type { TranslationKey } from "../i18n";
import { formatHistoryTitle } from "./HistoryPanel";

const t = (key: TranslationKey, values?: Record<string, string | number>) => {
  if (key === "history.podcastTitle") {
    return `podcast · ${values?.speakers} speakers · ${values?.segments} segments`;
  }
  return key;
};

describe("formatHistoryTitle", () => {
  it("formats podcast artifacts with speaker and segment counts", () => {
    const artifact: Artifact = {
      id: "p1",
      kind: "audio",
      provider_id: "mimo",
      operation: "podcast",
      mime_type: "audio/wav",
      created_at: "2026-01-01T00:00:00Z",
      metadata: { podcast_speaker_count: 2, podcast_segment_count: 8 },
      download_url: "/v1/artifacts/p1/download",
    };

    expect(formatHistoryTitle(artifact, t)).toBe("podcast · 2 speakers · 8 segments");
  });
});
```

Run:

```bash
rtk npm --prefix apps/web test -- HistoryPanel.test.ts
```

Expected: fail because `history.podcastTitle` handling does not exist yet.

- [ ] **Step 2: Implement podcast history title**

Modify `apps/web/src/components/HistoryPanel.tsx` in `formatHistoryTitle`:

```ts
if (artifact.operation === "podcast") {
  const speakers = Number(artifact.metadata?.podcast_speaker_count ?? 0);
  const segments = Number(artifact.metadata?.podcast_segment_count ?? 0);
  return t("history.podcastTitle", { speakers, segments });
}
```

Add i18n:

```ts
"history.podcastTitle": "podcast · {speakers} speakers · {segments} segments",
```

Add Chinese:

```ts
"history.podcastTitle": "播客 · {speakers} 人 · {segments} 段",
```

- [ ] **Step 3: Document Podcast in README**

Add a `Podcast` section to `README.md`:

````markdown
## Podcast generation

The Podcast workspace turns a multi-speaker script into one audio file.
Use one TTS provider/model, map each speaker to a built-in voice, and generate.

Supported script formats:

```text
Alice: Welcome to the show. [pause:600]
Bob: Thanks for having me.
```

Markdown headings are also accepted:

```markdown
### Alice
Welcome to the show.

### Bob
Thanks for having me.
```

JSON/YAML accepts a `lines` list with `speaker`, `text`, and optional
`pause_after_ms`. The generated artifact includes a `.podcast.json` manifest
with speakers, voices, segment text, pauses, and timing when duration can be
decoded.
```
````

- [ ] **Step 4: Run full verification**

Run:

```bash
rtk uv run pytest -q
rtk npm --prefix apps/web test
rtk npm --prefix apps/web run build
rtk uv run ruff check .
rtk uv run ruff format --check .
```

Expected: all pass.

- [ ] **Step 5: Commit Task 7**

Run:

```bash
rtk git add README.md apps/web/src apps/api/src/voice_toolbox_api/main.py tests
rtk git commit -m "docs(podcast): document generation flow"
```

## Task 8: Final Adversarial Review And Fixes

**Files:**
- Review: full branch diff from base
- Modify: files named by review findings

- [ ] **Step 1: Dispatch final adversarial review**

Use subagent reviewer with this prompt:

```text
Review entire podcast feature branch.
Focus on: parser/API mismatch, async job race, artifact privacy leaks, manifest path safety, broken UI states, history regression, missing docs, flaky tests.
Use caveman-review format. Severity: Critical, Risk, Nit.
```

- [ ] **Step 2: Verify each finding**

Mark each finding as real or not real. Real Critical/Risk findings require a code/test/doc change. Nits are fixed if cheap and not scope-expanding.

- [ ] **Step 3: Fix real findings**

Use focused patches. Add regression tests for bugs that could reappear.

- [ ] **Step 4: Run full verification again**

Run:

```bash
rtk uv run pytest -q
rtk npm --prefix apps/web test
rtk npm --prefix apps/web run build
rtk uv run ruff check .
rtk uv run ruff format --check .
```

Expected: all pass.

- [ ] **Step 5: Commit final review fixes**

If fixes were made:

```bash
rtk git add .
rtk git commit -m "fix(podcast): address final review"
```

If no fixes were needed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage:
  - multi-format parser: Task 1
  - speaker auto-detect/order: Task 1
  - per-line pause: Task 1 and Task 2
  - backend job polling: Task 3
  - audio artifact and manifest: Task 2 and Task 3
  - Split Compose UI: Task 6
  - history/docs: Task 7
  - adversarial reviews: Task 4 and Task 8
- Placeholder scan:
  - No `TBD`.
  - No `TODO`.
  - No "implement later".
  - No "add appropriate".
- Type consistency:
  - Python uses `PodcastScriptFormat`, `PodcastManifest`, `PodcastJobStatus`.
  - Web uses `PodcastScriptFormat`, `PodcastJobStatus`, `createPodcastJob`, `getPodcastJob`.
  - Artifact metadata names match spec: `podcast_manifest_version`, `podcast_manifest_sidecar`, `podcast_speaker_count`, `podcast_segment_count`.

## Execution Choice

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
