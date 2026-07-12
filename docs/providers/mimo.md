# MiMo 供应商 | MiMo Provider

默认语音工具箱供应商。通过 `MIMO_API_KEY` 进行 Bearer 认证。

Default Voice Toolbox provider. Bearer-auth via `MIMO_API_KEY`.

## 配置 | Configuration

```toml
[[providers]]
id = "mimo"
type = "mimo"
name = "MiMo"
base_url = "https://api.xiaomimimo.com/v1"
api_key_env = "MIMO_API_KEY"
default_voice = "mimo_default"
```

## 模型 | Models

| 能力 Capability | 模型 ID | 名称 Name |
|---|---|---|
| `tts.builtin` | `mimo-v2.5-tts` | MiMo TTS |
| `tts.design` | `mimo-v2.5-tts-voicedesign` | MiMo 声音设计 |
| `tts.clone` | `mimo-v2.5-tts-voiceclone` | MiMo 声音克隆 |
| `asr.transcribe` | `mimo-v2.5-asr` | MiMo V2.5 ASR |

旧版 V2 ASR 已于 2026-06-30 下线。

Legacy V2 ASR was taken offline on 2026-06-30.

## 格式支持 | Format Support

TTS 输出：v1 仅支持 `wav`。MP3 输出尚未启用。

TTS output: `wav` only in v1. MP3 output is not yet enabled.

ASR 上传：`wav`、`mp3`、`pcm`、`m4a`、`flac`、`ogg`、`webm`、`aac`。非原生格式在调用供应商前自动转换。

ASR uploads: `wav`, `mp3`, `pcm`, `m4a`, `flac`, `ogg`, `webm`, `aac`. Non-native inputs are auto-converted before calling the provider.

## ASR 语言 | ASR Languages

`auto`、`zh`、`en` — MiMo V2.5 官方语言集。

## Token Plan 基础 URL | Token Plan Base URLs

MiMo Token Plan 用户可使用替代基础 URL（待验证）：

For MiMo Token Plan users, alternative base URLs (pending verification):

- 中国 China: `https://token-plan-cn.xiaomimimo.com/v1`
- 新加坡 Singapore: `https://token-plan-sgp.xiaomimimo.com/v1`

在供应商配置块中设置 `base_url`。设置后将覆盖默认 URL。

Set `base_url` in the provider block. These URLs override the default when set.

## API 说明 | API Notes

- TTS 使用 OpenAI SDK 发送 `Authorization: Bearer ...` 头
- ASR 载荷限制：10 MiB base64；原始音频建议 ≤ 7.5 MiB
- 错误元数据中的 `X-Tt-Logid` 用于支持诊断

- TTS uses the OpenAI SDK to send `Authorization: Bearer ...` headers
- ASR payload limit: 10 MiB base64; raw audio ~7.5 MiB or smaller recommended
- X-Tt-Logid in error metadata for support diagnostics
