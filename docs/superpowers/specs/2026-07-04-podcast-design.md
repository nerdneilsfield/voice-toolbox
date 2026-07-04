# Podcast Generation Design

## Summary

Add a Podcast workspace that turns a multi-speaker script into one generated audio artifact. The user provides formatted text, the app parses speakers and segments, the user maps each speaker to a voice from one selected provider/model/mode, and the backend generates each segment, inserts pauses, and merges the audio into a podcast-like conversation.

The first implementation supports `tts.builtin` generation. The API and internal models keep a small extension point for future `tts.clone` speaker samples, but clone UI and clone execution are out of scope for the first pass.

## Goals

- Parse multi-speaker scripts from practical formats:
  - `Speaker: text`
  - Markdown speaker headings such as `### Alice`
  - structured JSON/YAML with speakers and lines
- Detect speakers automatically and preserve speaker order.
- Let users adjust the speaker list and assign a built-in voice to each speaker.
- Support a global default pause and per-line `[pause:800]` overrides.
- Run podcast generation as a backend job with pollable progress.
- Produce a complete audio artifact and a manifest describing segment timing, speaker, text, voice, and source line.
- Show completed podcast artifacts in history with a useful title and preview.

## Non-Goals

- Speaker-level provider/model/mode mixing. All speakers use the same provider, same model, and same TTS mode in the first version.
- `tts.design` podcast voices. Design mode does not map cleanly to reusable speaker voices.
- `tts.clone` execution in the first version. The schema should not block it later, but no clone sample upload UI or clone synthesis is shipped now.
- Per-segment download UI.
- SSE/WebSocket progress streaming. Polling is enough for the first version.
- Automatic LLM rewriting, speaker diarization, or script generation.

## Script Parsing

Add a parser module under `voice_toolbox.podcast` that returns a normalized podcast script:

- `PodcastScript`
  - `speakers: list[PodcastSpeaker]`
  - `segments: list[PodcastSegment]`
  - `source_format: "speaker_colon" | "markdown" | "json" | "yaml"`
- `PodcastSpeaker`
  - `id: str`
  - `name: str`
- `PodcastSegment`
  - `speaker_id: str`
  - `speaker_name: str`
  - `text: str`
  - `pause_after_ms: int | None`
  - `source_line: int | None`

Parsing rules:

- `Speaker: text` accepts a speaker name before the first colon. Empty text is ignored unless it carries a pause directive.
- Markdown mode treats `#`, `##`, and `###` headings as speaker changes. Text until the next heading becomes one or more segments. Blank lines split paragraphs.
- JSON/YAML mode accepts either:
  - `{ "lines": [{ "speaker": "Alice", "text": "..." }] }`
  - `{ "speakers": [...], "lines": [...] }`
- YAML parsing promotes `pyyaml` to a direct runtime dependency so base installs can parse YAML without relying on optional MLX dependencies.
- `[pause:800]` may appear at the end of a spoken line or as a standalone line immediately after a spoken segment. The value overrides `default_pause_ms` after that segment. `[pause:0]` is valid and means no inserted pause.
- Invalid pause values, missing speaker names, empty parsed output, and malformed structured input produce parser errors with line numbers when available.
- Speaker IDs are stable slugs generated from names, with suffixes for collisions. Display keeps the original speaker name.

## Backend API

Add podcast job endpoints:

- `POST /v1/podcast/jobs`
  - form fields:
    - `provider_id`
    - `model`
    - `script`
    - `script_format`: `auto | speaker_colon | markdown | json | yaml`
    - `default_pause_ms`
    - `speaker_voices`: JSON object keyed by speaker ID or speaker name
    - `provider_options`: existing provider option JSON
    - `chunking_mode`, `chunk_max_chars`, `chunk_silence_ms`
  - returns `PodcastJobStatus`
- `GET /v1/podcast/jobs/{job_id}`
  - returns current status, progress, errors, and artifact when complete.
- `DELETE /v1/podcast/jobs/{job_id}`
  - marks a queued job cancelled, or requests cancellation for a running job. A running segment may finish before the job stops, but no later segments should start after cancellation is observed.

Status values:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

Progress fields:

- `current_segment`
- `total_segments`
- `current_speaker`
- `current_text_preview`
- `artifact`
- `error_summary`
- `failed_segment`

The first implementation runs jobs in a lightweight in-process job store and dispatches generation in a background task. `POST /v1/podcast/jobs` returns after synchronous validation with a `queued` job, while generation updates status and progress for polling. Jobs need process-local status only; completed output is persisted through artifacts. The job store should have a bounded history and TTL cleanup to avoid unbounded memory growth. Failed jobs do not appear in history because they have no completed artifact; they remain pollable in the job store until TTL cleanup.

## Generation Flow

The backend job runner:

1. Validates provider configuration.
2. Validates the selected model supports `tts.builtin`.
3. Parses the script.
4. Validates every parsed speaker has a voice mapping.
5. For each segment:
   - builds a `TTSRequest` with the shared provider/model and that speaker's `voice_id`.
   - passes provider options through existing validation.
   - calls `provider.synthesize_bytes`.
   - records raw result, model used, speaker, source line, and text preview.
6. Merges results with `merge_audio_results`.
7. Applies per-segment pauses. If `merge_audio_results` only supports one silence value, add a podcast-specific merge helper that accepts segment pause values instead of misusing uniform chunk silence.
8. Writes the final audio artifact with `operation="podcast"`.
9. Writes a manifest sidecar next to the audio artifact.
10. Records an `OperationResult` with operation `podcast`.

Manifest fields:

- `version: 1`
- `provider_id`
- `model`
- `mode: "builtin"`
- `default_pause_ms`
- `speakers: [{ id, name, voice_id, voice_name? }]`
- `segments: [{ index, speaker_id, speaker_name, voice_id, text, source_line, pause_after_ms, start_ms, end_ms, audio_duration_ms }]`
- `created_at`

Timing accuracy should be derived from decoded segment audio durations plus pauses. If a provider returns compressed audio and exact duration cannot be read, the job should still complete but mark the affected segment duration as `null` and omit start/end values for that segment rather than inventing timing.

## Artifact Metadata

Extend artifact metadata allowlist for podcast-safe fields:

- `podcast_speaker_count`
- `podcast_segment_count`
- `podcast_default_pause_ms`
- `podcast_manifest_version`
- `podcast_manifest_sidecar`
- `podcast_mode`
- `podcast_voice_ids`
- `podcast_speakers`

Do not store full source text or full segment text in artifact metadata. Store only lengths, counts, voice IDs, speaker names, and the normal `source_text_preview`. Full segment text belongs in the manifest sidecar.

History preview uses the script preview, not provider output. History title should read like:

`podcast · 3 speakers · 18 segments`

## Web UI

Add a third primary tab named Podcast. It uses the chosen Split Compose layout:

Left column:

- Script editor with import support.
- Script format selector: Auto, Speaker lines, Markdown, JSON, YAML.
- Parse preview showing segment order, speaker, text preview, and pause.
- Parser errors with line numbers.

Right column:

- Provider/model controls limited to models with `tts.builtin`.
- Speaker cards generated from the parsed script.
- Each speaker card has a voice select. Unmapped speakers are marked invalid.
- Default pause control.
- Generate button.
- Progress panel showing `current / total`, current speaker, and current status.

Output panel:

- Reuse `ResultPanel` for the final audio artifact.
- Reuse `HistoryPanel`, with podcast-specific titles and previews.

Navigation:

- Add a shared `MainTab` type that includes `podcast`, and import it from both `App` and `Sidebar`.
- Keep TTS mode state separate from Podcast state.
- Switching providers clears incompatible podcast model/voice selections, matching existing TTS behavior.

## Validation And Errors

Client-side validation:

- Script is non-empty.
- Parsed script has at least one segment.
- Every speaker has a selected voice.
- Provider supports `tts.builtin`.
- Selected model supports `tts.builtin`.

Server-side validation:

- Repeat all client validation.
- Reject unknown speaker IDs in `speaker_voices`.
- Reject missing voice mapping for parsed speakers.
- Reject unsupported model capability.
- Reject scripts above the existing max text input length.
- Reject too many segments. Initial limit: 200 segments.
- Reject per-segment text above provider-safe limits using the same preparation/chunking path used by normal TTS.

Provider failure should include:

- provider id
- model
- segment index
- speaker
- safe provider error summary

## Tests

Backend tests:

- Parser accepts `Speaker: text`.
- Parser accepts Markdown headings.
- Parser accepts JSON/YAML structured scripts.
- Parser extracts `[pause:800]`.
- Parser reports malformed pause and missing speaker line numbers.
- API creates a job and returns queued/running/completed status.
- Fake provider receives the expected `voice_id` per speaker.
- Completed job writes audio artifact and manifest.
- Provider failure marks job failed with failed segment metadata.
- Missing speaker voice mapping returns 422.

Frontend tests:

- Podcast tab renders in navigation.
- Parsing script creates speaker cards.
- Missing voice mapping disables submit.
- Submit posts expected job payload.
- Polling progress updates status text.
- Completed job displays audio artifact.
- History title handles podcast artifacts.

Verification commands:

- `rtk uv run pytest -q`
- `rtk npm --prefix apps/web test`
- `rtk npm --prefix apps/web run build`
- `rtk uv run ruff check .`
- `rtk uv run ruff format --check .`

## Implementation Tasks

1. Add podcast parser and manifest models in the Python package.
2. Add backend podcast job store, API routes, generation runner, artifact manifest writing, and tests.
3. Add Podcast tab, Split Compose UI, parser preview, speaker voice mapping, progress polling, and web tests.
4. Polish history/result display and README documentation.
5. Run adversarial review after task 3, fix findings, then continue.
6. Run final adversarial review after all tasks, fix findings, then commit final polish.

Each completed task gets its own commit. The design document is committed before implementation planning.
