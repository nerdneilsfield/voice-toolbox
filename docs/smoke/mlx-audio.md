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

| Model path | Extra dependency |
| --- | --- |
| Kokoro | `pip install misaki`; Japanese `pip install 'misaki[ja]'`; Mandarin `pip install 'misaki[zh]'` |
| Qwen3 ForcedAligner | Future alignment capability only; Japanese needs `pip install nagisa`, Korean needs `pip install soynlp` |
| Ming Omni BailingMM | May need `pip install onnx safetensors` if campplus conversion runs |
| Voxtral TTS | Covered by `mlx-audio[tts]` through `mistral-common[audio]` |
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
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model longcat-audiodit-1b --text "Short LongCat smoke test." --voice default
```

Run Higgs Audio v3 only when memory allows:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model higgs-audio-v3-tts-4b --text "Short Higgs smoke test." --voice default
```

Run Ming Omni load/generate only on a machine with enough memory:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model ming-omni-tts-16.8b-a3b --text "Short Ming Omni smoke test." --voice default
```
