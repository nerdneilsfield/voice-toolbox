# voice-toolbox

Local-first voice toolbox for MiMo TTS and ASR. Python core, Typer CLI, FastAPI API, and React web UI share one provider layer.

## Setup

Install Python dependencies with `uv`:

```bash
rtk uv sync --extra dev
```

Install frontend dependencies with `bun`:

```bash
rtk bun install --cwd apps/web
```

Create local environment config:

```bash
rtk cp -n .env.example .env
```

Edit `.env` and set `MIMO_API_KEY`. Default `MIMO_BASE_URL` is:

```text
https://api.xiaomimimo.com/v1
```

## Run

Start API server on `127.0.0.1:8000`:

```bash
rtk make backend-test-server
```

Start web dev server on `127.0.0.1:5173`:

```bash
rtk make frontend-test-server
```

The Vite dev server proxies `/v1/*` to `http://127.0.0.1:8000`.

## Make Targets

```bash
rtk make test
rtk make check
rtk make backend-test-server
rtk make frontend-test-server
```

`make check` runs backend tests, `ruff`, `ty`, frontend type checks, and the web build.

## CLI Examples

Built-in TTS:

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "你好，欢迎使用 MiMo 语音合成。" \
  --voice 冰糖 \
  --format wav
```

ASR:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-short.wav \
  --language auto
```

More real-provider checks live in [docs/smoke/mimo.md](docs/smoke/mimo.md).

## Local Data

Generated audio, transcripts, and redacted sidecar metadata are local-first artifacts under `data/artifacts/YYYYMMDD/`. SQLite metadata uses `data/voice_toolbox.sqlite`.

Voice clone samples are temporary inputs only. API upload handlers spool them during a request and delete them afterward; clone samples are not stored as artifacts.
