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
- Expose masked config path, API key status, and masked API key preview to the API and frontend.
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
- No full API key values in HTTP responses, logs, sidecars, or frontend state. A short masked preview is allowed only for the localhost trusted UI.

## Changes From 2026-06-26 Design

- `.env` remains the secret source, but provider URL/model/voice configuration moves to `voice_toolbox.toml`.
- `ProviderConfig` in `models.py` becomes a compatibility type or is removed during implementation; new code should use `AppConfig` and `ConfiguredProvider` from `config.py`.
- `settings.py` should shrink to environment and config discovery helpers, not own provider defaults.
- `ASRRequest.model` changes from a hard-coded default string to `str | None`; the shared request-preparation layer resolves omitted ASR models from provider config before calling the provider.
- MiMo's built-in models and voices move to `defaults.py` and are used only as fallback defaults.
- API/CLI key checks become provider-generic. They must use each provider's `api_key_env`; no code path should special-case only `MIMO_API_KEY` except the built-in fallback provider.
- `create_app()` keeps test seams: callers may still pass `registry`, `artifact_root`, and `config`.

## Dependencies

Add runtime dependency:

```toml
loguru = ">=0.7"
```

No extra TOML dependency is needed because the project targets Python 3.11+ and uses stdlib `tomllib`.

## Selected Approach

Use a conservative config refactor.

`voice_toolbox.toml` becomes the canonical non-secret configuration. It can define any number of MiMo-compatible provider instances. The app ships with an internal default MiMo config so existing development flows still work without a TOML file. A configured MiMo provider may either rely on those built-in model and voice defaults or override them explicitly.

The provider abstraction remains the boundary used by CLI, API, and UI. MiMo-specific request construction remains in the MiMo provider, but model IDs, voices, base URL, and capability declarations come from provider config.

Loguru is configured once at process startup. Standard logging is intercepted so Uvicorn/FastAPI records use the same sinks and formatting.

Normalization is introduced before provider requests. Providers only receive provider-ready plain text and do not parse Markdown.

## Config File

Config discovery order:

1. If `VOICE_TOOLBOX_CONFIG` is set, load that exact path.
2. Otherwise, load `Path.cwd() / "voice_toolbox.toml"` if it exists.
3. Otherwise, use the built-in default config.

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

If `models`, `voices`, or `default_models` are omitted for a `type = "mimo"` provider, the loader fills them from the built-in MiMo defaults. If `models` are explicitly provided, the provider supports only the capabilities represented by those models. Missing default-model fields are filled only when a matching model for that capability exists.

Token Plan URLs remain user-configured candidates, not defaults.

Boundary rules:

- If `VOICE_TOOLBOX_CONFIG` points to a missing file, startup fails with a clear config error.
- If a discovered `voice_toolbox.toml` exists but has TOML syntax errors, startup fails. It must not silently fall back.
- If `voice_toolbox.toml` exists but omits `providers`, the loader uses the built-in default provider and logs a warning.
- If `providers = []` is explicitly empty, the loader uses the built-in default provider and logs a warning.
- If `MIMO_BASE_URL`, `VOICE_TOOLBOX_API_HOST`, or `VOICE_TOOLBOX_API_PORT` are set while `voice_toolbox.toml` is active, TOML wins and startup logs a warning naming the ignored env var. Values are not secret, so the active base URL may be logged.
- Relative file logging paths are resolved relative to the config file directory when a config file is active, otherwise relative to `Path.cwd()`.
- `voice_toolbox.toml` is secret-adjacent because it controls where API keys are sent. Documentation must tell users not to place it in untrusted shared directories.

## Config Models

Add a focused config module:

```text
packages/voice_toolbox/src/voice_toolbox/config.py
```

Primary Pydantic models:

```python
class AppConfig(BaseModel):
    config_path: Path | None
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    providers: list[ConfiguredProvider]

class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000

class LoggingConfig(BaseModel):
    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)

class ConsoleLoggingConfig(BaseModel):
    enabled: bool = True
    level: str = "INFO"
    format: Literal["human"] = "human"
    colorize: bool = True

class FileLoggingConfig(BaseModel):
    enabled: bool = False
    path: str = "logs/voice-toolbox.log"
    level: str = "DEBUG"
    rotation: str = "50 MB"
    retention: str = "14 days"
    compression: str | None = "gz"
    enqueue: bool = True

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
    tts_builtin: str | None = None
    tts_design: str | None = None
    tts_clone: str | None = None
    asr: str | None = None
```

Validation rules:

- Provider IDs must be unique.
- Provider type must be `mimo`.
- If `models` are omitted, built-in MiMo models are used.
- If `models` are explicitly provided, do not add built-in models that are absent from config.
- If `voices` are omitted, built-in MiMo voices are used.
- Missing individual `default_models` fields are filled from built-in MiMo defaults only when that default model exists in the provider's model list.
- Each configured default model must exist in the provider's `models`.
- Default model capability must match its slot:
  - `tts_builtin` → `tts.builtin`
  - `tts_design` → `tts.design`
  - `tts_clone` → `tts.clone`
  - `asr` → `asr.transcribe`
- Model IDs must be unique per provider.
- Voice IDs must be unique per provider.
- If `default_voice` is set, it must exist in the provider's voices after fallback defaults are applied.
- API key values must never appear in config models.
- Capability lists returned to API consumers are sorted for stable output.
- Model fallback order is deterministic: configured default for capability, then first model with the matching capability in config order.
- If no model has a capability, that provider does not support that capability.

`settings.py` may remain as a compatibility wrapper, but new code should load `AppConfig`.

## Provider Construction

Add a builder:

```text
def build_provider_registry(config: AppConfig, *, artifact_root: Path) -> ProviderRegistry
```

For each configured provider:

- If `type == "mimo"`, build `MimoProvider(config=provider_config, artifact_root=artifact_root)`.
- Fill omitted model and voice lists from built-in MiMo defaults before instantiating the provider.
- Fill missing default-model fields only for capabilities represented by the provider's model list.
- Resolve the API key from `provider_config.api_key_env` using the same `.env` + `os.environ` merge behavior as current `settings.py`; environment variables override `.env` values.
- Pass `base_url`, `models`, `voices`, and `default_models` to the provider.

New constructor shape:

```text
MimoProvider(
    *,
    config: ConfiguredProvider,
    api_key: str | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_root: Path | str | None = None,
    client: Any | None = None,
    client_factory: Callable[..., Any] = OpenAI,
    sleep_func: Callable[[float], None] = time.sleep,
)
```

Compatibility:

- Tests may still inject `client`, `client_factory`, `artifact_store`, and `sleep_func`.
- Direct `base_url` constructor arguments are removed from production paths; tests should use `ConfiguredProvider`.
- If `api_key` is passed explicitly, it wins over environment lookup.

`MimoProvider` behavior changes:

- `id` and `name` come from config.
- `capabilities()` derives from configured model capabilities.
- `list_models()` returns configured models.
- `list_voices()` returns configured voices.
- `_resolve_tts_model()` becomes an instance method and uses request model if present; otherwise uses configured defaults by TTS mode.
- ASR request model defaults to provider config when the API/CLI did not specify one.
- Unsupported model errors are checked against the configured model list.
- `_validate_model_id()` becomes an instance method using that provider's configured model IDs.
- Module-level `_TTS_MODEL_BY_MODE`, `_MODEL_IDS`, `MIMO_MODELS`, and `MIMO_VOICES` move to `defaults.py` or are removed.

Built-in MiMo defaults stay in one explicit location, for fallback only:

```text
packages/voice_toolbox/src/voice_toolbox/defaults.py
```

They are not scattered through provider logic.

## Masked Config and API Key Status

API provider summary includes configuration safe for the local UI:

```json
{
  "id": "mimo",
  "name": "MiMo",
  "type": "mimo",
  "base_url": "https://api.xiaomimimo.com/v1",
  "api_key_env": "MIMO_API_KEY",
  "has_api_key": true,
  "api_key_preview": "tp-...abcd",
  "config_path_preview": "voice-toolbox/voice_toolbox.toml",
  "capabilities": ["asr.transcribe", "tts.builtin"],
  "models": []
}
```

Masking rules:

- API key preview:
  - If no key: `null`
  - If key length <= 8: `"configured"`
  - Else if key contains `-`: `key.split("-", 1)[0] + "-..." + key[-4:]`
  - Else: `"..." + key[-4:]`
  - Example: `tp-1234567890abcd` becomes `tp-...abcd`
- Config path preview:
  - Show only parent directory basename and config filename, for example `voice-toolbox/voice_toolbox.toml`.
  - Do not include usernames, home directories, drive roots, or full absolute paths.

Security boundary:

- `api_key_preview` is allowed because this app defaults to `127.0.0.1` and is intended as a local trusted UI.
- If the API host is configured to anything other than `127.0.0.1` or `localhost`, provider summaries must return `api_key_preview: "configured"` instead of key-derived preview characters.
- Logs and sidecars never include `api_key_preview`.

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

Implementation details:

- `configure_logging()` must be idempotent. Calling it twice replaces previous Voice Toolbox sinks instead of adding duplicates.
- Use a custom `InterceptHandler(logging.Handler)` to forward standard `logging` records into Loguru.
- Root `logging` receives exactly one `InterceptHandler` after configuration.
- Uvicorn loggers have empty `handlers` lists and `propagate = True`.
- The file log parent directory is created automatically with `mkdir(parents=True, exist_ok=True)`.
- Tests must cover repeated `configure_logging()` calls and assert no duplicate Uvicorn access lines.

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
- Add `sanitize_log_metadata(metadata: Mapping[str, object]) -> dict[str, object]`.
- Application logging calls that include request data must log only sanitized metadata from allowlisted keys:
  - `operation`
  - `operation_id`
  - `provider_id`
  - `model`
  - `capability`
  - `status_code`
  - `mime_type`
  - `raw_byte_size`
  - `base64_size`
  - `input_length`
  - `output_length`
  - `duration_ms`
  - `artifact_id`
- Tests must capture console/file logs for a request containing a fake API key, raw text, style prompt, voice description, data URL, and base64 payload, then assert none of those raw values appear.

## API Changes

API startup:

- Load `AppConfig`.
- Configure Loguru.
- Build provider registry from config.
- Keep `create_app` keyword injection seams for tests: `registry`, `artifact_root`, and `config`.

Endpoints:

- `/v1/providers` returns provider summaries with masked config.
- `/v1/providers/{provider_id}/models` returns configured models.
- `/v1/providers/{provider_id}/voices` returns configured voices.
- TTS endpoints accept:
  - `model`
  - `text_format`
- ASR endpoint accepts:
  - `model`
- Provider readiness checks use each provider's configured `api_key_env`. Missing keys disable operations for that provider only; provider listing still succeeds with `has_api_key = false`.
- New endpoint:

```http
POST /v1/normalize/text
```

Limits and errors:

- Maximum `content` length is 200,000 characters.
- Empty or whitespace-only content returns HTTP 422 with `detail = "content is required"`.
- Normalized empty output returns HTTP 422 with `detail = "normalized text is empty"`.
- Unknown `normalizer_id` returns HTTP 422 with `detail = "unknown normalizer: <id>"`.
- Unsupported `input_format` returns normal Pydantic 422.
- Over-limit content returns HTTP 413 with `detail = "content exceeds 200000 characters"`.

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

1. API/CLI collect raw text and `text_format`.
2. A shared request-preparation function normalizes raw text before constructing `TTSRequest`.
3. The preparation function constructs `TTSRequest` using `normalized.text` for the request `text` field.
4. Provider adapters receive only provider-ready plain text and do not call normalizers.
5. Store only normalization metadata on artifact sidecar.

Shared function:

```text
prepare_tts_request(raw_text: str | None, text_format: str, fields: dict[str, object]) -> tuple[TTSRequest, NormalizedContent | None]
```

`text_format` is an API/CLI/input-pipeline field, not a provider field. It must not be added to provider request bodies.

## CLI Changes

CLI startup loads config and configures Loguru once.

Options:

- Existing `--provider` remains.
- Existing `--model` remains.
- TTS commands add:

```text
--text-format plain|markdown|auto
```

Defaults:

- `--provider` defaults to:
  - `mimo` if a configured or fallback provider with ID `mimo` exists
  - otherwise the first configured provider in TOML order
- `--model` omitted means provider default by operation.
- `--text-format plain` unless explicitly overridden.

CLI errors should state which provider/config/key is missing without printing secret values.

## Frontend Changes

Provider selector remains global in the header.

Provider status shows:

- Provider name
- API key status and key env
- Masked key preview when available and API is bound to localhost
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
- Built-in TTS voice selection resets on provider change:
  - first choose provider `default_voice`
  - fallback to first voice in provider voice order
  - if no voices exist, disable built-in TTS submit and show a local form error

Component split:

- Do not keep growing `App.tsx` as one monolith.
- Move provider/model selection helpers into focused hooks or modules:
  - `useProviderCatalog`
  - `selectModelForCapability`
  - `selectDefaultVoice`
- Move fullscreen editor into a focused component:
  - `FullscreenTextEditor`
- Move Advanced settings into reusable form components where practical.

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

- TTS text inputs expose `Format: Plain | Markdown | Auto`.
- `Preview cleaned text` calls `/v1/normalize/text`.
- Preview is read-only and never exposes hidden metadata by default.
- Submit still sends content and `text_format` to the backend; backend normalizes again.
- Default format is `Plain`. Users must explicitly choose `Markdown` or `Auto`.

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
    normalizer_id: str
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
    input_format: Literal["plain", "markdown", "auto"] = "plain"
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

Default behavior:

- All TTS entry points default to `input_format = "plain"`.
- `auto` is available only when the user explicitly selects it.
- `auto_text` must be conservative:
  - It delegates to Markdown only if at least two different Markdown signals are present.
  - Recognized signals are:
    - heading marker at line start: `^#{1,6}\s+\S`
    - fenced code block line: starts with three backticks
    - Markdown link: `\[.+?\]\(.+?\)`
    - Markdown image: `!\[.*?\]\(.+?\)`
    - unordered list marker at line start: `^\s*[-*+]\s+\S`
    - ordered list marker at line start: `^\s*\d+\.\s+\S`
    - table separator line: `^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$`
    - paired emphasis around non-space text: `(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(__[^_\n]+__)|(_[^_\n]+_)`
  - Literal math or script text such as `5 * 4 = 20`, `会议 #1 重点`, and `a < b 且 c > d` must remain unchanged in `auto` mode.

Normalizer options:

- `plain_passthrough` accepts no options; unknown options are ignored.
- `auto_text` accepts no options; unknown options are ignored.
- `markdown_basic` accepts:
  - `preserve_code_blocks: bool = true`
  - `preserve_inline_code: bool = true`
- Any other option keys are ignored in v1 and are returned in metadata as `ignored_options`.

Markdown cleanup is intentionally conservative:

- Heading markers are removed.
- Emphasis markers are removed.
- Links become link text.
- Images become alt text if present, otherwise are removed.
- List markers are removed while preserving item text.
- Blockquote markers are removed.
- Code fence markers are removed while preserving code content by default.
- Inline code backticks are removed while preserving code content by default.
- Simple table separators are removed.
- HTML stripping only removes paired tag syntax such as `<em>text</em>` or standalone simple tags such as `<br>`. Comparisons like `a < b 且 c > d` are not tags and remain unchanged.
- MiMo audio tags such as `(唱歌)`, `(叹气)`, `[breath]`, and `[laughter]` are preserved exactly.
- Chinese punctuation and sentence content are not rewritten.

Empty output:

- If normalized text is empty or whitespace-only, normalization raises a typed error before `TTSRequest` validation.
- API surfaces this as HTTP 422 with `detail = "normalized text is empty"`.
- CLI surfaces `Error: normalized text is empty`.

Normalization metadata:

- `input_length`
- `output_length`
- `changed`
- `normalizer_id`
- `input_format`
- `ignored_options`
- No raw content.

Artifact metadata stores these fields with a `normalization_` prefix except `normalizer_id`:

```json
{
  "normalizer_id": "markdown_basic",
  "normalization_input_format": "markdown",
  "normalization_output_format": "plain",
  "normalization_changed": true,
  "normalization_input_length": 22,
  "normalization_output_length": 17,
  "normalization_ignored_options": []
}
```

Artifact redaction:

- Extend `redact_metadata` allowlist to include normalization metadata keys:
  - `normalizer_id`
  - `normalization_input_format`
  - `normalization_output_format`
  - `normalization_changed`
  - `normalization_input_length`
  - `normalization_output_length`
  - `normalization_ignored_options`
- Sidecars must not include raw pre-normalized or post-normalized text.

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
- `VOICE_TOOLBOX_CONFIG` pointing to a missing file fails startup with a config error.
- TOML syntax errors fail startup and do not silently fall back.
- TOML present with omitted `providers` falls back to built-in MiMo provider and logs a warning.
- TOML present with `providers = []` falls back to built-in MiMo provider and logs a warning.
- Config loading from explicit TOML creates multiple MiMo providers.
- Duplicate provider IDs fail validation.
- Missing required provider fields such as `base_url` fail validation when provider does not rely on fallback defaults.
- Default model not present in model list fails validation.
- Default model with wrong capability fails validation.
- `default_voice` not present in voices fails validation.
- `MIMO_BASE_URL` with active TOML logs an ignored-env warning.
- Provider registry builder constructs providers with configured IDs, names, base URLs, models, and voices.
- `MimoProvider.list_models()` and `list_voices()` reflect config.
- Omitted TTS model resolves to configured default by mode.
- Omitted ASR model resolves to configured default.
- Unsupported explicit model is rejected against configured model IDs.
- Masked key preview follows the exact algorithm and never returns full key.
- Non-local API binding returns `"configured"` instead of key-derived preview.
- Masked config path includes only parent basename and filename, not the full absolute path.
- Loguru config adds console sink and optional file sink.
- Standard logging and Uvicorn logger records are intercepted once.
- Logging tests assert no duplicate handlers on `uvicorn.error` and `uvicorn.access`.
- Repeated `configure_logging()` calls do not duplicate handlers or output.
- File logging creates parent directories and resolves relative paths against config directory.
- Log redaction regression captures log output and asserts it does not contain API key values, raw text, style prompt, voice description, transcript text, base64 payload, or data URLs.
- `/v1/providers` includes masked provider config.
- `/v1/normalize/text` returns expected Markdown cleanup.
- `/v1/normalize/text` rejects missing, empty, whitespace-only, and over-limit content with the documented statuses.
- `plain` normalization keeps `5 * 4 = 20`, `会议 #1 重点`, and `a < b 且 c > d` unchanged.
- Explicit `auto` keeps ambiguous literal script text unchanged unless at least two Markdown signals are present.
- Markdown normalization preserves MiMo audio tags.
- Normalized empty output raises `normalized text is empty`.
- TTS endpoints normalize Markdown before provider calls.
- Artifact metadata includes normalization lengths, not raw content.
- Artifact redaction allowlist preserves normalization metadata keys and still strips raw content.

Frontend tests:

- Provider switch filters model selects by capability.
- Invalid model selection resets to provider default.
- Missing capability disables the relevant submit button.
- Provider switch resets voice selection to configured `default_voice`.
- Provider with no voices disables built-in TTS submit.
- Advanced settings hide model select by default but preserve selected model.
- Full-screen editor Apply writes changes back.
- Full-screen editor Cancel leaves original text unchanged.
- Text format selector sends `text_format`.
- Preview cleaned text calls `/v1/normalize/text` and renders response text.
- Providers list empty state renders a recoverable setup/error message.

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
- Precedence is observable:
  - `VOICE_TOOLBOX_CONFIG` missing path: startup error
  - `VOICE_TOOLBOX_CONFIG` valid path: that TOML wins
  - CWD `voice_toolbox.toml` present: that TOML wins
  - no TOML: built-in defaults plus `.env` compatibility values
  - TOML plus legacy `.env` non-secret overrides: TOML wins and a warning names the ignored env var

Repository hygiene:

- `.superpowers/` is ignored because the visual brainstorming companion stores transient local mockups there.
- Add `voice_toolbox.toml.example` to the repository.
- Do not commit a real `voice_toolbox.toml` if it contains local paths or private endpoint details.
- Keep `.env.example` focused on secret env var names and simple local server overrides.

## Deferred Work

- JSON log format is deferred until a caller needs machine-ingested logs.
- Chunking implementation is deferred to a future spec.
- Additional normalizers such as HTML, SSML stripping, subtitle formats, DOCX, or PDF are deferred.
