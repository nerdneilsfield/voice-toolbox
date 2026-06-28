# voice-toolbox

Local-first voice toolbox for MiMo, Fish Audio, and OpenRouter TTS/ASR providers. Python core, Typer CLI, FastAPI API, and React web UI share one provider layer.

## Setup

Install Python dependencies with `uv`:

```bash
rtk uv sync --extra dev
```

Audio format conversion uses `pydub`; install `ffmpeg` on the host for mp3,
m4a, flac, ogg, webm, and aac decoding/encoding.

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

MiMo and Fish Audio currently accept `wav` output through Voice Toolbox. OpenRouter
TTS uses its OpenAI-compatible speech endpoint and stores browser-friendly MP3
artifacts, so use `--format mp3` when targeting the OpenRouter provider.

The API can convert generated audio on download with
`/v1/artifacts/{id}/download?format=wav|mp3|pcm|m4a|aac|flac|ogg|webm`.
Converted download names use `YYYYMMDD-HHMMSS-<hash>.<ext>` instead of exposing
internal operation IDs. Raw `pcm` is 24 kHz mono int16 little-endian. ASR and
voice clone uploads accept common audio inputs (`wav`, `mp3`, `pcm`, `m4a`,
`flac`, `ogg`, `webm`, `aac`) and convert non-native inputs to a
provider-compatible format before calling the provider. `audio/L16` uploads must
include `rate=24000; channels=1`; other L16 rates are rejected instead of being
silently reinterpreted.

ASR:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-short.wav \
  --language auto
```

More real-provider checks live in [docs/smoke/mimo.md](docs/smoke/mimo.md).

Fish Audio provider support:

- `tts.builtin`: calls `POST /v1/tts` with Fish `reference_id` from `voice_id`.
- `tts.design`: calls `POST /v1/voice-design`; optional preview text maps to `reference_text` and must be at most 150 chars.
- `tts.clone`: calls `POST /v1/tts` with `application/msgpack` direct references; provide the uploaded sample transcript as clone reference text.
- `asr.transcribe`: calls `POST /v1/asr` with multipart audio upload.

OpenRouter provider support:

- `tts.builtin`: calls `POST /api/v1/audio/speech`; OpenRouter supports `mp3` or `pcm`, so artifacts are stored as `.mp3`. Style prompts are sent as OpenAI provider instructions.
- `asr.transcribe`: calls `POST /api/v1/audio/transcriptions` with base64 `input_audio`.
- `tts.design` and `tts.clone`: not enabled because OpenRouter docs only define the standard TTS endpoint.

## Markdown Cleanup Preview

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

Chunking options are reserved for future long-text workflows and are not
implemented yet.

## Local Data

Generated audio, transcripts, and redacted sidecar metadata are local-first artifacts under `data/artifacts/YYYYMMDD/`. SQLite metadata uses `data/voice_toolbox.sqlite`.

Voice clone samples are temporary inputs only. API upload handlers spool them during a request and delete them afterward; clone samples are not stored as artifacts.
