# MLX Audio Smoke Tests

These tests require Apple Silicon macOS and:

```bash
rtk uv sync --extra mac
```

## Provider Config

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
default_voice = "Ryan"
```

## Model-Specific Dependencies

MLX Audio voices are model-specific. Qwen3 builtin TTS has preset speakers;
LongCat, Ming Omni, and Higgs Audio v3 use zero-shot/reference workflows instead
of the Qwen3 speaker list.

| Model | Voice behavior |
| --- | --- |
| Qwen3 TTS builtin | Preset speakers: `Ryan`, `Aiden`, `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, `Eric` |
| Qwen3 TTS clone | Reference audio plus exact `--reference-text`; preset `--voice` is not required |
| LongCat AudioDiT | Zero-shot generation or reference audio/text; do not pass Qwen3 speaker names |
| Ming Omni BailingMM | Reference audio/text, prompts, and style instructions; do not pass Qwen3 speaker names |
| Higgs Audio v3 | Reference clips/transcripts and inline control tokens; do not pass Qwen3 speaker names |

| Model path | Extra dependency |
| --- | --- |
| Kokoro (upstream-only; not in default Voice Toolbox model list) | `rtk uv pip install misaki`; Japanese `rtk uv pip install 'misaki[ja]'`; Mandarin `rtk uv pip install 'misaki[zh]'` |
| Qwen3 ForcedAligner (future alignment capability; not in default model list) | Japanese needs `rtk uv pip install nagisa`, Korean needs `rtk uv pip install soynlp` |
| Ming Omni BailingMM | May need `rtk uv pip install onnx safetensors` if campplus conversion runs |
| Voxtral TTS (upstream-only; not in default Voice Toolbox model list) | Covered by `mlx-audio[tts]` through `mistral-common[audio]` |
| Non-WAV encode/decode | Install host binary with `brew install ffmpeg` |

## Required Smoke Matrix

Run Qwen3 builtin TTS:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --text "Hello from MLX Audio." --voice Ryan
```

Run Qwen3 clone with transcript:

```bash
rtk uv run voice-toolbox tts clone --provider mlx-audio --text "This is the cloned voice." --sample ./reference.wav --reference-text "Exact transcript for the reference audio." --consent
```

Run Qwen3 ASR:

```bash
rtk uv run voice-toolbox asr transcribe --file ./speech.wav --provider mlx-audio --language auto
```

Run LongCat short WAV:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model longcat-audiodit-1b --text "Short LongCat smoke test."
```

Run Higgs Audio v3 only when memory allows:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model higgs-audio-v3-tts-4b --text "Short Higgs smoke test."
```

Run Ming Omni load/generate only on a machine with enough memory:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model ming-omni-tts-16.8b-a3b --text "Short Ming Omni smoke test."
```
