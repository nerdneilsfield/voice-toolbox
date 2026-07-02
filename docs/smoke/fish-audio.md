# Fish Audio smoke tests

Fish Audio API docs used for this provider:

- <https://docs.fish.audio/api-reference/introduction>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/speech-to-text>
- <https://docs.fish.audio/api-reference/endpoint/openapi-v1/voice-design>

## Setup

```bash
rtk cp -n .env.example .env
rtk cp -n voice_toolbox.toml.example voice_toolbox.toml
```

Set `FISH_AUDIO_API_KEY` in `.env`. Uncomment the Fish Audio provider block in
`voice_toolbox.toml`.

Optional provider options can be added to the Fish provider in TOML and are sent
by the web/API as `provider_options` JSON object strings. CLI provider options
are not exposed yet.

Prepare inputs:

```bash
rtk mkdir -p smoke-inputs
rtk printf 'Fish Audio TXT smoke.\n\nSecond paragraph for chunking.\n' > smoke-inputs/fish-tts.txt
rtk printf '# Fish Audio Markdown smoke\n\nSpeak **this** cleaned Markdown.\n' > smoke-inputs/fish-tts.md
```

## Built-in TTS

Built-in TTS models: `s2.1-pro-free` (free tier, default), `s2.1-pro`, `s2-pro`,
and `s1`. The model id is passed as the Fish Audio `model:` request header; the
free model covers 83 languages under Fair Use.

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider fish-audio \
  --model s1 \
  --voice e58b0d7efca34eb38d5c4985e378abcb \
  --text "Hello from Fish Audio." \
  --format wav
```

Expected: local `data/artifacts/YYYYMMDD/fish-audio-*-tts-1.wav`.

## TTS TXT And Markdown Files

```bash
rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider fish-audio \
  --model s1 \
  --voice e58b0d7efca34eb38d5c4985e378abcb \
  --file smoke-inputs/fish-tts.txt \
  --text-format plain \
  --chunking force \
  --chunk-max-chars 200 \
  --format wav

rtk uv run --env-file .env voice-toolbox tts synthesize \
  --provider fish-audio \
  --model s1 \
  --voice e58b0d7efca34eb38d5c4985e378abcb \
  --file smoke-inputs/fish-tts.md \
  --text-format markdown \
  --chunking auto \
  --format wav
```

Expected: each command writes one merged WAV audio artifact; Markdown markup is cleaned before synthesis.

## Voice Design

```bash
rtk uv run --env-file .env voice-toolbox tts design \
  --provider fish-audio \
  --model s1-design \
  --description "A warm documentary narrator with relaxed pacing." \
  --text "Short preview."
```

Expected: generated candidate audio artifact. Keep `--text` at or below 150 chars.
Voice design never chunks in v1. Overlong design text/file returns 422 instead.

## ASR

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider fish-audio \
  --file smoke-inputs/asr-short.wav \
  --language en
```

Expected: transcript artifact and printed text.

Backend ASR chunking:

```bash
rtk uv run --env-file .env voice-toolbox asr transcribe \
  --provider fish-audio \
  --file smoke-inputs/asr-long.wav \
  --language en \
  --chunking force \
  --chunk-seconds 90 \
  --chunk-overlap-ms 1200
```

Expected: one merged transcript artifact with chunking metadata.

Transcript downloads through the API:

```bash
ARTIFACT_ID='replace-with-transcript-artifact-id'
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=txt" -o smoke-inputs/fish-transcript.txt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=json" -o smoke-inputs/fish-transcript.json
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=srt" -o smoke-inputs/fish-transcript.srt
rtk curl -fsS "http://127.0.0.1:8000/v1/artifacts/${ARTIFACT_ID}/transcript?format=vtt" -o smoke-inputs/fish-transcript.vtt
```

Fish Audio ASR is configured without timestamp/speaker transcript capabilities in the example config, so `format=srt` and `format=vtt` should return 422 unless you configure a model that actually returns complete timestamp segments.

## Browser Chunking API Contract

The web UI uses browser WAV chunk sessions when enabled. `source_duration_ms` is
required on `POST /v1/asr/chunk-sessions`; `provider_options` is a JSON object
string on create/finish. Disabled browser chunking returns 422, missing or
expired sessions return 404, and duplicate chunk indexes return 409.

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

Expected: `/v1/tts` request encoded as `application/msgpack` with Fish `references[].audio` bytes and `references[].text`. Clone models `s2.1-pro-clone` and `s2-pro-clone` map to the `s2.1-pro` / `s2-pro` API headers respectively.

## Adding Reference Voices

Built-in TTS picks a voice from the provider's voice list, sent to Fish Audio as
`reference_id`. Append your own voices in `voice_toolbox.toml` — each entry's
`id` is a Fish Audio `reference_id` or model id (browse them at
<https://fish.audio>), and `name` / `note` are local labels shown in the web UI:

```toml
[[providers.voices]]
id = "your-fish-audio-reference-id"
name = "My Custom Voice"
note = "optional local note"
```

The first entry becomes `default_voice` unless you set it explicitly. Omitting
`[[providers.voices]]` keeps the built-in default reference.

