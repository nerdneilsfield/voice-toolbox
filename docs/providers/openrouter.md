# OpenRouter 供应商 | OpenRouter Provider

API 参考 API reference: [OpenRouter TTS](https://openrouter.ai/docs/guides/overview/multimodal/tts)、[OpenRouter STT](https://openrouter.ai/docs/guides/overview/multimodal/stt)

## 配置 | Configuration

```toml
[[providers]]
id = "openrouter"
type = "openrouter"
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
default_voice = "alloy"

[providers.default_models]
tts_builtin = "openai/gpt-4o-mini-tts-2025-12-15"
asr = "openai/whisper-1"

[[providers.models]]
id = "openai/gpt-4o-mini-tts-2025-12-15"
name = "OpenAI GPT-4o Mini TTS"
capability = "tts.builtin"
note = "OpenRouter TTS endpoint; response_format mp3"

[[providers.models.options]]
key = "instructions"
label = "Provider instructions"
type = "text"
capability = "tts.builtin"
placeholder = "Speak warmly, with careful pacing."
safe_metadata = false

[[providers.models]]
id = "openai/whisper-1"
name = "OpenAI Whisper"
capability = "asr.transcribe"
[providers.models.transcript_capabilities]
timestamps = false
speakers = false
segments = false

[[providers.voices]]
id = "alloy"
name = "Alloy"
```

## 能力 | Capabilities

| 能力 Capability | 支持 Supported | 备注 Notes |
|---|---|---|
| `tts.builtin` | 是 Yes | OpenAI 兼容语音端点，MP3 输出 |
| `tts.design` | 否 No | OpenRouter 文档未定义 |
| `tts.clone` | 否 No | OpenRouter 文档未定义 |
| `asr.transcribe` | 是 Yes | OpenAI 兼容转录端点 |

### `tts.builtin` — 内置 TTS

调用 `POST /api/v1/audio/speech`。v1 输出格式仅 `mp3`；PCM 输出尚未暴露。风格提示通过 `provider_options` 作为 OpenAI provider instructions 发送。

Calls `POST /api/v1/audio/speech`. Output format is `mp3` only in v1; PCM output is not exposed. Style prompts are sent as OpenAI provider instructions via `provider_options`.

### `asr.transcribe` — 语音识别

调用 `POST /api/v1/audio/transcriptions`，以 base64 `input_audio` 发送。默认模型配置无时间戳/说话人能力，因此 SRT/VTT 下载返回 422。

Calls `POST /api/v1/audio/transcriptions` with base64 `input_audio`. No timestamp or speaker capabilities in the default model config, so SRT/VTT downloads return 422.

## 语音选项 | Voice Options

标准 OpenAI TTS 语音 | Standard OpenAI TTS voices: `alloy`、`ash`、`ballad`、`coral`、`echo`、`fable`、`onyx`、`nova`、`sage`、`shimmer`、`verse`。在 TOML 供应商块中添加语音条目。

Add voice entries to the provider block in TOML.

## 供应商选项 | Provider Options

`instructions` 文本选项允许向 TTS 模型传递风格指令。通过 Web UI 或 API 以 `provider_options` JSON 设置：

The `instructions` text option allows passing style instructions to the TTS model. Set via web UI or API as `provider_options` JSON:

```json
{"instructions": "Speak in a calm, professional tone."}
```
