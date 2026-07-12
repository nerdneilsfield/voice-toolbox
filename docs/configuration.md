# 配置 Configuration

## 发现顺序 | Discovery Order

1. Python / API 代码传入的显式路径
2. `VOICE_TOOLBOX_CONFIG` 环境变量
3. 当前工作目录下的 `voice_toolbox.toml`
4. 内置 MiMo 回退配置

当 `voice_toolbox.toml` 存在时，它是 `base_url`、`api.host` 和 `api.port` 的权威来源。`.env` 中的值（`MIMO_BASE_URL`、`VOICE_TOOLBOX_API_HOST`、`VOICE_TOOLBOX_API_PORT`）仅在没有 TOML 配置时作为回退别名使用。

When `voice_toolbox.toml` exists, it is the source of truth for `base_url`, `api.host`, and `api.port`. `.env` values (`MIMO_BASE_URL`, `VOICE_TOOLBOX_API_HOST`, `VOICE_TOOLBOX_API_PORT`) are fallback-only aliases used when no TOML config is active.

## `.env` — 密钥 | Secrets

```bash
cp -n .env.example .env
```

| 变量 Variable | 供应商 Provider | 必需 Required |
|---|---|---|
| `MIMO_API_KEY` | MiMo | 是（使用 MiMo 时） |
| `FISH_AUDIO_API_KEY` | Fish Audio | 使用 Fish Audio 时 |
| `OPENROUTER_API_KEY` | OpenRouter | 使用 OpenRouter 时 |
| `VOLCENGINE_SPEECH_API_KEY` | Volcengine | 使用 Volcengine 时 |

仅回退（无 `voice_toolbox.toml` 时生效）| Fallback-only (used when no TOML):

| 变量 Variable | 默认值 Default |
|---|---|
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` |
| `VOICE_TOOLBOX_API_HOST` | `127.0.0.1` |
| `VOICE_TOOLBOX_API_PORT` | `8000` |

API 密钥存于 `.env` 或进程环境变量。密钥**变量名**（如 `MIMO_API_KEY`）写在 `voice_toolbox.toml` 中；实际密钥**值**绝不出现于 TOML。

API keys stay in `.env` or the process environment. Key **variable names** (e.g. `MIMO_API_KEY`) are stored in `voice_toolbox.toml`; actual key **values** never appear in TOML.

## `voice_toolbox.toml` — 结构 | Structure

```bash
cp -n voice_toolbox.toml.example voice_toolbox.toml
```

### `[api]`

```toml
[api]
host = "127.0.0.1"
port = 8000
```

默认绑定 loopback。改为 `0.0.0.0` 可监听所有网络接口。

Default binding is loopback-only. Change `host` to `0.0.0.0` to listen on all interfaces.

### `[logging.console]`

```toml
[logging.console]
enabled = true
level = "INFO"
format = "human"    # "human" 或 "json"
colorize = true
```

### `[logging.file]`

```toml
[logging.file]
enabled = false
path = "logs/voice-toolbox.log"
level = "DEBUG"
rotation = "50 MB"
retention = "14 days"
compression = "gz"
enqueue = true
```

### `[chunking.tts]` — TTS 分块

```toml
[chunking.tts]
mode = "auto"               # off | auto | force
max_chars = 1500            # 每块最大字符数
max_chunks = 40             # 最大总块数
max_text_file_bytes = 2000000
silence_ms = 120            # 合并块间的静音间隔
repeat_leading_audio_tags = true
```

- `off`：不拆分文本
- `auto`：仅当文本超过 `max_chars` 时拆分
- `force`：始终拆分

### `[chunking.asr]` — ASR 分块

```toml
[chunking.asr]
mode = "auto"
target_seconds = 90         # 每块目标时长
overlap_ms = 1200           # 块间重叠
max_chunks = 200
max_upload_mb = 250
browser_upload = true       # 启用浏览器分块会话
session_ttl_seconds = 3600
dedupe_min_chars = 8
dedupe_max_chars = 200
```

### `[[providers]]` — 供应商配置块 | Provider Blocks

每个 `[[providers]]` 块声明一个 TTS/ASR 后端：

Each provider block declares one TTS/ASR backend:

```toml
[[providers]]
id = "mimo"                     # 唯一供应商 ID
type = "mimo"                   # 驱动类型：mimo | fish_audio | openrouter | volcengine | mlx_audio
name = "MiMo"                   # Web UI 显示名称
base_url = "https://api.xiaomimimo.com/v1"
api_key_env = "MIMO_API_KEY"    # 保存密钥的环境变量名
default_voice = "mimo_default"

[providers.default_models]
tts_builtin = "mimo-v2.5-tts"
tts_design = "mimo-v2.5-tts-voicedesign"
tts_clone = "mimo-v2.5-tts-voiceclone"
asr = "mimo-v2.5-asr"

[[providers.models]]
id = "mimo-v2.5-tts"
name = "MiMo TTS"
capability = "tts.builtin"

[[providers.models]]
id = "mimo-v2.5-asr"
name = "MiMo V2.5 ASR"
capability = "asr.transcribe"
[providers.models.transcript_capabilities]
timestamps = true
speakers = false
segments = true
```

**能力值 Capability values**: `tts.builtin`、`tts.design`、`tts.clone`、`asr.transcribe`

**`transcript_capabilities`** 控制哪些转录下载格式可用。SRT/VTT 需要 `timestamps=true` 和 `segments=true`。

### 供应商与模型选项 | Provider & Model Options

选项由 `/v1/providers` 暴露，由 Web UI 渲染。CLI 尚未支持。

Options are exposed by `/v1/providers` and rendered by the web UI. CLI does not expose them yet.

```toml
# 供应商级选项（适用于所有模型） | Provider-level option
[[providers.options]]
key = "domain"
label = "Domain vocabulary"
type = "select"
capability = "asr.transcribe"
default = "general"
safe_metadata = true           # 可安全记录到日志；自由文本选项省略此项
[[providers.options.choices]]
value = "general"
label = "General"

# 模型级选项（覆盖供应商级） | Model-level option (overrides provider-level)
[[providers.models.options]]
key = "domain"
capability = "asr.transcribe"
default = "meeting"
```

- `type`: `select`、`multiselect`、`text`、`boolean`、`number`
- `safe_metadata=true`：值可存入附属元数据
- 自由文本选项在附属文件中仅存储键名（不存值）
- Multipart API 调用将选项作为 `provider_options` JSON 对象字符串传递

### 添加多个供应商 | Adding Multiple Providers

同类型支持多个 `[[providers]]` 块（如两个 MiMo 账号）。使用不同的 `api_key_env`：

Multiple `[[providers]]` blocks for the same type are supported. Use different `api_key_env` values:

```toml
[[providers]]
id = "mimo-cn"
type = "mimo"
api_key_env = "MIMO_API_KEY"
# ...

[[providers]]
id = "mimo-sgp"
type = "mimo"
api_key_env = "MIMO_SGP_API_KEY"
# ...
```

## 密钥安全 | Key Security

- TOML 存储 `api_key_env`（变量名），绝不存密钥值
- 密钥值存在于 `.env` 或进程环境变量
- `/v1/providers` 仅暴露密钥是否已配置，加上脱敏预览
- 完整密钥绝不通过 API 返回

## 旧版回退（无 TOML）| Legacy Fallback (No TOML)

当 `voice_toolbox.toml` 缺失时，内置 MiMo 回退读取：

```env
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
VOICE_TOOLBOX_API_HOST=127.0.0.1
VOICE_TOOLBOX_API_PORT=8000
```

旧版 `API_HOST` 和 `API_PORT` 也在此无 TOML 路径中接受。
