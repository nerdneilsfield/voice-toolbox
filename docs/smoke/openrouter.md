# OpenRouter smoke tests

OpenRouter docs used for this provider:

- <https://openrouter.ai/docs/guides/overview/multimodal/tts>
- <https://openrouter.ai/docs/guides/overview/multimodal/stt>

## Setup

```bash
rtk cp -n .env.example .env
rtk cp -n voice_toolbox.toml.example voice_toolbox.toml
```

Set `OPENROUTER_API_KEY` in `.env`. Uncomment the OpenRouter provider block in
`voice_toolbox.toml`.

Provider/model-specific options are configured in TOML and rendered by the web
UI for the selected model. For API calls, pass them as a `provider_options` JSON
object string. CLI provider options are not exposed yet.

Prepare inputs:

```bash
rtk mkdir -p smoke-inputs
rtk printf 'OpenRouter TXT smoke.\n\nSecond paragraph for chunking.\n' > smoke-inputs/openrouter-tts.txt
rtk printf '# OpenRouter Markdown smoke\n\nSpeak **this** cleaned Markdown.\n' > smoke-inputs/openrouter-tts.md
```

## Built-in TTS

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider openrouter \
  --model openai/gpt-4o-mini-tts-2025-12-15 \
  --voice alloy \
  --text "Hello from OpenRouter text to speech." \
  --format mp3
```

Expected: local `data/artifacts/YYYYMMDD/openrouter-*-tts-1.mp3`. OpenRouter TTS stores MP3 artifacts in v1; MiMo and Fish Audio remain WAV-only.

## TTS TXT And Markdown Files

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider openrouter \
  --model openai/gpt-4o-mini-tts-2025-12-15 \
  --voice alloy \
  --file smoke-inputs/openrouter-tts.txt \
  --text-format plain \
  --chunking force \
  --chunk-max-chars 200 \
  --format mp3

rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider openrouter \
  --model openai/gpt-4o-mini-tts-2025-12-15 \
  --voice alloy \
  --file smoke-inputs/openrouter-tts.md \
  --text-format markdown \
  --chunking auto \
  --format mp3
```

Expected: each command writes one merged MP3 audio artifact. Markdown markup is cleaned before synthesis.

## ASR

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider openrouter \
  --model openai/whisper-1 \
  --file smoke-inputs/asr-short.wav \
  --language en
```

Expected: transcript artifact and printed text.

Backend ASR chunking:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider openrouter \
  --model openai/whisper-1 \
  --file smoke-inputs/asr-long.wav \
  --language en \
  --chunking force \
  --chunk-seconds 90 \
  --chunk-overlap-ms 1200
```

Expected: one merged transcript artifact with overlap dedupe metadata.

Transcript downloads through the API:

```bash
ARTIFACT_ID='replace-with-transcript-artifact-id'
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=txt&timestamps=true&speakers=true" -o smoke-inputs/openrouter-transcript.txt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=json" -o smoke-inputs/openrouter-transcript.json
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=srt" -o smoke-inputs/openrouter-transcript.srt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=vtt" -o smoke-inputs/openrouter-transcript.vtt
```

SRT/VTT return 200 only for configured models that produce complete timestamp
segments. Otherwise they return 422.

## Browser Chunking API Contract

The web UI uses browser WAV chunk sessions when enabled. `source_duration_ms` is
required on `POST /v1/asr/chunk-sessions`; `provider_options` is a JSON object
string on create/finish. Disabled browser chunking returns 422, missing or
expired sessions return 404, and duplicate chunk indexes return 409.

## Deferred

OpenRouter `tts.design` and `tts.clone` are not enabled. Their public docs define standard text-to-speech and speech-to-text endpoints only.
