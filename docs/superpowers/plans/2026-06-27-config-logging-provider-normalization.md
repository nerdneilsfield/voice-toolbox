# Config, Logging, Provider Models, and Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement configurable MiMo providers, Loguru logging, provider/model-aware UI, fullscreen editing, and text normalization as specified in `docs/superpowers/specs/2026-06-27-config-logging-provider-normalization-design.md`.

**Architecture:** `voice_toolbox.toml` owns non-secret provider/API/logging config; `.env` remains the secret/env override source. Providers receive normalized, provider-ready requests and sidecar-safe metadata from a shared pipeline. FastAPI and the React app consume provider summaries, model lists, and normalization endpoints rather than hard-coded MiMo assumptions.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, OpenAI SDK, Loguru, Typer, pytest, ruff, ty, React 19, Vite, Bun, TypeScript, ESLint, Prettier.

---

## Execution Rules

- Each task ends with one commit.
- Use `rtk` before shell commands.
- After Tasks 3, 6, and 9, stop for a large adversarial review before continuing.
- Do not run real MiMo smoke tests unless `MIMO_API_KEY` is present.
- Keep full API keys, raw text, base64 audio, transcript contents, and clone sample contents out of logs, sidecars, and frontend state.

## File Structure

Create:

- `packages/voice_toolbox/src/voice_toolbox/config_models.py` - Pydantic config models shared by config/defaults/provider construction; prevents `config.py` ↔ `defaults.py` circular imports.
- `packages/voice_toolbox/src/voice_toolbox/config.py` - TOML loading, config discovery, provider default filling, env precedence warnings, and re-export of config models.
- `packages/voice_toolbox/src/voice_toolbox/defaults.py` - built-in MiMo model/voice/default provider constants and `make_default_mimo_provider_config()`.
- `packages/voice_toolbox/src/voice_toolbox/providers/factory.py` - `build_provider_registry(config, artifact_root, env_values=None)` without importing from API code.
- `packages/voice_toolbox/src/voice_toolbox/logging_config.py` - Loguru sinks and stdlib/Uvicorn interception.
- `apps/api/src/voice_toolbox_api/server.py` - logging-aware Uvicorn entrypoint used by Makefile.
- `packages/voice_toolbox/src/voice_toolbox/pipeline.py` - shared `prepare_tts_request()` and sidecar-safe normalization metadata assembly.
- `packages/voice_toolbox/src/voice_toolbox/normalizers/__init__.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/base.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/markdown.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/registry.py`
- `apps/web/src/hooks/useProviderCatalog.ts`
- `apps/web/src/lib/providerSelection.ts`
- `apps/web/src/lib/providerSelection.test.ts`
- `apps/web/src/components/FullscreenTextEditor.tsx`
- `apps/web/src/components/AdvancedSettings.tsx`
- `voice_toolbox.toml.example`
- `tests/test_config.py`
- `tests/test_logging_config.py`
- `tests/test_normalizers.py`
- `tests/test_pipeline.py`
- `tests/test_provider_config.py`

Modify:

- `pyproject.toml` - add `loguru>=0.7`.
- `.env.example` - add/clarify `MIMO_SGP_API_KEY`, `VOICE_TOOLBOX_API_HOST`, `VOICE_TOOLBOX_API_PORT`, fallback-only comments.
- `Makefile` - route API server through `python -m voice_toolbox_api.server`.
- `packages/voice_toolbox/src/voice_toolbox/models.py` - `ASRRequest.model: str | None`, compatibility `ProviderConfig`, any normalization models if not placed in normalizer modules.
- `packages/voice_toolbox/src/voice_toolbox/settings.py` - shrink to env helpers and compatibility wrapper.
- `packages/voice_toolbox/src/voice_toolbox/providers/base.py` - add `artifact_metadata` keyword to `synthesize()`.
- `packages/voice_toolbox/src/voice_toolbox/providers/registry.py` - generic provider list/build behaviors if required.
- `packages/voice_toolbox/src/voice_toolbox/providers/fake.py` - accept and write sidecar-safe metadata.
- `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py` - configurable provider instance, instance model validation, default model resolution, metadata merge.
- `packages/voice_toolbox/src/voice_toolbox/artifacts.py` - extend redaction allowlist.
- `packages/voice_toolbox/src/voice_toolbox/cli.py` - load config/logging, provider defaults, `--text-format`, ASR `model=None`.
- `apps/api/src/voice_toolbox_api/main.py` - `create_app(config=test_config)`, provider summaries, `/v1/normalize/text`, `text_format`, generic key checks.
- `apps/web/src/api.ts` - provider summary fields, normalize endpoint, text format, model fields.
- `apps/web/src/App.tsx` - provider/model UI, fullscreen editor integration, text format preview.
- `apps/web/src/styles.css` - fullscreen editor and advanced settings polish.
- `apps/web/package.json` - change only the existing `test` script to Vitest and add Vitest as a dev dependency; do not rewrite unrelated scripts.
- Existing tests in `tests/` - update imports and expectations.

---

### Task 1: Config Models, Defaults, and Env Precedence

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/defaults.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/config.py`
- Create: `tests/test_config.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/settings.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/models.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency test and config tests**

Add `tests/test_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from voice_toolbox.config import ConfigError, load_app_config, mask_api_key_preview, preview_config_path


def test_loads_builtin_default_without_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOICE_TOOLBOX_CONFIG", raising=False)

    config = load_app_config()

    assert config.config_path is None
    assert config.api.host == "127.0.0.1"
    assert config.api.port == 8000
    assert [provider.id for provider in config.providers] == ["mimo"]
    assert config.providers[0].base_url == "https://api.xiaomimimo.com/v1"


def test_explicit_missing_config_path_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing.toml"
    monkeypatch.setenv("VOICE_TOOLBOX_CONFIG", str(missing))

    with pytest.raises(ConfigError, match="VOICE_TOOLBOX_CONFIG"):
        load_app_config()


def test_toml_with_empty_providers_falls_back_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIMO_BASE_URL", "https://ignored.example/v1")
    path = tmp_path / "voice_toolbox.toml"
    path.write_text("providers = []\n", encoding="utf-8")

    config = load_app_config(path)

    assert [provider.id for provider in config.providers] == ["mimo"]
    assert "providers is empty" in caplog.text
    assert "ignored env var MIMO_BASE_URL" in caplog.text


def test_configured_provider_overrides_models_and_voices(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[api]
host = "127.0.0.1"
port = 9001

[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"
default_voice = "Mia"

[providers.default_models]
tts_builtin = "custom-tts"

[[providers.models]]
id = "custom-tts"
name = "Custom TTS"
capability = "tts.builtin"

[[providers.voices]]
id = "Mia"
name = "Mia"
language = "en"
gender = "female"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)

    provider = config.providers[0]
    assert provider.id == "mimo-lite"
    assert provider.default_models is not None
    assert provider.default_models.tts_builtin == "custom-tts"
    assert provider.default_models.tts_design is None
    assert [model.id for model in provider.models] == ["custom-tts"]
    assert [voice.id for voice in provider.voices] == ["Mia"]


def test_legacy_env_applies_only_without_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MIMO_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("VOICE_TOOLBOX_API_HOST", "127.0.0.2")
    monkeypatch.setenv("VOICE_TOOLBOX_API_PORT", "9002")

    fallback = load_app_config()

    assert fallback.providers[0].base_url == "https://env.example/v1"
    assert fallback.api.host == "127.0.0.2"
    assert fallback.api.port == 9002

    path = tmp_path / "voice_toolbox.toml"
    path.write_text("[api]\nhost = '127.0.0.1'\nport = 8000\n", encoding="utf-8")
    active = load_app_config(path)

    assert active.providers[0].base_url == "https://api.xiaomimimo.com/v1"
    assert "ignored env var MIMO_BASE_URL" in caplog.text


def test_masked_key_preview_short_boundaries() -> None:
    assert mask_api_key_preview(None, trusted_local=True) is None
    assert mask_api_key_preview("tp-1234", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-123456", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-12345678", trusted_local=True) == "configured"
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=True) == "tp-...abcd"
    assert mask_api_key_preview("abcdef123456", trusted_local=True) == "...3456"
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=False) == "configured"


def test_config_path_preview() -> None:
    assert preview_config_path(None) == "built-in default"
    assert preview_config_path(Path("/Users/example/voice-toolbox/voice_toolbox.toml")) == (
        "voice-toolbox/voice_toolbox.toml"
    )
    assert preview_config_path(Path("voice_toolbox.toml")) == "voice_toolbox.toml"


def test_validation_rejects_bad_defaults(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "bad"
type = "mimo"
name = "Bad"
base_url = "https://example.test/v1"
api_key_env = "BAD_KEY"
default_voice = "missing"

[providers.default_models]
tts_builtin = "asr-only"

[[providers.models]]
id = "asr-only"
name = "ASR"
capability = "asr.transcribe"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="default_voice|capability"):
        load_app_config(path)


def test_load_app_config_uses_explicit_env_path(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.custom"
    env_path.write_text("MIMO_BASE_URL=https://custom-env.example/v1\n", encoding="utf-8")

    config = load_app_config(env_path=env_path)

    assert config.providers[0].base_url == "https://custom-env.example/v1"


def test_partial_model_fallback_does_not_add_absent_capabilities(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "mimo-lite"
type = "mimo"
name = "MiMo Lite"
base_url = "https://example.test/v1"
api_key_env = "MIMO_LITE_KEY"

[[providers.models]]
id = "custom-tts"
name = "Custom TTS"
capability = "tts.builtin"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    defaults = config.providers[0].default_models

    assert defaults is not None
    assert defaults.tts_builtin == "custom-tts"
    assert defaults.tts_design is None
    assert defaults.tts_clone is None
    assert defaults.asr is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
rtk uv run pytest tests/test_config.py -v
```

Expected: FAIL with import errors for `voice_toolbox.config`.

- [ ] **Step 3: Implement config model and defaults modules**

Create `packages/voice_toolbox/src/voice_toolbox/config_models.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from voice_toolbox.models import ModelInfo, VoiceInfo


class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


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


class LoggingConfig(BaseModel):
    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)


class ProviderDefaultModels(BaseModel):
    tts_builtin: str | None = None
    tts_design: str | None = None
    tts_clone: str | None = None
    asr: str | None = None


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


class AppConfig(BaseModel):
    config_path: Path | None = None
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    providers: list[ConfiguredProvider]

    @model_validator(mode="after")
    def validate_providers(self) -> AppConfig:
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider ids must be unique")
        for provider in self.providers:
            validate_configured_provider(provider)
        return self


def validate_configured_provider(provider: ConfiguredProvider) -> None:
    model_by_id = {model.id: model for model in provider.models}
    if len(model_by_id) != len(provider.models):
        raise ValueError(f"provider {provider.id} has duplicate model ids")
    voice_ids = {voice.id for voice in provider.voices}
    if len(voice_ids) != len(provider.voices):
        raise ValueError(f"provider {provider.id} has duplicate voice ids")
    if provider.default_voice is not None and provider.default_voice not in voice_ids:
        raise ValueError(f"provider {provider.id} default_voice is not configured")
    expected = {
        "tts_builtin": "tts.builtin",
        "tts_design": "tts.design",
        "tts_clone": "tts.clone",
        "asr": "asr.transcribe",
    }
    defaults = provider.default_models or ProviderDefaultModels()
    for field_name, capability in expected.items():
        model_id = getattr(defaults, field_name)
        if model_id is None:
            continue
        model = model_by_id.get(model_id)
        if model is None:
            raise ValueError(f"provider {provider.id} default model {model_id} is missing")
        if model.capability != capability:
            raise ValueError(
                f"provider {provider.id} default model {model_id} has capability {model.capability}, expected {capability}"
            )
```

Create `packages/voice_toolbox/src/voice_toolbox/defaults.py`:

```python
from __future__ import annotations

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ModelInfo, VoiceInfo

DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"

MIMO_MODELS: list[ModelInfo] = [
    ModelInfo(id="mimo-v2.5-tts", name="MiMo TTS", capability="tts.builtin"),
    ModelInfo(
        id="mimo-v2.5-tts-voicedesign",
        name="MiMo Voice Design",
        capability="tts.design",
    ),
    ModelInfo(
        id="mimo-v2.5-tts-voiceclone",
        name="MiMo Voice Clone",
        capability="tts.clone",
    ),
    ModelInfo(id="mimo-v2.5-asr", name="MiMo ASR", capability="asr.transcribe"),
]

MIMO_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="mimo_default", name="MiMo-默认", note="cluster-dependent"),
    VoiceInfo(id="冰糖", name="冰糖", language="zh", gender="female"),
    VoiceInfo(id="茉莉", name="茉莉", language="zh", gender="female"),
    VoiceInfo(id="苏打", name="苏打", language="zh", gender="male"),
    VoiceInfo(id="白桦", name="白桦", language="zh", gender="male"),
    VoiceInfo(id="Mia", name="Mia", language="en", gender="female"),
    VoiceInfo(id="Chloe", name="Chloe", language="en", gender="female"),
    VoiceInfo(id="Milo", name="Milo", language="en", gender="male"),
    VoiceInfo(id="Dean", name="Dean", language="en", gender="male"),
]

DEFAULT_MIMO_MODELS = ProviderDefaultModels(
    tts_builtin="mimo-v2.5-tts",
    tts_design="mimo-v2.5-tts-voicedesign",
    tts_clone="mimo-v2.5-tts-voiceclone",
    asr="mimo-v2.5-asr",
)


def make_default_mimo_provider_config(
    *,
    provider_id: str = "mimo",
    name: str = "MiMo",
    base_url: str = DEFAULT_MIMO_BASE_URL,
    api_key_env: str = "MIMO_API_KEY",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="mimo",
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice="mimo_default",
        default_models=DEFAULT_MIMO_MODELS,
        models=[model.model_copy() for model in MIMO_MODELS],
        voices=[voice.model_copy() for voice in MIMO_VOICES],
    )
```

- [ ] **Step 4: Implement config module**

Create `packages/voice_toolbox/src/voice_toolbox/config.py` with these public names:

```python
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from dotenv import dotenv_values
from pydantic import ValidationError

from voice_toolbox.config_models import (
    APIConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    FileLoggingConfig,
    LoggingConfig,
    ProviderDefaultModels,
)
from voice_toolbox.defaults import DEFAULT_MIMO_BASE_URL, DEFAULT_MIMO_MODELS, MIMO_MODELS, MIMO_VOICES

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    pass


def load_app_config(
    path: Path | str | None = None,
    *,
    env_path: Path | str | None = None,
    env_values: dict[str, str] | None = None,
) -> AppConfig:
    env = env_values or load_env_values(env_path)
    config_path = _discover_config_path(path, env)
    if config_path is None:
        return _fallback_config(env)
    payload = _read_toml(config_path)
    payload["config_path"] = config_path
    _warn_ignored_env(env)
    if not payload.get("providers"):
        logger.warning("providers is empty; using built-in default provider")
        payload["providers"] = [_default_provider_payload(env, use_env_base_url=False)]
    payload["providers"] = [_fill_mimo_defaults(provider) for provider in payload["providers"]]
    try:
        return AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_env_values(env_path: Path | str | None = None) -> dict[str, str]:
    values: dict[str, object] = {}
    path = Path(env_path) if env_path is not None else Path.cwd() / ".env"
    if env_path is not None and not path.exists():
        raise ConfigError(f"env file does not exist: {path}")
    if path.exists():
        values.update(dotenv_values(path))
    values.update(os.environ)
    return {key: str(value) for key, value in values.items() if value is not None}


def mask_api_key_preview(value: str | None, *, trusted_local: bool) -> str | None:
    if not value:
        return None
    if not trusted_local:
        return "configured"
    if len(value) <= 8:
        return "configured"
    if "-" in value:
        prefix = value.split("-", 1)[0] + "-"
        if len(value) <= len(prefix) + 8:
            return "configured"
        return f"{prefix}...{value[-4:]}"
    return f"...{value[-4:]}"


def preview_config_path(path: Path | None) -> str:
    if path is None:
        return "built-in default"
    parent = path.parent.name
    return f"{parent}/{path.name}" if parent else path.name
```

Implement private helpers with these contracts:

```python
IGNORED_WHEN_TOML_ACTIVE = (
    "MIMO_BASE_URL",
    "VOICE_TOOLBOX_API_HOST",
    "VOICE_TOOLBOX_API_PORT",
    "API_HOST",
    "API_PORT",
)


def _discover_config_path(path: Path | str | None, env: dict[str, str]) -> Path | None:
    if path is not None:
        candidate = Path(path)
        if not candidate.exists():
            raise ConfigError(f"config file does not exist: {candidate}")
        return candidate
    env_path = env.get("VOICE_TOOLBOX_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if not candidate.exists():
            raise ConfigError(f"VOICE_TOOLBOX_CONFIG points to missing file: {candidate}")
        return candidate
    cwd_candidate = Path.cwd() / "voice_toolbox.toml"
    return cwd_candidate if cwd_candidate.exists() else None


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as file:
            payload = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return dict(payload)


def _fallback_config(env: dict[str, str]) -> AppConfig:
    payload = {
        "config_path": None,
        "api": {
            "host": env.get("VOICE_TOOLBOX_API_HOST") or env.get("API_HOST") or "127.0.0.1",
            "port": int(env.get("VOICE_TOOLBOX_API_PORT") or env.get("API_PORT") or "8000"),
        },
        "providers": [_default_provider_payload(env, use_env_base_url=True)],
    }
    return AppConfig.model_validate(payload)


def _default_provider_payload(env: dict[str, str], *, use_env_base_url: bool) -> dict[str, object]:
    base_url = env.get("MIMO_BASE_URL") if use_env_base_url else None
    return {
        "id": "mimo",
        "type": "mimo",
        "name": "MiMo",
        "base_url": base_url or DEFAULT_MIMO_BASE_URL,
        "api_key_env": "MIMO_API_KEY",
        "default_voice": "mimo_default",
        "default_models": DEFAULT_MIMO_MODELS.model_dump(),
        "models": [model.model_dump() for model in MIMO_MODELS],
        "voices": [voice.model_dump() for voice in MIMO_VOICES],
    }


def _warn_ignored_env(env: dict[str, str]) -> None:
    for key in IGNORED_WHEN_TOML_ACTIVE:
        if env.get(key):
            logger.warning("ignored env var %s because voice_toolbox.toml is active", key)


def _fill_mimo_defaults(provider: dict[str, object]) -> dict[str, object]:
    result = dict(provider)
    configured_models = "models" in result
    if not configured_models:
        result["models"] = [model.model_dump() for model in MIMO_MODELS]
    if "voices" not in result:
        result["voices"] = [voice.model_dump() for voice in MIMO_VOICES]
    models = [ModelInfo.model_validate(model) for model in result.get("models", [])]
    models_by_capability: dict[str, str] = {}
    for model in models:
        if model.capability and model.capability not in models_by_capability:
            models_by_capability[model.capability] = model.id
    current_defaults = ProviderDefaultModels.model_validate(result.get("default_models") or {})
    fallback = ProviderDefaultModels(
        tts_builtin=current_defaults.tts_builtin or models_by_capability.get("tts.builtin"),
        tts_design=current_defaults.tts_design or models_by_capability.get("tts.design"),
        tts_clone=current_defaults.tts_clone or models_by_capability.get("tts.clone"),
        asr=current_defaults.asr or models_by_capability.get("asr.transcribe"),
    )
    result["default_models"] = fallback.model_dump()
    return result
```

- [ ] **Step 5: Keep compatibility settings wrapper**

Modify `packages/voice_toolbox/src/voice_toolbox/settings.py` so `load_settings()` returns the existing `ProviderConfig` while internally using `load_app_config()` for fallback values. Preserve `API_HOST`/`API_PORT` aliases only when TOML is absent.

Required behavior:

```python
def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    app_config = load_app_config(env_path=env_path)
    provider = app_config.providers[0]
    return ProviderConfig(
        provider_id=provider.id,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        api_host=app_config.api.host,
        api_port=app_config.api.port,
    )
```

`get_mimo_api_key(env_path)` must call `load_env_values(env_path)` and read the resolved `api_key_env`.

- [ ] **Step 6: Add Loguru dependency**

Modify `pyproject.toml` dependencies:

```toml
  "loguru>=0.7",
```

- [ ] **Step 7: Sync dependencies**

Run:

```bash
rtk uv sync --extra dev
```

Expected: dependency sync succeeds and `loguru` is installed.

- [ ] **Step 8: Run backend checks**

Run:

```bash
rtk uv run pytest tests/test_config.py tests/test_imports.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/config.py packages/voice_toolbox/src/voice_toolbox/config_models.py packages/voice_toolbox/src/voice_toolbox/defaults.py
rtk uv run ty check packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
rtk git add pyproject.toml uv.lock packages/voice_toolbox/src/voice_toolbox/config.py packages/voice_toolbox/src/voice_toolbox/config_models.py packages/voice_toolbox/src/voice_toolbox/defaults.py packages/voice_toolbox/src/voice_toolbox/settings.py packages/voice_toolbox/src/voice_toolbox/models.py tests/test_config.py
rtk git commit -m "feat: add configurable provider settings"
```

---

### Task 2: Configurable Provider Construction

**Files:**
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/base.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/fake.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/factory.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/registry.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/models.py`
- Create: `tests/test_provider_config.py`
- Modify: `tests/test_mimo_provider.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add provider configuration tests**

Create `tests/test_provider_config.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from voice_toolbox.config import AppConfig, ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ASRRequest, ModelInfo, TTSMode, TTSRequest, VoiceInfo
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.mimo import MIMO_MODELS, MIMO_VOICES, MimoProvider


def _completion() -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(audio=SimpleNamespace(data="V0FW")))]
    )


class RecordingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return _completion()


def _provider_config() -> ConfiguredProvider:
    return ConfiguredProvider(
        id="mimo-sgp",
        type="mimo",
        name="MiMo SGP",
        base_url="https://sgp.example/v1",
        api_key_env="MIMO_SGP_API_KEY",
        default_voice="Mia",
        default_models=ProviderDefaultModels(tts_builtin="custom-tts", asr="custom-asr"),
        models=[
            ModelInfo(id="custom-tts", name="Custom TTS", capability="tts.builtin"),
            ModelInfo(id="custom-asr", name="Custom ASR", capability="asr.transcribe"),
        ],
        voices=[VoiceInfo(id="Mia", name="Mia", language="en", gender="female")],
    )


def test_mimo_provider_uses_configured_identity_models_and_voices(tmp_path: Path) -> None:
    provider = MimoProvider(config=_provider_config(), api_key="secret", artifact_root=tmp_path)

    assert provider.id == "mimo-sgp"
    assert provider.name == "MiMo SGP"
    assert provider.capabilities() == {"tts.builtin", "asr.transcribe"}
    assert [model.id for model in provider.list_models()] == ["custom-tts", "custom-asr"]
    assert [voice.id for voice in provider.list_voices()] == ["Mia"]


def test_mimo_provider_resolves_configured_default_tts_model(tmp_path: Path) -> None:
    completions = RecordingCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = MimoProvider(
        config=_provider_config(),
        api_key="secret",
        artifact_root=tmp_path,
        client=client,
    )

    provider.synthesize(TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="Mia"))

    assert completions.calls[0]["model"] == "custom-tts"


def test_mimo_provider_keeps_base_url_test_seam(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=RecordingCompletions()))

    MimoProvider(api_key="secret", base_url="https://override.test/v1", artifact_root=tmp_path, client_factory=factory)

    assert captured["base_url"] == "https://override.test/v1"


def test_defaults_reexport_for_existing_tests() -> None:
    assert {model.id for model in MIMO_MODELS} >= {"mimo-v2.5-tts", "mimo-v2.5-asr"}
    assert {voice.id for voice in MIMO_VOICES} >= {"mimo_default", "Mia"}


def test_asr_model_can_be_omitted(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")
    request = ASRRequest(
        model=None,
        audio_path=audio,
        mime_type="audio/wav",
        raw_byte_size=16,
        base64_size=24,
    )

    assert request.model is None


def test_build_provider_registry_uses_config_and_env_values(tmp_path: Path) -> None:
    registry = build_provider_registry(
        config=AppConfig(config_path=None, providers=[_provider_config()]),
        artifact_root=tmp_path,
        env_values={"MIMO_SGP_API_KEY": "secret"},
    )

    provider = registry.get("mimo-sgp")

    assert isinstance(provider, MimoProvider)
    assert provider.id == "mimo-sgp"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
rtk uv run pytest tests/test_provider_config.py -v
```

Expected: FAIL because `MimoProvider` does not accept `config`, and `ASRRequest.model` still defaults to a string.

- [ ] **Step 3: Update models and provider protocol**

Modify `ASRRequest` in `models.py`:

```python
class ASRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = "mimo"
    model: str | None = None
    audio_path: Path
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp3"]
    raw_byte_size: int = Field(ge=0)
    base64_size: int = Field(ge=0)
    language: Literal["auto", "zh", "en"] = "auto"
```

Keep the existing `TTSRequest.strip_text_fields` validator unchanged. Do not add a strip validator to `ASRRequest`; ASR has no free-text prompt fields and its `model` must preserve explicit provider IDs.

Also explicitly keep `TTSRequest.text: str | None = None`. Design mode with `optimize_text_preview=True` depends on `text=None` to omit the assistant message.

Keep the compatibility `ProviderConfig` class in `models.py` independent from the new config modules. `models.py` must not import `voice_toolbox.config`, `voice_toolbox.config_models`, or `voice_toolbox.defaults`; otherwise `config_models.py -> models.py -> config.py` would recreate a circular import.

Modify `VoiceProvider.synthesize()` in `providers/base.py`:

```python
from collections.abc import Mapping

def synthesize(
    self,
    request: TTSRequest,
    *,
    artifact_metadata: Mapping[str, object] | None = None,
) -> AudioArtifact:
    raise NotImplementedError
```

- [ ] **Step 4: Refactor MiMo provider**

Modify `providers/mimo.py`:

- Import defaults from `voice_toolbox.defaults`.
- Re-export `MIMO_MODELS` and `MIMO_VOICES` from `voice_toolbox.defaults` for compatibility. They are now `list[ModelInfo]` and `list[VoiceInfo]`.
- Constructor accepts `config: ConfiguredProvider | None = None` and `base_url: str | None = None`.
- If `config is None`, call `make_default_mimo_provider_config(base_url=base_url or DEFAULT_MIMO_BASE_URL)`.
- Store `self._config`, `self._models_by_id`, and `self._default_models`.
- Convert `_build_tts_body`, `_build_asr_body`, `_resolve_tts_model`, `_validate_model_id` into instance methods.
- Delete module-level `_build_tts_body`, `_build_asr_body`, `_resolve_tts_model`, `_validate_model_id`, `_TTS_MODEL_BY_MODE`, and `_MODEL_IDS`. Do not create wrapper functions by instantiating a provider; body building is provider-instance behavior.
- Update `tests/test_mimo_provider.py` imports and calls:
  - Remove `_build_tts_body` and `_build_asr_body` imports.
  - In body-shape tests, construct `provider = MimoProvider(api_key="secret", artifact_root=tmp_path, client=FakeClient(_tts_completion()))` and call `provider._build_tts_body(request)`.
  - In ASR body-shape tests, call `provider._build_asr_body(request, data_url)`.
  - Where tests previously expected module-level validation, assert against provider instance methods.

The key method signatures:

```python
def __init__(
    self,
    *,
    config: ConfiguredProvider | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_root: Path | str | None = None,
    env_path: Path | str | None = None,
    client: Any | None = None,
    client_factory: Callable[..., Any] = OpenAI,
    sleep_func: Callable[[float], None] = time.sleep,
) -> None:
    resolved_config = config or make_default_mimo_provider_config()
    if base_url is not None:
        resolved_config = resolved_config.model_copy(update={"base_url": base_url})
    self._config = resolved_config
    self.id = resolved_config.id
    self.name = resolved_config.name

def _build_tts_body(self, request: TTSRequest) -> dict[str, Any]:
    self._validate_tts_request(request)
    model = self._resolve_tts_model(request)
    # existing message/audio body construction follows

def _build_asr_body(self, request: ASRRequest, audio_data_url: str) -> dict[str, Any]:
    model = self._resolve_asr_model(request)
    self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
    # existing input_audio body construction follows

def synthesize(
    self,
    request: TTSRequest,
    *,
    artifact_metadata: Mapping[str, object] | None = None,
) -> AudioArtifact:
    body = self._build_tts_body(request)
    metadata = {**_tts_metadata(request, body), **dict(artifact_metadata or {})}
    # write audio with metadata
```

`id` and `name` should be instance attributes set in `__init__`:

```python
self.id = self._config.id
self.name = self._config.name
```

This preserves simple test doubles such as `RecordingMimoProvider(FakeProvider)` that expose class attributes.

- [ ] **Step 5: Add provider registry factory**

Create `packages/voice_toolbox/src/voice_toolbox/providers/factory.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config import AppConfig, load_env_values
from voice_toolbox.providers.mimo import MimoProvider
from voice_toolbox.providers.registry import ProviderRegistry


def build_provider_registry(
    config: AppConfig,
    *,
    artifact_root: Path | str,
    env_values: Mapping[str, str] | None = None,
) -> ProviderRegistry:
    env = dict(env_values or load_env_values())
    root = Path(artifact_root)
    providers = []
    for provider_config in config.providers:
        if provider_config.type == "mimo":
            api_key = env.get(provider_config.api_key_env)
            providers.append(
                MimoProvider(
                    config=provider_config,
                    api_key=api_key,
                    artifact_store=ArtifactStore(root),
                )
            )
    return ProviderRegistry(providers)
```

- [ ] **Step 6: Update fake provider and test doubles**

Modify `providers/fake.py` so `synthesize()` accepts `artifact_metadata` and merges it into written artifact metadata:

```python
def synthesize(
    self,
    request: TTSRequest,
    *,
    artifact_metadata: Mapping[str, object] | None = None,
) -> AudioArtifact:
    metadata = {
        "operation": "tts",
        "provider_id": self.id,
        "model": request.model or "fake-tts",
        **dict(artifact_metadata or {}),
    }
    return self._artifact_store.write_audio(
        operation_id=self._next_operation_id("tts"),
        provider_id=self.id,
        operation="tts",
        audio=b"FAKE AUDIO",
        metadata=metadata,
    )
```

Update `tests/test_api.py` `RecordingMimoProvider.synthesize()`:

```python
from collections.abc import Mapping

def synthesize(
    self,
    request: TTSRequest,
    *,
    artifact_metadata: Mapping[str, object] | None = None,
):
    self.tts_requests.append(request)
    if request.clone_sample_path is not None:
        self.clone_sample_paths.append(request.clone_sample_path)
        self.clone_sample_exists_during_call.append(request.clone_sample_path.exists())
    return super().synthesize(request, artifact_metadata=artifact_metadata)
```

Update `tests/test_cli.py` `RecordingProvider.synthesize()`:

```python
from collections.abc import Mapping

def synthesize(
    self,
    request: TTSRequest,
    *,
    artifact_metadata: Mapping[str, object] | None = None,
) -> AudioArtifact:
    self.tts_requests.append(request)
    metadata = {"tts_mode": request.mode.value, **dict(artifact_metadata or {})}
    path = self.artifact_root / f"audio-{len(self.tts_requests)}.wav"
    path.write_bytes(b"WAV")
    return AudioArtifact(
        id=f"audio-{len(self.tts_requests)}",
        provider_id=self.id,
        operation="tts",
        path=path,
        mime_type="audio/wav",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata=metadata,
    )
```

Update `tests/test_api.py` `RecordingMimoProvider.list_voices()` because `MIMO_VOICES` is now `list[VoiceInfo]`:

```python
def list_voices(self) -> list[VoiceInfo]:
    return [voice.model_copy() for voice in MIMO_VOICES]
```

- [ ] **Step 7: Run provider tests**

```bash
rtk uv run pytest tests/test_provider_config.py tests/test_mimo_provider.py tests/test_provider_registry.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/providers tests/test_provider_config.py
rtk uv run ty check packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/models.py packages/voice_toolbox/src/voice_toolbox/providers tests/test_provider_config.py tests/test_mimo_provider.py tests/test_api.py tests/test_cli.py
rtk git commit -m "feat: make mimo provider configurable"
```

---

### Task 3: API Config Wiring and Provider Summaries

**Files:**
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add API tests**

Append to `tests/test_api.py` and update the existing `_client()` helper:

```python
from voice_toolbox.config import (
    APIConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    LoggingConfig,
    ProviderDefaultModels,
)
from voice_toolbox.models import ModelInfo, VoiceInfo


def _test_config(*, host: str = "127.0.0.1") -> AppConfig:
    return AppConfig(
        api=APIConfig(host=host, port=8000),
        logging=LoggingConfig(console=ConsoleLoggingConfig(enabled=False)),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
                default_voice="mimo_default",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
                voices=[VoiceInfo(id="mimo_default", name="MiMo-默认")],
            )
        ],
    )


def _client(
    tmp_path: Path, *, has_api_key: bool = True
) -> tuple[TestClient, RecordingMimoProvider]:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key" if has_api_key else ""},
    )
    return TestClient(app), provider


def test_create_app_accepts_config_and_provider_summary_masks_key(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    mimo = response.json()["providers"][0]
    assert mimo["api_key_env"] == "MIMO_API_KEY"
    assert mimo["api_key_preview"] == "tp-...abcd"
    assert mimo["config_path_preview"] == "built-in default"
    assert mimo["base_url"] == "https://api.xiaomimimo.com/v1"
    assert mimo["default_voice"] == "mimo_default"
    assert mimo["default_models"]["tts_builtin"] == "fake-tts"


def test_provider_summary_non_local_host_hides_key_preview(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(host="0.0.0.0"),
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    assert response.json()["providers"][0]["api_key_preview"] == "configured"


def test_missing_key_blocks_only_operation_not_listing(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, has_api_key=False)

    listed = client.get("/v1/providers")
    blocked = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello", "voice_id": "Mia"},
    )

    assert listed.status_code == 200
    assert listed.json()["providers"][0]["has_api_key"] is False
    assert blocked.status_code == 503
```

Replace the old `_client()` helper; do not keep `has_mimo_api_key_func` in tests or production API construction.

- [ ] **Step 2: Run tests to verify failure**

```bash
rtk uv run pytest tests/test_api.py::test_create_app_accepts_config_and_provider_summary_masks_key -v
```

Expected: FAIL because `create_app` lacks `config` and `env_values`.

- [ ] **Step 3: Implement API wiring**

Modify `create_app()` signature:

```python
def create_app(
    *,
    registry: ProviderRegistry | None = None,
    artifact_root: Path | str | None = None,
    config: AppConfig | None = None,
    env_path: Path | str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> FastAPI:
```

Implementation rules:

- If `config is None`, call `load_app_config(env_path=env_path, env_values=dict(env_values) if env_values else None)`.
- If `env_values is None`, call `load_env_values(env_path)` even when `config` was supplied, so key status still works for tests and production.
- Store `config` and the resolved env dict in `app.state`.
- If `registry is None`, call `build_provider_registry(config, artifact_root=root)`.
- `_provider_summary()` reads the matching `ConfiguredProvider` by ID.
- `has_api_key` checks `provider_config.api_key_env` in merged env values.
- `api_key_preview` uses `mask_api_key_preview(value, trusted_local=config.api.host in {"127.0.0.1", "localhost"})`.
- `config_path_preview` uses `preview_config_path(config.config_path)`.
- `base_url`, `api_key_env`, `type`, `default_voice`, and `default_models` come from `ConfiguredProvider`.
- If a registry-injected test provider has no matching `ConfiguredProvider`, return this exact fallback summary and do not raise `KeyError`:

```python
{
    "id": provider.id,
    "name": provider.name,
    "type": "test",
    "base_url": None,
    "api_key_env": None,
    "has_api_key": True,
    "api_key_preview": None,
    "config_path_preview": preview_config_path(config.config_path),
    "default_voice": None,
    "default_models": {},
    "capabilities": sorted(provider.capabilities()),
    "models": [model.model_dump(mode="json") for model in provider.list_models()],
}
```
- Remove module-level `app = create_app()` from `main.py`; server startup uses `voice_toolbox_api.server` and tests call `create_app()` explicitly. This avoids configuring logging at import time.

- [ ] **Step 4: Remove old key-check seam**

Remove `has_mimo_api_key_func` from `create_app()`. Existing tests use `_client(tmp_path, has_api_key=False)`, but the helper now translates that to:

```python
env_values={"MIMO_API_KEY": "test-key" if has_api_key else ""}
```

Provider readiness checks must use `app.state.config.providers[*].api_key_env`, never hard-code `MIMO_API_KEY` outside fallback config construction.

Use this replacement implementation:

```python
def _ensure_provider_configured_for_operation(request: Request, provider_id: str) -> None:
    config_provider = _configured_provider_for_id(request.app.state.config, provider_id)
    if config_provider is None:
        return
    value = request.app.state.env_values.get(config_provider.api_key_env)
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"{config_provider.api_key_env} is required for provider {provider_id}",
        )
```

- [ ] **Step 5: Run API tests**

```bash
rtk uv run pytest tests/test_api.py tests/test_config.py -v
rtk uv run ruff check apps/api/src tests/test_api.py
rtk uv run ty check apps/api/src packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add apps/api/src/voice_toolbox_api/main.py tests/test_api.py tests/test_config.py
rtk git commit -m "feat: wire api to app config"
```

- [ ] **Step 7: Large adversarial review checkpoint**

Review Tasks 1-3 before proceeding:

```bash
rtk git diff HEAD~3..HEAD --stat
rtk uv run pytest tests/test_config.py tests/test_provider_config.py tests/test_api.py -v
rtk uv run ruff check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Expected: all PASS. Inspect specifically:

- No full API key appears in API responses.
- `api_key_preview` obeys localhost gate.
- Existing tests can still use fake providers and `MimoProvider(base_url="https://example.test/v1", client=fake_client)`.
- ASR model omission has a configured-provider path.

Stop and report review findings before Task 4.

---

### Task 4: Loguru Logging and Redaction

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/logging_config.py`
- Create: `apps/api/src/voice_toolbox_api/server.py`
- Create: `tests/test_logging_config.py`
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `Makefile`

- [ ] **Step 1: Add logging tests**

Create `tests/test_logging_config.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

from loguru import logger

from voice_toolbox.config import ConsoleLoggingConfig, FileLoggingConfig, LoggingConfig
from voice_toolbox.logging_config import configure_logging, sanitize_log_metadata


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "voice-toolbox.log"
    config = LoggingConfig(
        console=ConsoleLoggingConfig(enabled=False),
        file=FileLoggingConfig(enabled=True, path=str(path)),
    )

    configure_logging(config, config_path=None)
    logging.getLogger("uvicorn.access").info("first")
    configure_logging(config, config_path=None)
    logging.getLogger("uvicorn.access").info("second")

    text = path.read_text(encoding="utf-8")
    assert text.count("first") == 1
    assert text.count("second") == 1
    assert logging.getLogger("uvicorn.access").handlers == []
    assert logging.getLogger("uvicorn.access").propagate is True


def test_sanitize_log_metadata_allowlist() -> None:
    sanitized = sanitize_log_metadata(
        {
            "operation": "tts",
            "model": "mimo-v2.5-tts",
            "source_text": "secret raw text",
            "api_key": "tp-secret",
            "data_url": "data:audio/wav;base64,abc",
            "source_text_length": 15,
        }
    )

    assert sanitized == {
        "operation": "tts",
        "model": "mimo-v2.5-tts",
        "source_text_length": 15,
    }


def test_log_file_never_contains_raw_request_values(tmp_path: Path) -> None:
    path = tmp_path / "voice.log"
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path=str(path)),
        ),
        config_path=None,
    )

    logger.bind(
        **sanitize_log_metadata(
            {
                "operation": "tts",
                "source_text": "raw secret text",
                "style_instruction": "raw style",
                "voice_description": "raw voice",
                "transcript": "raw transcript",
                "payload": "data:audio/wav;base64,abcdef",
                "api_key": "tp-secret",
                "source_text_length": 15,
            }
        )
    ).info("request completed")

    text = path.read_text(encoding="utf-8")
    assert "raw secret text" not in text
    assert "raw style" not in text
    assert "raw voice" not in text
    assert "raw transcript" not in text
    assert "base64" not in text
    assert "tp-secret" not in text
    assert "request completed" in text


def test_relative_file_path_resolves_against_config_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "voice_toolbox.toml"
    config_path.parent.mkdir()
    configure_logging(
        LoggingConfig(
            console=ConsoleLoggingConfig(enabled=False),
            file=FileLoggingConfig(enabled=True, path="logs/voice.log"),
        ),
        config_path=config_path,
    )

    logger.info("relative path works")

    assert (tmp_path / "configs" / "logs" / "voice.log").is_file()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
rtk uv run pytest tests/test_logging_config.py -v
```

Expected: FAIL because `voice_toolbox.logging_config` does not exist.

- [ ] **Step 3: Implement logging config**

Create `logging_config.py` with:

- `HUMAN_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"`
- `LOG_METADATA_KEYS` containing the spec allowlist.
- `sanitize_log_metadata(metadata)`.
- `InterceptHandler(logging.Handler)`.
- `configure_logging(config: LoggingConfig, *, config_path: Path | None)`.

Implementation details:

```python
def configure_logging(config: LoggingConfig, *, config_path: Path | None) -> None:
    logger.remove()
    if config.console.enabled:
        logger.add(
            sys.stderr,
            level=config.console.level,
            format=HUMAN_FORMAT,
            colorize=config.console.colorize,
        )
    if config.file.enabled:
        path = Path(config.file.path)
        if not path.is_absolute() and config_path is not None:
            path = config_path.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            path,
            level=config.file.level,
            format=HUMAN_FORMAT,
            rotation=config.file.rotation,
            retention=config.file.retention,
            compression=config.file.compression,
            enqueue=config.file.enqueue,
        )
    root_logger = logging.getLogger()
    root_logger.handlers = [InterceptHandler()]
    root_logger.setLevel(logging.NOTSET)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "starlette"):
        target = logging.getLogger(name)
        target.handlers = []
        target.propagate = True
```

- [ ] **Step 4: Wire API startup**

In `create_app()`, after loading config and before returning app, call:

```python
configure_logging(config.logging, config_path=config.config_path)
```

Make sure tests pass `LoggingConfig(console=ConsoleLoggingConfig(enabled=False))` to avoid noisy console logs. `config.py` warnings remain standard `logging` calls and are tested with `caplog` before any API app configures Loguru.

- [ ] **Step 5: Add logging-aware server entrypoint and Makefile command**

Create `apps/api/src/voice_toolbox_api/server.py`:

```python
from __future__ import annotations

import uvicorn

from voice_toolbox.config import load_app_config
from voice_toolbox_api.main import create_app


def main() -> None:
    config = load_app_config()
    app = create_app(config=config)
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
```

`server.py` must not read `VOICE_TOOLBOX_API_HOST`, `VOICE_TOOLBOX_API_PORT`, `API_HOST`, or `API_PORT` directly. `load_app_config()` has already applied the env/TOML precedence rules, and TOML must win when active. `server.py` must not call `configure_logging()` directly; `create_app(config=config)` is the single logging configuration point.

Update Makefile:

```make
backend-server:
	$(PYTHON_ENV) python -m voice_toolbox_api.server
```

- [ ] **Step 6: Run logging checks**

```bash
rtk uv run pytest tests/test_logging_config.py tests/test_api.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/logging_config.py apps/api/src/voice_toolbox_api/main.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/logging_config.py apps/api/src/voice_toolbox_api/main.py tests/test_logging_config.py Makefile
rtk git commit -m "feat: add loguru logging pipeline"
```

---

### Task 5: Normalizers and TTS Preparation Pipeline

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/normalizers/__init__.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/normalizers/base.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/normalizers/markdown.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/normalizers/registry.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/pipeline.py`
- Create: `tests/test_normalizers.py`
- Create: `tests/test_pipeline.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/artifacts.py`

- [ ] **Step 1: Add normalizer tests**

Create `tests/test_normalizers.py`:

```python
from __future__ import annotations

import pytest

from voice_toolbox.normalizers.registry import NormalizerRegistry


def test_markdown_basic_cleans_markup_and_preserves_tags() -> None:
    result = NormalizerRegistry.default().normalize(
        "# Title\n\n- Hello **world**\n- (唱歌)啦啦啦[breath]\n[site](https://example.com)",
        input_format="markdown",
        normalizer_id=None,
    )

    assert result.text == "Title\n\nHello world\n(唱歌)啦啦啦[breath]\nsite"
    assert result.normalizer_id == "markdown_basic"
    assert result.changed is True


def test_auto_keeps_math_and_script_literals() -> None:
    registry = NormalizerRegistry.default()
    for text in ["5 * 4 = 20", "5 * 4 * 3 = 60 * 2", "会议 #1 重点", "a < b 且 c > d"]:
        result = registry.normalize(text, input_format="auto", normalizer_id=None)
        assert result.text == text
        assert result.normalizer_id == "plain_passthrough"


def test_auto_uses_markdown_for_structural_signals() -> None:
    result = NormalizerRegistry.default().normalize(
        "# Title\n\n- one\n- two",
        input_format="auto",
        normalizer_id=None,
    )

    assert result.normalizer_id == "markdown_basic"
    assert result.text == "Title\n\none\ntwo"


def test_html_tag_stripping_does_not_strip_comparisons() -> None:
    result = NormalizerRegistry.default().normalize(
        "<em>Hello</em><br><img src=\"x\"> a < b 且 c > d",
        input_format="markdown",
        normalizer_id=None,
    )

    assert result.text == "Hello a < b 且 c > d"


def test_unknown_normalizer_fails() -> None:
    with pytest.raises(ValueError, match="unknown normalizer"):
        NormalizerRegistry.default().normalize("hello", input_format="plain", normalizer_id="missing")
```

- [ ] **Step 2: Add pipeline tests**

Create `tests/test_pipeline.py`:

```python
from __future__ import annotations

from voice_toolbox.models import TTSMode
from voice_toolbox.pipeline import prepare_tts_request


def test_prepare_tts_request_normalizes_text_and_metadata() -> None:
    prepared = prepare_tts_request(
        "# Title\nHello **world**",
        "markdown",
        {"mode": TTSMode.BUILTIN, "voice_id": "Mia"},
    )

    assert prepared.request.text == "Title\nHello world"
    assert prepared.artifact_metadata == {
        "normalizer_id": "markdown_basic",
        "normalization_input_format": "markdown",
        "normalization_output_format": "plain",
        "normalization_changed": True,
        "normalization_input_length": 22,
        "normalization_output_length": 17,
        "normalization_ignored_options": [],
    }


def test_prepare_tts_request_skips_none_text_for_optimized_design() -> None:
    prepared = prepare_tts_request(
        None,
        "plain",
        {
            "mode": TTSMode.DESIGN,
            "voice_description": "warm alto",
            "optimize_text_preview": True,
        },
    )

    assert prepared.request.text is None
    assert prepared.artifact_metadata == {}
```

- [ ] **Step 3: Run tests to verify failure**

```bash
rtk uv run pytest tests/test_normalizers.py tests/test_pipeline.py -v
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement normalizer modules**

Create:

- `normalizers/base.py` with `ContentNormalizer`, `NormalizationRequest`, and `NormalizedContent`.
- `normalizers/markdown.py` with `PlainPassthroughNormalizer`, `MarkdownBasicNormalizer`, and `AutoTextNormalizer`.
- `normalizers/registry.py` with `NormalizerRegistry.default()`.

`normalizers/base.py` contains:

```python
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


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


class ContentNormalizer(Protocol):
    normalizer_id: str
    input_formats: set[str]
    output_format: str

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        raise NotImplementedError
```

`normalizers/registry.py` contains:

```python
from __future__ import annotations

from typing import Any

from voice_toolbox.normalizers.base import ContentNormalizer, NormalizedContent
from voice_toolbox.normalizers.markdown import (
    AutoTextNormalizer,
    MarkdownBasicNormalizer,
    PlainPassthroughNormalizer,
)


class NormalizerRegistry:
    def __init__(self, normalizers: list[ContentNormalizer]) -> None:
        self._normalizers = {normalizer.normalizer_id: normalizer for normalizer in normalizers}

    @classmethod
    def default(cls) -> NormalizerRegistry:
        plain = PlainPassthroughNormalizer()
        markdown = MarkdownBasicNormalizer()
        return cls([plain, markdown, AutoTextNormalizer(plain=plain, markdown=markdown)])

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        normalizer_id: str | None,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        if not content.strip():
            raise ValueError("content is required")
        selected_id = normalizer_id or self._default_normalizer_id(input_format)
        normalizer = self._normalizers.get(selected_id)
        if normalizer is None:
            raise ValueError(f"unknown normalizer: {selected_id}")
        if input_format not in normalizer.input_formats:
            raise ValueError(f"normalizer {selected_id} does not support {input_format}")
        result = normalizer.normalize(content, input_format=input_format, options=options)
        if not result.text.strip():
            raise ValueError("normalized text is empty")
        return result

    def _default_normalizer_id(self, input_format: str) -> str:
        if input_format == "plain":
            return "plain_passthrough"
        if input_format == "markdown":
            return "markdown_basic"
        if input_format == "auto":
            return "auto_text"
        raise ValueError(f"unsupported input format: {input_format}")
```

Core rules for `normalizers/markdown.py`:

- `normalizer_id=None` selects by input format.
- `auto` requires at least two structural signals.
- Emphasis is cleaned in markdown mode but is not an auto signal.
- HTML stripping uses `</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*)?\s*/?>`.
- Unknown options are returned as sorted `ignored_options`.
- `PlainPassthroughNormalizer.normalize()` returns the content unchanged with `normalizer_id="plain_passthrough"`.
- `AutoTextNormalizer` receives `plain` and `markdown` normalizers in its constructor. It delegates to markdown only when two structural signals are present; otherwise it delegates to plain.

Use these exact signal helpers in `markdown.py`:

```python
import re

MARKDOWN_SIGNAL_PATTERNS = {
    "heading": re.compile(r"^#{1,6}\s+\S", re.MULTILINE),
    "fence": re.compile(r"^```", re.MULTILINE),
    "link": re.compile(r"\[.+?\]\(.+?\)"),
    "image": re.compile(r"!\[.*?\]\(.+?\)"),
    "unordered_list": re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE),
    "ordered_list": re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE),
    "table_separator": re.compile(
        r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
        re.MULTILINE,
    ),
}
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*)?\s*/?>")


def markdown_signal_count(content: str) -> int:
    return sum(1 for pattern in MARKDOWN_SIGNAL_PATTERNS.values() if pattern.search(content))
```

`MarkdownBasicNormalizer.normalize()` should apply cleanup in this order:

1. Remove code fences while preserving contents when `preserve_code_blocks` is true.
2. Convert links to link text and images to alt text.
3. Strip `HTML_TAG_PATTERN`.
4. Remove heading, list, and blockquote markers.
5. Remove emphasis markers `**`, `*`, `__`, `_` without using them as auto signals.
6. Drop table separator lines.
7. Trim trailing spaces on each line and collapse three or more blank lines to two.

- [ ] **Step 5: Implement pipeline**

Create `pipeline.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from voice_toolbox.models import TTSRequest
from voice_toolbox.normalizers.base import NormalizedContent
from voice_toolbox.normalizers.registry import NormalizerRegistry


class PreparedTTSRequest(BaseModel):
    request: TTSRequest
    normalized: NormalizedContent | None = None
    artifact_metadata: dict[str, object] = Field(default_factory=dict)


def prepare_tts_request(
    raw_text: str | None,
    text_format: Literal["plain", "markdown", "auto"],
    fields: dict[str, object],
    *,
    normalizers: NormalizerRegistry | None = None,
) -> PreparedTTSRequest:
    if raw_text is None:
        return PreparedTTSRequest(request=TTSRequest(text=None, **fields))
    registry = normalizers or NormalizerRegistry.default()
    normalized = registry.normalize(raw_text, input_format=text_format, normalizer_id=None)
    request = TTSRequest(text=normalized.text, **fields)
    return PreparedTTSRequest(
        request=request,
        normalized=normalized,
        artifact_metadata=_normalization_metadata(normalized),
    )
```

Implement `_normalization_metadata()` with the exact `normalization_*` fields from the spec.

- [ ] **Step 6: Extend artifact redaction allowlist**

Modify `artifacts.py` so `redact_metadata()` keeps:

```python
"normalizer_id",
"normalization_input_format",
"normalization_output_format",
"normalization_changed",
"normalization_input_length",
"normalization_output_length",
"normalization_ignored_options",
```

and still strips raw text/data URL/base64 fields.

- [ ] **Step 7: Run tests**

```bash
rtk uv run pytest tests/test_normalizers.py tests/test_pipeline.py tests/test_artifacts.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/normalizers packages/voice_toolbox/src/voice_toolbox/pipeline.py
rtk uv run ty check packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/normalizers packages/voice_toolbox/src/voice_toolbox/pipeline.py packages/voice_toolbox/src/voice_toolbox/artifacts.py tests/test_normalizers.py tests/test_pipeline.py tests/test_artifacts.py
rtk git commit -m "feat: add text normalization pipeline"
```

---

### Task 6: API and CLI Normalization Integration

**Files:**
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/cli.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add API integration tests**

Append to `tests/test_api.py`:

```python
def test_normalize_text_endpoint(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.post(
        "/v1/normalize/text",
        json={"content": "# Title\nHello **world**", "input_format": "markdown"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Title\nHello world"
    assert response.json()["normalizer_id"] == "markdown_basic"


def test_normalize_text_endpoint_rejects_empty_and_too_large(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    empty = client.post("/v1/normalize/text", json={"content": " ", "input_format": "plain"})
    large = client.post("/v1/normalize/text", json={"content": "x" * 200001, "input_format": "plain"})

    assert empty.status_code == 422
    assert empty.json()["detail"] == "content is required"
    assert large.status_code == 413
    assert large.json()["detail"] == "content exceeds 200000 characters"


def test_tts_endpoint_normalizes_markdown_and_writes_metadata(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "# Title\nHello **world**",
            "text_format": "markdown",
            "voice_id": "Mia",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text == "Title\nHello world"
    assert response.json()["artifact"]["metadata"]["normalizer_id"] == "markdown_basic"
    assert "Hello **world**" not in str(response.json())


def test_clone_endpoint_normalizes_markdown(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/clone",
        data={
            "provider_id": "mimo",
            "text": "# Clone",
            "text_format": "markdown",
            "consent_confirmed": "true",
        },
        files={"sample": ("sample.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text == "Clone"
    assert response.json()["artifact"]["metadata"]["normalizer_id"] == "markdown_basic"


def test_design_optimize_preview_empty_text_skips_normalization(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "warm narrator",
            "text": "",
            "text_format": "markdown",
            "optimize_text_preview": "true",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text is None


def test_asr_model_omitted_passes_none_to_provider(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        data={"language": "auto", "provider_id": "mimo"},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[-1].model is None
```

- [ ] **Step 2: Add CLI tests**

Append to `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from voice_toolbox.cli import app


def test_cli_tts_accepts_text_format_markdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["tts", "synthesize", "--text", "# Title", "--text-format", "markdown", "--voice", "Mia"],
    )

    assert result.exit_code == 0
    assert "audio" in result.output.lower()


def test_cli_asr_model_can_be_omitted(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    runner = CliRunner()

    result = runner.invoke(app, ["asr", "transcribe", "--file", str(audio)])

    assert result.exit_code == 0
```

If existing CLI tests already monkeypatch providers, adapt these tests to that fixture rather than performing real provider calls.

- [ ] **Step 3: Run tests to verify failure**

```bash
rtk uv run pytest tests/test_api.py::test_normalize_text_endpoint tests/test_api.py::test_tts_endpoint_normalizes_markdown_and_writes_metadata -v
```

Expected: FAIL because `/v1/normalize/text` and `text_format` do not exist.

- [ ] **Step 4: Implement `/v1/normalize/text`**

In `main.py`, add Pydantic request model or import from normalizers:

```python
@app.post("/v1/normalize/text")
def normalize_text(request: NormalizationRequest) -> dict[str, Any]:
    if not request.content.strip():
        raise HTTPException(status_code=422, detail="content is required")
    if len(request.content) > 200_000:
        raise HTTPException(status_code=413, detail="content exceeds 200000 characters")
    try:
        result = NormalizerRegistry.default().normalize(
            request.content,
            input_format=request.input_format,
            normalizer_id=request.normalizer_id,
            options=request.options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result.text.strip():
        raise HTTPException(status_code=422, detail="normalized text is empty")
    return result.model_dump(mode="json")
```

- [ ] **Step 5: Integrate TTS API with pipeline**

For every TTS route:

- Add `text_format: Annotated[Literal["plain", "markdown", "auto"], Form()] = "plain"`.
- Call `prepare_tts_request(raw_text, text_format, fields)`.
- Pass `prepared.request` to provider.
- Pass `prepared.artifact_metadata` to `provider.synthesize()`.
- Catch `ValueError` from `prepare_tts_request()` and return HTTP 422 with `detail=str(exc)`.
- Update all four `_run_tts()` call sites:
  - `/v1/tts/synthesize` built-in/design branch
  - `/v1/tts/builtin`
  - `/v1/tts/design`
  - `_run_clone_upload()` for `/v1/tts/clone` and synthesize clone dispatch
- For design mode, compute `raw_text = text or None` when `optimize_text_preview is True`; this skips normalization for empty optimized previews.
- For clone mode, pass uploaded sample fields through `fields` and still normalize `text` before constructing `TTSRequest`.

Change `_run_tts()`:

```python
def _run_tts(
    provider_registry: ProviderRegistry,
    provider_id: str,
    prepared: PreparedTTSRequest,
) -> dict[str, Any]:
    provider = _ensure_tts_provider(provider_registry, provider_id, prepared.request)
    started_at = datetime.now(UTC)
    try:
        artifact = provider.synthesize(
            prepared.request,
            artifact_metadata=prepared.artifact_metadata,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finished_at = datetime.now(UTC)
    return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)
```

Helper pattern for route code:

```python
def _prepare_tts_or_422(
    *,
    raw_text: str | None,
    text_format: Literal["plain", "markdown", "auto"],
    fields: dict[str, object],
) -> PreparedTTSRequest:
    try:
        return prepare_tts_request(raw_text, text_format, fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Update `_run_clone_upload()` to return `PreparedTTSRequest` through the same `_run_tts()` path:

```python
def _run_clone_upload(
    *,
    http_request: Request,
    sample: UploadFile,
    provider_id: str,
    text: str,
    text_format: Literal["plain", "markdown", "auto"],
    consent_confirmed: bool,
    style_instruction: str | None,
    model: str | None,
) -> dict[str, Any]:
    contents = _read_upload(sample)
    mime_type = _normalize_mime_type(sample.content_type)
    suffix = _suffix_for_upload(sample.filename)
    _validate_upload_signature(contents, mime_type, suffix)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / _safe_upload_filename(sample.filename, suffix)
        temp_path.write_bytes(contents)
        prepared = _prepare_tts_or_422(
            raw_text=text,
            text_format=text_format,
            fields={
                "provider_id": provider_id,
                "mode": TTSMode.CLONE,
                "model": model,
                "style_instruction": style_instruction,
                "clone_sample_path": temp_path,
                "clone_mime_type": mime_type,
                "clone_raw_byte_size": len(contents),
                "clone_base64_size": _base64_size(contents),
                "consent_confirmed": consent_confirmed,
            },
        )
        return _run_tts(_registry_from_request(http_request), provider_id, prepared)
```

ASR route signature changes to:

```python
model: Annotated[str | None, Form()] = None
```

- [ ] **Step 6: Integrate CLI with config and pipeline**

In `cli.py`:

- Add `TextFormatOption = Annotated[Literal["plain", "markdown", "auto"], typer.Option("--text-format")]`.
- TTS commands pass raw text and text format to `prepare_tts_request()`.
- ASR `model` option becomes `str | None = None`.
- `build_provider_registry()` loads `AppConfig` and calls config-based registry builder.
- `--provider` options default to `None`, not `"mimo"`. Resolve inside each command with:

```python
def _resolve_provider_id(registry: ProviderRegistry, requested: str | None) -> str:
    if requested:
        return requested
    providers = registry.list_providers()
    if any(provider.id == "mimo" for provider in providers):
        return "mimo"
    if providers:
        return providers[0].id
    _fail("no providers configured")
```

- [ ] **Step 7: Run API/CLI tests**

```bash
rtk uv run pytest tests/test_api.py tests/test_cli.py tests/test_pipeline.py -v
rtk uv run ruff check apps/api/src packages/voice_toolbox/src tests/test_api.py tests/test_cli.py
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add apps/api/src/voice_toolbox_api/main.py packages/voice_toolbox/src/voice_toolbox/cli.py tests/test_api.py tests/test_cli.py
rtk git commit -m "feat: normalize tts inputs in api and cli"
```

- [ ] **Step 9: Large adversarial review checkpoint**

Review Tasks 4-6 before proceeding:

```bash
rtk git diff HEAD~3..HEAD --stat
rtk uv run pytest tests/test_logging_config.py tests/test_normalizers.py tests/test_pipeline.py tests/test_api.py tests/test_cli.py -v
rtk uv run ruff check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Inspect specifically:

- Log files do not contain raw text, style prompt, transcript, data URL, base64, or API keys.
- TTS sidecars contain `normalization_*` metadata.
- Design with `optimize_text_preview=true` and empty text sends no assistant text.
- ASR request model omission reaches provider as `None`.

Stop and report review findings before Task 7.

---

### Task 7: Frontend Provider Models, Text Format, and Fullscreen Editor

**Files:**
- Modify: `apps/web/src/api.ts`
- Create: `apps/web/src/hooks/useProviderCatalog.ts`
- Create: `apps/web/src/lib/providerSelection.ts`
- Create: `apps/web/src/lib/providerSelection.test.ts`
- Create: `apps/web/src/components/FullscreenTextEditor.tsx`
- Create: `apps/web/src/components/AdvancedSettings.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/package.json`

- [ ] **Step 1: Update frontend API types**

Modify only these parts of `apps/web/package.json`; do not rewrite or reorder the full `scripts` object and do not change existing `build`, `lint`, `format`, `format:check`, `dev`, or `preview` scripts:

```json
{
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "<resolved by bun add -d vitest>"
  }
}
```

Install with:

```bash
rtk bun add --cwd apps/web -d vitest
```

Commit the lock file that actually exists after install. This repository currently uses `apps/web/bun.lock`, not `apps/web/bun.lockb`.

Modify `api.ts`:

```ts
export type TextFormat = "plain" | "markdown" | "auto";

export type Provider = {
  id: string;
  name: string;
  type?: string;
  base_url?: string;
  api_key_env?: string;
  api_key_preview?: string | null;
  config_path_preview?: string;
  default_voice?: string | null;
  default_models?: Partial<Record<"tts_builtin" | "tts_design" | "tts_clone" | "asr", string | null>>;
  capabilities: Capability[];
  models: ProviderModel[];
  has_api_key?: boolean;
};

export type NormalizeRequest = {
  content: string;
  input_format: TextFormat;
  normalizer_id?: string | null;
  options?: Record<string, unknown>;
};

export type NormalizeResponse = {
  text: string;
  input_format: TextFormat;
  output_format: "plain";
  normalizer_id: string;
  changed: boolean;
  metadata: Record<string, unknown>;
};
```

Add:

```ts
export function normalizeText(request: NormalizeRequest): Promise<NormalizeResponse> {
  return requestJsonWithBody("/v1/normalize/text", request);
}
```

Add `requestJsonWithBody()`:

```ts
async function requestJsonWithBody<TResponse, TBody extends Record<string, unknown>>(
  url: string,
  body: TBody,
): Promise<TResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<TResponse>(response);
}
```

Append `text_format` to TTS FormData builders.

- [ ] **Step 2: Add selection helpers**

Create `apps/web/src/lib/providerSelection.ts`:

```ts
import { Capability, Provider, Voice } from "../api";

export function selectModelForCapability(
  provider: Provider | null | undefined,
  capability: Capability,
  currentModelId?: string | null,
): string | null {
  const models = provider?.models.filter((model) => model.capability === capability) ?? [];
  if (currentModelId && models.some((model) => model.id === currentModelId)) {
    return currentModelId;
  }
  const defaultKeyByCapability: Record<string, keyof NonNullable<Provider["default_models"]>> = {
    "tts.builtin": "tts_builtin",
    "tts.design": "tts_design",
    "tts.clone": "tts_clone",
    "asr.transcribe": "asr",
  };
  const defaultKey = defaultKeyByCapability[capability];
  const configuredDefault = defaultKey ? provider?.default_models?.[defaultKey] : null;
  if (configuredDefault && models.some((model) => model.id === configuredDefault)) {
    return configuredDefault;
  }
  return models[0]?.id ?? null;
}

export function selectDefaultVoice(
  provider: Provider | null | undefined,
  voices: Voice[],
  currentVoiceId?: string | null,
): string | null {
  if (currentVoiceId && voices.some((voice) => voice.id === currentVoiceId)) {
    return currentVoiceId;
  }
  const configuredDefault = provider?.default_voice;
  if (configuredDefault && voices.some((voice) => voice.id === configuredDefault)) {
    return configuredDefault;
  }
  return voices[0]?.id ?? null;
}
```

Create `apps/web/src/lib/providerSelection.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { Provider, Voice } from "../api";
import { selectDefaultVoice, selectModelForCapability } from "./providerSelection";

const provider: Provider = {
  id: "mimo",
  name: "MiMo",
  capabilities: ["tts.builtin", "asr.transcribe"],
  default_voice: "Mia",
  default_models: { tts_builtin: "tts-default", asr: "asr-default" },
  models: [
    { id: "tts-first", name: "First", capability: "tts.builtin" },
    { id: "tts-default", name: "Default", capability: "tts.builtin" },
    { id: "asr-default", name: "ASR", capability: "asr.transcribe" },
  ],
};

const voices: Voice[] = [
  { id: "冰糖", name: "冰糖" },
  { id: "Mia", name: "Mia" },
];

describe("provider selection", () => {
  it("keeps current valid model", () => {
    expect(selectModelForCapability(provider, "tts.builtin", "tts-first")).toBe("tts-first");
  });

  it("uses configured default model before first model", () => {
    expect(selectModelForCapability(provider, "tts.builtin", "missing")).toBe("tts-default");
  });

  it("uses configured default voice", () => {
    expect(selectDefaultVoice(provider, voices, null)).toBe("Mia");
  });
});
```

- [ ] **Step 3: Add hook**

Create `apps/web/src/hooks/useProviderCatalog.ts`:

```ts
import { useEffect, useMemo, useState } from "react";
import { getProviders, Provider } from "../api";

export function useProviderCatalog() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("mimo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const items = await getProviders();
      setProviders(items);
      setSelectedProviderId((current) => items.find((item) => item.id === current)?.id ?? items[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load providers");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId) ?? providers[0] ?? null,
    [providers, selectedProviderId],
  );

  return { providers, selectedProvider, selectedProviderId, setSelectedProviderId, error, loading, refresh };
}
```

- [ ] **Step 4: Add fullscreen editor component**

Create `components/FullscreenTextEditor.tsx` with props:

```ts
type FullscreenTextEditorProps = {
  title: string;
  value: string;
  onApply(value: string): void;
  buttonLabel?: string;
};
```

Behavior:

- Button opens modal.
- Local draft state receives current value.
- Escape cancels.
- Cmd/Ctrl+Enter applies.
- Apply calls `onApply(draft)`.

- [ ] **Step 5: Add advanced settings component**

Create `components/AdvancedSettings.tsx`:

```ts
type AdvancedSettingsProps = {
  label: string;
  models: ProviderModel[];
  selectedModel: string | null;
  onModelChange(modelId: string): void;
  disabled?: boolean;
};
```

Render a `<details>` element with a model `<select>`.

- [ ] **Step 6: Refactor App.tsx**

Update `App.tsx`:

- Replace local provider loading logic with `useProviderCatalog()`.
- Keep provider selector global.
- Show provider status: `has_api_key`, `api_key_env`, `api_key_preview`, `base_url`, `config_path_preview`.
- Maintain per-form model state:
  - `builtinModel`
  - `designModel`
  - `cloneModel`
  - `asrModel`
- On provider change, call `selectModelForCapability()` for each capability.
- Add `textFormat` state for TTS long text fields.
- Add `Preview cleaned text` button calling `normalizeText()`.
- Add `FullscreenTextEditor` beside long textareas.

- [ ] **Step 7: Style additions**

Modify `styles.css`:

- Add modal overlay and fullscreen editor layout.
- Add advanced settings spacing.
- Ensure provider key preview and config path do not wrap awkwardly; use `overflow-wrap: anywhere`.
- Keep existing color variables.

- [ ] **Step 8: Run frontend checks**

```bash
rtk bun run --cwd apps/web lint
rtk bun run --cwd apps/web format:check
rtk bun run --cwd apps/web test
rtk bun run --cwd apps/web build
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
rtk git add apps/web/package.json apps/web/bun.lock apps/web/src
rtk git commit -m "feat: add provider-aware frontend controls"
```

---

### Task 8: Examples, Docs, and Local Server Hygiene

**Files:**
- Create: `voice_toolbox.toml.example`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `Makefile`

- [ ] **Step 1: Add config examples**

Create `voice_toolbox.toml.example`:

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

# To add another provider, copy the [[providers]] block and use another api_key_env,
# for example MIMO_SGP_API_KEY. Do not put API key values in this file.
```

Update `.env.example`:

```dotenv
MIMO_API_KEY=
# Optional second provider example:
MIMO_SGP_API_KEY=

# Used only when voice_toolbox.toml is absent:
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
VOICE_TOOLBOX_API_HOST=127.0.0.1
VOICE_TOOLBOX_API_PORT=8000
```

- [ ] **Step 2: Update README**

Add sections:

- Config discovery order.
- API key source and masked preview behavior.
- Local-only default binding.
- How to run backend/frontend with Makefile.
- How to preview Markdown cleanup.
- Note that chunking is reserved and not implemented.

Update Makefile help text so `backend-server` says it starts from `voice_toolbox.toml` / fallback config, not from `API_HOST` and `API_PORT`. Keep `API_HOST`/`API_PORT` documented only as legacy no-TOML aliases in `.env.example` and README.

- [ ] **Step 3: Verify Makefile targets**

Run:

```bash
rtk make backend-test
rtk make backend-lint
rtk make backend-type
rtk make frontend-lint
rtk make frontend-test
rtk make frontend-build
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add voice_toolbox.toml.example .env.example README.md Makefile
rtk git commit -m "docs: document configurable providers"
```

---

### Task 9: Full Validation and Smoke Prep

**Files:**
- Modify: `docs/smoke/mimo.md` if smoke docs need new config steps.
- No production code changes unless tests reveal a bug.

- [ ] **Step 1: Run full backend validation**

```bash
rtk uv run pytest -v
rtk uv run ruff check .
rtk uv run ruff format --check .
rtk uv run ty check packages/voice_toolbox/src apps/api/src
```

Expected: all PASS.

- [ ] **Step 2: Run full frontend validation**

```bash
rtk bun run --cwd apps/web lint
rtk bun run --cwd apps/web format:check
rtk bun run --cwd apps/web test
rtk bun run --cwd apps/web build
```

Expected: all PASS.

- [ ] **Step 3: Run local API smoke without credentials**

Run:

```bash
rtk uv run python -c "from voice_toolbox.config import load_app_config; c=load_app_config(); print(c.providers[0].id, c.providers[0].base_url)"
rtk uv run python - <<'PY'
from voice_toolbox.config import ConsoleLoggingConfig, LoggingConfig, load_app_config
from voice_toolbox_api.main import create_app

config = load_app_config()
config = config.model_copy(
    update={"logging": LoggingConfig(console=ConsoleLoggingConfig(enabled=False))}
)
app = create_app(config=config)
print(app.title)
PY
```

Expected:

```text
mimo https://api.xiaomimimo.com/v1
Voice Toolbox API
```

- [ ] **Step 4: Optional real MiMo smoke**

Only run when `MIMO_API_KEY` is present:

```bash
rtk uv run voice-toolbox tts synthesize --text "你好，配置化 smoke test。" --voice "冰糖"
```

Expected: audio artifact written under `data/artifacts/YYYYMMDD/`.

If Bearer auth fails, do not guess. Record the exact error in `docs/smoke/mimo.md`, verify MiMo's documented `api-key` header path with a minimal request, then make a focused follow-up change only if verified.

- [ ] **Step 5: Large adversarial review checkpoint**

Review all implementation commits:

```bash
rtk git log --oneline -9
rtk git diff HEAD~9..HEAD --stat
rtk git status --short
```

Inspect specifically:

- Config never stores secret values.
- API summaries expose only masked key preview and only by `AppConfig.api.host`.
- Logs do not include raw text/base64/key values.
- Markdown normalization does not alter math/script examples.
- Provider model selection is config-driven in API, CLI, and frontend.
- Frontend does not keep full API key values in state.

- [ ] **Step 6: Commit smoke docs if changed**

```bash
rtk git add docs/smoke/mimo.md
rtk git commit -m "docs: update mimo smoke steps"
```

If `docs/smoke/mimo.md` did not change, skip this commit and report that Task 9 produced no code/docs changes.

---

## Final Validation

Run:

```bash
rtk make check
rtk git status --short
```

Expected:

- Backend tests, ruff, ty pass.
- Frontend ESLint, Prettier check, TypeScript, Vite build pass.
- Worktree is clean.

## Handoff

Plan complete when this document is committed. Recommended execution mode: Subagent-Driven, one fresh subagent per task, with mandatory adversarial review after Tasks 3, 6, and 9.
