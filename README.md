# voice-toolbox

Local-first voice toolbox for MiMo, Fish Audio, and OpenRouter TTS/ASR providers. Python core, Typer CLI, FastAPI API, and React web UI share one provider layer.

## Setup

Install Python dependencies with `uv`:

```bash
rtk uv sync --extra dev
```

Audio format conversion uses `pydub`; Python 3.13+ also installs `audioop-lts`
because the stdlib `audioop` module was removed. Install `ffmpeg` on the host
for mp3, m4a, flac, ogg, webm, and aac decoding/encoding.

Install frontend dependencies with `bun`:

```bash
rtk bun install --cwd apps/web
```

Create local environment config:

```bash
rtk cp -n .env.example .env
```

Edit `.env` and set `MIMO_API_KEY`, `FISH_AUDIO_API_KEY`, and/or `OPENROUTER_API_KEY`. For configurable providers, copy
`voice_toolbox.toml.example` to `voice_toolbox.toml` and edit non-secret provider
settings there.

```bash
rtk cp -n voice_toolbox.toml.example voice_toolbox.toml
```

Config discovery order:

1. Explicit path passed by Python/API code.
2. `VOICE_TOOLBOX_CONFIG`.
3. `voice_toolbox.toml` in the current working directory.
4. Built-in MiMo fallback config.

`voice_toolbox.toml` stores provider IDs, model IDs, voices, logging, and local API
binding. It stores only API key environment variable names such as
`MIMO_API_KEY`, `MIMO_SGP_API_KEY`, `FISH_AUDIO_API_KEY`, or `OPENROUTER_API_KEY`; key values stay in `.env` or the process
environment. When the API reports provider status, it exposes only whether a key
is configured plus a masked local preview, never the full key.

Provider and model-specific options also live in `voice_toolbox.toml`. The web
UI reads option schemas from `/v1/providers` and renders only options that apply
to the selected provider, model, and capability. Multipart API calls pass option
values as a `provider_options` JSON object string. The CLI does not expose
provider-specific options yet.

### MLX Audio on Apple Silicon

MLX Audio is optional and local-only. Install it only on Apple Silicon macOS:

```bash
rtk uv sync --extra mac
```

Enable it with a provider block:

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
default_voice = "Ryan"
```

The first MLX Audio version supports `tts.builtin`, `tts.clone`, and
`asr.transcribe`. Voice clone models require `clone_reference_text` so MLX Audio
can pass `ref_audio` and `ref_text` to the upstream model. Clone-capable defaults
include Qwen3 TTS Base, LongCat AudioDiT, Ming Omni/BailingMM, and Higgs Audio
v3.

MLX Audio voices are model-specific. Qwen3 builtin TTS exposes preset speakers
`Ryan`, `Aiden`, `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, and `Eric`. LongCat,
Ming Omni, and Higgs Audio v3 do not use the Qwen3 preset speaker list; they use
zero-shot generation, reference audio, reference text, and/or inline control
tokens depending on the model. Ming Omni may need `onnx` and `safetensors` if
campplus conversion runs.

The built-in MLX ASR list includes Qwen3 ASR 0.6B and 1.7B 8-bit transcription
models. Language hints include `auto`, `zh`, `yue`, `en`, `de`, `es`, `fr`,
`it`, `pt`, `ru`, `ko`, and `ja`, matching the Qwen3 ASR language set. Upstream
also ships Qwen3 ForcedAligner, but that model performs word-level alignment
with transcript text; Voice Toolbox does not expose it as `asr.transcribe`.
MiMo ASR keeps the official `auto`, `zh`, and `en` language set. Fish Audio ASR
uses the multilingual set exposed in the web UI: `auto`, `zh`, `yue`, `en`,
`de`, `es`, `fr`, `it`, `pt`, `ru`, `ko`, and `ja`.

When `voice_toolbox.toml` exists, it is the source of truth for `base_url`,
`api.host`, and `api.port`. The `.env` values `MIMO_BASE_URL`,
`VOICE_TOOLBOX_API_HOST`, and `VOICE_TOOLBOX_API_PORT` are fallback-only aliases
used when no TOML config is active. Legacy `API_HOST` and `API_PORT` are also
accepted only in that no-TOML fallback path.

The default local API binding is `127.0.0.1:8000`, so the backend listens on the
loopback interface unless you deliberately change `[api]` in `voice_toolbox.toml`
or use the fallback env vars without TOML. Default `MIMO_BASE_URL` is:

```text
https://api.xiaomimimo.com/v1
```

## Run

Start API server from `voice_toolbox.toml` or fallback config:

```bash
rtk make backend-server
```

Start web dev server on `127.0.0.1:5173`:

```bash
rtk make frontend-server
```

The Vite dev server proxies `/v1/*` to `http://127.0.0.1:8000`.

## Podcast Generation

The Podcast workspace turns a multi-speaker script into one audio file. Use one
TTS provider/model, map each speaker to a built-in voice, and generate.

Supported speaker-line scripts:

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

## Make Targets

```bash
rtk make test
rtk make check
rtk make backend-server
rtk make frontend-server
```

`make check` runs backend tests, `ruff`, `ty`, frontend lint/format/test checks, and the web build.

## CLI Examples

Built-in TTS:

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "你好，欢迎使用 MiMo 语音合成。" \
  --voice 冰糖 \
  --format wav
```

TTS from a `.txt` file:

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --file smoke-inputs/tts-long.txt \
  --text-format plain \
  --voice 冰糖 \
  --chunking auto \
  --format wav
```

TTS from Markdown:

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --file smoke-inputs/tts-long.md \
  --text-format markdown \
  --voice 冰糖 \
  --chunking auto \
  --format wav
```

MiMo and Fish Audio currently accept `wav` output through Voice Toolbox. OpenRouter
TTS uses its OpenAI-compatible speech endpoint and stores browser-friendly MP3
artifacts, so use `--format mp3` when targeting the OpenRouter provider.

The API can convert generated audio on download with
`/v1/artifacts/{id}/download?format=wav|mp3|pcm|m4a|aac|flac|ogg|webm`.
Converted download names use `YYYYMMDD-HHMMSS-<hash>.<ext>` instead of exposing
internal operation IDs. Raw `pcm` is 24 kHz mono int16 little-endian. API and web
ASR/voice-clone uploads accept common audio inputs (`wav`, `mp3`, `pcm`, `m4a`,
`flac`, `ogg`, `webm`, `aac`) and convert non-native inputs to a
provider-compatible format before calling the provider. CLI ASR and voice-clone
commands currently accept `wav` and `mp3` paths only. `audio/L16` uploads must
include `rate=24000; channels=1`; other L16 rates are rejected instead of being
silently reinterpreted.

ASR:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-short.wav \
  --language auto
```

Backend ASR chunking:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-long.wav \
  --language auto \
  --chunking force \
  --chunk-seconds 90 \
  --chunk-overlap-ms 1200
```

More real-provider checks live in [docs/smoke/mimo.md](docs/smoke/mimo.md),
[docs/smoke/fish-audio.md](docs/smoke/fish-audio.md),
[docs/smoke/openrouter.md](docs/smoke/openrouter.md), and
[docs/smoke/mlx-audio.md](docs/smoke/mlx-audio.md).

Fish Audio provider support:

- `tts.builtin`: calls `POST /v1/tts` with Fish `reference_id` from `voice_id`.
- `tts.design`: calls `POST /v1/voice-design`; optional preview text maps to `reference_text` and must be at most 150 chars.
- `tts.clone`: calls `POST /v1/tts` with `application/msgpack` direct references; provide the uploaded sample transcript as clone reference text.
- `asr.transcribe`: calls `POST /v1/asr` with multipart audio upload.

OpenRouter provider support:

- `tts.builtin`: calls `POST /api/v1/audio/speech`; Voice Toolbox v1 requests `mp3` from OpenRouter and stores `.mp3` artifacts. OpenRouter `pcm` output is not exposed yet. Style prompts are sent as OpenAI provider instructions.
- `asr.transcribe`: calls `POST /api/v1/audio/transcriptions` with base64 `input_audio`.
- `tts.design` and `tts.clone`: not enabled because OpenRouter docs only define the standard TTS endpoint.

## TTS Text Input And Cleanup

The API and web UI can preview Markdown cleanup before synthesis. In the web UI,
set the text format to Markdown or Auto, then use `Preview cleaned text`.
Cleanup is intentionally conservative: it removes common Markdown markup while
preserving text that could affect TTS pronunciation, so it may leave some
spacing around punctuation when that is safer than changing numbers, CJK text,
or code-like fragments.

Programmatic preview:

```bash
rtk curl -s http://127.0.0.1:8000/v1/normalize/text \
  -H 'Content-Type: application/json' \
  -d '{"content":"# Title\n\nHello **MiMo**.","input_format":"markdown"}'
```

TTS accepts inline text or `.txt` / `.md` uploads. The API uses multipart
`text_file`; the CLI uses `--file`. Long text can be split with
`chunking_mode=auto|force`, `chunk_max_chars`, and `chunk_silence_ms`; the
backend calls the selected provider once per chunk and writes one merged audio
artifact. All first-class fields and validated `provider_options` are copied to
each chunk request.

Voice design does not enter the chunked path in v1. It treats chunking as `off`;
if the design source text or uploaded file exceeds the single-call `max_chars`,
the API returns 422 instead of chunking.

## ASR Chunking

ASR has two chunking paths:

- Backend chunking: upload one audio file to `/v1/asr/transcribe` or use the CLI
  `--chunking force|auto`. The backend converts/splits audio, transcribes each
  chunk, then deduplicates overlap text into one transcript artifact.
  Oversized supported container uploads such as `m4a`, `flac`, `ogg`, `webm`,
  and `aac` are allowed into this path instead of being rejected by the per-call
  provider payload limit before chunking. The planner also caps chunk duration
  by the provider byte budget, so high-bitrate WAV chunks stay under the
  per-call payload limit.
- Browser chunking: the web client slices WAV audio in the browser, creates
  `/v1/asr/chunk-sessions`, uploads chunks to
  `/v1/asr/chunk-sessions/{session_id}/chunks`, then calls
  `/v1/asr/chunk-sessions/{session_id}/finish`.
  Browser chunk duration is also capped by the same byte budget before upload.

Browser chunk session rules:

- `source_duration_ms` is required when creating a session.
- `provider_options` is a JSON object string on create/finish; malformed JSON,
  arrays, unknown keys, invalid choices, more than 32 keys, or more than 4096
  UTF-8 bytes return 422.
- If browser chunk upload is disabled by config, session routes return 422.
- Missing or expired sessions return 404.
- Duplicate chunk indexes return 409.
- Finish-time provider/model/language/transcript option mismatches return 409.
- Raw `provider_options` values are not written to session metadata JSON. A
  fingerprint is stored instead; clients resend `provider_options` on finish so a
  process restart can still complete the session without exposing raw values.

## Transcript Downloads

Transcript artifacts can be downloaded as the source `.txt`, or rendered through:

```text
/v1/artifacts/{id}/transcript?format=txt|srt|vtt|json
```

For `txt`, `timestamps=true` and `speakers=true` add available timestamp/speaker
labels. SRT/VTT are available only when the provider returns complete timestamp
segments. Audio artifacts return 422 from the transcript endpoint, and transcript
artifacts return 422 for converted audio downloads.

## Privacy Boundaries

Voice Toolbox stores generated artifacts and redacted sidecars under local
`data/artifacts/YYYYMMDD/`. It does not write raw TTS text, transcript text,
base64 audio, clone sample bytes, or unsafe provider option values to sidecar
metadata or logs. Safe provider option metadata is intentionally narrow:
booleans/numbers/enums may be stored when marked `safe_metadata=true`, while
free text stores keys only. Multiselect options store `<key>_count`.

Browser chunk session metadata stores file name, chunk indexes, offsets,
durations, and redacted option keys. Chunk audio is deleted when the session is
finished, explicitly deleted, expired, or cleaned up on startup/session activity.

## Local Data

Generated audio, transcripts, and redacted sidecar metadata are local-first artifacts under `data/artifacts/YYYYMMDD/`. SQLite metadata uses `data/voice_toolbox.sqlite`.

Voice clone samples are temporary inputs only. API upload handlers spool them during a request and delete them afterward; clone samples are not stored as artifacts.
