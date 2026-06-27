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

- `packages/voice_toolbox/src/voice_toolbox/config.py` - TOML loading, config discovery, config models, provider default filling, env precedence warnings.
- `packages/voice_toolbox/src/voice_toolbox/defaults.py` - built-in MiMo model/voice/default provider constants and `make_default_mimo_provider_config()`.
- `packages/voice_toolbox/src/voice_toolbox/logging_config.py` - Loguru sinks and stdlib/Uvicorn interception.
- `packages/voice_toolbox/src/voice_toolbox/pipeline.py` - shared `prepare_tts_request()` and sidecar-safe normalization metadata assembly.
- `packages/voice_toolbox/src/voice_toolbox/normalizers/__init__.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/base.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/markdown.py`
- `packages/voice_toolbox/src/voice_toolbox/normalizers/registry.py`
- `apps/web/src/hooks/useProviderCatalog.ts`
- `apps/web/src/lib/providerSelection.ts`
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
- `Makefile` - route API server through a logging-aware entrypoint if needed.
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
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text("providers = []\n", encoding="utf-8")

    config = load_app_config(path)

    assert [provider.id for provider in config.providers] == ["mimo"]
    assert "providers is empty" in caplog.text


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
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=True) == "tp-...abcd"
    assert mask_api_key_preview("abcdef123456", trusted_local=True) == "...3456"
    assert mask_api_key_preview("tp-1234567890abcd", trusted_local=False) == "configured"


def test_config_path_preview() -> None:
    assert preview_config_path(None) == "built-in default"
    assert preview_config_path(Path("/Users/example/voice-toolbox/voice_toolbox.toml")) == (
        "voice-toolbox/voice_toolbox.toml"
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
rtk uv run pytest tests/test_config.py -v
```

Expected: FAIL with import errors for `voice_toolbox.config`.

- [ ] **Step 3: Implement defaults module**

Create `packages/voice_toolbox/src/voice_toolbox/defaults.py`:

```python
from __future__ import annotations

from voice_toolbox.config import ConfiguredProvider, ProviderDefaultModels
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
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, ValidationError, model_validator

from voice_toolbox.models import ModelInfo, VoiceInfo

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    pass


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
            _validate_provider(provider)
        return self


def load_app_config(path: Path | str | None = None) -> AppConfig:
    env = load_env_values()
    config_path = _discover_config_path(path, env)
    if config_path is None:
        return _fallback_config(env)
    payload = _read_toml(config_path)
    payload["config_path"] = config_path
    if not payload.get("providers"):
        logger.warning("providers is empty; using built-in default provider")
        payload["providers"] = [_default_provider_payload(env, use_env_base_url=False)]
    else:
        _warn_ignored_env(env)
    payload["providers"] = [_fill_mimo_defaults(provider) for provider in payload["providers"]]
    try:
        return AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_env_values(env_path: Path | str | None = None) -> dict[str, str]:
    values: dict[str, object] = {}
    path = Path(env_path) if env_path is not None else Path.cwd() / ".env"
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
    return f"{path.parent.name}/{path.name}"
```

Also implement private helpers `_discover_config_path`, `_read_toml`, `_fallback_config`, `_default_provider_payload`, `_warn_ignored_env`, `_fill_mimo_defaults`, and `_validate_provider` with exactly the spec rules.

- [ ] **Step 5: Keep compatibility settings wrapper**

Modify `packages/voice_toolbox/src/voice_toolbox/settings.py` so `load_settings()` returns the existing `ProviderConfig` while internally using `load_app_config()` for fallback values. Preserve `API_HOST`/`API_PORT` aliases only when TOML is absent.

- [ ] **Step 6: Add Loguru dependency**

Modify `pyproject.toml` dependencies:

```toml
  "loguru>=0.7",
```

- [ ] **Step 7: Run backend checks**

Run:

```bash
rtk uv run pytest tests/test_config.py tests/test_imports.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/config.py packages/voice_toolbox/src/voice_toolbox/defaults.py
rtk uv run ty check packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add pyproject.toml packages/voice_toolbox/src/voice_toolbox/config.py packages/voice_toolbox/src/voice_toolbox/defaults.py packages/voice_toolbox/src/voice_toolbox/settings.py packages/voice_toolbox/src/voice_toolbox/models.py tests/test_config.py
rtk git commit -m "feat: add configurable provider settings"
```

---

### Task 2: Configurable Provider Construction

**Files:**
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/base.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/fake.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`
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

from voice_toolbox.config import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ASRRequest, ModelInfo, TTSMode, TTSRequest, VoiceInfo
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
- Re-export `MIMO_MODELS` and `MIMO_VOICES` for compatibility.
- Constructor accepts `config: ConfiguredProvider | None = None` and `base_url: str | None = None`.
- If `config is None`, call `make_default_mimo_provider_config(base_url=base_url or DEFAULT_MIMO_BASE_URL)`.
- Store `self._config`, `self._models_by_id`, and `self._default_models`.
- Convert `_build_tts_body`, `_build_asr_body`, `_resolve_tts_model`, `_validate_model_id` into instance methods.
- Keep module-level `_build_tts_body(request)` and `_build_asr_body(request, audio_data_url)` compatibility wrappers by creating a default `MimoProvider(client=_MissingCredentialsClient())` and calling instance methods; existing tests should pass while new code uses instance methods.

The key method signatures:

```python
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

- [ ] **Step 5: Update fake provider**

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

- [ ] **Step 6: Run provider tests**

```bash
rtk uv run pytest tests/test_provider_config.py tests/test_mimo_provider.py tests/test_provider_registry.py -v
rtk uv run ruff check packages/voice_toolbox/src/voice_toolbox/providers tests/test_provider_config.py
rtk uv run ty check packages/voice_toolbox/src
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/models.py packages/voice_toolbox/src/voice_toolbox/providers tests/test_provider_config.py tests/test_mimo_provider.py tests/test_api.py
rtk git commit -m "feat: make mimo provider configurable"
```

---

### Task 3: API Config Wiring and Provider Summaries

**Files:**
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add API tests**

Append to `tests/test_api.py`:

```python
from voice_toolbox.config import APIConfig, AppConfig, ConfiguredProvider, LoggingConfig, ProviderDefaultModels
from voice_toolbox.models import ModelInfo


def test_create_app_accepts_config_and_provider_summary_masks_key(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    config = AppConfig(
        api=APIConfig(host="127.0.0.1", port=8000),
        logging=LoggingConfig(),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    mimo = response.json()["providers"][0]
    assert mimo["api_key_env"] == "MIMO_API_KEY"
    assert mimo["api_key_preview"] == "tp-...abcd"
    assert mimo["config_path_preview"] == "built-in default"
    assert mimo["base_url"] == "https://api.xiaomimimo.com/v1"


def test_provider_summary_non_local_host_hides_key_preview(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    config = AppConfig(
        api=APIConfig(host="0.0.0.0", port=8000),
        logging=LoggingConfig(),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
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

Adjust the local `_client()` helper to accept the new `create_app(config=test_config, env_values=test_env)` parameters after implementation.

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

- If `config is None`, call `load_app_config()`.
- Store `config` and `env_values` in `app.state`.
- If `registry is None`, call `build_provider_registry(config, artifact_root=root)`.
- `_provider_summary()` reads the matching `ConfiguredProvider` by ID.
- `has_api_key` checks `provider_config.api_key_env` in merged env values.
- `api_key_preview` uses `mask_api_key_preview(value, trusted_local=config.api.host in {"127.0.0.1", "localhost"})`.
- `config_path_preview` uses `preview_config_path(config.config_path)`.
- `base_url`, `api_key_env`, and `type` come from `ConfiguredProvider`.

- [ ] **Step 4: Keep legacy test helper working**

For existing tests that use `has_mimo_api_key_func`, either keep that optional argument as a compatibility seam or update the helper to pass `env_values`. If kept, the signature is:

```python
has_mimo_api_key_func: Callable[[], bool] | None = None
```

Use it only when provider ID is `mimo` and `env_values` was not supplied.

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

from voice_toolbox.config import FileLoggingConfig, LoggingConfig
from voice_toolbox.logging_config import configure_logging, sanitize_log_metadata


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "voice-toolbox.log"
    config = LoggingConfig(file=FileLoggingConfig(enabled=True, path=str(path)))

    configure_logging(config)
    logging.getLogger("uvicorn.access").info("first")
    configure_logging(config)
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
    configure_logging(LoggingConfig(file=FileLoggingConfig(enabled=True, path=str(path))))

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
    assert "source_text_length" in text or "request completed" in text
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
- `configure_logging(config: LoggingConfig)`.

Implementation details:

```python
def configure_logging(config: LoggingConfig) -> None:
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
configure_logging(config.logging)
```

Make sure tests can pass a config with console/file disabled or use the default without duplicate log noise.

- [ ] **Step 5: Update Makefile server command if needed**

If Uvicorn CLI duplicates handlers, add a Python module entrypoint later. For this task keep:

```make
backend-server:
	$(PYTHON_ENV) uvicorn voice_toolbox_api.main:app --host $(API_HOST) --port $(API_PORT) --log-config /dev/null
```

If `/dev/null` is not portable in the current local environment, leave Makefile unchanged and document that logging is configured by app import in `README.md` in Task 8.

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

Core rules:

- `normalizer_id=None` selects by input format.
- `auto` requires at least two structural signals.
- Emphasis is cleaned in markdown mode but is not an auto signal.
- HTML stripping uses `</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*)?\s*/?>`.
- Unknown options are returned as sorted `ignored_options`.

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

- [ ] **Step 6: Integrate CLI with config and pipeline**

In `cli.py`:

- Add `TextFormatOption = Annotated[Literal["plain", "markdown", "auto"], typer.Option("--text-format")]`.
- TTS commands pass raw text and text format to `prepare_tts_request()`.
- ASR `model` option becomes `str | None = None`.
- `build_provider_registry()` loads `AppConfig` and calls config-based registry builder.

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
- Create: `apps/web/src/components/FullscreenTextEditor.tsx`
- Create: `apps/web/src/components/AdvancedSettings.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`

- [ ] **Step 1: Update frontend API types**

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
  return models[0]?.id ?? null;
}

export function selectDefaultVoice(
  voices: Voice[],
  currentVoiceId?: string | null,
): string | null {
  if (currentVoiceId && voices.some((voice) => voice.id === currentVoiceId)) {
    return currentVoiceId;
  }
  return voices.find((voice) => voice.id === "mimo_default")?.id ?? voices[0]?.id ?? null;
}
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
rtk git add apps/web/src
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

Create `voice_toolbox.toml.example` with the single-provider TOML from the spec and a commented second-provider example. Include no secret values.

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
rtk uv run python -c "from voice_toolbox_api.main import create_app; app=create_app(); print(app.title)"
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

If Bearer auth fails and MiMo requires `api-key`, add an OpenAI client header fallback in `MimoProvider` before proceeding:

```python
client_factory(
    api_key=resolved_api_key,
    base_url=resolved_base_url,
    default_headers={"api-key": resolved_api_key},
    max_retries=0,
)
```

Then rerun the smoke command.

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
