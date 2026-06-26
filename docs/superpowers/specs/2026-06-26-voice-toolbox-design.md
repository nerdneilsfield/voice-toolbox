# Voice Toolbox Design

Date: 2026-06-26

## Summary

Voice Toolbox is a local-first voice workflow app for TTS and ASR. The first provider is MiMo, using real MiMo APIs from the start. The product starts as a single-user local app, with data boundaries that can later support multi-user workspaces.

The initial implementation has two top-level domains:

- TTS: built-in voices, voice design, voice clone, style control, optional streaming.
- ASR: audio transcription.

The implementation uses Python for backend, CLI, provider adapters, and artifact handling. React provides a single-page toolbox UI that calls the same backend/core used by the CLI.

## Goals

- Provide one local interface for MiMo TTS and ASR.
- Hide provider-specific API details behind a provider abstraction.
- Support MiMo built-in TTS, voice design, and voice clone through the TTS domain.
- Support MiMo ASR through the ASR domain.
- Save every generated or transcribed result as an artifact under `data/artifacts/`.
- Provide both CLI-first usage and a single-page React UI.
- Store local configuration in `.env` for development speed.
- Keep the domain model ready for future providers such as OpenAI-compatible APIs, `mlx-audio`, and CUDA-backed libraries.

## Non-Goals

- No multi-user login or workspace permission model in the first version.
- No cloud artifact storage in the first version.
- No model marketplace or provider plugin installer in the first version.
- No guessed provider schemas. Provider-specific calls must be based on confirmed docs or clearly disabled.
- No standalone desktop packaging in the first version.

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

Main backend layers:

- Domain models: typed request and response objects for TTS, ASR, artifacts, providers, and jobs.
- Provider registry: resolves provider IDs such as `mimo`.
- Provider adapter: implements provider capabilities behind the shared interface.
- Artifact store: writes generated audio and transcription outputs under `data/artifacts/`.
- CLI: calls the domain layer directly.
- FastAPI app: calls the domain layer through HTTP endpoints.

## Provider Model

Every provider exposes capabilities instead of hard-coded UI features.

Core capabilities:

- `tts.builtin`
- `tts.design`
- `tts.clone`
- `tts.stream`
- `asr.transcribe`

Provider contract:

```python
class VoiceProvider:
    id: str
    name: str

    def capabilities(self) -> set[str]: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def list_voices(self) -> list[VoiceInfo]: ...
    async def synthesize(self, request: TTSRequest) -> AudioArtifact: ...
    async def transcribe(self, request: ASRRequest) -> TranscriptArtifact: ...
```

MiMo is the first concrete provider. Future providers can implement only the capabilities they support.

## MiMo Provider Details

Configuration:

- `MIMO_API_KEY`: required for real calls.
- `MIMO_BASE_URL`: optional; default `https://token-plan-cn.xiaomimimo.com/v1`.
- Supported base URLs:
  - China Token Plan: `https://token-plan-cn.xiaomimimo.com/v1`
  - Singapore Token Plan: `https://token-plan-sgp.xiaomimimo.com/v1`
  - Pay-as-you-go API: `https://api.xiaomimimo.com/v1`

MiMo TTS uses Chat Completions as the primary path because it supports style control, voice design, and voice clone.

Built-in TTS:

- Model: `mimo-v2.5-tts`
- Audio format: `wav`, `mp3`, or `pcm16`
- Built-in voices:
  - `mimo_default`
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
  - `messages[].role=assistant`: required target text to synthesize.
  - `audio.voice`: selected built-in voice.

Voice design:

- Model: `mimo-v2.5-tts-voicedesign`
- `messages[].role=user`: required voice description.
- `messages[].role=assistant`: target preview or synthesis text.
- `audio.optimize_text_preview`: supported boolean.
- Built-in voices are not used for this model.

Voice clone:

- Model: `mimo-v2.5-tts-voiceclone`
- Audio sample is passed through `audio.voice`.
- `audio.voice` format: `data:{MIME_TYPE};base64,{BASE64_AUDIO}`.
- Supported sample MIME values:
  - `audio/mpeg`
  - `audio/mp3`
  - `audio/wav`
- Supported sample file types: `mp3`, `wav`.
- Base64-encoded sample string must not exceed 10 MB.
- `messages[].role=user`: optional style instruction, may be empty.
- `messages[].role=assistant`: required target text to synthesize.
- UI and CLI must include an explicit consent confirmation before clone calls.

Streaming:

- `mimo-v2.5-tts` supports low-latency streaming.
- Streaming output should request `audio.format="pcm16"`.
- `mimo-v2.5-tts-voicedesign` and `mimo-v2.5-tts-voiceclone` accept streaming calls but return once after inference completes, so the UI must label these as compatibility streaming, not low-latency streaming.

ASR:

- Model: `mimo-v2.5-asr`
- Endpoint: OpenAI-compatible audio transcription.
- Input files: common audio formats including `wav`, `mp3`, `m4a`, `flac`, and `ogg`.
- Response format:
  - default text response.
  - optional verbose response when timestamps are requested.

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
- text
- style instruction
- output format
- streaming flag
- built-in voice ID for built-in mode
- voice design description and `optimize_text_preview` for design mode
- clone sample path, MIME type, and consent flag for clone mode

`ASRRequest`:

- provider ID
- model
- input audio path
- language hint
- response format
- timestamp flag

`Artifact`:

- ID
- kind: `audio`, `transcript`, or `metadata`
- provider ID
- source operation
- file path under `data/artifacts/`
- MIME type
- created time
- request metadata without secrets

`Job`:

- ID
- operation
- status
- started time
- finished time
- artifact IDs
- error summary

The first version may execute jobs synchronously while still recording job-like metadata. The model should not prevent later background workers.

## Storage

Local files:

- `.env`: local secrets and provider settings.
- `.env.example`: documented environment variables without secrets.
- `data/voice_toolbox.sqlite`: local SQLite database for job and artifact metadata.
- `data/artifacts/`: generated audio, transcripts, and sidecar metadata.

Git ignore rules:

- `.env`
- `data/voice_toolbox.sqlite`
- `data/artifacts/*`
- keep `data/artifacts/.gitkeep`

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
  --format text
```

The CLI must fail fast when `MIMO_API_KEY` is missing.

## API Design

Initial HTTP endpoints:

```text
GET  /health
GET  /providers
GET  /providers/{provider_id}/models
GET  /providers/{provider_id}/voices

POST /tts/synthesize
POST /tts/design
POST /tts/clone
POST /asr/transcribe

GET  /jobs
GET  /jobs/{job_id}
GET  /artifacts/{artifact_id}
GET  /artifacts/{artifact_id}/download
```

For file uploads, the API accepts multipart form data. For clone requests, the backend validates sample size, sample type, and consent before calling MiMo.

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
- style instruction input
- output format selector
- streaming toggle when supported
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

Clone mode controls:

- sample file upload
- consent checkbox
- MIME/type validation display
- model fixed to `mimo-v2.5-tts-voiceclone`

ASR controls:

- audio file upload
- response format selector
- timestamps toggle
- submit button
- transcript viewer
- artifact link

A compact side panel contains provider settings:

- provider selector
- base URL selector
- API key status only, never the key value
- capability list

The UI should be quiet and tool-like: dense but readable, clear labels, predictable controls, no marketing-style hero.

## Error Handling

Validation errors are caught before provider calls:

- missing API key
- missing text
- missing voice description for design
- missing sample file for clone
- clone sample format not `mp3` or `wav`
- clone sample base64 size above 10 MB
- clone consent not confirmed

Provider errors preserve:

- provider ID
- operation
- HTTP status when available
- shortest useful provider message
- request metadata without secrets or base64 audio payloads

Artifacts are only marked complete after file write succeeds.

## Security and Consent

The app is local-first, but it still handles sensitive audio. The first version must:

- Keep API keys out of logs, artifacts, request metadata, and UI responses.
- Require explicit consent for voice clone requests.
- Store clone consent status in job metadata.
- Avoid writing raw base64 clone samples to logs or sidecar metadata.
- Document that users must only clone voices they have rights to use.

## Testing

Unit tests:

- provider registry resolution
- MiMo request construction for built-in TTS
- MiMo request construction for voice design
- MiMo request construction for voice clone data URL
- clone validation for MIME type, file extension, size, and consent
- ASR request path validation
- artifact path creation

Integration tests:

- CLI argument parsing for all four commands
- API validation paths with fake provider
- artifact creation with fake provider

Manual smoke tests with real MiMo:

- built-in TTS with `冰糖`
- voice design with a short description
- voice clone with a small `wav` or `mp3` sample
- ASR transcription of a short `wav`

## Implementation Order

1. Python package skeleton and typed domain models.
2. Artifact store and local settings loader.
3. Provider registry and fake provider for tests.
4. MiMo provider for TTS built-in, TTS design, TTS clone, and ASR.
5. CLI commands.
6. FastAPI endpoints.
7. React single-page toolbox UI.
8. Smoke test docs.

## Open Decisions

All required MVP decisions are closed:

- Run shape: local-first single user, ready for later multi-user.
- Initial provider: MiMo.
- Provider calls: real API calls, no guessed schemas.
- Tech stack: Python backend/core plus React UI.
- Secrets: `.env`.
- Artifacts: `data/artifacts/`.
- Interface shape: CLI first plus single-page UI.
- Product domains: TTS and ASR only; voice design and voice clone live under TTS.
