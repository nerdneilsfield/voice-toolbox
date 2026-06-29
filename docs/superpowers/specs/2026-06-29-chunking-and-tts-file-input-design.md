# Chunking and TTS File Input Design

Date: 2026-06-29

## Summary

Voice Toolbox needs bounded chunking for long TTS and ASR work. TTS should accept inline text or uploaded text files, normalize `txt` / Markdown content, split long text on natural boundaries, call the selected provider per chunk, and merge audio into one final artifact. ASR should split long audio into overlapping chunks, call the selected provider per chunk, and merge transcripts with deterministic overlap deduplication.

This design keeps provider adapters simple: providers still synthesize or transcribe one provider-ready request. A new backend chunking layer orchestrates multi-call work, temporary chunk files, merge logic, artifact metadata, and safety limits.

## Goals

- Add TTS input from uploaded `.txt` and `.md` / `.markdown` files.
- Reuse the existing normalization pipeline for inline text and uploaded text files.
- Add backend TTS text chunking for long normalized text.
- Prefer paragraph and sentence boundaries before hard character splits.
- Merge chunked TTS audio into a single downloadable artifact.
- Add backend ASR audio chunking for large or long audio files.
- Add ASR chunk overlap and deterministic transcript deduplication.
- Keep chunk temp files private and delete them after the request completes.
- Add frontend controls for text-file input and chunking mode.
- Keep raw text, transcript contents, base64, and file contents out of logs and sidecars.

## Non-Goals

- No background job queue in this round.
- No resumable completed operations in this round.
- No parallel provider calls in v1; chunk calls are sequential to reduce rate-limit and billing surprises.
- No semantic or LLM transcript deduplication.
- No support for document formats beyond `txt`, `md`, and `markdown`.
- No per-chunk artifacts in the visible artifact history by default.
- No server-sent or websocket provider progress stream in this round.
- No resumable chunk sessions after browser refresh in this round.

## Selected Architecture

Use a backend-owned bounded pipeline with two ASR ingress paths:

```text
TTS:
source text/file -> decode -> normalize -> text chunk plan -> provider synthesize per chunk
  -> audio concat -> final audio artifact

ASR:
source audio upload -> decode/convert -> audio chunk plan with overlap -> provider transcribe per chunk
  -> transcript dedup merge -> final transcript artifact

ASR browser chunk upload:
browser audio file -> browser slices with overlap -> upload chunk session parts
  -> backend validates/stores each part -> finish triggers provider transcribe per chunk
  -> transcript dedup merge -> final transcript artifact
```

Why this split:

- Provider limits, retries, artifact storage, and log redaction already live behind the API.
- TTS text upload is small compared with audio; there is no useful browser-side bandwidth saving.
- ASR audio can be large. Browser-side chunk upload reduces remote upload failure risk and lets the UI keep each request under backend/proxy limits.
- Backend chunking still solves the provider per-call size limit because the backend can convert and split before provider calls.
- Both ASR paths share the same backend transcript merge and artifact logic, so frontend chunking is a transport optimization, not a second transcription implementation.

V1 browser chunk sessions are temp-file based and are not a resumable product feature in the web UI. Session files may survive a process restart until TTL cleanup, but raw provider options are not persisted; clients must resend matching `provider_options` on `finish` when a process restart or multi-worker boundary loses the in-memory copy. If a session is abandoned, temp files expire and no artifact is created.

## Config

Add global chunking config to `AppConfig`:

```toml
[chunking.tts]
mode = "auto"          # "off" | "auto" | "force"
max_chars = 1500
max_chunks = 40
max_text_file_bytes = 2000000
silence_ms = 120
repeat_leading_audio_tags = true

[chunking.asr]
mode = "auto"          # "off" | "auto" | "force"
target_seconds = 90
overlap_ms = 1200
max_chunks = 80
max_upload_mb = 250
browser_upload = true
session_ttl_seconds = 3600
dedupe_min_chars = 8
dedupe_max_chars = 200
```

Model shape:

```python
ChunkingMode = Literal["off", "auto", "force"]

class TTSChunkingConfig(BaseModel):
    mode: ChunkingMode = "auto"
    max_chars: int = Field(default=1500, ge=200, le=8000)
    max_chunks: int = Field(default=40, ge=1, le=200)
    max_text_file_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)
    silence_ms: int = Field(default=120, ge=0, le=3000)
    repeat_leading_audio_tags: bool = True

class ASRChunkingConfig(BaseModel):
    mode: ChunkingMode = "auto"
    target_seconds: int = Field(default=90, ge=10, le=600)
    overlap_ms: int = Field(default=1200, ge=0, le=10000)
    max_chunks: int = Field(default=80, ge=1, le=500)
    max_upload_mb: int = Field(default=250, ge=1, le=2048)
    browser_upload: bool = True
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    dedupe_min_chars: int = Field(default=8, ge=1, le=100)
    dedupe_max_chars: int = Field(default=200, ge=20, le=2000)

class ChunkingConfig(BaseModel):
    tts: TTSChunkingConfig = Field(default_factory=TTSChunkingConfig)
    asr: ASRChunkingConfig = Field(default_factory=ASRChunkingConfig)
```

Provider payload size limits stay provider-owned. The chunking layer asks the active provider metadata for upload limits when available; until a provider-level field exists, it uses the same project constants already used by the upload path:

- provider base64 limit: `MAX_BASE64_AUDIO_SIZE`
- provider raw limit: `(MAX_BASE64_AUDIO_SIZE // 4) * 3`

Request-level controls may override mode and numeric values within config bounds. Invalid overrides return HTTP 422.

`max_chunks` is intentionally not request-overridable because it bounds server work, provider calls, and temp file consumption. Raising it requires a config change.

Config validation:

- `chunking.asr.dedupe_min_chars <= chunking.asr.dedupe_max_chars`.
- `chunking.asr.overlap_ms < chunking.asr.target_seconds * 1000 / 2`.

Config attachment points:

- `AppConfig` owns `chunking: ChunkingConfig`.
- `ConfiguredProvider` owns provider-level `options: list[ProviderOptionSpec]`.
- `ModelInfo` owns model-level `options: list[ProviderOptionSpec | ProviderOptionOverride]` and optional `transcript_capabilities`.
- Provider summaries expose provider-level options; model summaries expose model-level options and transcript capabilities.

## Provider and Model-Specific Options

The frontend must not reduce every provider to one generic Advanced panel. Each provider/model can expose its own controls so model-specific features are visible instead of hidden behind the maximum common denominator.

Add a small UI option schema to provider config and API summaries.

```python
ProviderOptionType = Literal[
    "boolean",
    "integer",
    "number",
    "string",
    "text",
    "select",
    "multiselect",
]

class ProviderOptionChoice(BaseModel):
    value: str
    label: str
    description: str | None = None

class ProviderOptionSpec(BaseModel):
    key: str
    label: str
    type: ProviderOptionType
    capability: str
    description: str | None = None
    default: bool | int | float | str | list[str] | None = None
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

class ProviderOptionOverride(BaseModel):
    key: str
    capability: str
    label: str | None = None
    type: ProviderOptionType | None = None
    description: str | None = None
    default: bool | int | float | str | list[str] | None = None
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
```

Option attachment points:

- Provider-level options apply to every model with the matching capability.
- Model-level options override or extend provider-level options.
- Provider-level entries are complete `ProviderOptionSpec` objects.
- Model-level entries may be complete `ProviderOptionSpec` objects or partial `ProviderOptionOverride` objects.
- If the same option key appears at both levels, merge specs per field: start with the provider-level spec, then overwrite only non-`None` fields from the model-level override. This lets a model narrow `max_value` without restating label, description, or choices.
- Implementations should parse model-level raw dicts into `ProviderOptionOverride` before building the final `ProviderOptionSpec`; do not require `label` or `type` when `enabled=false`.
- A model-level option with the same key and `enabled=false` removes that provider-level option for the model. This is terminal: inherited `required`, `default`, and other fields are ignored, the option is hidden in the UI, and submitted values for that key are rejected.
- When `enabled=false`, the model-level entry may contain only `key`, `capability`, and `enabled`. Any other explicitly set field is a config validation error.
- For model-level options, `capability` must match the model's capability. It is accepted for schema uniformity but ignored for routing once attached to the model.
- Capability-specific built-in controls such as text, voice, style instruction, voice description, file upload, chunking, transcript download, and shared timestamp/speaker toggles stay first-class controls, not provider options.
- Provider-specific controls are for provider/model knobs that do not belong to the shared request contract.
- `provider_specific=false` marks a shared, schema-defined option that multiple provider types may reuse. It does not change validation or rendering; it is informational for docs and custom panels.
- `provider_specific` is reserved for future documentation/tooling. V1 runtime must not branch on it.
- Option keys must match `^[a-z][a-z0-9_]{0,63}$` and must not collide with shared request field names such as `text`, `model`, `voice_id`, `style_instruction`, `voice_description`, `chunking_mode`, `language`, `provider_options`, `transcript_timestamps`, or `transcript_speakers`.

Request model extension:

```python
class TTSRequest(BaseModel):
    ...
    provider_options: dict[str, object] = Field(default_factory=dict)

class ASRRequest(BaseModel):
    ...
    provider_options: dict[str, object] = Field(default_factory=dict)
```

Non-persisting provider result types:

```python
class ProviderAudioResult(BaseModel):
    audio: bytes
    mime_type: str
    suffix: str
    model: str | None = None
```

Rules:

- Schema validation at config load:
  - option keys must match the naming rule and avoid shared-field collisions;
  - `select` and `multiselect` must define at least one choice;
  - `select` defaults must exist in `choices[].value`;
  - `multiselect` defaults must be a list of strings and every value must exist in `choices[].value`;
  - `integer` / `number` defaults must be inside `[min_value, max_value]` when those bounds are set;
  - `required=true` and a non-`None` `default` are mutually exclusive;
  - `enabled=false` entries must not set any field except `key`, `capability`, and `enabled`.
- API validates submitted option keys against the selected provider/model option schema.
- Unknown option keys return 422.
- Submitted option keys must belong to the current request capability after provider/model option merge; submitting a TTS option to ASR returns 422.
- Required option missing returns 422.
- Type mismatch or out-of-range value returns 422.
- `provider_options` is limited to 32 keys and 4096 UTF-8 bytes after JSON serialization. Larger payloads return 422.
- Multipart routes receive `provider_options` as a JSON object string. The API parses it before constructing `TTSRequest` / `ASRRequest`. Malformed JSON, JSON arrays, JSON strings, or any non-object JSON return 422 with `provider_options must be a JSON object`.
- `select` options must define at least one choice, and submitted/default values must exist in `choices[].value`.
- `multiselect` options must define at least one choice, submitted/default values must be a list of strings, and every value must exist in `choices[].value`.
- `required=true` and a non-`None` `default` are mutually exclusive at schema validation time. Use either "caller must explicitly provide value" or "backend applies default", not both.
- Defaults are applied by the API after schema merge and before provider calls. Defaults are also reflected in the frontend when provider/model changes.
- Providers receive validated `provider_options`.
- Sidecars/logs never store raw provider option values by default.
- `safe_metadata=true` is intentionally narrow:
  - it is intended only for non-sensitive, non-user-generated, publicly auditable enum/numeric parameters such as `speed`, `format`, or `latency_priority`;
  - it must not be used for prompts, instructions, URLs, paths, identity fields, routing policy, reference text, or any free-form user input;
  - raw values may be stored only for `boolean`, `integer`, `number`, and `select`;
  - stored string values from `select` must be one of `choices[].value` and `<= 256` characters;
  - `string`, `text`, and `multiselect` values are never stored raw even if marked safe; store length or count only.
- Sidecars always may store `provider_option_keys`.
- `provider_option_safe_values` is a flat object mapping safe option keys to sanitized scalar values, for example `{"speed": 1.1, "format": "mp3", "tag_count": 3}`. For `multiselect`, use count-only shape such as `{ "<key>_count": 3 }`.

Frontend rendering:

- Provider/model summaries provide option specs.
- Frontend renders controls from schema as fallback.
- First-party providers may later register provider-specific React panels for richer UX.
- The generic fallback is still required so config-defined providers remain usable.
- Advanced settings are grouped by selected provider and selected model, not by a fixed global layout.
- When provider or model changes, invalid option values are dropped and defaults for the new schema are applied.
- Fallback rendering rules:
  - `boolean` -> checkbox/toggle
  - `integer` / `number` -> numeric input, honoring `min_value`, `max_value`, and `step`
  - `string` -> single-line text input
  - `text` -> textarea
  - `select` -> select or segmented control when choices are few
  - `multiselect` -> checkbox group
- `placeholder`, `required`, `default`, `choices`, `min_value`, `max_value`, and `step` must be honored by the fallback renderer.
- `advanced=false` does not move the field outside `ProviderOptionsPanel`; it means the field appears in the panel's always-visible summary section. `advanced=true` appears in the collapsible advanced section.
- Optional custom renderer registry keys use provider `type` plus capability, for example `openrouter:tts.builtin`. Provider instances with the same `type` share renderer code; schema still comes from the selected provider/model and can differ per instance.
- Provider/model change migration algorithm:
  1. Merge the new provider/model option schema for the current capability.
  2. Drop keys absent from the new schema or marked `enabled=false`.
  3. For each remaining key, keep the old value only if it validates against the new merged spec, including type, range, choices, and key count limits.
  4. If old value is missing or invalid, apply the new default when present.
  5. If a required option has no valid old value and no default, leave it unset and show a local validation error before submit.
  6. `safe_metadata` changes do not affect frontend retention; they affect only backend metadata redaction.

Examples:

- MiMo TTS design can expose model-specific voice-design hints or audio-tag helpers that do not belong to the shared TTS contract.
- Fish Audio can expose latency/format/reference-related knobs that do not apply to MiMo.
- OpenRouter can expose OpenAI-style `instructions` / provider routing options only on models that support them.
- In this app OpenRouter is a voice provider for TTS/ASR through OpenRouter audio endpoints; a future `OpenRouterTTSOptionsPanel` would be intentional, but v1 schema fallback is sufficient.
- ASR models with diarization can expose speaker-related controls; plain ASR models should not show them.

## TTS File Input

Text source can be:

- Inline form field `text`
- Uploaded form file `text_file`

Rules:

- `text` and `text_file` are mutually exclusive.
- `text_file` is accepted for built-in TTS and clone TTS.
- `text_file` is accepted for voice design only when `optimize_text_preview=false`; it supplies the target preview/synthesis text, not the voice description/persona.
- If `optimize_text_preview=true`, `text_file` must be absent and empty `text` remains allowed.
- Accepted suffixes: `.txt`, `.md`, `.markdown`.
- Accepted MIME types: `text/plain`, `text/markdown`, `text/x-markdown`, `application/octet-stream` when suffix is valid.
- File bytes are decoded as UTF-8 with optional BOM. Invalid UTF-8 returns 422.
- Text files are streamed or read with a hard limit of `chunking.tts.max_text_file_bytes` before decoding. Oversized text files return 413.
- Binary-looking text files are rejected if they contain NUL bytes.
- Uploaded text filenames may not be stored raw. Sidecars may store only suffix and `uploaded_text_file_name_hash = sha256(basename).hexdigest()[:12]`. File contents are never stored in sidecars or logs.

Text format inference:

- Explicit `text_format` still wins.
- If `text_file` exists and `text_format` is omitted:
  - `.txt` -> `plain`
  - `.md` / `.markdown` -> `markdown`
- Inline text keeps current default: `plain`.

New safe metadata:

- `source_kind`: `"inline"` or `"file"`
- `uploaded_text_file_name_hash`
- `uploaded_text_file_suffix`
- `uploaded_text_file_size_bytes`
- `source_text_raw_char_count`: decoded source text length before normalization
- Normalized length is already captured by `normalization_output_length`; chunk lengths are captured by `chunking_text_lengths`.

No raw text preview should be added for file uploads.

## TTS Text Chunking

Chunking happens after normalization.

Modes:

- `off`: require a single provider call. If normalized text exceeds `max_chars`, return 422.
- `auto`: single call if normalized text length is `<= max_chars`; otherwise chunk.
- `force`: route through the chunking planner even if text is short. It may still produce a single chunk when there is no safe split point or text length is under `max_chars`.

Scope:

- Chunked TTS applies only to `builtin` and `clone` modes in v1.
- `design` mode is always a single provider call because voice design returns one designed voice preview/result, not a sequence of independently mergeable voice-design operations.
- If `design` mode receives text or `text_file` longer than `max_chars`, return 422 with `voice design text exceeds single-call limit`; do not chunk it.
- `chunking_mode=force` on `design` returns 422.

Chunk splitter priority:

1. Natural paragraphs separated by one or more blank lines.
2. Sentence boundaries inside a paragraph:
   - Chinese punctuation: `。！？；`
   - ASCII punctuation followed by whitespace: `.`, `!`, `?`, `;`
3. Clause boundaries: `，`, `,`, `、`, `:`, `：`
4. Hard split at `max_chars`.

Hard rules:

- Chunks are non-empty after `.strip()`.
- Chunk count must be `<= max_chunks`.
- If one token-like span exceeds `max_chars`, split by character boundary.
- Do not split inside UTF-16 surrogate pairs; Python `str` indexing is acceptable.
- Do not mutate normalized text except boundary whitespace trimming and optional leading audio-tag propagation.

Audio tag propagation:

- A leading bracketed audio-tag prefix such as `(唱歌)`, `（东北话）`, `[breath]` may define global delivery style.
- If `repeat_leading_audio_tags=true`, the prefix is prepended to chunks after the first when the chunk does not already start with a bracketed tag.
- This is metadata-free text control sent to the provider, not stored as raw sidecar text.
- The sidecar stores only `chunking_repeated_leading_audio_tags: true|false`.

Provider requests:

- Each chunk uses the normal `TTSRequest` shape, but it must go through an internal non-persisting provider call path. The chunk call returns audio bytes / mime metadata, not a visible artifact.
- `style_instruction`, `voice_id`, `voice_description`, `clone_*`, `model`, provider ID, and validated `provider_options` are copied to each chunk request.
- Provider options are copied unchanged to every chunk request. Options that must vary per chunk, such as random seeds or per-call request IDs, must not be exposed as provider options in v1; defer them until a future per-chunk option mechanism exists.
- Voice design never enters the chunked path in v1.
- Clone sample upload is converted once, then reused as the same temp file for all chunk requests.

Audio merge:

- Decode each returned chunk audio buffer through `pydub`.
- Concatenate in chunk order.
- Insert `silence_ms` silence between chunks.
- Export the final artifact in the requested TTS output format.
- Delete temporary chunk buffers/files after final artifact creation.
- If a provider returns a format that cannot be decoded, fail the operation with 502 and no final artifact.

Artifact behavior:

- The visible artifact is one final `audio` artifact.
- Chunk provider outputs are temporary implementation details and must not be inserted into the visible artifact store or history.
- Final sidecar metadata stores counts and lengths only:
  - `chunking_enabled`
  - `chunking_operation`
  - `chunking_mode`
  - `chunking_strategy`
  - `chunking_chunk_count`
  - `chunking_max_chars`
  - `chunking_silence_ms`
  - `chunking_text_lengths`
  - `chunking_repeated_leading_audio_tags`

## ASR Audio Chunking

ASR supports two chunking paths:

- Backend chunking: one whole source upload reaches the API, then the backend decodes, chunks, and transcribes.
- Browser chunk upload: the browser slices the source audio into overlapped chunks and uploads them one by one to a backend chunk session; the backend validates, optionally converts, transcribes, then merges.

Both paths produce the same final transcript artifact model.

Modes:

- `off`: current behavior. Convert whole upload to a provider-native format and call provider once. If converted provider payload exceeds the provider limit, return 413.
- `auto`: try whole-file path first if it fits provider limits; otherwise chunk.
- `force`: always chunk.

Backend upload handling:

- ASR uses a new temp-file save path for all modes, including `off`, instead of `_read_upload()` so large source uploads do not have to fit the provider 10 MiB base64 limit or memory.
- Enforce `chunking.asr.max_upload_mb` on raw uploaded bytes while streaming to temp file.
- Reuse existing MIME/suffix validation.
- Decode audio with `pydub` from the temp source file.
- Unsupported or corrupt audio returns 422.

Browser chunk session handling:

- Browser chunking is enabled only when `chunking.asr.browser_upload=true`.
- The browser is responsible for producing ordered chunk files with overlap.
- Session creation records selected provider, model, language, transcript options, safe option metadata, and a fingerprint of validated `provider_options`; raw option values are not written to metadata JSON.
- Individual chunk uploads do not accept `provider_options`; they are transport-only.
- `finish` may resend transcript options and `provider_options` only to support stateless clients, process restarts, or multi-worker boundaries. If present, options must validate to the same normalized fingerprint stored at session creation. Mismatch returns 409.
- If a session was created with non-empty provider options and the backend no longer has an in-memory copy, `finish` without resent `provider_options` returns 409 rather than silently dropping provider-specific behavior.
- The backend is authoritative for validation:
  - `session_id` must be server-generated.
  - `chunk_index` must be `0..total_chunks-1`.
  - Duplicate chunk indexes are rejected.
  - `total_chunks` must be `<= max_chunks`.
- Each uploaded chunk must pass MIME/suffix/signature validation.
- Browser-uploaded chunks are WAV only in v1 and must be decoded as PCM WAV. Non-PCM WAV, malformed WAV, or decoded duration mismatch returns 422 or falls back to backend upload on the frontend before upload.
  - Each provider-ready chunk must satisfy provider raw/base64 limits.
- Browser-provided `offset_ms` is the chunk start offset and is used for transcript timestamp adjustment after validation. Offsets must be non-negative and strictly increasing by chunk index, while overlap is represented by `offset[i + 1] < offset[i] + duration[i]`.
- Browser-provided `duration_ms` is treated as a client plan, not truth. The backend decodes each chunk, records actual duration, and rejects the chunk if client duration differs from decoded duration by more than 1000 ms.
- `source_duration_ms` is required for browser chunk sessions. Finish cross-checks the union of chunk offsets/durations against it. A gap or overrun larger than 1500 ms returns 422.
- Session state is stored under a private temp directory, not `data/artifacts`.
- Session state contains only safe metadata, temp chunk paths, and the `provider_options` fingerprint. Raw `source_file_name` and raw provider option values are never stored; state may store an opaque `source_file_name_hash` plus suffix.
- A session expires after `session_ttl_seconds`.
- `finish` fails if any chunk is missing.
- Abandoned sessions are cleaned on startup and opportunistically during new session creation, chunk upload, finish, delete, and session lookup.
- Each session's disk usage is bounded by `chunking.asr.max_upload_mb`; chunk upload must stream to disk with cumulative session byte accounting before accepting the chunk. Worst-case temporary leak before cleanup is roughly `active_or_expired_session_count * max_upload_mb`.
- V1 does not run a periodic background cleanup task. If temp directory growth is observed in long-lived deployments, add a periodic cleanup task in a follow-up.

Chunk planning:

- `target_seconds` defines the nominal chunk duration.
- `overlap_ms` is included at the end of every chunk except the final chunk.
- `overlap_ms` must be less than half of `target_seconds`.
- Chunk count must be `<= max_chunks`.
- Each chunk is exported to the provider's native upload format:
  - Prefer `wav` for providers that accept wav.
  - Use `mp3` only when provider config declares no wav support later.
- Each chunk must satisfy provider raw/base64 size limits after export.

Provider requests:

- Each chunk uses the normal `ASRRequest` shape, but it must go through an internal non-persisting provider call path. The chunk call returns a `TranscriptPayload`, not a visible transcript artifact.
- `provider_id`, `model`, `language`, and validated `provider_options` are copied to every chunk request.
- Provider options are copied unchanged to every chunk request. Options that must vary per chunk are out of scope for v1.
- Per-chunk temp files are unlinked after the provider call completes.
- For browser chunk sessions, provider calls happen during `finish`, not during individual chunk upload. This keeps transcript merge deterministic and prevents partial billing if the upload fails midway.

Provider transcript richness:

Some providers can return timestamps, segments, or speaker labels. V1 models this without forcing every provider to support it.

First-class transcript toggles:

- `transcript_timestamps` and `transcript_speakers` are shared intent flags, not provider options.
- If a selected model declares the requested capability as unsupported, the API returns 422 before provider calls.
- Adapters map these flags to provider-specific request fields internally when the provider API requires it.
- Provider option schemas must not define keys named `transcript_timestamps`, `transcript_speakers`, `timestamps`, or `speakers` for the same purpose.
- If a provider needs extra diarization or timestamp tuning beyond the shared toggles, expose those as provider-specific options with distinct names, for example `diarization_min_speakers`.
- The shared toggles control requested provider output and available download renderers. Frontend download buttons still use artifact metadata (`transcript_has_timestamps`, `transcript_has_speakers`) because a provider may fail to return requested richness.

Provider config may declare transcript capabilities:

```python
class TranscriptCapabilities(BaseModel):
    timestamps: bool = False
    speakers: bool = False
    segments: bool = False
```

The shared transcript result shape is:

```python
class TranscriptSegment(BaseModel):
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None

class TranscriptPayload(BaseModel):
    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    has_timestamps: bool = False
    has_speakers: bool = False
```

Adapters that only return plain text produce `segments=[]`.

When chunking ASR with timestamped segments:

- Add each chunk's `offset_ms` to segment `start_ms` and `end_ms`.
- Subtract the deduped overlap only from transcript text, not from segment timestamps.
- Keep speaker labels as returned by provider.
- Do not attempt cross-chunk speaker diarization reconciliation in v1.
- `transcript_has_timestamps` is true only if the final rendered transcript can be fully represented by timestamped segments. If any non-empty merged text span lacks timestamps, the flag is false and SRT/VTT are disabled.
- `transcript_has_speakers` is true only if every non-empty merged segment has a speaker label. Partial speaker labels remain available in JSON, but speaker-prefixed TXT variants are disabled when the flag is false.
- Download renderers that require timestamps still return 422 when the final `transcript_has_timestamps` flag is false.

Transcript merge:

Without timestamps, v1 uses deterministic text overlap deduplication:

1. Build a normalized view for matching while preserving an index map back to original transcript text:
   - Collapse ASCII whitespace to one space.
   - Preserve CJK characters and punctuation order.
2. For each next transcript, find the longest suffix of the accumulated transcript that equals a prefix of the next transcript.
3. Search match lengths from `min(dedupe_max_chars, len(tail), len(next))` down to `dedupe_min_chars`.
4. If a match exists, use the normalized-to-original index map to append only the non-overlapping suffix from the original next transcript.
5. If no match exists, append `\n` plus the next transcript.

Defaults are `dedupe_min_chars=8` and `dedupe_max_chars=200`. The minimum avoids deleting tiny repeated particles; the maximum bounds CPU work and avoids matching across unrelated long sections. This is intentionally conservative. It removes exact repeated overlap text but does not attempt fuzzy semantic merging.

With timestamped segments:

- Merge segment lists by adjusted time order.
- Drop a segment if its text is fully removed by exact overlap dedupe and its time range sits inside the prior overlap window.
- Otherwise keep the segment and let duplicate text removal affect only the final plain text rendering.
- If provider returns only word-level timestamps, adapter should coerce them into segment-level timestamps where possible; raw word lists are deferred.

Transcript download renderers:

- `txt`: plain transcript text.
- `txt?timestamps=1`: each segment line prefixed with `[HH:MM:SS.mmm - HH:MM:SS.mmm]` when timestamps exist.
- `txt?speakers=1`: each segment line prefixed with `Speaker: ` when speaker labels exist.
- `txt?timestamps=1&speakers=1`: both prefixes.
- `srt`: requires timestamped segments; returns 422 if unavailable.
- `vtt`: requires timestamped segments; returns 422 if unavailable.
- `json`: returns safe transcript payload metadata and segments. It includes transcript text because this is an explicit transcript download endpoint, not sidecar metadata.

Transcript artifact storage:

- The primary transcript artifact remains a `.txt` file for backward compatibility and history preview.
- When a provider returns segments, timestamps, or speakers, store an additional private sibling payload file:
  - filename: `{artifact_id}.transcript.json`
  - permissions: `0600`
  - contents: `TranscriptPayload`
- This payload file is transcript content, not metadata. It is allowed to contain transcript text and segments.
- Sidecar `.json` remains metadata-only and must not contain transcript text, segment text, or speaker utterance text.
- Download renderers load the sibling payload when present; otherwise they render from the plain `.txt` transcript artifact.

Final transcript artifact metadata:

- `chunking_enabled`
- `chunking_operation`
- `chunking_mode`
- `chunking_chunk_count`
- `chunking_target_seconds`
- `chunking_overlap_ms`
- `chunking_audio_durations_ms`
- `chunking_transcript_lengths`
- `chunking_dedupe_removed_chars`
- `transcript_has_timestamps`
- `transcript_has_speakers`
- `transcript_segment_count`
- `transcript_download_formats`

No transcript contents are stored in sidecars or logs.

## API Changes

Provider summaries must include stable `type`:

```json
{
  "id": "openrouter",
  "type": "openrouter",
  "name": "OpenRouter"
}
```

`type` identifies the provider implementation family used by the frontend options renderer registry. `id` identifies a configured provider instance.

`type` source:

- Built-in providers set `type` from the provider implementation family: `mimo`, `fish_audio`, `openrouter`, or `fake`.
- Configured providers may declare `type` only from the supported provider type enum accepted by backend registry construction.
- The backend must not derive `type` from `id`.
- `type` must be stable across restarts.
- Unknown/custom provider types use schema fallback rendering unless a frontend renderer is registered for that `type:capability` key.

Provider/model summaries add optional ASR transcript capability fields:

```json
{
  "id": "model-id",
  "name": "Model",
  "capability": "asr.transcribe",
  "transcript_capabilities": {
    "timestamps": true,
    "speakers": false,
    "segments": true
  }
}
```

If absent, the frontend treats all fields as `false`.

Provider/model summaries also include provider/model-specific option schemas:

```json
{
  "id": "model-id",
  "capability": "tts.builtin",
  "options": [
    {
      "key": "speed",
      "label": "Speed",
      "type": "number",
      "capability": "tts.builtin",
      "default": 1.0,
      "min_value": 0.5,
      "max_value": 2.0,
      "step": 0.1,
      "provider_specific": true
    }
  ]
}
```

Provider-level summary may also include `options`; the frontend merges provider-level and selected-model options for the selected capability.

TTS routes add:

```text
text_file: UploadFile | None
chunking_mode: "off" | "auto" | "force" | None
chunk_max_chars: int | None
chunk_silence_ms: int | None
provider_options: JSON object string | None
```

`text_format` becomes nullable at the API boundary so file upload can infer default format.

ASR route adds:

```text
chunking_mode: "off" | "auto" | "force" | None
chunk_seconds: int | None
chunk_overlap_ms: int | None
transcript_timestamps: bool | None
transcript_speakers: bool | None
provider_options: JSON object string | None
```

ASR browser chunk upload endpoints:

```text
POST /v1/asr/chunk-sessions
  provider_id
  model?
  language
  total_chunks
  source_duration_ms
  transcript_timestamps?
  transcript_speakers?
  provider_options?
  source_file_name?

POST /v1/asr/chunk-sessions/{session_id}/chunks
  chunk_index
  offset_ms
  duration_ms
  file

POST /v1/asr/chunk-sessions/{session_id}/finish
  transcript_timestamps?
  transcript_speakers?
  provider_options?

DELETE /v1/asr/chunk-sessions/{session_id}
```

Session creation returns:

```json
{
  "session_id": "...",
  "expires_at": "...",
  "max_chunks": 80,
  "browser_slice_formats": ["wav"],
  "backend_accept_formats": ["wav", "mp3", "m4a", "aac", "flac", "ogg", "webm"]
}
```

`browser_slice_formats` is the subset the frontend should upload after browser-side slicing. V1 uses WAV chunks because providers accept WAV and browser-side mp3/m4a/aac/ogg/webm encoders are not consistently available. The v1 browser helper slices PCM WAV only; non-PCM WAV or other formats fall back to backend whole-file upload. `backend_accept_formats` intentionally excludes raw `pcm` for browser chunk upload because raw PCM has no self-describing sample rate/channel metadata.

Chunk upload returns safe progress only:

```json
{
  "session_id": "...",
  "received_chunks": 3,
  "total_chunks": 10
}
```

`finish` returns the normal operation response.

Transcript download endpoints:

```text
GET /v1/artifacts/{artifact_id}/download
GET /v1/artifacts/{artifact_id}/transcript
GET /v1/artifacts/{artifact_id}/transcript?format=txt
GET /v1/artifacts/{artifact_id}/transcript?format=txt&timestamps=1&speakers=1
GET /v1/artifacts/{artifact_id}/transcript?format=srt
GET /v1/artifacts/{artifact_id}/transcript?format=vtt
GET /v1/artifacts/{artifact_id}/transcript?format=json
```

`/download` keeps existing behavior:

- Audio artifacts use audio conversion `format=source|wav|mp3|...`.
- Transcript artifacts return the source `.txt` transcript when `format` is omitted or `format=source`.
- Transcript artifacts reject `format=txt|srt|vtt|json` on `/download` with 422; clients must use `/transcript`.
- Transcript artifacts reject audio formats on `/download` with 422.

`/transcript` is transcript-renderer-only:

- It accepts only transcript artifacts.
- It rejects audio artifacts with 422.
- `format=txt|srt|vtt|json`; omitted format defaults to `txt`.
- Unsupported combinations return 422.

Response shape remains unchanged:

```json
{
  "operation": "...",
  "artifact": "..."
}
```

The artifact metadata reveals whether chunking happened. No chunk text or transcript content is returned outside the artifact file itself.

## CLI Changes

TTS commands add:

```text
--file PATH
--chunking off|auto|force
--chunk-max-chars N
--chunk-silence-ms N
```

Rules:

- `--text` and `--file` are mutually exclusive.
- `--text-format` may be omitted when `--file` is used; suffix inference applies.

ASR command adds:

```text
--chunking off|auto|force
--chunk-seconds N
--chunk-overlap-ms N
--timestamps / --no-timestamps
--speakers / --no-speakers
```

CLI output prints final artifact only, plus chunk count when chunking occurred.

Provider-specific `provider_options` are API/frontend-only in v1. CLI support for arbitrary provider option JSON is deferred.

Transcript download CLI may add later; v1 can document HTTP download URLs for `txt`, `srt`, `vtt`, and `json`.

## Frontend Changes

TTS:

- Add source selector: `Text` / `File`.
- File source accepts `.txt,.md,.markdown,text/plain,text/markdown`.
- When a Markdown file is selected, default format display becomes Markdown unless the user overrides it.
- Frontend `TextFormat` type stays `"plain" | "markdown" | "auto"`, but TTS form builders may omit `text_format` when submitting a file so the backend can infer from suffix.
- `Preview cleaned text` works for uploaded text files by reading the file in the browser and calling `/v1/normalize/text`; submit still sends the original file to the backend.
- Add chunking controls under Advanced:
  - Mode: Auto / Off / Force
  - Max chars
  - Silence between chunks
- Show estimated chunk count after local text is available. Estimate is best-effort only; backend remains authoritative.
- Add `ProviderOptionsPanel` below model selection:
  - It receives selected provider, selected model, capability, and current option values.
  - It merges provider-level and model-level option specs.
  - It renders schema-driven fallback controls.
- It may delegate to provider-specific panels in a later enhancement, but v1 can ship schema fallback only as long as provider/model schemas remain distinct and no provider-specific `if/else` lives in `App.tsx`.
  - It serializes validated values into `provider_options` FormData.

ASR:

- Add chunking controls under Advanced:
  - Mode: Auto / Off / Force
  - Chunk seconds
  - Overlap milliseconds
- Add upload strategy:
  - `Backend upload`: current whole-file upload; backend chunks if needed.
  - `Prefer browser chunk upload`: browser slices and uploads chunks to `/v1/asr/chunk-sessions`, with backend upload fallback when browser slicing fails.
- Browser chunk upload uses sequential uploads with visible progress: `uploaded N / total`.
- Browser chunk upload aborts in-flight create/upload/finish requests when the user cancels, then best-effort deletes the session.
- If browser cannot decode/slice a file, or if the WAV is non-PCM, fall back to backend upload with a clear local message.
- Add transcript options:
  - request timestamps when provider/model declares support
  - request speakers when provider/model declares support
- Render provider/model-specific ASR options from the same `ProviderOptionsPanel`.
- Add transcript download controls:
  - TXT
  - TXT + timestamps
  - TXT + speakers
  - TXT + timestamps + speakers
  - SRT
  - VTT
  - JSON
- Disable SRT/VTT buttons when artifact metadata says `transcript_has_timestamps=false`.
- Disable speaker variants when `transcript_has_speakers=false`.

Frontend modularity:

- Do not place provider-specific conditionals directly inside `App.tsx`.
- V1 uses a schema-driven fallback panel as the required implementation. A custom renderer registry is an extension seam, not required until a provider needs UX richer than schema controls.
- Optional future registry shape:

```ts
type ProviderOptionsPanelProps = {
  provider: Provider;
  model: ProviderModel | null;
  capability: Capability;
  value: Record<string, unknown>;
  onChange(value: Record<string, unknown>): void;
};

type ProviderOptionsRenderer = (props: ProviderOptionsPanelProps) => React.ReactNode;
```

- If a custom renderer registry exists, `ProviderOptionsPanel` first checks by provider `type` and capability.
- If no custom renderer exists, use schema fallback.
- Current v1 files live under:

```text
apps/web/src/components/
  ProviderOptionsPanel.tsx
apps/web/src/lib/
  providerOptions.ts
  audioChunks.ts
```

- The schema fallback must be accessible and complete enough for config-only providers.
- Custom panels must still round-trip through the same `provider_options` object.

## Logging and Metadata Safety

Allowed new metadata keys:

- `source_kind`
- `uploaded_text_file_name_hash`
- `uploaded_text_file_suffix`
- `uploaded_text_file_size_bytes`
- `source_text_raw_char_count`
- `source_file_name_hash`
- `source_file_suffix`
- `provider_option_keys`
- `provider_option_safe_values`
- `chunking_enabled`
- `chunking_operation`
- `chunking_mode`
- `chunking_strategy`
- `chunking_chunk_count`
- `chunking_max_chars`
- `chunking_silence_ms`
- `chunking_text_lengths`
- `chunking_repeated_leading_audio_tags`
- `chunking_target_seconds`
- `chunking_overlap_ms`
- `chunking_audio_durations_ms`
- `chunking_transcript_lengths`
- `chunking_dedupe_removed_chars`

Forbidden everywhere except temp files, provider requests, final transcript artifact files, sibling transcript payload files, and explicit transcript download responses:

- Raw uploaded text
- Normalized text
- Per-chunk TTS text
- Transcript text
- Base64 audio
- Clone sample bytes
- Provider option raw values unless their schema marks them `safe_metadata=true`

This applies to sidecars, application logs, Uvicorn/FastAPI logs, provider adapter debug logs, and future error-reporting integrations. Adapter logging must explicitly redact `provider_options` and log only `provider_option_keys` plus allowed `provider_option_safe_values`.

## Error Matrix

- TTS `text` and `text_file` both present: 422
- TTS no text source and not design optimized preview: 422
- Unsupported text file suffix: 422
- Text file exceeds `chunking.tts.max_text_file_bytes`: 413
- Invalid UTF-8 text file: 422
- Normalized text empty: 422
- Voice design with `chunking_mode=force`: 422
- Voice design text/file exceeds single-call limit: 422
- Chunk count exceeds max: 422
- ASR upload exceeds server max upload size: 413
- ASR browser chunk session disabled by config: 422 with `browser chunk upload is disabled`
- ASR browser chunk session missing/expired: 404
- ASR browser chunk session duplicate chunk index: 409
- ASR browser chunk session finish with mismatched transcript/provider options: 409
- ASR browser chunk session finish omits `provider_options` after process reload when options are required: 409
- ASR browser chunk session finish with missing chunks: 422
- ASR browser chunk offset/duration inconsistent with decoded audio: 422
- ASR browser upload of non-PCM WAV: frontend fallback to backend upload, or backend 422 if submitted directly
- ASR browser chunk session missing `source_duration_ms`: 422
- ASR browser chunk source coverage gap with `source_duration_ms`: 422
- ASR browser chunk session cumulative upload exceeds `max_upload_mb`: 413
- ASR chunk count exceeds max: 422
- Unknown provider option key: 422
- Provider option key for another capability: 422
- Provider option type mismatch or out-of-range value: 422
- Required provider option missing: 422
- Malformed `provider_options` JSON or non-object JSON: 422
- `provider_options` exceeds 4096 bytes or 32 keys: 422
- `select` / `multiselect` schema without choices: config validation error
- `select` / `multiselect` submitted/default value outside choices: 422 or config validation error
- `integer` / `number` default outside min/max: config validation error
- Provider option schema with `required=true` and non-`None` default: config validation error
- Provider option schema with `enabled=false` plus other explicit fields: config validation error
- `dedupe_min_chars > dedupe_max_chars`: config validation error
- Converted provider chunk exceeds provider size limit: 413
- Audio decode/conversion failure: 422
- Provider chunk call fails: 502
- Audio merge failure: 502
- Transcript SRT/VTT requested without timestamps: 422
- Transcript speaker rendering requested without speakers: 422

## Testing

Backend tests:

- Text file decoding accepts `.txt` UTF-8 and `.md` UTF-8 BOM.
- Text file decoding rejects invalid UTF-8 and NUL bytes.
- `text` plus `text_file` is rejected.
- Markdown file infers `markdown` when `text_format` is omitted.
- Inline text keeps default `plain`.
- TTS splitter prefers paragraphs, then sentences, then hard split.
- TTS splitter preserves total text after joining chunks, ignoring boundary trim.
- Leading audio tags can be repeated on later chunks.
- TTS auto mode sends one provider call for short text.
- TTS auto mode sends multiple provider calls for long text.
- TTS force mode runs the chunk planner for short text and may still produce one chunk.
- TTS off mode rejects text over max chars.
- TTS design mode never chunks and rejects `chunking_mode=force`.
- TTS design mode rejects text/file longer than the single-call `max_chars`.
- TTS chunk merge inserts configured silence.
- Provider/model option schema validates allowed keys and types.
- Provider option schema rejects invalid key names and shared-field collisions.
- Unknown provider option is rejected.
- Provider option for the wrong capability is rejected.
- `select` / `multiselect` submitted value outside `choices` is rejected.
- `required=true` missing option is rejected.
- Schema validation rejects `required=true` with non-`None` default.
- Schema validation rejects `select` / `multiselect` without choices.
- Schema validation rejects `integer` / `number` defaults outside configured min/max.
- Schema validation rejects `dedupe_min_chars > dedupe_max_chars`.
- Model-level option overrides provider-level option by per-field merge.
- Model-level `enabled=false` removes a provider-level option for that model.
- Model-level `enabled=false` rejects any explicitly set field except `key`, `capability`, and `enabled`.
- Provider option defaults are applied before provider calls.
- Malformed `provider_options`, JSON arrays, JSON strings, and JSON numbers return 422.
- Oversized `provider_options` and too many keys return 422.
- Provider option sidecar stores keys, not raw values, unless `safe_metadata=true`.
- `safe_metadata=true` stores allowed scalar values and refuses to store raw `string`, `text`, or `multiselect` values.
- TTS final artifact metadata includes chunk count and text lengths only.
- TTS chunk requests receive validated `provider_options` on every chunk.
- TTS chunk temp files are deleted after success and failure.
- Clone TTS converts sample once and reuses it across chunks.
- Design optimized preview with empty text skips chunking.
- ASR auto mode sends one provider call when converted payload fits.
- ASR auto mode chunks when converted payload exceeds provider limit.
- ASR chunk planner enforces overlap < half target duration.
- ASR chunk planner enforces max chunks.
- ASR per-chunk exported files satisfy provider size checks.
- ASR chunk requests receive validated `provider_options` on every chunk.
- ASR transcript merge removes exact overlap duplicates.
- ASR transcript merge inserts newline when no overlap match exists.
- ASR timestamped segment merge offsets chunk timestamps.
- ASR speaker labels are preserved when provider returns them.
- Transcript download renders plain `txt`.
- Transcript download renders `txt` with timestamps and speakers.
- Transcript download renders `srt` and `vtt` when timestamps exist.
- Transcript download rejects `srt` and `vtt` when timestamps are absent.
- Transcript renderer uses `/v1/artifacts/{id}/transcript` and `/download` rejects transcript renderer formats.
- `/v1/artifacts/{id}/transcript` rejects audio artifacts with 422.
- `/v1/artifacts/{id}/download?format=txt` rejects transcript artifacts with 422.
- ASR final sidecar does not contain transcript contents.
- Browser chunk session creates server-generated session ID.
- Browser chunk session stores a validated `provider_options` fingerprint from create without raw values on disk.
- Browser chunk upload rejects duplicate chunk indexes.
- Browser chunk finish rejects missing chunks.
- Browser chunk finish rejects mismatched resent `provider_options`.
- Browser chunk finish accepts matching resent `provider_options` after process-local option cache is gone.
- Browser chunk finish rejects omitted `provider_options` after process-local option cache is gone when the session requires options.
- Browser chunk upload rejects non-monotonic or materially wrong `offset_ms` / `duration_ms`.
- Browser chunk upload rejects non-PCM WAV or frontend falls back before upload.
- Browser chunk session requires `source_duration_ms`.
- Browser chunk finish rejects source coverage gaps.
- Browser chunk finish passes validated provider options from the in-memory session copy or matching resent finish payload to provider chunk calls.
- Browser chunk finish produces the same operation response shape as whole-file ASR.
- Browser chunk temp files are removed on success, cancel, and expiry cleanup.
- Log capture does not contain raw uploaded text, chunk text, transcripts, or base64.

Frontend tests:

- TTS source selector switches between textarea and text file input.
- Markdown file selection sets inferred format display.
- Preview cleaned text reads selected file and calls normalize endpoint.
- Submit sends `text_file` rather than browser-cleaned preview.
- Chunking controls append expected form fields.
- ASR chunking controls append expected form fields.
- Browser ASR chunk mode creates a chunk session and uploads chunks sequentially.
- Browser ASR chunk mode sends `source_duration_ms` on create, not finish.
- Browser ASR chunk progress renders uploaded count.
- Browser ASR finish renders the final transcript artifact.
- Browser ASR cancel aborts in-flight requests and deletes the session when possible.
- Browser ASR non-PCM WAV falls back to backend upload.
- Provider-specific options panel renders schema fallback for unknown provider type.
- Provider-specific options panel can use a custom renderer for a known provider.
- Provider/model change drops invalid provider option values and applies defaults.
- Transcript download buttons enable/disable from artifact metadata.
- SRT/VTT links use `/v1/artifacts/{id}/transcript?format=srt|vtt`.
- Invalid local file type shows form error before submit.

Manual smoke:

- Built-in TTS from `.txt` file produces one artifact.
- Built-in TTS from `.md` file strips Markdown before provider call.
- Long TTS text chunks and merges to one audio file.
- Long ASR audio chunks and returns one transcript.
- Long ASR audio uses browser chunk upload and returns one transcript.
- ASR overlap case removes repeated phrase once.
- Timestamped ASR artifact downloads valid `.vtt` and `.srt`.

## Implementation Notes

Suggested new modules:

```text
packages/voice_toolbox/src/voice_toolbox/chunking/
  __init__.py
  text.py
  audio.py
  merge.py
  sessions.py
  models.py
```

Suggested API helpers:

- `_read_text_source(...)`
- `_infer_text_format_from_upload(...)`
- `_prepare_tts_source(...)`
- `_run_tts_chunked_or_single(...)`
- `_save_audio_upload_to_temp(...)`
- `_run_asr_chunked_or_single(...)`
- `_create_asr_chunk_session(...)`
- `_append_asr_session_chunk(...)`
- `_finish_asr_chunk_session(...)`

Existing provider adapters should not gain chunking logic.

Provider internal call seam:

- Add internal adapter methods or service helpers that can perform one provider call without writing to `ArtifactStore`:
  - `synthesize_bytes(request: TTSRequest) -> ProviderAudioResult`
  - `transcribe_payload(request: ASRRequest) -> TranscriptPayload`
- Public `synthesize()` / `transcribe()` may delegate to these helpers and then persist the final artifact.
- Chunking must call the non-persisting helpers and persist only the final merged artifact.
