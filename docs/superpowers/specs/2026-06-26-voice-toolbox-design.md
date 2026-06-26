# Voice Toolbox Design

Date: 2026-06-26

## Summary

Voice Toolbox is a local-first voice workflow app for TTS and ASR. The first provider is MiMo, using real MiMo APIs from the start. The first version is a single-user local app.

The initial implementation has two top-level domains:

- TTS: built-in voices, voice design, voice clone, natural-language style control, and audio tag control.
- ASR: audio transcription.

The implementation uses Python for backend, CLI, provider adapters, and artifact handling. React provides a single-page toolbox UI that calls the same backend/core used by the CLI. Python dependencies use `uv`; frontend dependencies use `pnpm`.

## Goals

- Provide one local interface for MiMo TTS and ASR.
- Hide provider-specific API details behind a provider abstraction.
- Support MiMo built-in TTS, voice design, voice clone, and TTS audio tag control through the TTS domain.
- Support MiMo ASR through the ASR domain.
- Save every generated or transcribed result as an artifact under `data/artifacts/`.
- Provide both CLI-first usage and a single-page React UI.
- Store local configuration in `.env` for development speed.
- Keep future-provider seams explicit: provider registry, provider config storage interface, artifact store interface, and typed request/response models.

## Non-Goals

- No multi-user login, workspace permission model, owner columns, or per-user encryption in the first version.
- No claim that v1 storage is multi-user-ready. Multi-user support will require a later storage model with owners, auth, and non-local secret handling.
- No cloud artifact storage in the first version.
- No model marketplace or provider plugin installer in the first version.
- No guessed provider schemas. Provider-specific calls must be based on confirmed docs or clearly disabled.
- No standalone desktop packaging in the first version.
- No streaming UX or streaming API in the first version. MiMo streaming behavior will be verified after synchronous TTS/ASR are stable.
- No reusable designed voice library in the first version unless MiMo documents a reusable voice handle.
- No dedicated Director Mode builder in the first version. Director Mode is supported as natural-language text in the existing style instruction field.
- No ASR timestamps, SRT, VTT, or verbose JSON in the first version.
- No background worker or job state machine in the first version.
- No unverified TTS `mp3` output in the first version. TTS output defaults to `wav`; `mp3` output is deferred until a real MiMo smoke test confirms it.

## Approach Options

### Option A: CLI-Only Core First

Build only Python core, provider adapter, and CLI first. Add UI later.

Benefits:

- Fastest path to validating MiMo API calls.
- Simplest test surface.
- Good for automation and scripts.

Costs:

- Delays the unified toolbox experience.
- Harder to inspect artifact history and compare voices.

### Option B: UI-Only Web App

Build a React UI and backend endpoints first, with no CLI surface.

Benefits:

- Best early user experience.
- Easier to explore TTS modes visually.

Costs:

- Makes provider debugging slower.
- Risks duplicating backend behavior in UI state before the core is stable.

### Option C: Shared Core With CLI and UI

Build a Python core used by both CLI and FastAPI endpoints. Build CLI first, then a single-page React UI against the same backend.

Benefits:

- CLI validates provider behavior quickly.
- UI gets a stable backend contract.
- Shared core reduces drift.
- Future providers can plug into one registry.

Costs:

- Slightly more upfront structure than CLI-only.

Selected approach: Option C.

## Architecture

The app is a small monorepo:

```text
voice-toolbox/
  apps/
    api/
    web/
  packages/
    voice_toolbox/
  data/
    artifacts/
  docs/
    superpowers/
      specs/
```

The Python package owns domain models, provider contracts, MiMo adapter, artifact storage, and CLI commands. The API app imports the same package and exposes HTTP endpoints. The React app calls the API and does not know provider-specific request schemas.

Development import path:

- `apps/api/` imports the core package through an editable install, for example `uv pip install -e packages/voice_toolbox`.
- `apps/web/` talks to the API at `http://127.0.0.1:8000` in development.

Main backend layers:

- Domain models: typed request and response objects for TTS, ASR, artifacts, providers, and operation results.
- Provider registry: resolves provider IDs such as `mimo`, exposes capabilities, and performs capability preflight.
- Provider adapter: implements provider capabilities behind the shared interface.
- Artifact store: writes generated audio and transcription outputs under `data/artifacts/`.
- Metadata store: records artifact metadata in SQLite.
- CLI: calls the domain layer directly.
- FastAPI app: calls the domain layer through HTTP endpoints.

The future-provider seams are interfaces, not v1 multi-user implementation:

- `ProviderConfigStore`: reads provider settings from `.env` in v1; can later be backed by database rows or a secret manager.
- `ArtifactStore`: writes local files in v1; can later be backed by S3-compatible object storage.
- `MetadataStore`: uses SQLite in v1; can later be backed by PostgreSQL with `owner_id` and workspace scoping.

## Provider Model

Every provider exposes capabilities for UI gating and preflight validation.

Core capabilities:

- `tts.builtin`
- `tts.design`
- `tts.clone`
- `asr.transcribe`

Provider contract:

```python
from typing import Protocol

class VoiceProvider(Protocol):
    id: str
    name: str

    def capabilities(self) -> set[str]: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def list_voices(self) -> list[VoiceInfo]: ...
    async def synthesize(self, request: TTSRequest) -> AudioArtifact: ...
    async def transcribe(self, request: ASRRequest) -> TranscriptArtifact: ...
```

TTS design and clone dispatch through `TTSRequest.mode`. The registry checks `mode` against provider capabilities before invoking `synthesize`. If provider code is called directly with an unsupported request, it must raise `UnsupportedCapability`. This makes `capabilities()` both a UI switch and a runtime contract.

MiMo is the first concrete provider. Future providers can implement only the capabilities they support.

## MiMo Provider Details

Configuration:

- `MIMO_API_KEY`: required for real calls.
- `MIMO_BASE_URL`: optional; default `https://api.xiaomimimo.com/v1`, the base URL used by the official TTS and ASR examples.
- Token Plan base URLs are accepted as advanced configuration only after local smoke testing:
  - China Token Plan candidate: `https://token-plan-cn.xiaomimimo.com/v1`
  - Singapore Token Plan candidate: `https://token-plan-sgp.xiaomimimo.com/v1`
- Authentication uses the OpenAI Python SDK `api_key` parameter, which sends `Authorization: Bearer ...`. The app does not manually inject `api-key` headers in v1.
- MiMo models and built-in voices are hard-coded provider constants in v1. The app must not call a remote `/voices` endpoint for MiMo unless MiMo later documents one.

MiMo TTS and ASR both use Chat Completions. The app must not use OpenAI `/audio/speech` or `/audio/transcriptions` endpoints for MiMo v1.

Built-in TTS:

- Model: `mimo-v2.5-tts`
- Endpoint: `POST /v1/chat/completions`
- Audio format: `wav` in v1. `mp3` output is not enabled until verified by a real MiMo smoke test. `pcm16` is reserved for later streaming work; MiMo examples write it as 24 kHz mono signed 16-bit PCM.
- Built-in voices:
  - `mimo_default` (cluster-dependent: China cluster resolves to `冰糖`; other clusters resolve to `Mia`)
  - `冰糖`
  - `茉莉`
  - `苏打`
  - `白桦`
  - `Mia`
  - `Chloe`
  - `Milo`
  - `Dean`
- Request shape:
  - `messages[].role=user`: optional natural language style instruction.
  - `messages[].role=assistant`: required target text to synthesize. This text may include MiMo audio tags.
  - `audio.voice`: selected built-in voice.

Audio tag control:

- Tags are embedded directly in `assistant.content`, not in `user.content`.
- Supported bracket styles pass through unchanged: `()`, `（）`, and `[]`.
- Examples include `(唱歌)歌词`, `(东北话)文本`, `[叹气]`, `(深呼吸)`, laughter/crying/breathing tags, dialect tags, and role-play tags.
- Singing mode is only supported by `mimo-v2.5-tts`; it should start the target text with `(唱歌)` and works best with Chinese lyrics.
- The UI should keep one target text field and provide lightweight tag insertion helpers for common tags such as singing, dialect, sigh, laugh, whisper, and pause. The provider performs no special validation for tags.

Voice design:

- Model: `mimo-v2.5-tts-voicedesign`
- Endpoint: `POST /v1/chat/completions`
- `messages[].role=user`: required voice description.
- `messages[].role=assistant`: target preview or synthesis text. When `audio.optimize_text_preview=true`, this assistant message may be omitted and MiMo can generate suitable preview text.
- `audio.optimize_text_preview`: supported boolean.
- Built-in voices are not used for this model.
- Output is a one-shot synthesized audio artifact. The current MiMo documentation does not define a reusable designed voice ID or voice token, so v1 will not persist designed voices as reusable voice records.

Voice clone:

- Model: `mimo-v2.5-tts-voiceclone`
- Endpoint: `POST /v1/chat/completions`
- Public API and CLI receive a sample file path/upload; the provider adapter converts it into `audio.voice`.
- Provider `audio.voice` format: `data:{MIME_TYPE};base64,{BASE64_AUDIO}`.
- Supported sample MIME values:
  - `audio/mpeg`
  - `audio/mp3`
  - `audio/wav`
- Supported sample file types: `mp3`, `wav`.
- The pure base64 payload must not exceed 10 MiB. MiMo documents this as 10 MB; v1 interprets the limit conservatively as 10 MiB. Because base64 expands data, the UI and CLI should warn that raw audio must be roughly 7.5 MiB or smaller before encoding.
- `messages[].role=user`: optional style instruction, may be empty.
- `messages[].role=assistant`: required target text to synthesize.
- UI and CLI must include an explicit consent confirmation before clone calls.
- Request metadata and logs must record clone sample file name, size, MIME type, and consent status, but never the base64 payload or data URL.
- Uploaded clone samples are temporary inputs in v1. API handlers may spool them to a temp file while processing, then delete them after the provider call completes or fails. Clone samples are not saved as artifacts in v1.

ASR:

- Model: `mimo-v2.5-asr`
- Endpoint: `POST /v1/chat/completions`
- Input shape:

```json
{
  "model": "mimo-v2.5-asr",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_audio",
          "input_audio": {
            "data": "data:audio/wav;base64,{BASE64_AUDIO}"
          }
        }
      ]
    }
  ],
  "asr_options": {
    "language": "auto"
  }
}
```

- Python SDK call must pass `asr_options` through `extra_body`.
- Supported input file types: `wav`, `mp3`.
- Supported MIME values:
  - `audio/wav`
  - `audio/mpeg`
  - `audio/mp3`
- Supported language values: `auto`, `zh`, `en`.
- The pure base64 payload must not exceed 10 MiB. MiMo documents this as 10 MB; v1 interprets the limit conservatively as 10 MiB. The UI and CLI should warn that raw audio must be roughly 7.5 MiB or smaller before encoding.
- Output is `completion.choices[0].message.content` as plain text.
- Streaming, timestamps, `response_format`, SRT, VTT, and verbose JSON are not documented for MiMo ASR v1 and are out of scope for the first version.

## Data Model

`ProviderConfig`:

- provider ID
- base URL
- API key source
- default output format

`TTSRequest`:

- provider ID
- mode: `builtin`, `design`, or `clone`
- model
- target text, which may include MiMo audio tags; optional only for design mode when `optimize_text_preview=true`
- natural-language style instruction for `user.content`
- output format: `wav`
- built-in voice ID for built-in mode
- voice design description and `optimize_text_preview` for design mode
- clone sample path, MIME type, raw byte size, base64 payload size, and consent flag for clone mode

`ASRRequest`:

- provider ID
- model
- input audio path
- MIME type
- raw byte size
- base64 payload size
- language: `auto`, `zh`, or `en`

`Artifact`:

- ID
- kind: `audio` or `transcript`
- provider ID
- source operation
- file path under `data/artifacts/`
- MIME type
- created time
- request metadata allowlist without secrets, base64 payloads, or data URLs

Artifact naming:

- Store files under `data/artifacts/YYYYMMDD/`.
- Use operation IDs in filenames, for example `{operation_id}.wav`, `{operation_id}.txt`, and `{operation_id}.json`.
- Audio artifacts use the selected output MIME type, initially `audio/wav`.
- Transcript artifacts are stored as `.txt` with MIME `text/plain; charset=utf-8`.
- Sidecar metadata is a same-operation `.json` file that contains redacted operation and artifact metadata.

`OperationResult`:

- operation ID
- operation
- status: `completed` or `failed`
- started time
- finished time
- artifact IDs
- error summary

The first version executes operations synchronously. There are no `/jobs` endpoints and no pending/running job states in v1.

## Storage

Local files:

- `.env`: local secrets and provider settings.
- `.env.example`: documented environment variables without secrets.
- `data/voice_toolbox.sqlite`: local SQLite database for artifact and operation metadata.
- `data/artifacts/`: generated audio, transcripts, and sidecar metadata.

SQLite startup behavior:

- Use simple startup schema creation for v1.
- Enable WAL mode.
- Configure a busy timeout.
- Keep metadata writes short and retry bounded write conflicts.

Git ignore rules:

- `.env`
- `data/voice_toolbox.sqlite`
- `data/voice_toolbox.sqlite-*`
- `data/artifacts/*`
- keep `data/artifacts/.gitkeep`

API key configuration:

- v1 expects users to set `MIMO_API_KEY` in `.env`.
- `.env.example` documents `MIMO_API_KEY` and `MIMO_BASE_URL`.
- The UI does not write secrets back to `.env` in v1.
- If the key is missing, CLI and UI show a setup message pointing to `.env` and `.env.example`.

## CLI Design

The CLI must support both module execution and console script alias:

```bash
python -m voice_toolbox tts synthesize
python -m voice_toolbox tts design
python -m voice_toolbox tts clone
python -m voice_toolbox asr transcribe
voice-toolbox tts synthesize
voice-toolbox tts design
voice-toolbox tts clone
voice-toolbox asr transcribe
```

Example command shape:

```bash
python -m voice_toolbox tts synthesize \
  --text "你好，欢迎使用 MiMo 语音合成。" \
  --voice 冰糖 \
  --style "轻快活泼" \
  --format wav
```

```bash
python -m voice_toolbox tts design \
  --description "年轻男声，温暖，自信，语速适中" \
  --text "欢迎来到今天的节目。" \
  --format wav
```

When `--optimize-text-preview` is set for `tts design`, `--text` may be omitted.

```bash
python -m voice_toolbox tts clone \
  --sample voice.wav \
  --consent \
  --text "这是克隆音色测试。" \
  --format wav
```

```bash
python -m voice_toolbox asr transcribe \
  --file input.wav \
  --language auto
```

The CLI must fail fast when `MIMO_API_KEY` is missing.

For clone calls, `--consent` means the caller confirms they have rights to use the sample voice. In interactive CLI mode, omitting `--consent` should prompt for confirmation before failing.

## API Design

Initial HTTP endpoints:

```text
GET  /v1/health
GET  /v1/providers
GET  /v1/providers/{provider_id}/models
GET  /v1/providers/{provider_id}/voices

POST /v1/tts/synthesize
POST /v1/tts/design
POST /v1/tts/clone
POST /v1/asr/transcribe

GET  /v1/artifacts/{artifact_id}
GET  /v1/artifacts/{artifact_id}/download
```

Endpoint semantics:

- `/v1/artifacts/{artifact_id}` returns JSON metadata.
- `/v1/artifacts/{artifact_id}/download` returns raw artifact bytes.
- Browser-facing upload endpoints accept multipart form data where files are involved.
- The provider layer never receives multipart data. API handlers read uploaded files, validate size/type/consent, and pass normalized request models to the provider adapter.
- Clone and ASR provider calls encode file bytes as base64 data URLs in Chat Completions JSON.

CORS:

- Development allows the React dev origin, normally `http://localhost:5173`.
- Non-dev local serving should prefer same-origin. The API binds to `127.0.0.1` by default and only binds externally when explicitly configured.

Development ports:

- FastAPI: `127.0.0.1:8000`.
- React dev server: `127.0.0.1:5173`.
- React dev requests should proxy `/v1/*` to `http://127.0.0.1:8000`.

## UI Design

The first UI is a single-page toolbox. It has two top-level tabs:

- TTS
- ASR

The TTS tab has a segmented mode control:

- Built-in
- Design
- Clone

Common TTS controls:

- text input
- audio tag insertion helpers for common MiMo tags
- style instruction input
- output format selector fixed to `wav` in v1
- submit button
- audio preview player
- artifact link
- raw error panel collapsed by default

Built-in mode controls:

- voice selector
- model selector defaulting to `mimo-v2.5-tts`

Design mode controls:

- voice description input
- optimize text preview toggle
- model fixed to `mimo-v2.5-tts-voicedesign`
- explanatory label that designed voices are one-shot synthesis outputs in v1, not reusable voice assets
- when optimize text preview is enabled, target text becomes optional

Clone mode controls:

- sample file upload
- consent checkbox
- MIME/type validation display
- base64 size warning
- model fixed to `mimo-v2.5-tts-voiceclone`

ASR controls:

- audio file upload
- language selector: `auto`, `zh`, `en`
- submit button
- transcript viewer
- artifact link
- no response-format selector or timestamp toggle in v1

A compact side panel contains provider settings:

- provider selector
- base URL selector
- API key status based only on whether the env var is present, never the key value
- capability list

The UI should be quiet and tool-like: dense but readable, clear labels, predictable controls, no marketing-style hero.

## Error Handling

Validation errors are caught before provider calls:

- missing API key
- missing text
- missing voice description for design
- missing sample file for clone
- missing ASR file
- clone sample format not `mp3` or `wav`
- ASR file format not `mp3` or `wav`
- clone or ASR base64 payload size above 10 MiB
- clone consent not confirmed
- unsupported provider capability

Provider calls:

- Use bounded HTTP timeouts: 60 seconds for TTS, 90 seconds for ASR, and 30 seconds for metadata-style provider calls if added later.
- Retry only transient network failures and 429/5xx responses with a small bounded backoff: at most 2 retries, exponential backoff starting at 1 second.
- Do not retry validation errors or 4xx provider request errors other than 429.

Provider errors preserve:

- provider ID
- operation
- HTTP status when available
- shortest useful provider message
- request metadata allowlist without secrets, base64 payloads, or data URLs

Artifacts are only marked complete after file write succeeds.

## Metadata Redaction

Metadata and logs use an allowlist. Allowed request metadata keys:

- provider ID
- model
- operation
- TTS mode
- output format
- built-in voice ID
- voice design description length
- style instruction length
- source text length
- uploaded file name
- uploaded file MIME type
- raw byte size
- base64 payload size
- language
- consent status

Forbidden metadata/log values:

- API keys
- Authorization headers
- `api-key` headers
- base64 payloads
- data URLs
- raw uploaded audio bytes

## Security and Consent

The app is local-first, but it still handles sensitive audio. The first version must:

- Keep API keys out of logs, artifacts, request metadata, and UI responses.
- Require explicit consent for voice clone requests.
- Store clone consent status in operation metadata.
- Avoid writing raw base64 clone samples or ASR audio data to logs or sidecar metadata.
- Document that users must only clone voices they have rights to use.

## Testing

Unit tests:

- provider registry capability preflight
- unsupported capability behavior
- MiMo request construction for built-in TTS
- MiMo request construction for built-in TTS with audio tags in `assistant.content`
- MiMo request construction for voice design
- MiMo request construction for voice design with omitted text when `optimize_text_preview=true`
- MiMo request construction for voice clone data URL
- MiMo request construction for ASR Chat Completions with `extra_body.asr_options`
- clone validation for MIME type, file extension, base64 size, and consent
- ASR validation for MIME type, file extension, base64 size, and language
- artifact path creation
- artifact naming and transcript MIME type
- metadata redaction allowlist excludes secrets, base64 payloads, and data URLs
- SQLite startup enables WAL and busy timeout

Integration tests:

- CLI argument parsing for all four commands
- API validation paths with fake provider
- artifact creation with fake provider
- CORS allows configured dev origin
- `/v1/artifacts/{id}` returns metadata and `/v1/artifacts/{id}/download` returns bytes

Manual smoke tests with real MiMo:

- built-in TTS with `冰糖`
- built-in TTS with `(唱歌)` tag in Chinese lyrics
- voice design with a short description
- voice design with `optimize_text_preview=true` and no target text
- voice clone with a small `wav` or `mp3` sample
- ASR transcription of a short `wav`
- ASR transcription of a short `mp3`

## Implementation Order

1. Python package skeleton and typed domain models.
2. Artifact store, metadata store, local settings loader, SQLite WAL setup, and redaction allowlist.
3. Provider registry and fake provider for tests.
4. MiMo built-in TTS request construction plus real MiMo smoke test.
5. MiMo voice design, voice clone, and ASR provider support plus targeted real MiMo smoke tests.
6. CLI commands.
7. FastAPI `/v1` endpoints and CORS.
8. React single-page toolbox UI.
9. Smoke test docs.

## Resolved Decisions

- Run shape: local-first single user.
- Initial provider: MiMo.
- Provider calls: real API calls, no guessed schemas.
- Tech stack: Python backend/core plus React UI.
- Secrets: `.env`.
- Artifacts: `data/artifacts/`.
- Interface shape: CLI first plus single-page UI.
- Product domains: TTS and ASR only; voice design and voice clone live under TTS.
- TTS and ASR provider calls both use MiMo Chat Completions in v1.
- Streaming and ASR timestamps are deferred until documented and smoke-tested.
- TTS output is `wav` only in v1. `mp3` output is deferred until smoke-tested.
- Default MiMo base URL is `https://api.xiaomimimo.com/v1`; Token Plan base URLs are advanced candidates until smoke-tested.
