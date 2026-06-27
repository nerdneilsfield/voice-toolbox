# Config, Logging, Provider Models, and Normalization Design

Date: 2026-06-27

## Summary

This change upgrades Voice Toolbox from a single hard-coded MiMo setup into a configurable local voice workbench. The first implementation still targets MiMo-compatible providers, but the application configuration can define multiple MiMo provider instances, each with its own base URL, API key environment variable, supported models, default models, and voices.

The same work adds Loguru-based logging, frontend model selection inside per-feature advanced settings, full-screen text editing for long inputs, and a normalized input pipeline. Markdown cleanup is the first built-in normalizer, but it is modeled as one implementation of a general `ContentNormalizer` interface.

Text and audio chunking are analyzed and reserved as a future hybrid pipeline. They are not implemented in this round.

## Goals

- Add `voice_toolbox.toml` at the repository root as the default config file.
- Allow `VOICE_TOOLBOX_CONFIG` to point at another TOML config file.
- Keep `.env` as the secret store for API keys and simple environment overrides.
- Configure multiple `type = "mimo"` provider instances.
- Move MiMo model, voice, default model, base URL, and key-env metadata out of hard-coded runtime assumptions.
- Keep built-in MiMo defaults as fallback when no config file exists, or when a configured MiMo provider omits models, voices, or default models.
- Configure Loguru console and file sinks from TOML.
- Route FastAPI, Starlette, Uvicorn, and standard `logging` records through Loguru without duplicate output.
- Expose masked config and key status to the API and frontend.
- Let the frontend select Provider globally and Model inside each feature's Advanced settings.
- Add full-screen editing for long text inputs.
- Add a generic text normalization interface and implement basic Markdown-to-plain-text cleanup.
- Preserve a future hybrid chunking architecture without implementing chunking now.

## Non-Goals

- No hot reload of config. Changing `voice_toolbox.toml` requires restarting the API or CLI command.
- No provider type beyond `mimo` in this implementation. `fake` remains a test fixture, not a user-configured provider.
- No provider plugin installer or dynamic Python import from config.
- No storage of API key values in TOML.
- No frontend editing of `voice_toolbox.toml`.
- No JSON logging sink in the first implementation.
- No LLM rewriting or semantic text optimization in normalization.
- No TTS text chunking implementation.
- No ASR audio chunking implementation.
- No background job queue or resumable job state machine in this round.

## Selected Approach

Use a conservative config refactor.

`voice_toolbox.toml` becomes the canonical non-secret configuration. It can define any number of MiMo-compatible provider instances. The app ships with an internal default MiMo config so existing development flows still work without a TOML file. A configured MiMo provider may either rely on those built-in model and voice defaults or override them explicitly.

The provider abstraction remains the boundary used by CLI, API, and UI. MiMo-specific request construction remains in the MiMo provider, but model IDs, voices, base URL, and capability declarations come from provider config.

Loguru is configured once at process startup. Standard logging is intercepted so Uvicorn/FastAPI records use the same sinks and formatting.

Normalization is introduced before provider requests. Providers only receive provider-ready plain text and do not parse Markdown.

## Config File

Default path:

```text
voice_toolbox.toml
```

Override:

```bash
VOICE_TOOLBOX_CONFIG=/path/to/voice_toolbox.toml
```

Secrets stay in environment variables or `.env`:

```dotenv
MIMO_API_KEY=tp-...
MIMO_SGP_API_KEY=tp-...
```

Example:

```toml
[api]
host = "127.0.0.1"
port = 8000

[logging.console]
enabled = true
level = "INFO"
format = "human"
colorize = true

[logging.file]
enabled = false
path = "logs/voice-toolbox.log"
level = "DEBUG"
rotation = "50 MB"
retention = "14 days"
compression = "gz"
enqueue = true

[[providers]]
id = "mimo"
type = "mimo"
name = "MiMo"
base_url = "https://api.xiaomimimo.com/v1"
api_key_env = "MIMO_API_KEY"
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
id = "mimo-v2.5-tts-voicedesign"
name = "MiMo Voice Design"
capability = "tts.design"

[[providers.models]]
id = "mimo-v2.5-tts-voiceclone"
name = "MiMo Voice Clone"
capability = "tts.clone"

[[providers.models]]
id = "mimo-v2.5-asr"
name = "MiMo ASR"
capability = "asr.transcribe"

[[providers.voices]]
id = "mimo_default"
name = "MiMo-默认"
note = "cluster-dependent"
```

Multiple provider instances use repeated `[[providers]]` tables:

```toml
[[providers]]
id = "mimo-sgp"
type = "mimo"
name = "MiMo SGP"
base_url = "https://token-plan-sgp.xiaomimimo.com/v1"
api_key_env = "MIMO_SGP_API_KEY"
default_voice = "Mia"
```

If `models`, `voices`, or `default_models` are omitted for a `type = "mimo"` provider, the loader fills them from the built-in MiMo defaults. The provider may still override any of them by specifying those tables explicitly.

Token Plan URLs remain user-configured candidates, not defaults.

## Config Models

Add a focused config module:

```text
packages/voice_toolbox/src/voice_toolbox/config.py
```

Primary Pydantic models:

```python
class AppConfig(BaseModel):
    config_path: Path | None
    api: APIConfig
    logging: LoggingConfig
    providers: list[ConfiguredProvider]

class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000

class LoggingConfig(BaseModel):
    console: ConsoleLoggingConfig
    file: FileLoggingConfig

class ConfiguredProvider(BaseModel):
    id: str
    type: Literal["mimo"]
    name: str
    base_url: str
    api_key_env: str
    default_voice: str | None = None
    default_models: ProviderDefaultModels | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    voices: list[VoiceInfo] = Field(default_factory=list)

class ProviderDefaultModels(BaseModel):
    tts_builtin: str
    tts_design: str
    tts_clone: str
    asr: str
```

Validation rules:

- Provider IDs must be unique.
- Provider type must be `mimo`.
- Missing `models`, `voices`, or `default_models` are filled from built-in MiMo defaults before validation.
- Each default model must exist in the provider's `models`.
- Default model capability must match its slot:
  - `tts_builtin` → `tts.builtin`
  - `tts_design` → `tts.design`
  - `tts_clone` → `tts.clone`
  - `asr` → `asr.transcribe`
- Model IDs must be unique per provider.
- Voice IDs must be unique per provider.
- API key values must never appear in config models.

`settings.py` may remain as a compatibility wrapper, but new code should load `AppConfig`.

## Provider Construction

Add a builder:

```text
def build_provider_registry(config: AppConfig, *, artifact_root: Path) -> ProviderRegistry
```

For each configured provider:

- If `type == "mimo"`, build `MimoProvider(config=provider_config, artifact_root=artifact_root)`.
- Fill missing model, voice, and default-model fields from built-in MiMo defaults before instantiating the provider.
- Resolve the API key from `provider_config.api_key_env`.
- Pass `base_url`, `models`, `voices`, and `default_models` to the provider.

`MimoProvider` behavior changes:

- `id` and `name` come from config.
- `capabilities()` derives from configured model capabilities.
- `list_models()` returns configured models.
- `list_voices()` returns configured voices.
- `_resolve_tts_model()` uses request model if present; otherwise uses configured defaults by TTS mode.
- ASR request model defaults to provider config when the API/CLI did not specify one.
- Unsupported model errors are checked against the configured model list.

Built-in MiMo defaults stay in one explicit location, for fallback only:

```text
packages/voice_toolbox/src/voice_toolbox/defaults.py
```

They are not scattered through provider logic.

## Masked Config and API Key Status

API provider summary includes masked configuration:

```json
{
  "id": "mimo",
  "name": "MiMo",
  "type": "mimo",
  "base_url": "https://api.xiaomimimo.com/v1",
  "api_key_env": "MIMO_API_KEY",
  "has_api_key": true,
  "api_key_preview": "tp-...abcd",
  "config_path_preview": ".../voice_toolbox.toml",
  "capabilities": ["asr.transcribe", "tts.builtin"],
  "models": []
}
```

Masking rules:

- API key preview:
  - If no key: `null`
  - If key length <= 8: `"configured"`
  - Else: first prefix segment plus last 4 chars, for example `tp-...abcd`
- Config path preview:
  - Show basename and a shortened parent, for example `.../voice-toolbox/voice_toolbox.toml`
  - Do not expose unrelated absolute path details in the frontend.

## Logging

Add:

```text
packages/voice_toolbox/src/voice_toolbox/logging_config.py
```

Entry point:

```text
def configure_logging(config: LoggingConfig) -> None
```

Startup flow:

1. `logger.remove()` clears Loguru's default sink.
2. Add console sink if enabled.
3. Add file sink if enabled.
4. Install a standard logging interceptor.
5. Clear handlers on `uvicorn`, `uvicorn.error`, `uvicorn.access`, `fastapi`, and `starlette`.
6. Set those loggers to propagate into the interceptor.

Console config:

```toml
[logging.console]
enabled = true
level = "INFO"
format = "human"
colorize = true
```

File config:

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

`format = "human"` maps to:

```text
{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}
```

JSON logging is deferred.

Logging safety:

- Never log API key values.
- Never log base64 audio or data URLs.
- Never log raw TTS text, style prompts, voice descriptions, transcript contents, or clone sample contents.
- Log lengths, MIME types, model IDs, provider IDs, operation IDs, artifact IDs, and duration.
- Provider errors include sanitized provider ID, operation, and status code when available.

## API Changes

API startup:

- Load `AppConfig`.
- Configure Loguru.
- Build provider registry from config.

Endpoints:

- `/v1/providers` returns provider summaries with masked config.
- `/v1/providers/{provider_id}/models` returns configured models.
- `/v1/providers/{provider_id}/voices` returns configured voices.
- TTS endpoints accept:
  - `model`
  - `text_format`
- ASR endpoint accepts:
  - `model`
- New endpoint:

```http
POST /v1/normalize/text
```

Request:

```json
{
  "content": "# Title\nHello **world**",
  "input_format": "markdown",
  "normalizer_id": null,
  "options": {}
}
```

Response:

```json
{
  "text": "Title\nHello world",
  "input_format": "markdown",
  "output_format": "plain",
  "normalizer_id": "markdown_basic",
  "changed": true,
  "metadata": {
    "input_length": 22,
    "output_length": 17
  }
}
```

TTS request handling:

1. Normalize text before constructing `TTSRequest`.
2. Store only normalization metadata on artifact sidecar.
3. Pass normalized plain text to provider.

## CLI Changes

CLI startup loads config and configures Loguru once.

Options:

- Existing `--provider` remains.
- Existing `--model` remains.
- TTS commands add:

```text
--text-format auto|plain|markdown
```

Defaults:

- `--provider mimo` still works if fallback config provides provider `mimo`.
- `--model` omitted means provider default by operation.
- `--text-format auto` unless explicitly overridden.

CLI errors should state which provider/config/key is missing without printing secret values.

## Frontend Changes

Provider selector remains global in the header.

Provider status shows:

- Provider name
- API key status and key env
- Masked key preview when available
- Base URL
- Masked config path

Each feature form has an `Advanced settings` section:

- Built-in TTS model select lists models with `capability = "tts.builtin"`.
- Voice design model select lists models with `capability = "tts.design"`.
- Voice clone model select lists models with `capability = "tts.clone"`.
- ASR model select lists models with `capability = "asr.transcribe"`.

Selection behavior:

- If the selected provider changes, each form checks whether its selected model is still valid.
- If invalid, choose provider default for that capability.
- If no default exists, choose the first model for that capability.
- If no model exists for the capability, disable the submit button and show a local form error.

Full-screen text editor:

- Applies to all long text inputs:
  - Built-in script
- Any style prompt field if it is rendered as a long textarea in the UI
  - Design voice persona
  - Design script
  - Clone script
- Any clone style prompt field if it is rendered as a long textarea in the UI
- Textarea has a small expand button.
- Modal includes title, textarea, character count, Cancel, and Apply.
- `Esc` cancels.
- `Cmd+Enter` / `Ctrl+Enter` applies.
- Apply writes back to the original field.
- Cancel leaves original value unchanged.

Text format UI:

- TTS text inputs expose `Format: Auto | Plain | Markdown`.
- `Preview cleaned text` calls `/v1/normalize/text`.
- Preview is read-only and never exposes hidden metadata by default.
- Submit still sends content and `text_format` to the backend; backend normalizes again.

## Content Normalization

Add:

```text
packages/voice_toolbox/src/voice_toolbox/normalizers/
  __init__.py
  base.py
  markdown.py
  registry.py
```

Interface:

```python
class ContentNormalizer(Protocol):
    id: str
    input_formats: set[str]
    output_format: str

    def normalize(
        self,
        content: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        raise NotImplementedError
```

Models:

```python
class NormalizationRequest(BaseModel):
    input_format: Literal["auto", "plain", "markdown"] = "auto"
    normalizer_id: str | None = None
    content: str
    options: dict[str, Any] = Field(default_factory=dict)

class NormalizedContent(BaseModel):
    text: str
    input_format: str
    output_format: Literal["plain"] = "plain"
    normalizer_id: str
    changed: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Built-in normalizers:

- `plain_passthrough`: returns content unchanged.
- `markdown_basic`: converts basic Markdown to readable plain text.
- `auto_text`: detects Markdown-ish markers and delegates to `markdown_basic` or `plain_passthrough`.

Markdown cleanup is intentionally conservative:

- Heading markers are removed.
- Emphasis markers are removed.
- Links become link text.
- Images become alt text if present, otherwise are removed.
- List markers are removed while preserving item text.
- Blockquote markers are removed.
- Code fence markers are removed while preserving code content.
- Inline code backticks are removed while preserving code content.
- Simple table separators are removed.
- HTML tags are stripped.
- Chinese punctuation and sentence content are not rewritten.

Normalization metadata:

- `input_length`
- `output_length`
- `changed`
- `normalizer_id`
- `input_format`
- No raw content.

## Chunking Analysis and Future Boundary

Chunking is not implemented in this round.

The selected future architecture is hybrid:

- Backend owns chunk planning contracts, merge/dedup rules, artifact grouping, retry policy, and logging.
- Frontend may act as an ASR audio chunk producer when remote deployment or browser-side file limits make whole-file upload undesirable.
- TTS text chunking should primarily happen on the backend because text uploads are small and provider call orchestration belongs with artifact storage and retries.
- ASR audio chunking should support two paths later:
  - Backend receives a whole file and chunks it locally.
  - Frontend chunks audio and uploads chunk files with overlap metadata.

Reserved future models:

```python
class ChunkingPlan(BaseModel):
    operation: Literal["tts", "asr"]
    source_format: str
    chunk_count: int
    overlap_ms: int | None = None
    strategy: str

class ChunkRef(BaseModel):
    index: int
    total: int
    source_id: str
    offset_ms: int | None = None
    duration_ms: int | None = None
    text_range: tuple[int, int] | None = None

class ChunkedOperation(BaseModel):
    operation_id: str
    provider_id: str
    model: str
    chunks: list[ChunkRef]
    merge_strategy: str
```

Future pipeline:

```text
raw input -> normalize -> chunk plan -> provider calls -> merge -> artifact group
```

## Testing

Backend tests:

- Config loading without `voice_toolbox.toml` returns built-in default MiMo provider.
- Config loading from explicit TOML creates multiple MiMo providers.
- Duplicate provider IDs fail validation.
- Default model not present in model list fails validation.
- Default model with wrong capability fails validation.
- Provider registry builder constructs providers with configured IDs, names, base URLs, models, and voices.
- `MimoProvider.list_models()` and `list_voices()` reflect config.
- Omitted TTS model resolves to configured default by mode.
- Omitted ASR model resolves to configured default.
- Unsupported explicit model is rejected against configured model IDs.
- Masked key preview never returns full key.
- Masked config path does not expose the full absolute path.
- Loguru config adds console sink and optional file sink.
- Standard logging and Uvicorn logger records are intercepted once.
- Logging tests assert no duplicate handlers on `uvicorn.error` and `uvicorn.access`.
- `/v1/providers` includes masked provider config.
- `/v1/normalize/text` returns expected Markdown cleanup.
- TTS endpoints normalize Markdown before provider calls.
- Artifact metadata includes normalization lengths, not raw content.

Frontend tests:

- Provider switch filters model selects by capability.
- Invalid model selection resets to provider default.
- Missing capability disables the relevant submit button.
- Advanced settings hide model select by default but preserve selected model.
- Full-screen editor Apply writes changes back.
- Full-screen editor Cancel leaves original text unchanged.
- Text format selector sends `text_format`.
- Preview cleaned text calls `/v1/normalize/text` and renders response text.

Manual smoke:

- Start API without `voice_toolbox.toml`; existing MiMo default still appears.
- Start API with two configured MiMo providers; both appear in provider selector.
- Enable file logging and verify one log line per request.
- Submit Markdown TTS text and confirm provider receives plain text.
- Use full-screen editor on built-in script and design persona.

## Migration Notes

Existing `.env` remains valid:

```dotenv
MIMO_API_KEY=...
MIMO_BASE_URL=...
VOICE_TOOLBOX_API_HOST=127.0.0.1
VOICE_TOOLBOX_API_PORT=8000
```

Compatibility behavior:

- If `voice_toolbox.toml` is absent, built-in MiMo defaults are used.
- `MIMO_BASE_URL` may override the built-in default base URL only for the fallback MiMo provider.
- Once `voice_toolbox.toml` exists, provider base URLs come from TOML.
- API keys always come from `api_key_env`.

## Deferred Work

- JSON log format is deferred until a caller needs machine-ingested logs.
- Chunking implementation is deferred to a future spec.
- Additional normalizers such as HTML, SSML stripping, subtitle formats, DOCX, or PDF are deferred.
