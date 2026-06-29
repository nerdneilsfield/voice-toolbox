# MiMo Smoke Tests

Manual real-provider checks for MiMo TTS and ASR.

MiMo API default: `https://api.xiaomimimo.com/v1`.

Token Plan base URL candidates are pending verification:

- China: `https://token-plan-cn.xiaomimimo.com/v1`
- Singapore: `https://token-plan-sgp.xiaomimimo.com/v1`

TTS output is `wav` only in v1. Do not enable `mp3` output until the disabled check below passes against real MiMo.

## Prerequisites

```bash
rtk uv sync --extra dev
rtk cp -n .env.example .env
```

Set `MIMO_API_KEY` in `.env`. Keep `MIMO_BASE_URL=https://api.xiaomimimo.com/v1` for baseline checks.

Provider config is optional for baseline smoke:

- With no `voice_toolbox.toml`, the built-in MiMo provider is used and legacy `.env` values such as `MIMO_BASE_URL` apply.
- With `voice_toolbox.toml`, set provider `base_url`, models, and voices in TOML; keep only secret values such as `MIMO_API_KEY` in `.env`.
- Do not put API key values in `voice_toolbox.toml`.
- Confirm the active provider before real smoke:

```bash
rtk uv run --env-file .env python -c "from voice_toolbox.config import load_app_config; c=load_app_config(); print(c.providers[0].id, c.providers[0].base_url)"
```

Prepare local smoke inputs:

- `smoke-inputs/clone-sample.wav`: short voice sample, ideally under 10 seconds, with consent to use the voice.
- `smoke-inputs/asr-short.wav`: short spoken wav.
- `smoke-inputs/asr-short.mp3`: short spoken mp3.
- `smoke-inputs/asr-long.wav`: longer spoken wav for backend chunking.
- `smoke-inputs/browser-chunk.wav`: wav file for web browser chunking.

Clone and ASR uploads must stay under the 10 MiB base64 payload limit. Raw audio near 7.5 MiB or smaller is safest.

Create TTS text inputs:

```bash
rtk mkdir -p smoke-inputs
rtk printf '第一段：这是一份 TXT 烟测文本。\n\n第二段：它会按自然段优先分块。\n' > smoke-inputs/tts-long.txt
rtk printf '# Markdown 烟测\n\n这是 **Markdown** 文本，包含 [link](https://example.com)。\n' > smoke-inputs/tts-long.md
```

## Checklist

### Bearer-Auth Built-In TTS With `冰糖`

This uses `MIMO_API_KEY`; the OpenAI SDK sends it as `Authorization: Bearer ...`.

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "你好，我是冰糖。这是 Bearer auth smoke test。" \
  --voice 冰糖 \
  --format wav
```

Pass:

- Command exits 0.
- Output prints `id:` and `mime: audio/wav`; matching audio artifact exists under `data/artifacts`.
- File plays as `冰糖`.

### Built-In TTS From TXT File With Chunking

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --file smoke-inputs/tts-long.txt \
  --text-format plain \
  --voice 冰糖 \
  --chunking force \
  --chunk-max-chars 200 \
  --chunk-silence-ms 120 \
  --format wav
```

Pass:

- Command exits 0.
- Output is one merged `.wav`.
- Sidecar metadata has `chunking_enabled=true` and `chunking_operation=tts`.

### Built-In TTS From Markdown File

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --file smoke-inputs/tts-long.md \
  --text-format markdown \
  --voice 冰糖 \
  --chunking auto \
  --format wav
```

Pass:

- Command exits 0.
- Markdown markers such as `#`, `**`, and link syntax are not spoken literally.

### Built-In TTS With `(唱歌)` Chinese Lyrics

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "(唱歌)小星星，亮晶晶，满天都是小星星。" \
  --voice 冰糖 \
  --format wav
```

Pass:

- Command exits 0.
- Output is a `.wav`.
- Audio attempts singing mode rather than plain narration.

### Voice Design With Optimized Preview And No Target Text

```bash
rtk uv run --env-file .env voice-toolbox tts design \
  --description "年轻男声，温暖，自信，语速适中，适合产品介绍。" \
  --optimize-text-preview \
  --format wav
```

Pass:

- Command exits 0 without `--text`.
- Output is a `.wav`.
- Preview text is provider-generated.

### Voice Design Long Text Must Not Chunk

Voice design treats chunking as `off` in v1. Long source text over the single-call `max_chars` must return 422 instead of silently chunking.

```bash
rtk uv run python - <<'PY' > smoke-inputs/design-too-long.txt
print("这是很长的设计预览文本。" * 400)
PY

rtk uv run --env-file .env voice-toolbox tts design \
  --description "年轻男声，温暖，自信。" \
  --file smoke-inputs/design-too-long.txt \
  --chunking force \
  --format wav
```

Pass:

- Command exits non-zero.
- Error mentions design text/file exceeding the single-call limit or max chars.

### Voice Clone With Small WAV Sample And Consent

Use only a voice sample you have rights and consent to use.

```bash
rtk uv run --env-file .env voice-toolbox tts clone \
  --sample smoke-inputs/clone-sample.wav \
  --consent \
  --text "这是克隆音色的烟测。" \
  --format wav
```

Pass:

- Command exits 0.
- Output is a `.wav`.
- Sidecar metadata records file name, MIME type, size, and consent status, not base64 audio.
- Clone sample is not copied into `data/artifacts`.

### ASR With Short WAV

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-short.wav \
  --language auto
```

Pass:

- Command exits 0.
- Output prints `text: ...`.
- Transcript artifact is a `.txt` under `data/artifacts`.

### ASR Backend Chunking

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-long.wav \
  --language auto \
  --chunking force \
  --chunk-seconds 90 \
  --chunk-overlap-ms 1200
```

Pass:

- Command exits 0.
- Output is one merged transcript artifact.
- Sidecar metadata has `chunking_enabled=true`, `chunking_operation=asr`, and chunk counts.

### Transcript Render Downloads

Start the API in another shell:

```bash
rtk make backend-server
```

Use the transcript artifact id from an ASR smoke result:

```bash
ARTIFACT_ID='replace-with-transcript-artifact-id'
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=txt&timestamps=true&speakers=true" -o smoke-inputs/transcript.txt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=json" -o smoke-inputs/transcript.json
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=srt" -o smoke-inputs/transcript.srt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=vtt" -o smoke-inputs/transcript.vtt
```

Pass:

- `txt` and `json` download for every transcript artifact.
- `srt` and `vtt` return 200 only when the provider/model returned complete timestamp segments; otherwise they return 422.

### Browser ASR Chunk Session Manual Smoke

The web UI uses these endpoints automatically. The API contract is multipart form data.

Create session. `source_duration_ms` is required. `provider_options` is a JSON object string.

```bash
rtk curl -fsS -X POST http://127.0.0.1:8000/v1/asr/chunk-sessions \
  -F provider_id=mimo \
  -F language=auto \
  -F source_duration_ms=125000 \
  -F total_chunks=2 \
  -F source_file_name=browser-chunk.wav \
  -F provider_options='{}'
```

Upload browser-sliced WAV chunks:

```bash
SESSION_ID='replace-with-session-id'
rtk curl -fsS -X POST "http://127.0.0.1:8000/v1/asr/chunk-sessions/${SESSION_ID}/chunks" \
  -F chunk_index=0 \
  -F offset_ms=0 \
  -F duration_ms=90000 \
  -F file=@smoke-inputs/browser-chunk.0.wav

rtk curl -fsS -X POST "http://127.0.0.1:8000/v1/asr/chunk-sessions/${SESSION_ID}/chunks" \
  -F chunk_index=1 \
  -F offset_ms=88800 \
  -F duration_ms=36200 \
  -F file=@smoke-inputs/browser-chunk.1.wav
```

Finish:

```bash
rtk curl -fsS -X POST "http://127.0.0.1:8000/v1/asr/chunk-sessions/${SESSION_ID}/finish" \
  -F provider_id=mimo \
  -F language=auto \
  -F provider_options='{}'
```

Pass:

- Create returns `session_id`, `browser_slice_formats=["wav"]`, and `backend_accept_formats`.
- Each upload returns `received_chunks` and `total_chunks`.
- Finish returns one transcript artifact and deletes the session.
- Re-finishing the same session returns 404.
- Uploading a duplicate `chunk_index` before finish returns 409.
- If `[chunking.asr].browser_upload=false`, create/upload/finish/delete return 422.
- Expired or missing sessions return 404.

### ASR With Short MP3

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --file smoke-inputs/asr-short.mp3 \
  --language auto
```

Pass:

- Command exits 0.
- Output prints `text: ...`.
- Transcript artifact is a `.txt` under `data/artifacts`.

## Optional Advanced Checks: Token Plan Base URLs

Run only after baseline default URL passes. These candidates are not verified yet; failures do not block default-url release.

China candidate, when no `voice_toolbox.toml` is active:

```bash
rtk uv run --env-file .env env MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1 voice-toolbox tts synthesize \
  --text "Token Plan China candidate smoke test." \
  --voice 冰糖 \
  --format wav
```

Singapore candidate, when no `voice_toolbox.toml` is active:

```bash
rtk uv run --env-file .env env MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1 voice-toolbox tts synthesize \
  --text "Token Plan Singapore candidate smoke test." \
  --voice 冰糖 \
  --format wav
```

If a `voice_toolbox.toml` is active, edit that provider's `base_url` instead of setting `MIMO_BASE_URL`; TOML provider config takes precedence over legacy fallback env.

Record:

- Base URL tested.
- HTTP/provider error, if any.
- Whether output `.wav` is valid.

## Disabled Future Check: TTS MP3 Output

Do not run as a release gate for v1. This is expected to fail today because the MiMo provider currently enforces `wav` output.

Enable this check only when MiMo `mp3` TTS output is confirmed and implementation support lands.

```bash
# DISABLED
# rtk uv run --env-file .env voice-toolbox tts synthesize \
#   --text "MP3 output smoke test." \
#   --voice 冰糖 \
#   --format mp3
```
