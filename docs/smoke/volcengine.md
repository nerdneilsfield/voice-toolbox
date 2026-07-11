# Volcengine Agent Plan smoke test

Prerequisites:

- Obtain the dedicated Agent Plan API key; a normal Ark API key is not accepted.
- Enable the speech models and, if needed, overage post-payment in the Volcengine console.
- Add the commented `volcengine` provider block from `voice_toolbox.toml.example`.
- Set `VOLCENGINE_SPEECH_API_KEY` in `.env`.

The provider pins the required Resource IDs. `Auto` and console model switching are not supported:

- TTS: `seed-tts-2.0`
- ASR: `volc.seedasr.sauc.duration`

TTS over HTTP:

```bash
uv run --env-file .env voice-toolbox tts synthesize \
  --provider volcengine \
  --text "你好，这是豆包语音合成测试。" \
  --voice zh_female_vv_uranus_bigtts \
  --format mp3
```

Streaming ASR over WebSocket:

```bash
uv run --env-file .env voice-toolbox asr transcribe \
  --provider volcengine \
  --file smoke-inputs/asr-short.wav \
  --language auto
```

On failures, retain `X-Tt-Logid` from provider error metadata for support diagnostics. HTTP `429` usually means quota exhaustion; enable overage post-payment or wait for quota renewal.
