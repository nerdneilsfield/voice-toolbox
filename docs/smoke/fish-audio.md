# Fish Audio smoke tests

Fish Audio API docs used for this provider:

- <https://docs.fish.audio/api-reference/introduction>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/speech-to-text>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/voice-design>

## Setup

```bash
export FISH_AUDIO_API_KEY='...'
cp -n voice_toolbox.toml.example voice_toolbox.toml
```

Uncomment the Fish Audio provider block in `voice_toolbox.toml`.

## Built-in TTS

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider fish-audio \
  --model s1 \
  --voice e58b0d7efca34eb38d5c4985e378abcb \
  --text "Hello from Fish Audio." \
  --format wav
```

Expected: local `data/artifacts/YYYYMMDD/fish-audio-*-tts-1.wav`.

## Voice Design

```bash
rtk uv run --env-file .env voice-toolbox tts design \
  --provider fish-audio \
  --model s1-design \
  --description "A warm documentary narrator with relaxed pacing." \
  --text "Short preview."
```

Expected: generated candidate audio artifact. Keep `--text` at or below 150 chars.

## ASR

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider fish-audio \
  --file smoke-inputs/asr-short.wav \
  --language en
```

Expected: transcript artifact and printed text.

## Direct Clone

```bash
rtk uv run --env-file .env voice-toolbox tts clone \
  --provider fish-audio \
  --model s1-clone \
  --sample smoke-inputs/clone-sample.wav \
  --reference-text "Transcript of the sample audio." \
  --text "Target synthesis text." \
  --consent
```

Expected: `/v1/tts` request encoded as `application/msgpack` with Fish `references[].audio` bytes and `references[].text`.
