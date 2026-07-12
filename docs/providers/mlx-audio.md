# MLX Audio 供应商 | MLX Audio Provider

纯本地供应商，仅限 Apple Silicon macOS。无需 API 密钥 — 模型通过 Metal 在设备端运行。

Local-only provider for Apple Silicon macOS. No API key required — models run on-device via Metal.

## 环境要求 | Requirements

- Apple Silicon Mac（M1/M2/M3/M4）
- Python 3.11+

## 安装 | Installation

```bash
uv sync --extra mac
```

安装 `mlx-audio[tts,stt]>=0.4.4`（仅限 macOS arm64）。

This installs `mlx-audio[tts,stt]>=0.4.4` (macOS arm64 only).

## 配置 | Configuration

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
default_voice = "Ryan"
```

无需 `api_key_env` 或 `base_url`。合成以串行方式运行，避免 Metal/GPU 内存争用。

No `api_key_env` or `base_url` needed. Synthesis runs serial to avoid Metal/GPU memory contention.

## 模型 | Models

### TTS 内置 | TTS Builtin

**Qwen3 TTS Base** — 预设说话人 | preset speakers:

| 语音 Voice | | |
|---|---|---|
| `Ryan` | `Serena` | |
| `Aiden` | `Uncle_Fu` | |
| `Vivian` | `Dylan` | |
| | `Eric` | |

### TTS 克隆 | TTS Clone

声音克隆需要 `clone_reference_text`，以便 MLX Audio 将 `ref_audio` 和 `ref_text` 传递给上游模型。

Voice clone requires `clone_reference_text` so MLX Audio can pass `ref_audio` and `ref_text` to the upstream model.

| 模型 Model | 语音行为 Voice behavior | 额外依赖 Extra deps |
|---|---|---|
| Qwen3 TTS | 参考音频 + 精确 `--reference-text` | — |
| LongCat AudioDiT | 零样本或参考音频/文本 | — |
| Ming Omni / BailingMM | 参考音频/文本、prompts、风格指令 | `onnx`、`safetensors`（campplus 转换时） |
| Higgs Audio v3 | 参考片段/转录、内联控制 token | — |

克隆模型不使用 Qwen3 预设说话人列表。不要将 Qwen3 说话人名称传递给 LongCat、Ming Omni 或 Higgs Audio。

Clone-capable models do not use the Qwen3 preset speaker list. Do not pass Qwen3 speaker names to LongCat, Ming Omni, or Higgs Audio.

### ASR

| 模型 Model | 备注 Notes |
|---|---|
| Qwen3 ASR 0.6B | 8-bit |
| Qwen3 ASR 1.7B | 8-bit |

Qwen3 ForcedAligner（词级对齐）不作为 `asr.transcribe` 暴露。

### 语言提示 | Language Hints

`auto`、`zh`、`yue`、`en`、`de`、`es`、`fr`、`it`、`pt`、`ru`、`ko`、`ja` — 匹配 Qwen3 ASR 语言集。

## 模型特定说明 | Model-Specific Notes

### LongCat AudioDiT

零样本生成，无需说话人预设。直接传递文本：

Zero-shot generation, no speaker preset needed:

```bash
uv run voice-toolbox tts synthesize \
  --provider mlx-audio \
  --model longcat-audiodit-1b \
  --text "Hello from LongCat."
```

### Ming Omni / BailingMM

若 campplus 转换运行，可能需要额外依赖：

May need extra dependencies if campplus conversion runs:

```bash
uv pip install onnx safetensors
```

### Higgs Audio v3

4B 模型 — 确保内存充足。使用内联控制 token 控制语音质量。

4B model — ensure adequate memory. Uses inline control tokens for voice quality.

## 非 WAV 编解码 | Non-WAV Encode/Decode

系统安装 FFmpeg：

Install FFmpeg on the host:

```bash
brew install ffmpeg
```

## 快速示例 | Quick Examples

```bash
# 内置 TTS | Builtin TTS
uv run voice-toolbox tts synthesize \
  --provider mlx-audio --text "Hello from MLX." --voice Ryan

# 带转录的克隆 | Clone with transcript
uv run voice-toolbox tts clone \
  --provider mlx-audio --text "Target text." \
  --sample reference.wav \
  --reference-text "Exact transcript of reference audio." \
  --consent

# ASR
uv run voice-toolbox asr transcribe \
  --provider mlx-audio --file speech.wav --language auto
```
