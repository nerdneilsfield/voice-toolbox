# Fish Audio 供应商 | Fish Audio Provider

API 参考 API reference: [Fish Audio Docs](https://docs.fish.audio)

## 配置 | Configuration

```toml
[[providers]]
id = "fish-audio"
type = "fish_audio"
name = "Fish Audio"
base_url = "https://api.fish.audio"
api_key_env = "FISH_AUDIO_API_KEY"
default_voice = "e58b0d7efca34eb38d5c4985e378abcb"

[providers.default_models]
tts_builtin = "s1"
tts_design = "s1-design"
tts_clone = "s1-clone"
asr = "fish-audio-asr"

[[providers.models]]
id = "s1"
name = "Fish Audio S1"
capability = "tts.builtin"

[[providers.models]]
id = "s1-design"
name = "Fish Audio 声音设计"
capability = "tts.design"

[[providers.models]]
id = "s1-clone"
name = "Fish Audio 直接克隆"
capability = "tts.clone"

[[providers.models]]
id = "fish-audio-asr"
name = "Fish Audio ASR"
capability = "asr.transcribe"
[providers.models.transcript_capabilities]
timestamps = true
speakers = false
segments = true
```

## 模型 | Models

| 能力 Capability | 模型 ID | 备注 Notes |
|---|---|---|
| `tts.builtin` | `s2.1-pro-free` | 免费套餐，83 种语言 |
| `tts.builtin` | `s2.1-pro` | 付费套餐 |
| `tts.builtin` | `s2-pro` | |
| `tts.builtin` | `s1` | |
| `tts.design` | `s1-design` | 使用 `s1` 模型头 |
| `tts.design` | `s2.1-pro-design` | 使用 `s2.1-pro` 模型头 |
| `tts.clone` | `s1-clone` | MessagePack 引用 |
| `tts.clone` | `s2.1-pro-clone` | 使用 `s2.1-pro` 头 |
| `tts.clone` | `s2-pro-clone` | 使用 `s2-pro` 头 |
| `asr.transcribe` | `fish-audio-asr` | 多语言 |

模型 ID 作为 Fish Audio `model:` 请求头传递。| The model ID is passed as the Fish Audio `model:` request header.

### `tts.builtin` — 内置 TTS

调用 `POST /v1/tts`，以 Fish `reference_id` 作为 `voice_id`。格式：`wav`。

Calls `POST /v1/tts` with Fish `reference_id` from `voice_id`. Format: `wav`.

### `tts.design` — 声音设计

调用 `POST /v1/voice-design`。预览文本映射到 `reference_text`，最长 150 字符。声音设计禁用分块 — 超长输入返回 422。

Calls `POST /v1/voice-design`. Preview text maps to `reference_text`, max 150 chars. Chunking is disabled for voice design — oversized input returns 422.

### `tts.clone` — 声音克隆

调用 `POST /v1/tts`，以 `application/msgpack` 格式发送直接引用。克隆模型传递 `references[].audio` 字节和 `references[].text`。将上传的样本转录作为克隆参考文本。

Calls `POST /v1/tts` with `application/msgpack` direct references. Clone models pass `references[].audio` bytes and `references[].text`. Provide the uploaded sample transcript as clone reference text.

### `asr.transcribe` — 语音识别

调用 `POST /v1/asr`，以 multipart 上传音频。多语言集：`auto`、`zh`、`yue`、`en`、`de`、`es`、`fr`、`it`、`pt`、`ru`、`ko`、`ja`。

Calls `POST /v1/asr` with multipart audio upload. Multilingual set: `auto`, `zh`, `yue`, `en`, `de`, `es`, `fr`, `it`, `pt`, `ru`, `ko`, `ja`.

## 引用语音 | Reference Voices

内置 TTS 以 `reference_id` 作为语音 ID。在 TOML 中添加自定义语音：

Built-in TTS uses `reference_id` as voice ID. Add custom voices in TOML:

```toml
[[providers.voices]]
id = "your-fish-audio-reference-id"
name = "My Custom Voice"
note = "optional local note"
```

在 <https://fish.audio> 浏览 reference ID。每个条目的 `id` 是 Fish Audio 的 `reference_id` 或模型 ID；`name` 和 `note` 是本地标签。首个条目自动成为 `default_voice`，除非显式设置。

Browse reference IDs at <https://fish.audio>. Each entry's `id` is a Fish Audio `reference_id` or model ID; `name` and `note` are local labels. The first entry becomes `default_voice` unless set explicitly.
