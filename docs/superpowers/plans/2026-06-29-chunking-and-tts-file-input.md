# Chunking and TTS File Input Implementation Plan

> **For agentic workers:** REQUIRED FLOW: implement task-by-task, one commit per task. After Tasks 3, 6, and 9, stop for multi-agent adversarial review and fix every finding, including minor/nit, before continuing.

**Goal:** Implement `docs/superpowers/specs/2026-06-29-chunking-and-tts-file-input-design.md`.

**Architecture:** Providers still handle one provider-ready request. A backend chunking layer handles source decoding, text/audio chunk planning, provider option validation, multi-call orchestration, transcript/audio merge, temp cleanup, and final artifact metadata. Frontend uses schema-driven and provider-specific option modules instead of a single generic Advanced panel.

**Stack:** Python 3.11+, FastAPI, Pydantic v2, pydub/ffmpeg, pytest, ruff, ty, React 19, Vite, Bun, TypeScript, Vitest, ESLint, Prettier.

---

## Execution Rules

- Use `rtk` before shell commands.
- Start every task with failing tests.
- End every task with a commit.
- Do not run real provider smoke tests unless matching API keys are present.
- Never log or sidecar raw text, transcript text, base64, clone sample bytes, or unsafe provider option values.
- Keep runtime changes scoped. Do not refactor unrelated UI, provider, or storage code.

## New Files

- `packages/voice_toolbox/src/voice_toolbox/chunking/__init__.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/models.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/options.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/text.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/audio.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/merge.py`
- `packages/voice_toolbox/src/voice_toolbox/chunking/sessions.py`
- `packages/voice_toolbox/src/voice_toolbox/transcripts.py`
- `tests/test_chunking_text.py`
- `tests/test_chunking_audio.py`
- `tests/test_provider_options.py`
- `tests/test_transcripts.py`
- `apps/web/src/components/ProviderOptionsPanel.tsx`
- `apps/web/src/lib/providerOptions.ts`
- `apps/web/src/lib/providerOptions.test.ts`
- `apps/web/src/lib/audioChunks.ts`
- `apps/web/src/lib/audioChunks.test.ts`

## Modified Files

- `packages/voice_toolbox/src/voice_toolbox/config_models.py`
- `packages/voice_toolbox/src/voice_toolbox/config.py`
- `packages/voice_toolbox/src/voice_toolbox/artifacts.py`
- `packages/voice_toolbox/src/voice_toolbox/models.py`
- `packages/voice_toolbox/src/voice_toolbox/providers/base.py`
- `packages/voice_toolbox/src/voice_toolbox/providers/fake.py`
- `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`
- `packages/voice_toolbox/src/voice_toolbox/providers/fish_audio.py`
- `packages/voice_toolbox/src/voice_toolbox/providers/openrouter.py`
- `packages/voice_toolbox/src/voice_toolbox/pipeline.py`
- `packages/voice_toolbox/src/voice_toolbox/cli.py`
- `apps/api/src/voice_toolbox_api/main.py`
- `apps/web/src/api.ts`
- `apps/web/src/App.tsx`
- `apps/web/src/styles.css`
- `apps/web/src/i18n/dictionaries.ts`
- `README.md`
- `voice_toolbox.toml.example`

---

## Task 1: Config Models and Provider Options

**Objective:** Add chunking config, transcript capabilities, provider/model option schema, validation, and redaction metadata.

### Steps

- [ ] Add failing tests in `tests/test_provider_options.py` and `tests/test_config.py`:
  - option key regex and shared-field collision rejection
  - `select` / `multiselect` choices required
  - submitted/default values must be in choices
  - `integer` / `number` default inside min/max
  - `required=true` plus default rejected
  - model-level per-field merge uses only explicitly set fields
  - model-level partial overrides parse through `ProviderOptionOverride`, not full `ProviderOptionSpec`
  - model-level `enabled=false` removes inherited option and rejects extra explicit fields
  - `dedupe_min_chars <= dedupe_max_chars`
  - `overlap_ms < target_seconds * 1000 / 2`
  - provider `type` is stable, enum-validated, and not derived from provider `id`

- [ ] Add Pydantic models:
  - `ChunkingMode`
  - `TTSChunkingConfig`
  - `ASRChunkingConfig`
  - `ChunkingConfig`
  - `TranscriptCapabilities`
  - `ProviderOptionChoice`
  - `ProviderOptionSpec`
  - `ProviderOptionOverride`
  - `ProviderAudioResult`

- [ ] Extend config/model attachment points:
  - `AppConfig.chunking: ChunkingConfig`
  - `ConfiguredProvider.options: list[ProviderOptionSpec]`
  - `ModelInfo.options: list[ProviderOptionSpec | ProviderOptionOverride]`
  - `ModelInfo.transcript_capabilities: TranscriptCapabilities | None`
  - config loader parses provider-level options as complete specs
  - config loader parses model-level entries as `ProviderOptionOverride` first, then builds final merged specs

- [ ] Add option schema merge/validation in `chunking/options.py`:
  - merge provider-level and model-level specs by capability
  - parse model-level raw dicts through `ProviderOptionOverride`, then merge non-`None` fields
  - apply defaults after merge
  - parse multipart `provider_options` JSON string
  - reject malformed JSON, non-object JSON, >4096 bytes, >32 keys
  - validate type, range, choices, required, and capability
  - build `provider_option_keys` and `provider_option_safe_values`
  - compare normalized provider option dictionaries with sorted keys and numeric equality for session finish checks
  - expose a stable fingerprint helper for browser chunk sessions so raw option values never need to be persisted

- [ ] Extend provider/model summary models so API can return:
  - provider `type`
  - provider-level `options`
  - model-level `options`
  - `transcript_capabilities`
  - provider `id` and provider `type` remain distinct in summaries

- [ ] Extend `TTSRequest` and `ASRRequest` with `provider_options: dict[str, object]`.

- [ ] Extend artifact redaction allowlist:
  - `provider_option_keys`
  - `provider_option_safe_values`
  - `source_kind`
  - `uploaded_text_file_name_hash`
  - `uploaded_text_file_suffix`
  - `uploaded_text_file_size_bytes`
  - `source_text_raw_char_count`
  - `source_file_name_hash`
  - `source_file_suffix`
  - chunking metadata keys
  - transcript richness metadata keys

- [ ] Run:

```bash
rtk uv run pytest tests/test_provider_options.py tests/test_config.py tests/test_artifacts.py -v
rtk uv run ruff check packages/voice_toolbox/src tests/test_provider_options.py tests/test_config.py
rtk uv run ty check packages/voice_toolbox/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src tests/test_provider_options.py tests/test_config.py tests/test_artifacts.py
rtk git commit -m "feat: add provider option schemas"
```

---

## Task 2: TTS Text Sources and Text Chunk Planner

**Objective:** Add inline/file text source handling and deterministic TTS text chunking.

### Steps

- [ ] Add failing tests in `tests/test_chunking_text.py`:
  - `.txt` and `.md` UTF-8 decode, including BOM
  - `.markdown`, `text/x-markdown`, and valid suffix plus `application/octet-stream`
  - unsupported suffix and mismatched MIME/suffix rejected
  - text file above `max_text_file_bytes` returns 413 before decode
  - invalid UTF-8 and NUL bytes rejected
  - `text` plus `text_file` rejected
  - file suffix infers `plain` / `markdown`
  - inline default stays `plain`
  - split by paragraphs before sentences
  - split by Chinese punctuation and ASCII sentence boundaries
  - split on clause boundaries `，`, `,`, `、`, `:`, `：` before hard split
  - hard split for overlong spans
  - leading audio tag propagation
  - chunk count max enforced
  - design mode never chunks and rejects `force`
  - design accepts `text_file` when `optimize_text_preview=false`
  - design rejects `text_file` when `optimize_text_preview=true`
  - design optimized preview still allows empty text

- [ ] Add `chunking/models.py`:
  - `TextSource`
  - `TextChunk`
  - `TextChunkPlan`
  - `TTSChunkingRequest`

- [ ] Add `chunking/text.py`:
  - text upload decode and suffix/MIME validation
  - byte-limited text upload reader
  - natural paragraph/sentence/clause/hard splitting
  - leading audio tag detection and propagation
  - design-mode single-call guard

- [ ] Integrate with `pipeline.py`:
  - normalize source once
  - plan chunks after normalization
  - return source metadata and normalization metadata
  - avoid raw text preview for uploaded files

- [ ] Add API helper skeletons without route behavior change yet:
  - `_read_text_source(...)`
  - `_infer_text_format_from_upload(...)`
  - `_prepare_tts_source(...)`

- [ ] Run:

```bash
rtk uv run pytest tests/test_chunking_text.py tests/test_pipeline.py tests/test_normalizers.py -v
rtk uv run ruff check packages/voice_toolbox/src tests/test_chunking_text.py
rtk uv run ty check packages/voice_toolbox/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/chunking packages/voice_toolbox/src/voice_toolbox/pipeline.py tests/test_chunking_text.py tests/test_pipeline.py
rtk git commit -m "feat: plan tts text chunks"
```

---

## Task 3: TTS Chunk Execution and API/CLI File Input

**Objective:** Run chunked built-in/clone TTS, merge audio, expose text-file input and chunk options in API/CLI.

### Steps

- [ ] Add failing tests in `tests/test_api.py`, `tests/test_cli.py`, and `tests/test_chunking_audio.py`:
  - `/v1/tts/builtin` accepts `text_file`
  - `/v1/tts/clone` accepts `text_file`
  - `/v1/tts/design` accepts `text_file` when `optimize_text_preview=false`
  - `/v1/tts/design` rejects `text_file` when `optimize_text_preview=true`
  - design rejects `chunking_mode=force`
  - design rejects over-limit text/file instead of chunking
  - long built-in text produces multiple provider calls
  - `provider_options` reaches every TTS chunk request
  - chunked audio merges to one final artifact
  - silence insertion is honored
  - per-chunk provider calls do not create visible artifacts/history rows
  - chunk temp buffers/files deleted on success and provider failure
  - final sidecar stores counts/lengths only
  - CLI `--file`, `--chunking`, `--chunk-max-chars`, `--chunk-silence-ms`

- [ ] Add non-persisting provider seam:
  - `synthesize_bytes(request: TTSRequest) -> ProviderAudioResult`
  - public `synthesize()` delegates to `synthesize_bytes()` and persists the single-call artifact
  - chunking calls only `synthesize_bytes()` and persists one final merged artifact

- [ ] Add `chunking/audio.py` helpers:
  - pydub decode/export helpers
  - concat audio chunks with silence
  - export target format using existing conversion mappings

- [ ] Add `chunking/merge.py` audio merge wrapper.

- [ ] Update API TTS routes:
  - `text_file: UploadFile | None`
  - nullable `text_format`
  - `chunking_mode`
  - `chunk_max_chars`
  - `chunk_silence_ms`
  - `provider_options` JSON string
  - parse/validate provider options before provider call
  - copy validated options to every chunk request

- [ ] Update CLI:
  - `--file`
  - text format suffix inference
  - chunk options
  - provider option support can stay API-only unless existing CLI has a clear JSON option seam; document if deferred.

- [ ] Ensure clone sample conversion happens once and one temp sample path is reused for all clone chunks.

- [ ] Run:

```bash
rtk uv run pytest tests/test_api.py tests/test_cli.py tests/test_chunking_audio.py tests/test_chunking_text.py -v
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests/test_api.py tests/test_cli.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src apps/api/src tests/test_api.py tests/test_cli.py tests/test_chunking_audio.py
rtk git commit -m "feat: synthesize chunked tts"
```

### Review Checkpoint 1

After Task 3, run:

```bash
rtk git diff HEAD~3..HEAD --stat
rtk uv run pytest tests/test_provider_options.py tests/test_chunking_text.py tests/test_chunking_audio.py tests/test_api.py tests/test_cli.py -v
rtk uv run ruff check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Adversarial review focus:

- no raw text in logs/sidecars
- design mode never chunks
- provider options copied to every TTS chunk
- temp files removed on error paths
- chunk count and provider call count bounded

---

## Task 4: Transcript Payloads and Download Renderers

**Objective:** Add transcript payload model, timestamp/speaker segment support, and `/transcript` renderers.

### Steps

- [ ] Add failing tests in `tests/test_transcripts.py` and `tests/test_api.py`:
  - plain transcript payload renders txt
  - `txt&timestamps=1&speakers=1`
  - SRT and VTT rendering
  - SRT/VTT reject missing timestamps
  - JSON renderer includes text/segments only through explicit transcript endpoint
  - `/v1/artifacts/{id}/transcript` rejects audio artifacts
  - `/download?format=txt` rejects transcript artifacts
  - mixed timestamped/plain transcript payload does not enable SRT/VTT
  - partial speaker labels do not enable speaker-prefixed TXT variants
  - sibling `{artifact_id}.transcript.json` permission/shape
  - sidecar does not include transcript text or segment text

- [ ] Add `transcripts.py`:
  - `TranscriptSegment`
  - `TranscriptPayload`
  - `render_txt`
  - `render_srt`
  - `render_vtt`
  - `render_json`
  - timestamp formatting helpers

- [ ] Extend `ArtifactStore`:
  - write plain `.txt` artifact as today
  - optionally write sibling `.transcript.json`
  - read transcript payload for renderer

- [ ] Update providers:
  - fake provider can produce payload for tests
  - existing providers default to plain text payload
  - keep adapters plain unless provider already returns segments

- [ ] Add `/v1/artifacts/{artifact_id}/transcript`.

- [ ] Update `/download`:
  - transcript artifact with no format or `source` returns `.txt`
  - transcript renderer formats on `/download` return 422
  - audio artifacts keep existing format conversion

- [ ] Run:

```bash
rtk uv run pytest tests/test_transcripts.py tests/test_api.py tests/test_artifacts.py -v
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests/test_transcripts.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/transcripts.py packages/voice_toolbox/src/voice_toolbox/artifacts.py apps/api/src tests/test_transcripts.py tests/test_api.py tests/test_artifacts.py
rtk git commit -m "feat: render transcript downloads"
```

---

## Task 5: Backend ASR Chunking

**Objective:** Add backend whole-file ASR chunking with overlap, provider calls per chunk, transcript dedupe merge, and metadata.

### Steps

- [ ] Add failing tests in `tests/test_chunking_audio.py` and `tests/test_api.py`:
  - backend saves large upload to temp path instead of `_read_upload`
  - ASR `off` mode also uses temp-file upload path, not `_read_upload`
  - backend upload above `chunking.asr.max_upload_mb` returns 413
  - whole-file path used when converted payload fits
  - auto chunks when provider payload would exceed limit
  - force always chunks
  - overlap must be less than half target duration
  - max chunks enforced
  - each provider chunk satisfies raw/base64 limits
  - `provider_options` copied to every ASR chunk request
  - exact overlap transcript dedupe
  - no-overlap merge inserts newline
  - `dedupe_min_chars` / `dedupe_max_chars` honored
  - timestamped segments offset by chunk time
  - mixed richness flags computed from merged payload
  - per-chunk provider calls do not create visible transcript artifacts/history rows

- [ ] Add failing CLI tests:
  - ASR `--chunking`
  - ASR `--chunk-seconds`
  - ASR `--chunk-overlap-ms`
  - ASR `--timestamps`
  - ASR `--speakers`

- [ ] Add non-persisting provider seam:
  - `transcribe_payload(request: ASRRequest) -> TranscriptPayload`
  - public `transcribe()` delegates to `transcribe_payload()` and persists the single-call artifact
  - ASR chunking calls only `transcribe_payload()` and persists one final merged transcript artifact

- [ ] Add ASR planning to `chunking/audio.py`:
  - decode source
  - build chunk ranges with overlap
  - export provider-ready temp chunks
  - validate per-chunk size

- [ ] Add transcript merge helpers to `chunking/merge.py`:
  - exact suffix/prefix dedupe
  - segment offset merge
  - speaker label preservation

- [ ] Update `/v1/asr/transcribe`:
  - `chunking_mode`
  - `chunk_seconds`
  - `chunk_overlap_ms`
  - `transcript_timestamps`
  - `transcript_speakers`
  - `provider_options`
  - stream upload to temp up to `max_upload_mb`
  - return one final transcript artifact

- [ ] Update CLI ASR command with chunk and transcript richness flags.

- [ ] Ensure provider transcript richness flags:
  - reject unsupported timestamp/speaker request before provider call
  - adapters map shared flags internally when provider supports them

- [ ] Run:

```bash
rtk uv run pytest tests/test_chunking_audio.py tests/test_api.py tests/test_transcripts.py -v
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests/test_chunking_audio.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src apps/api/src tests/test_chunking_audio.py tests/test_api.py tests/test_transcripts.py
rtk git commit -m "feat: transcribe chunked audio"
```

---

## Task 6: Browser ASR Chunk Sessions

**Objective:** Add server-side chunk sessions for browser per-chunk upload and finish-time provider transcription.

### Steps

- [ ] Add failing tests in `tests/test_api.py` and `tests/test_chunking_audio.py`:
  - create session returns server-generated ID
  - disabled browser upload returns 422 fixed message
  - create stores provider/model/language/transcript options and a `provider_options` fingerprint, not raw `provider_options`
  - create rejects `total_chunks > max_chunks`
  - chunk upload rejects `chunk_index < 0` or `chunk_index >= total_chunks`
  - chunk upload rejects duplicate index
  - chunk upload rejects invalid signature
  - chunk upload rejects decoded WAV duration mismatch
  - chunk upload rejects chunks larger than provider raw/base64 limits
  - chunk upload rejects malicious/path-like `source_file_name` and stores only filename hash/suffix
  - chunk upload enforces cumulative session byte quota and returns 413 over `max_upload_mb`
  - chunk upload rejects bad/non-monotonic offset or duration
  - create requires `source_duration_ms`
  - `source_duration_ms` catches coverage gaps
  - finish rejects missing chunks
  - finish rejects mismatched transcript/provider options by comparing resent options to the stored fingerprint
  - finish can complete after process reload when the client resends matching `provider_options`
  - finish rejects sessions that require `provider_options` when the client omits them and no in-memory copy exists
  - finish passes validated provider options to every provider call
  - finish returns normal operation response
  - delete/cancel removes temp dir
  - expired sessions removed on startup/create/upload/finish/delete/lookup

- [ ] Add `chunking/sessions.py`:
  - session ID generation
  - private temp directory layout
  - metadata JSON
  - `provider_options_hash` / fingerprint only; no raw provider option values on disk
  - chunk path management
  - TTL cleanup
  - cumulative uploaded byte accounting
  - filename hash/suffix storage only
  - coverage validation
  - opportunistic cleanup during create/upload/finish/delete/load

- [ ] Add API endpoints:
  - `POST /v1/asr/chunk-sessions`
  - `POST /v1/asr/chunk-sessions/{session_id}/chunks`
  - `POST /v1/asr/chunk-sessions/{session_id}/finish`
  - `DELETE /v1/asr/chunk-sessions/{session_id}`

- [ ] Keep provider calls in `finish`, not upload.

- [ ] Return:
  - `browser_slice_formats` with `["wav"]` for v1
  - `backend_accept_formats` excluding raw `pcm` for browser upload
  - `max_chunks`
  - `expires_at`

- [ ] Run:

```bash
rtk uv run pytest tests/test_api.py tests/test_chunking_audio.py tests/test_provider_options.py -v
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests/test_api.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

- [ ] Commit:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/chunking/sessions.py apps/api/src tests/test_api.py tests/test_chunking_audio.py
rtk git commit -m "feat: add asr chunk sessions"
```

### Review Checkpoint 2

After Task 6, run:

```bash
rtk git diff HEAD~3..HEAD --stat
rtk uv run pytest tests/test_transcripts.py tests/test_chunking_audio.py tests/test_api.py tests/test_provider_options.py -v
rtk uv run ruff check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Adversarial review focus:

- chunk sessions cannot leak path traversal
- expired/cancelled sessions clean temp files
- provider options cannot leak to logs/sidecars
- chunk-session metadata cannot leak raw provider option values
- browser chunk upload enforces provider per-chunk payload limits
- transcript renderer endpoint split is unambiguous
- browser session and backend ASR produce same response shape

---

## Task 7: Frontend Provider-Specific Options and TTS File UI

**Objective:** Replace generic Advanced assumptions with modular provider/model options and add TTS file/chunk controls.

### Steps

- [ ] Add failing frontend tests:
  - schema fallback renders all option types
  - schema fallback honors `placeholder`, `default`, `min_value`, `max_value`, and `step`
  - `advanced=false` renders in always-visible summary section
  - choice validation and required UI errors
  - provider/model change migration keeps valid values and drops invalid values
  - schema-driven option helpers are isolated from `App.tsx`
  - TTS source selector switches Text/File
  - Markdown file infers Markdown display
  - preview reads selected file and calls normalize endpoint
  - submit sends original file, not cleaned preview
  - chunking fields append to FormData
  - `provider_options` serialized as JSON object string

- [ ] Update `apps/web/src/api.ts`:
  - provider/model option schema types
  - transcript capability types
  - chunk session API client types can wait until Task 8
  - TTS forms with `textFile`, nullable `textFormat`, chunk fields, provider options

- [ ] Add provider option modules:
  - `ProviderOptionsPanel.tsx`
  - `providerOptions.ts`
  - `providerOptions.test.ts`

- [ ] Keep custom provider renderer registry deferred until a provider needs richer controls than schema fallback. The v1 requirement is no provider-specific `if/else` in `App.tsx`, not a registry with empty first-party modules.

- [ ] Update `App.tsx`:
  - remove provider-specific option conditionals from main file
  - render `ProviderOptionsPanel` below selected model
  - remove hard-coded expected output format labels; generated artifacts use actual MIME type
  - add TTS Text/File source selector
  - file accept `.txt,.md,.markdown,text/plain,text/markdown`
  - preview selected text files by reading the file in browser; submit still sends original file
  - add chunk controls under TTS Advanced

- [ ] Update styles/i18n.

- [ ] Run:

```bash
rtk bun run --cwd apps/web lint
rtk bun run --cwd apps/web format:check
rtk bun run --cwd apps/web test
rtk bun run --cwd apps/web build
```

- [ ] Commit:

```bash
rtk git add apps/web/src
rtk git commit -m "feat(web): add provider option panels"
```

---

## Task 8: Frontend Browser ASR Chunking and Transcript Downloads

**Objective:** Add ASR browser chunk upload flow, transcript options, progress, and renderer download buttons.

### Steps

- [ ] Add failing frontend tests:
  - ASR advanced chunking controls append backend fields
  - browser upload creates session
  - browser upload uploads chunks sequentially and shows progress
  - finish renders final transcript artifact
  - browser decode/slice failure falls back to backend upload with message
  - browser chunking rejects non-PCM WAV before upload and falls back to backend upload
  - cancel aborts in-flight create/upload/finish requests and deletes the session when possible
  - transcript buttons enable/disable from artifact metadata
  - SRT/VTT links use `/transcript?format=srt|vtt`
  - speaker/timestamp TXT links include query flags

- [ ] Update `api.ts`:
  - chunk session create/upload/finish/delete methods
  - transcript download URL helpers

- [ ] Add browser audio slicing helper:
  - accept browser-side slicing only for PCM WAV in v1
  - produce chunk blobs as WAV in v1
  - produce chunk blobs and offset/duration metadata
  - send `source_duration_ms` on session create only
  - do not send `source_duration_ms` on finish; finish validates against stored session metadata
  - fall back to backend upload when browser decode or WAV chunk encoding fails

- [ ] Update ASR UI:
  - upload strategy selector
  - chunk seconds / overlap
  - transcript timestamp/speaker toggles only when model capabilities allow
  - progress display
  - cancel/delete session
  - label browser strategy as best-effort/preferred browser chunking if fallback is allowed

- [ ] Add transcript download controls in `TranscriptPanel`.
  - hide SRT/VTT when artifact metadata lacks complete timestamps
  - hide TXT timestamp/speaker flags when artifact metadata lacks those enrichments

- [ ] Run:

```bash
rtk bun run --cwd apps/web lint
rtk bun run --cwd apps/web format:check
rtk bun run --cwd apps/web test
rtk bun run --cwd apps/web build
```

- [ ] Commit:

```bash
rtk git add apps/web/src
rtk git commit -m "feat(web): upload asr chunks"
```

---

## Task 9: Docs, Examples, and Full Validation

**Objective:** Update docs/examples and run full check.

### Steps

- [ ] Update `README.md`:
  - TTS file input
  - TTS chunking
  - ASR backend chunking
  - ASR browser chunking
  - transcript downloads
  - provider/model-specific options
  - privacy boundaries

- [ ] Update `voice_toolbox.toml.example`:
  - `[chunking.tts]`
  - `[chunking.asr]`
  - provider/model option examples
  - transcript capabilities examples where appropriate

- [ ] Update smoke docs:
  - TTS `.txt` smoke
  - TTS Markdown smoke
  - ASR backend chunk smoke
  - browser chunk manual smoke
  - transcript `srt/vtt/json` download smoke

- [ ] Run backend full validation:

```bash
rtk uv run pytest -v
rtk uv run ruff check .
rtk uv run ruff format --check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

- [ ] Run frontend full validation:

```bash
rtk bun run --cwd apps/web lint
rtk bun run --cwd apps/web format:check
rtk bun run --cwd apps/web test
rtk bun run --cwd apps/web build
```

- [ ] Run integrated check:

```bash
rtk make check
```

- [ ] Commit:

```bash
rtk git add README.md voice_toolbox.toml.example docs/smoke apps/web/src packages/voice_toolbox/src apps/api/src tests
rtk git commit -m "docs: document chunking workflows"
```

### Review Checkpoint 3

After Task 9, run:

```bash
rtk git log --oneline -9
rtk git diff HEAD~9..HEAD --stat
rtk git status --short
rtk make check
```

Adversarial review focus:

- browser chunking cannot bypass provider option validation
- transcript download endpoints are unambiguous
- sidecars/logs still redact unsafe content
- no provider-specific UI logic sits in `App.tsx`
- no hard-coded provider output format label sits in `App.tsx`
- chunk/session temp cleanup is bounded and tested
- browser chunk session `provider_options` survives process reload via fingerprint + client resend without persisting raw values
- browser chunk uploads reject non-PCM WAV and bad decoded duration before provider calls
- all docs match actual endpoints/options

If any review finding is real, fix and commit before handoff.
