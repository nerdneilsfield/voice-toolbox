# OpenRouter smoke tests

OpenRouter docs used for this provider:

- <https://openrouter.ai/docs/guides/overview/multimodal/tts>
- <https://openrouter.ai/docs/guides/overview/multimodal/stt>

## Setup

```bash
export OPENROUTER_API_KEY='...'
cp -n voice_toolbox.toml.example voice_toolbox.toml
```

Uncomment the OpenRouter provider block in `voice_toolbox.toml`.

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

## ASR

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider openrouter \
  --model openai/whisper-1 \
  --file smoke-inputs/asr-short.wav \
  --language en
```

Expected: transcript artifact and printed text.

## Deferred

OpenRouter `tts.design` and `tts.clone` are not enabled. Their public docs define standard text-to-speech and speech-to-text endpoints only.
