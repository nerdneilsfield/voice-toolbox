# Volcengine 供应商 | Volcengine Provider

豆包 Seed TTS/ASR，通过火山引擎 Agent Plan 语音服务。需要专用的 Agent Plan API 密钥；普通 Ark API 密钥不被接受。

Doubao Seed TTS/ASR via Volcengine Agent Plan speech. Requires a dedicated Agent Plan API key; a normal Ark API key is not accepted.

## 前置条件 | Prerequisites

1. 从火山引擎控制台获取 Agent Plan API 密钥
2. 在控制台启用语音模型
3. 按需启用超量后付费（避免 HTTP 429 配额错误）

1. Obtain the Agent Plan API key from Volcengine console
2. Enable speech models in the console
3. Enable overage post-payment if needed (to avoid HTTP 429 quota errors)

## 配置 | Configuration

```toml
[[providers]]
id = "volcengine"
type = "volcengine"
name = "Volcengine Speech"
base_url = "https://openspeech.bytedance.com/api/v3/plan"
api_key_env = "VOLCENGINE_SPEECH_API_KEY"
default_voice = "zh_female_vv_uranus_bigtts"

[providers.default_models]
tts_builtin = "seed-tts-2.0"
asr = "volc.seedasr.sauc.duration"

[[providers.models]]
id = "seed-tts-2.0"
name = "豆包 Seed TTS 2.0"
capability = "tts.builtin"

[[providers.models]]
id = "volc.seedasr.sauc.duration"
name = "豆包 Seed ASR 2.0"
capability = "asr.transcribe"
[providers.models.transcript_capabilities]
timestamps = true
speakers = false
segments = true
```

## 能力 | Capabilities

| 能力 Capability | 支持 Supported | 备注 Notes |
|---|---|---|
| `tts.builtin` | 是 Yes | HTTP POST，资源 ID 固定 |
| `tts.design` | 否 No | |
| `tts.clone` | 否 No | |
| `asr.transcribe` | 是 Yes | WebSocket 流式 |

### `tts.builtin` — 内置 TTS

基于 HTTP 的合成。输出格式：`mp3`。资源 ID 固定为 `seed-tts-2.0`，无法通过 `Auto` 或控制台切换模型。

HTTP-based synthesis. Output format: `mp3`. Resource ID is pinned to `seed-tts-2.0` and cannot be switched through `Auto` or console model selection.

### `asr.transcribe` — 语音识别

WebSocket 流式 ASR。资源 ID 固定为 `volc.seedasr.sauc.duration`。

WebSocket streaming ASR. Resource ID is pinned to `volc.seedasr.sauc.duration`.

## 语音目录 | Voice Catalog

不写 `[[providers.voices]]` 即可加载火山引擎内置语音目录。定义任何 `[[providers.voices]]` 条目将替换整个目录，仅保留自定义条目。

Omit `[[providers.voices]]` to load the built-in Volcengine voice catalog. Defining any `[[providers.voices]]` entry replaces the catalog with only those entries.

## 错误诊断 | Error Diagnostics

失败时保留供应商错误元数据中的 `X-Tt-Logid` 用于支持排查。HTTP 429 通常意味着配额耗尽 — 启用超量后付费或等待配额恢复。

On failures, retain `X-Tt-Logid` from provider error metadata for support. HTTP 429 usually means quota exhaustion — enable overage post-payment or wait for quota renewal.
