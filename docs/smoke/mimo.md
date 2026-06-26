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

Prepare local smoke inputs:

- `smoke-inputs/clone-sample.wav`: short voice sample, ideally under 10 seconds, with consent to use the voice.
- `smoke-inputs/asr-short.wav`: short spoken wav.
- `smoke-inputs/asr-short.mp3`: short spoken mp3.

Clone and ASR uploads must stay under the 10 MiB base64 payload limit. Raw audio near 7.5 MiB or smaller is safest.

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
- Output prints `path: ...data/artifacts/...wav`.
- File plays as `冰糖`.

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

China candidate:

```bash
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1 rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "Token Plan China candidate smoke test." \
  --voice 冰糖 \
  --format wav
```

Singapore candidate:

```bash
MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1 rtk uv run --env-file .env voice-toolbox tts synthesize \
  --text "Token Plan Singapore candidate smoke test." \
  --voice 冰糖 \
  --format wav
```

Record:

- Base URL tested.
- HTTP/provider error, if any.
- Whether output `.wav` is valid.

## Disabled Future Check: TTS MP3 Output

Do not run as a release gate for v1. This is expected to fail today because CLI validation accepts only `wav`.

Enable this check only when MiMo `mp3` TTS output is confirmed and implementation support lands.

```bash
# DISABLED
# rtk uv run --env-file .env voice-toolbox tts synthesize \
#   --text "MP3 output smoke test." \
#   --voice 冰糖 \
#   --format mp3
```
