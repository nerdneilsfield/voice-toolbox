# MLX Audio Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Apple Silicon `mlx_audio` provider for `tts.builtin`, `tts.clone`, and `asr.transcribe`.

**Architecture:** Keep MLX imports lazy and behind `voice-toolbox[mac]`. Add a local provider type whose config can omit `base_url` and `api_key_env`, then implement `MlxAudioProvider` with provider-facing model aliases, per-model dependency hints, fake-loader unit tests, and manual Apple Silicon smoke docs.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, FastAPI API helpers, `mlx-audio[tts,stt]`; no direct `numpy` dependency in normal tests.

---

## File Map

- Modify `pyproject.toml`: add the `mac` optional dependency.
- Modify `packages/voice_toolbox/src/voice_toolbox/config_models.py`: add `mlx_audio` provider type and local-provider validation for `base_url = None` and `api_key_env = None`.
- Modify `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`: narrow optional config fields before network client setup.
- Modify `packages/voice_toolbox/src/voice_toolbox/providers/fish_audio.py`: narrow optional config fields before network client setup.
- Modify `packages/voice_toolbox/src/voice_toolbox/providers/openrouter.py`: narrow optional config fields before network client setup.
- Modify `packages/voice_toolbox/src/voice_toolbox/defaults.py`: add MLX Audio model aliases, default models, voices, and `make_default_mlx_audio_provider_config()`.
- Modify `packages/voice_toolbox/src/voice_toolbox/config.py`: fill defaults for `type = "mlx_audio"`.
- Modify `packages/voice_toolbox/src/voice_toolbox/providers/__init__.py`: export `MlxAudioProvider`.
- Modify `packages/voice_toolbox/src/voice_toolbox/providers/factory.py`: construct `MlxAudioProvider`.
- Create `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py`: local provider, lazy loaders, alias mapping, dependency hints, TTS/ASR implementation.
- Modify `apps/api/src/voice_toolbox_api/main.py`: mark local provider as not requiring an API key and skip key readiness for `api_key_env is None`.
- Modify `apps/web/src/api.ts`: add provider `requires_api_key`.
- Modify `apps/web/src/components/Topbar.tsx`: show local providers as ready rather than missing-key.
- Modify `apps/web/src/components/ProviderDetails.tsx`: hide missing-key warning for local providers.
- Modify `apps/web/src/i18n/dictionaries.ts`: add local-provider readiness labels.
- Create `apps/web/src/lib/providerReadiness.ts`: centralize key-required logic.
- Create `apps/web/src/lib/providerReadiness.test.ts`: cover local-provider readiness.
- Create `tests/test_mlx_audio_provider.py`: fake-loader provider tests.
- Modify `tests/test_config.py`: config parsing and `mac` extra tests.
- Modify `tests/test_provider_config.py`: registry/factory tests.
- Modify `tests/test_api.py`: provider summary and key-readiness tests.
- Modify `README.md`: install and local provider usage.
- Modify `voice_toolbox.toml.example`: commented MLX Audio provider block.
- Create `docs/smoke/mlx-audio.md`: manual smoke commands and model-specific dependency matrix.

## Task 1: Dependency Extra And Local Provider Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `packages/voice_toolbox/src/voice_toolbox/config_models.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/fish_audio.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/openrouter.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for `[mac]` and local provider config**

Append these imports to `tests/test_config.py`:

```python
import tomllib

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ModelInfo, VoiceInfo
```

Append these tests to `tests/test_config.py`:

```python
def test_mac_extra_installs_mlx_audio_without_model_specific_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    mac_deps = pyproject["project"]["optional-dependencies"]["mac"]
    joined = "\n".join(mac_deps)

    assert (
        "mlx-audio[tts,stt]>=0.4.4 ; "
        "sys_platform == 'darwin' and platform_machine == 'arm64'"
    ) in mac_deps
    assert "misaki" not in joined
    assert "nagisa" not in joined
    assert "soynlp" not in joined
    assert "onnx" not in joined


def test_mlx_audio_provider_accepts_local_credentials_none() -> None:
    provider = ConfiguredProvider(
        id="mlx-audio",
        type="mlx_audio",
        name="MLX Audio",
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=ProviderDefaultModels(
            tts_builtin="qwen3-tts-0.6b-base",
            tts_clone="qwen3-tts-0.6b-base-clone",
            asr="mlx-community/Qwen3-ASR-0.6B-8bit",
        ),
        models=[
            ModelInfo(id="qwen3-tts-0.6b-base", name="Qwen3 TTS", capability="tts.builtin"),
            ModelInfo(
                id="qwen3-tts-0.6b-base-clone",
                name="Qwen3 TTS Clone",
                capability="tts.clone",
            ),
            ModelInfo(
                id="mlx-community/Qwen3-ASR-0.6B-8bit",
                name="Qwen3 ASR",
                capability="asr.transcribe",
            ),
        ],
        voices=[VoiceInfo(id="Ryan", name="Ryan", language="en", gender="male")],
    )

    assert provider.base_url is None
    assert provider.api_key_env is None


def test_mlx_audio_provider_rejects_local_url_and_key_env() -> None:
    with pytest.raises(ValueError, match="base_url is not used by local provider type mlx_audio"):
        ConfiguredProvider(
            id="mlx-audio",
            type="mlx_audio",
            name="MLX Audio",
            base_url="https://localhost.example",
            api_key_env=None,
        )

    with pytest.raises(ValueError, match="api_key_env is not used by local provider type mlx_audio"):
        ConfiguredProvider(
            id="mlx-audio",
            type="mlx_audio",
            name="MLX Audio",
            base_url=None,
            api_key_env="MLX_AUDIO_API_KEY",
        )


def test_network_provider_still_requires_url_and_key_env() -> None:
    with pytest.raises(ValueError, match="base_url is required"):
        ConfiguredProvider(
            id="mimo",
            type="mimo",
            name="MiMo",
            base_url=None,
            api_key_env="MIMO_API_KEY",
        )

    with pytest.raises(ValueError, match="api_key_env is required"):
        ConfiguredProvider(
            id="mimo",
            type="mimo",
            name="MiMo",
            base_url="https://api.xiaomimimo.com/v1",
            api_key_env=None,
        )
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_mac_extra_installs_mlx_audio_without_model_specific_deps tests/test_config.py::test_mlx_audio_provider_accepts_local_credentials_none tests/test_config.py::test_mlx_audio_provider_rejects_local_url_and_key_env tests/test_config.py::test_network_provider_still_requires_url_and_key_env -q
```

Expected: FAIL because `mac` extra and `mlx_audio` provider type do not exist.

- [ ] **Step 3: Add `[mac]` extra**

Modify `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
  "httpx>=0.27",
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "ruff>=0.6",
  "ty>=0.0.54",
]
mac = [
  "mlx-audio[tts,stt]>=0.4.4 ; sys_platform == 'darwin' and platform_machine == 'arm64'",
]
```

- [ ] **Step 4: Update `ConfiguredProvider` validation**

Modify `packages/voice_toolbox/src/voice_toolbox/config_models.py`.
First extend the existing models import:

```python
from voice_toolbox.models import ModelInfo, ProviderOptionSpec, VoiceInfo
```

Then update `ConfiguredProvider`:

```python
class ConfiguredProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["mimo", "fish_audio", "openrouter", "mlx_audio"]
    name: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    default_voice: str | None = None
    default_models: ProviderDefaultModels | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    voices: list[VoiceInfo] = Field(default_factory=list)
    options: list[ProviderOptionSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_local_provider_network_fields(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("type") == "mlx_audio":
            if data.get("base_url") is not None:
                raise ValueError("base_url is not used by local provider type mlx_audio")
            if data.get("api_key_env") is not None:
                raise ValueError("api_key_env is not used by local provider type mlx_audio")
        return data

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("base_url must be an https URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not include credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not include query or fragment")
        return value.rstrip("/")

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_key_env must not be empty")
        return stripped

    @model_validator(mode="after")
    def validate_local_provider_credentials(self) -> ConfiguredProvider:
        if self.type == "mlx_audio":
            return self
        if self.base_url is None:
            raise ValueError(f"base_url is required for provider type {self.type}")
        if self.api_key_env is None:
            raise ValueError(f"api_key_env is required for provider type {self.type}")
        return self
```

Keep existing validators for model/default consistency below this class unchanged.

Because `ConfiguredProvider.base_url` and `api_key_env` are now optional at the
model level, also narrow them inside each existing network provider before
passing values into clients or missing-credential stubs. Apply this pattern in
`MimoProvider`, `FishAudioProvider`, and `OpenRouterProvider` after
`resolved_config` is assigned:

```python
        base_url_value = resolved_config.base_url
        api_key_env_value = resolved_config.api_key_env
        if base_url_value is None or api_key_env_value is None:
            raise ProviderError(f"provider {resolved_config.id} requires base_url and api_key_env")
```

Then use `base_url_value` for `client_factory(..., base_url=...)` and
`api_key_env_value` for `_MissingCredentialsClient(...)`. This keeps `ty check`
sound after local providers make those fields optional.

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_mac_extra_installs_mlx_audio_without_model_specific_deps tests/test_config.py::test_mlx_audio_provider_accepts_local_credentials_none tests/test_config.py::test_mlx_audio_provider_rejects_local_url_and_key_env tests/test_config.py::test_network_provider_still_requires_url_and_key_env -q
rtk uv run ty check packages/voice_toolbox/src/voice_toolbox/providers/mimo.py packages/voice_toolbox/src/voice_toolbox/providers/fish_audio.py packages/voice_toolbox/src/voice_toolbox/providers/openrouter.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add pyproject.toml packages/voice_toolbox/src/voice_toolbox/config_models.py packages/voice_toolbox/src/voice_toolbox/providers/mimo.py packages/voice_toolbox/src/voice_toolbox/providers/fish_audio.py packages/voice_toolbox/src/voice_toolbox/providers/openrouter.py tests/test_config.py
rtk git commit -m "feat(config): add mlx audio provider type"
```

## Task 2: Defaults, Config Filling, And Provider Factory

**Files:**
- Modify: `packages/voice_toolbox/src/voice_toolbox/defaults.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/config.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/__init__.py`
- Modify: `packages/voice_toolbox/src/voice_toolbox/providers/factory.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_provider_config.py`

- [ ] **Step 1: Create a temporary provider shell**

Create `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py`:

```python
from __future__ import annotations

from pathlib import Path

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider
from voice_toolbox.defaults import make_default_mlx_audio_provider_config
from voice_toolbox.models import ModelInfo, VoiceInfo


class MlxAudioProvider:
    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        artifact_root: Path | str | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._config = config or make_default_mlx_audio_provider_config()
        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            root = Path("." if artifact_root is None else artifact_root)
            self._artifact_root = root
            self._artifact_store = ArtifactStore(root)
        self.id = self._config.id
        self.name = self._config.name

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def capabilities(self) -> set[str]:
        return {model.capability for model in self._config.models if model.capability is not None}

    def list_models(self) -> list[ModelInfo]:
        return [model.model_copy() for model in self._config.models]

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in self._config.voices]
```

This shell exists only so factory/default tests can fail on missing exports and then pass. Task 3 replaces it with the full provider.

- [ ] **Step 2: Write failing tests for defaults and factory**

Append to `tests/test_config.py`:

```python
def test_mlx_audio_toml_gets_default_models_and_voices(tmp_path: Path) -> None:
    path = tmp_path / "voice_toolbox.toml"
    path.write_text(
        """
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
""".strip(),
        encoding="utf-8",
    )

    config = load_app_config(path)
    provider = config.providers[0]

    assert provider.default_models is not None
    assert provider.base_url is None
    assert provider.api_key_env is None
    assert provider.default_models.tts_builtin == "qwen3-tts-0.6b-base"
    assert provider.default_models.tts_clone == "qwen3-tts-0.6b-base-clone"
    assert provider.default_models.asr == "mlx-community/Qwen3-ASR-0.6B-8bit"
    assert {model.id for model in provider.models} >= {
        "qwen3-tts-0.6b-base",
        "qwen3-tts-0.6b-base-clone",
        "longcat-audiodit-1b",
        "ming-omni-tts-16.8b-a3b",
        "higgs-audio-v3-tts-4b",
        "mlx-community/Qwen3-ASR-0.6B-8bit",
    }
    assert {voice.id for voice in provider.voices} >= {"Ryan", "Aiden", "Vivian", "default"}
    assert {option.key for option in provider.options} >= {"lang_code", "temperature", "speed"}
    ming = next(model for model in provider.models if model.id == "ming-omni-tts-16.8b-a3b")
    assert ming.note is not None
    assert "onnx" in ming.note
    assert "safetensors" in ming.note
```

Append to `tests/test_provider_config.py`:

```python
def test_build_provider_registry_constructs_mlx_audio_without_api_key(tmp_path: Path) -> None:
    from voice_toolbox.defaults import make_default_mlx_audio_provider_config
    from voice_toolbox.providers.mlx_audio import MlxAudioProvider

    registry = build_provider_registry(
        config=AppConfig(config_path=None, providers=[make_default_mlx_audio_provider_config()]),
        artifact_root=tmp_path,
        env_values={},
    )

    provider = registry.get("mlx-audio")

    assert isinstance(provider, MlxAudioProvider)
    assert provider.id == "mlx-audio"
    assert provider.capabilities() >= {"tts.builtin", "tts.clone", "asr.transcribe"}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_mlx_audio_toml_gets_default_models_and_voices tests/test_provider_config.py::test_build_provider_registry_constructs_mlx_audio_without_api_key -q
```

Expected: FAIL because MLX defaults and factory branch do not exist.

- [ ] **Step 4: Add MLX defaults**

Modify the `voice_toolbox.models` import in
`packages/voice_toolbox/src/voice_toolbox/defaults.py`:

```python
from voice_toolbox.models import ModelInfo, ProviderOptionSpec, VoiceInfo
```

Then add MLX defaults:

```python
MLX_AUDIO_MODEL_ALIASES: dict[str, str] = {
    "qwen3-tts-0.6b-base": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    "qwen3-tts-0.6b-base-clone": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    "qwen3-tts-1.7b-base-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "longcat-audiodit-1b": "mlx-community/LongCat-AudioDiT-1B-bf16",
    "ming-omni-tts-16.8b-a3b": "mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    "higgs-audio-v3-tts-4b": "bosonai/higgs-audio-v3-tts-4b",
}

MLX_AUDIO_TTS_OPTIONS: list[ProviderOptionSpec] = [
    *[
        ProviderOptionSpec(
            key="lang_code",
            label="Language code",
            type="string",
            capability=capability,
            default="auto",
            description="Passed to MLX Audio TTS generate; use auto unless the model needs an explicit code.",
            advanced=True,
            safe_metadata=True,
        )
        for capability in ("tts.builtin", "tts.clone")
    ],
    *[
        ProviderOptionSpec(
            key="temperature",
            label="Temperature",
            type="number",
            capability=capability,
            min_value=0,
            max_value=2,
            step=0.05,
            advanced=True,
            safe_metadata=True,
        )
        for capability in ("tts.builtin", "tts.clone")
    ],
    *[
        ProviderOptionSpec(
            key="speed",
            label="Speed",
            type="number",
            capability=capability,
            min_value=0.25,
            max_value=4,
            step=0.05,
            advanced=True,
            safe_metadata=True,
        )
        for capability in ("tts.builtin", "tts.clone")
    ],
]

MLX_AUDIO_MODELS: list[ModelInfo] = [
    ModelInfo(id="qwen3-tts-0.6b-base", name="Qwen3 TTS 0.6B", capability="tts.builtin"),
    ModelInfo(
        id="qwen3-tts-0.6b-base-clone",
        name="Qwen3 TTS 0.6B Clone",
        capability="tts.clone",
        note="uses mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16; requires clone_reference_text",
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base-8bit",
        name="Qwen3 TTS 1.7B 8-bit",
        capability="tts.builtin",
    ),
    ModelInfo(id="longcat-audiodit-1b", name="LongCat AudioDiT 1B", capability="tts.builtin"),
    ModelInfo(
        id="ming-omni-tts-16.8b-a3b",
        name="Ming Omni TTS 16.8B A3B",
        capability="tts.builtin",
        note="may require pip install onnx safetensors if campplus conversion runs",
    ),
    ModelInfo(
        id="higgs-audio-v3-tts-4b",
        name="Higgs Audio v3 TTS 4B",
        capability="tts.builtin",
        note="large model; run smoke only when hardware memory allows",
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-0.6B-8bit",
        name="Qwen3 ASR 0.6B 8-bit",
        capability="asr.transcribe",
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-1.7B-8bit",
        name="Qwen3 ASR 1.7B 8-bit",
        capability="asr.transcribe",
    ),
]

MLX_AUDIO_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="Ryan", name="Ryan", language="en", gender="male"),
    VoiceInfo(id="Aiden", name="Aiden", language="en", gender="male"),
    VoiceInfo(id="Vivian", name="Vivian", language="en", gender="female"),
    VoiceInfo(id="Serena", name="Serena", language="en", gender="female"),
    VoiceInfo(id="default", name="Default", note="for models that ignore voice names"),
]

DEFAULT_MLX_AUDIO_MODELS = ProviderDefaultModels(
    tts_builtin="qwen3-tts-0.6b-base",
    tts_clone="qwen3-tts-0.6b-base-clone",
    asr="mlx-community/Qwen3-ASR-0.6B-8bit",
)


def make_default_mlx_audio_provider_config(
    *,
    provider_id: str = "mlx-audio",
    name: str = "MLX Audio",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="mlx_audio",
        name=name,
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=DEFAULT_MLX_AUDIO_MODELS,
        models=[model.model_copy() for model in MLX_AUDIO_MODELS],
        voices=[voice.model_copy() for voice in MLX_AUDIO_VOICES],
        options=[option.model_copy() for option in MLX_AUDIO_TTS_OPTIONS],
    )
```

- [ ] **Step 5: Wire config defaults**

Modify imports in `packages/voice_toolbox/src/voice_toolbox/config.py` to include:

```python
DEFAULT_MLX_AUDIO_MODELS,
MLX_AUDIO_MODELS,
MLX_AUDIO_TTS_OPTIONS,
MLX_AUDIO_VOICES,
```

Extend `_fill_defaults_for_provider()` so provider-level defaults can include
options:

```python
def _fill_defaults_for_provider(
    provider: dict[str, Any],
    *,
    default_models: ProviderDefaultModels,
    models: list[ModelInfo],
    voices: list[Any],
    options: list[ProviderOptionSpec] | None = None,
) -> dict[str, Any]:
    result = dict(provider)
    had_models = "models" in result
    had_voices = "voices" in result
    if "options" not in result and options:
        result["options"] = [option.model_dump() for option in options]
    # keep the existing models, voices, default_voice, and default_models logic below
```

Import `ProviderOptionSpec` from `voice_toolbox.models` if needed.

Add this branch in `_fill_provider_defaults()`:

```python
    if provider.get("type") == "mlx_audio":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_MLX_AUDIO_MODELS,
            models=MLX_AUDIO_MODELS,
            voices=MLX_AUDIO_VOICES,
            options=MLX_AUDIO_TTS_OPTIONS,
        )
```

- [ ] **Step 6: Export and construct the provider**

Modify `packages/voice_toolbox/src/voice_toolbox/providers/__init__.py`:

```python
from voice_toolbox.providers.mlx_audio import MlxAudioProvider
```

Add `"MlxAudioProvider"` to the existing `__all__` list in the same file.

Modify `packages/voice_toolbox/src/voice_toolbox/providers/factory.py`:

```python
from voice_toolbox.providers.mlx_audio import MlxAudioProvider
```

Add a small helper and use it for existing network-provider branches:

```python
def _api_key_for_network_provider(provider_config: ConfiguredProvider, env: Mapping[str, str]) -> str | None:
    if provider_config.api_key_env is None:
        raise ProviderError(f"provider {provider_config.id} requires api_key_env")
    return env.get(provider_config.api_key_env)
```

Import `ConfiguredProvider` and `ProviderError` if they are not already in the
file. Replace existing `env.get(provider_config.api_key_env)` calls in the
`mimo`, `fish_audio`, and `openrouter` branches with
`_api_key_for_network_provider(provider_config, env)`.

Add this branch in `build_provider_registry()`:

```python
        elif provider_config.type == "mlx_audio":
            providers.append(
                MlxAudioProvider(
                    config=provider_config,
                    artifact_store=ArtifactStore(root),
                )
            )
```

- [ ] **Step 7: Run tests and verify pass**

Run:

```bash
rtk uv run pytest tests/test_config.py::test_mlx_audio_toml_gets_default_models_and_voices tests/test_provider_config.py::test_build_provider_registry_constructs_mlx_audio_without_api_key -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/defaults.py packages/voice_toolbox/src/voice_toolbox/config.py packages/voice_toolbox/src/voice_toolbox/providers/__init__.py packages/voice_toolbox/src/voice_toolbox/providers/factory.py packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py tests/test_config.py tests/test_provider_config.py
rtk git commit -m "feat(providers): register mlx audio"
```

## Task 3: MLX Audio Provider Core

**Files:**
- Replace: `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py`
- Create: `tests/test_mlx_audio_provider.py`

- [ ] **Step 1: Write fake model tests**

Create `tests/test_mlx_audio_provider.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ASRRequest, ModelInfo, TTSMode, TTSRequest, VoiceInfo
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.mlx_audio import MlxAudioProvider, _dependency_error


def _config() -> ConfiguredProvider:
    return ConfiguredProvider(
        id="mlx-audio",
        type="mlx_audio",
        name="MLX Audio",
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=ProviderDefaultModels(
            tts_builtin="qwen3-tts-0.6b-base",
            tts_clone="qwen3-tts-0.6b-base-clone",
            asr="mlx-community/Qwen3-ASR-0.6B-8bit",
        ),
        models=[
            ModelInfo(id="qwen3-tts-0.6b-base", name="Qwen3 TTS", capability="tts.builtin"),
            ModelInfo(
                id="qwen3-tts-0.6b-base-clone",
                name="Qwen3 TTS Clone",
                capability="tts.clone",
            ),
            ModelInfo(
                id="ming-omni-tts-16.8b-a3b",
                name="Ming Omni TTS",
                capability="tts.builtin",
            ),
            ModelInfo(
                id="mlx-community/Qwen3-ASR-0.6B-8bit",
                name="Qwen3 ASR",
                capability="asr.transcribe",
            ),
        ],
        voices=[VoiceInfo(id="Ryan", name="Ryan")],
    )


class FakeTTSModel:
    sample_rate = 24000

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object):
        self.calls.append(kwargs)
        yield SimpleNamespace(audio=[0.0, 0.25], sample_rate=24000)
        yield SimpleNamespace(audio=[-0.25], sample_rate=24000)


class FakeASRModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, audio: str, **kwargs: object) -> object:
        self.calls.append({"audio": audio, **kwargs})
        return SimpleNamespace(
            text="hello world",
            segments=[{"text": "hello world", "start": 0.0, "end": 1.2}],
        )


def _writer(audio: object, sample_rate: int) -> bytes:
    return f"WAV:{sample_rate}:{list(audio)}".encode()


def _provider(
    tmp_path: Path,
    *,
    config: ConfiguredProvider | None = None,
    tts_model: FakeTTSModel | None = None,
    asr_model: FakeASRModel | None = None,
):
    tts = tts_model or FakeTTSModel()
    asr = asr_model or FakeASRModel()
    tts_calls: list[dict[str, object]] = []
    asr_calls: list[dict[str, object]] = []

    def tts_loader(model_id: str, **kwargs: object) -> FakeTTSModel:
        tts_calls.append({"model_id": model_id, **kwargs})
        return tts

    def asr_loader(model_id: str, **kwargs: object) -> FakeASRModel:
        asr_calls.append({"model_id": model_id, **kwargs})
        return asr

    provider = MlxAudioProvider(
        config=config or _config(),
        artifact_root=tmp_path,
        tts_loader=tts_loader,
        stt_loader=asr_loader,
        wav_writer=_writer,
        platform_check=lambda: None,
    )
    return provider, tts, asr, tts_calls, asr_calls


def test_tts_builtin_uses_alias_and_generation_kwargs(tmp_path: Path) -> None:
    provider, model, _, tts_calls, _ = _provider(tmp_path)

    result = provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="Ryan",
            provider_options={"lang_code": "English", "temperature": 0.1},
        )
    )

    assert result.audio == b"WAV:24000:[0.0, 0.25, -0.25]"
    assert result.model == "qwen3-tts-0.6b-base"
    assert tts_calls[0]["model_id"] == "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
    assert model.calls[0]["text"] == "hello"
    assert model.calls[0]["voice"] == "Ryan"
    assert model.calls[0]["lang_code"] == "English"
    assert model.calls[0]["temperature"] == 0.1


def test_tts_provider_options_cannot_override_core_kwargs(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)

    with pytest.raises(ProviderError, match="provider option text collides"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.BUILTIN,
                text="hello",
                voice_id="Ryan",
                provider_options={"text": "override"},
            )
        )


def test_tts_design_is_unsupported(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)

    with pytest.raises(UnsupportedCapability, match="design"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.DESIGN,
                text="hello",
                voice_description="warm narrator",
            )
        )


def test_tts_clone_requires_reference_text(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="clone_reference_text"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.CLONE,
                text="hello",
                clone_sample_path=sample,
                clone_mime_type="audio/wav",
                consent_confirmed=True,
            )
        )


def test_tts_clone_passes_reference_audio_and_text(tmp_path: Path) -> None:
    provider, model, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.CLONE,
            text="hello",
            clone_sample_path=sample,
            clone_mime_type="audio/wav",
            clone_reference_text="reference words",
            consent_confirmed=True,
        )
    )

    assert model.calls[0]["ref_audio"] == str(sample)
    assert model.calls[0]["ref_text"] == "reference words"


def test_tts_artifact_metadata_keeps_trusted_values_and_no_raw_clone_text(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    artifact = provider.synthesize(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.CLONE,
            text="hello",
            clone_sample_path=sample,
            clone_mime_type="audio/wav",
            clone_raw_byte_size=16,
            clone_base64_size=24,
            clone_reference_text="reference words",
            consent_confirmed=True,
        ),
        artifact_metadata={"provider_id": "spoofed", "source_text_length": 999},
    )

    assert artifact.metadata["provider_id"] == "mlx-audio"
    assert artifact.metadata["source_text_length"] == 5
    assert artifact.metadata["clone_reference_text_length"] == len("reference words")
    assert artifact.metadata["raw_byte_size"] == 16
    assert artifact.metadata["base64_size"] == 24
    assert artifact.metadata["uploaded_file_mime_type"] == "audio/wav"
    assert artifact.metadata["uploaded_file_suffix"] == ".wav"
    assert isinstance(artifact.metadata["uploaded_file_name_hash"], str)
    assert "clone_reference_text" not in artifact.metadata


def test_ming_loader_includes_onnx_allow_pattern(tmp_path: Path) -> None:
    provider, _, _, tts_calls, _ = _provider(tmp_path)

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            model="ming-omni-tts-16.8b-a3b",
            text="hello",
            voice_id="Ryan",
        )
    )

    assert tts_calls[0]["model_id"] == "mlx-community/Ming-omni-tts-16.8B-A3B-bf16"
    assert "*.onnx" in tts_calls[0]["allow_patterns"]
    for pattern in ("*.json", "*.model", "*.tiktoken", "*.npz", "*.pth"):
        assert pattern in tts_calls[0]["allow_patterns"]


def test_bailingmm_upstream_model_includes_onnx_allow_pattern(tmp_path: Path) -> None:
    config = _config()
    config = config.model_copy(
        update={
            "models": [
                *config.models,
                ModelInfo(
                    id="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
                    name="Custom BailingMM",
                    capability="tts.builtin",
                ),
            ]
        }
    )
    provider, _, _, tts_calls, _ = _provider(tmp_path, config=config)

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
            text="hello",
            voice_id="Ryan",
        )
    )

    assert "*.onnx" in tts_calls[0]["allow_patterns"]


def test_asr_maps_language_and_segments(tmp_path: Path) -> None:
    provider, _, asr, _, asr_calls = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    payload = provider.transcribe_payload(
        ASRRequest(
            provider_id="mlx-audio",
            audio_path=audio,
            mime_type="audio/wav",
            raw_byte_size=16,
            base64_size=24,
            language="zh",
        )
    )

    assert asr_calls == [{"model_id": "mlx-community/Qwen3-ASR-0.6B-8bit"}]
    assert asr.calls[0]["audio"] == str(audio)
    assert asr.calls[0]["language"] == "Chinese"
    assert payload.text == "hello world"
    assert payload.segments[0].start_seconds == 0.0
    assert payload.segments[0].end_seconds == 1.2


def test_asr_artifact_metadata_keeps_trusted_values(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    artifact = provider.transcribe(
        ASRRequest(
            provider_id="mlx-audio",
            audio_path=audio,
            mime_type="audio/wav",
            raw_byte_size=16,
            base64_size=24,
            artifact_metadata={"base64_size": 999, "provider_id": "spoofed"},
        )
    )

    assert artifact.metadata["base64_size"] == 24
    assert artifact.metadata["provider_id"] == "mlx-audio"
    assert artifact.metadata["raw_byte_size"] == 16


def test_asr_provider_options_cannot_override_core_audio_arg(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="provider option audio collides"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
                provider_options={"audio": "override"},
            )
        )

    with pytest.raises(ProviderError, match="provider option language collides"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
                provider_options={"language": "Japanese"},
            )
        )


def test_unknown_asr_model_is_rejected_before_loader(tmp_path: Path) -> None:
    provider, _, _, _, asr_calls = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="unsupported MLX Audio model"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                model="attacker/custom-asr",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
            )
        )

    assert asr_calls == []


def test_forced_aligner_model_is_not_asr_transcribe(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(UnsupportedCapability, match="forced alignment"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
            )
        )


def test_missing_dependency_error_has_install_hint(tmp_path: Path) -> None:
    def broken_loader(model_id: str, **kwargs: object) -> object:
        raise ImportError("Japanese tokenization requires nagisa. Install with: pip install nagisa")

    provider = MlxAudioProvider(
        config=_config(),
        artifact_root=tmp_path,
        tts_loader=broken_loader,
        stt_loader=lambda model_id, **kwargs: FakeASRModel(),
        wav_writer=_writer,
        platform_check=lambda: None,
    )

    with pytest.raises(ProviderError, match="pip install nagisa"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.BUILTIN,
                text="hello",
                voice_id="Ryan",
            )
        )


def test_kokoro_dependency_error_includes_request_language_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'misaki'", name="misaki"),
        selected_model="custom-kokoro",
        upstream_model="hexgrad/Kokoro-82M",
        request_language="j",
    )

    assert "pip install misaki" in str(error)
    assert "misaki[ja]" in str(error)


def test_kokoro_dependency_error_includes_mandarin_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'misaki'", name="misaki"),
        selected_model="custom-kokoro",
        upstream_model="hexgrad/Kokoro-82M",
        request_language="zh",
    )

    assert "misaki[zh]" in str(error)


def test_forced_aligner_dependency_error_mentions_korean_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'soynlp'", name="soynlp"),
        selected_model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
        upstream_model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
    )

    assert "pip install soynlp" in str(error)
    assert "Korean" in str(error)


def test_bailingmm_dependency_error_mentions_onnx_safetensors() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'onnx'", name="onnx"),
        selected_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
        upstream_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    )

    assert "pip install onnx safetensors" in str(error)


def test_bailingmm_non_dependency_error_preserves_original_failure() -> None:
    error = _dependency_error(
        RuntimeError("download timed out"),
        selected_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
        upstream_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    )

    assert "missing a dependency" not in str(error)
    assert "download timed out" in str(error)


def test_non_bailingmm_onnx_error_is_not_labeled_bailingmm() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'onnx'", name="onnx"),
        selected_model="qwen3-tts-0.6b-base",
        upstream_model="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    )

    assert "BailingMM" not in str(error)
    assert "onnx" in str(error)
```

- [ ] **Step 2: Run provider tests and verify they fail**

Run:

```bash
rtk uv run pytest tests/test_mlx_audio_provider.py -q
```

Expected: FAIL because the provider shell has no synthesize/transcribe implementation.

- [ ] **Step 3: Replace provider shell with full implementation**

Replace `packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py` with an implementation using these exact public helpers and class signatures:

```python
from __future__ import annotations

import io
import inspect
import platform
import tempfile
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import uuid4

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.defaults import (
    MLX_AUDIO_MODEL_ALIASES,
    make_default_mlx_audio_provider_config,
)
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment

# Keep aligned with Blaizzy/mlx-audio `mlx_audio/utils.py`
# `DEFAULT_ALLOW_PATTERNS`, then append `*.onnx` only for BailingMM/Ming Omni loads.
DEFAULT_MLX_ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "*.py",
    "*.model",
    "*.tiktoken",
    "*.txt",
    "*.jinja",
    "*.jsonl",
    "*.yaml",
    "*.npz",
    "*.pth",
]
BAILINGMM_MODEL_MARKERS = ("ming-omni", "bailingmm", "bailing-mm")
KOKORO_MODEL_MARKERS = ("kokoro",)
TTS_CORE_OPTION_KEYS = {"text", "voice", "ref_audio", "ref_text"}
ASR_CORE_OPTION_KEYS = {"audio", "language"}
FORCED_ALIGNER_MARKERS = ("forcedaligner", "forced-aligner", "qwen3-forcedaligner")

TTSLoader = Callable[..., Any]
STTLoader = Callable[..., Any]
WavWriter = Callable[[Any, int], bytes]
PlatformCheck = Callable[[], None]
```

Add default lazy loaders:

```python
def _load_tts_model(model_id: str, **kwargs: object) -> Any:
    try:
        from mlx_audio.tts.utils import load
    except ImportError as exc:
        raise _dependency_error(exc, selected_model=model_id, upstream_model=model_id) from exc
    return load(model_id, **kwargs)


def _load_stt_model(model_id: str, **kwargs: object) -> Any:
    try:
        from mlx_audio.stt import load
    except ImportError as exc:
        raise _dependency_error(exc, selected_model=model_id, upstream_model=model_id) from exc
    return load(model_id, **kwargs)


def _write_wav_bytes(audio: Any, sample_rate: int) -> bytes:
    try:
        from mlx_audio.audio_io import write
    except ImportError as exc:
        raise _dependency_error(exc, selected_model="audio_io", upstream_model="audio_io") from exc
    buffer = io.BytesIO()
    write(buffer, audio, sample_rate, format="wav")
    return buffer.getvalue()
```

Implement `MlxAudioProvider.__init__`, list methods, context methods, TTS/ASR operations, and helpers with these behaviors:

```python
class MlxAudioProvider:
    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        artifact_root: Path | str | None = None,
        artifact_store: ArtifactStore | None = None,
        tts_loader: TTSLoader = _load_tts_model,
        stt_loader: STTLoader = _load_stt_model,
        wav_writer: WavWriter = _write_wav_bytes,
        platform_check: PlatformCheck | None = None,
    ) -> None:
        self._config = config or make_default_mlx_audio_provider_config()
        self._default_models = self._config.default_models or ProviderDefaultModels()
        self._models_by_id = {model.id: model for model in self._config.models}
        self._operation_prefix = uuid4().hex
        self._operation_counter = 0
        self._closed = False
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._tts_models: dict[str, Any] = {}
        self._stt_models: dict[str, Any] = {}
        self._tts_loader = tts_loader
        self._stt_loader = stt_loader
        self._wav_writer = wav_writer
        self._platform_check = platform_check or _ensure_apple_silicon_macos
        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            if artifact_root is None:
                self._temp_dir = tempfile.TemporaryDirectory()
                root = Path(self._temp_dir.name)
            else:
                root = Path(artifact_root)
            self._artifact_root = root
            self._artifact_store = ArtifactStore(root)
        self.id = self._config.id
        self.name = self._config.name

    def capabilities(self) -> set[str]:
        return {model.capability for model in self._config.models if model.capability is not None}

    def list_models(self) -> list[ModelInfo]:
        return [model.model_copy() for model in self._config.models]

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in self._config.voices]

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def close(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
        self._closed = True

    def __enter__(self) -> MlxAudioProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
```

For TTS/ASR artifact methods, mirror the existing provider pattern:

```python
    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        operation_id = self._next_operation_id("tts")
        started_at = datetime.now(UTC)
        result = self.synthesize_bytes(request)
        metadata = {
            **dict(artifact_metadata or {}),
            "model": result.model,
            "operation": "tts",
            "output_format": request.output_format,
            "provider_id": self.id,
            "source_text_length": len(request.text or ""),
            "tts_mode": request.mode.value,
            "voice_id": request.voice_id,
        }
        if request.clone_reference_text:
            metadata["clone_reference_text_length"] = len(request.clone_reference_text)
        if request.mode == TTSMode.CLONE:
            if request.clone_sample_path is not None:
                metadata["uploaded_file_name_hash"] = _file_name_hash(request.clone_sample_path.name)
                metadata["uploaded_file_suffix"] = request.clone_sample_path.suffix
            metadata.update(
                {
                    "base64_size": request.clone_base64_size,
                    "consent_confirmed": request.consent_confirmed,
                    "raw_byte_size": request.clone_raw_byte_size,
                    "uploaded_file_mime_type": request.clone_mime_type,
                }
            )
        artifact = self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=result.audio,
            mime_type=result.mime_type,
            suffix=result.suffix,
            metadata=metadata,
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="tts",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self._ensure_open()
        self._platform_check()
        if request.output_format != "wav":
            raise ProviderError("mlx_audio TTS output format must be wav")
        selected = self._resolve_tts_model(request)
        upstream = _upstream_model_id(selected)
        model = self._load_tts(selected, upstream)
        kwargs = self._tts_kwargs(request)
        kwargs = _validated_generate_kwargs(model.generate, kwargs)
        try:
            results = list(model.generate(**kwargs))
            audio, sample_rate = _merge_generation_results(results, model)
            return ProviderAudioResult(
                audio=self._wav_writer(audio, sample_rate),
                mime_type="audio/wav",
                suffix=".wav",
                model=selected,
            )
        except ProviderError:
            raise
        except Exception as exc:
            request_language = kwargs.get("lang_code")
            raise _dependency_error(
                exc,
                selected_model=selected,
                upstream_model=upstream,
                request_language=str(request_language) if request_language is not None else None,
            ) from exc
```

Add ASR with language and segment mapping:

```python
    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        operation_id = self._next_operation_id("asr")
        started_at = datetime.now(UTC)
        payload = self.transcribe_payload(request)
        artifact = self._artifact_store.write_transcript(
            operation_id=operation_id,
            provider_id=self.id,
            operation="asr",
            text=payload.text,
            payload=payload,
            metadata={
                **request.artifact_metadata,
                "base64_size": request.base64_size,
                "language": request.language,
                "model": request.model or self._default_models.asr,
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name_hash": _file_name_hash(request.audio_path.name),
                "uploaded_file_suffix": request.audio_path.suffix,
            },
        )
        self._artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="asr",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        return artifact

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        self._ensure_open()
        self._platform_check()
        selected = self._resolve_asr_model(request)
        if _is_forced_aligner(selected):
            raise UnsupportedCapability(
                "mlx_audio forced alignment is not asr.transcribe; use a future alignment capability"
            )
        upstream = _upstream_model_id(selected)
        model = self._load_stt(selected, upstream)
        kwargs = _provider_options_without_core_collisions(
            request.provider_options,
            core_keys=ASR_CORE_OPTION_KEYS,
        )
        language = _asr_language(request.language)
        if language is not None:
            kwargs["language"] = language
        kwargs = _validated_generate_kwargs(model.generate, kwargs)
        try:
            result = model.generate(str(request.audio_path), **kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
        text = getattr(result, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("mlx_audio response is missing transcript text")
        return TranscriptPayload(text=text, segments=_segments_from_result(result))
```

Add helpers for validation, model resolution, loading, dependency hints, and audio joining:

```python
def _ensure_apple_silicon_macos() -> None:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise ProviderError("mlx_audio provider requires Apple Silicon macOS")


def _upstream_model_id(model_id: str) -> str:
    return MLX_AUDIO_MODEL_ALIASES.get(model_id, model_id)


def _is_forced_aligner(model_id: str) -> bool:
    lowered = model_id.lower()
    return any(marker in lowered for marker in FORCED_ALIGNER_MARKERS)


def _is_bailingmm_model(selected_model: str, upstream_model: str) -> bool:
    lowered = f"{selected_model} {upstream_model}".lower()
    return any(marker in lowered for marker in BAILINGMM_MODEL_MARKERS)


def _is_kokoro_model(selected_model: str, upstream_model: str) -> bool:
    lowered = f"{selected_model} {upstream_model}".lower()
    return any(marker in lowered for marker in KOKORO_MODEL_MARKERS)


def _asr_language(language: str) -> str | None:
    return {"auto": None, "zh": "Chinese", "en": "English"}[language]


def _file_name_hash(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:12]


def _provider_options_without_core_collisions(
    options: Mapping[str, object],
    *,
    core_keys: set[str],
) -> dict[str, object]:
    collisions = sorted(set(options) & core_keys)
    if collisions:
        raise ProviderError(f"provider option {collisions[0]} collides with mlx_audio core argument")
    return dict(options)


def _validated_generate_kwargs(
    generate: Callable[..., object],
    kwargs: dict[str, object],
) -> dict[str, object]:
    try:
        signature = inspect.signature(generate)
    except (TypeError, ValueError):
        return kwargs
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs
    allowed = {
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind
        in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    unsupported = sorted(set(kwargs) - allowed)
    if unsupported:
        raise ProviderError(f"unsupported mlx_audio provider option: {unsupported[0]}")
    return kwargs
```

Inside the class add model resolution, cache, and kwargs helpers:

```python
    def _load_tts(self, selected: str, upstream: str) -> Any:
        if selected not in self._tts_models:
            kwargs: dict[str, object] = {}
            if _is_bailingmm_model(selected, upstream):
                kwargs["allow_patterns"] = [*DEFAULT_MLX_ALLOW_PATTERNS, "*.onnx"]
            try:
                self._tts_models[selected] = self._tts_loader(upstream, **kwargs)
            except Exception as exc:
                raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
        return self._tts_models[selected]

    def _load_stt(self, selected: str, upstream: str) -> Any:
        if selected not in self._stt_models:
            try:
                self._stt_models[selected] = self._stt_loader(upstream)
            except Exception as exc:
                raise _dependency_error(exc, selected_model=selected, upstream_model=upstream) from exc
        return self._stt_models[selected]

    def _resolve_tts_model(self, request: TTSRequest) -> str:
        if request.mode == TTSMode.DESIGN:
            raise UnsupportedCapability("mlx_audio provider does not support TTS mode: design")
        capability = TTS_MODE_CAPABILITIES[request.mode]
        model = request.model or self._default_tts_model(request.mode)
        self._validate_model_id(model, expected_capability=capability)
        if request.mode == TTSMode.CLONE and not request.clone_reference_text:
            raise ProviderError("mlx_audio clone mode requires clone_reference_text")
        return model

    def _resolve_asr_model(self, request: ASRRequest) -> str:
        model = request.model or self._default_models.asr
        if model is None:
            raise ProviderError(f"mlx_audio provider {self.id} has no default ASR model")
        if _is_forced_aligner(model):
            return model
        self._validate_model_id(model, expected_capability=ASR_CAPABILITY)
        return model

    def _default_tts_model(self, mode: TTSMode) -> str:
        default_by_mode = {
            TTSMode.BUILTIN: self._default_models.tts_builtin,
            TTSMode.DESIGN: self._default_models.tts_design,
            TTSMode.CLONE: self._default_models.tts_clone,
        }
        model = default_by_mode[mode]
        if model is None:
            raise ProviderError(f"mlx_audio provider {self.id} has no default TTS model for {mode}")
        return model

    def _validate_model_id(self, model: str, *, expected_capability: str) -> None:
        model_info = self._models_by_id.get(model)
        if model_info is None:
            raise ProviderError(f"unsupported MLX Audio model: {model}")
        if model_info.capability != expected_capability:
            raise ProviderError(f"unsupported MLX Audio model for {expected_capability}: {model}")

    def _tts_kwargs(self, request: TTSRequest) -> dict[str, object]:
        kwargs = _provider_options_without_core_collisions(
            request.provider_options,
            core_keys=TTS_CORE_OPTION_KEYS,
        )
        kwargs["text"] = request.text or ""
        if request.voice_id:
            kwargs["voice"] = request.voice_id
        if "lang_code" not in kwargs:
            kwargs["lang_code"] = "auto"
        if request.mode == TTSMode.CLONE:
            kwargs["ref_audio"] = str(request.clone_sample_path)
            kwargs["ref_text"] = request.clone_reference_text
        return kwargs

    def _next_operation_id(self, operation: str) -> str:
        self._operation_counter += 1
        return f"{self.id}-{self._operation_prefix}-{operation}-{self._operation_counter}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderError("mlx_audio provider is closed")
```

Add audio/result conversion helpers:

```python
def _merge_generation_results(results: Iterable[Any], model: Any) -> tuple[Any, int]:
    result_list = list(results)
    if not result_list:
        raise ProviderError("mlx_audio generated no audio")
    chunks: list[float] = []
    sample_rate = getattr(model, "sample_rate", 24000)
    for result in result_list:
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        chunks.extend(_audio_values(audio))
        sample_rate = int(getattr(result, "sample_rate", sample_rate))
    if not chunks:
        raise ProviderError("mlx_audio generated no audio")
    return chunks, sample_rate


def _audio_values(audio: Any) -> list[float]:
    if hasattr(audio, "tolist"):
        audio = audio.tolist()
    if isinstance(audio, list):
        return [float(value) for value in audio]
    return [float(value) for value in audio]


def _segments_from_result(result: Any) -> list[TranscriptSegment]:
    segments = getattr(result, "segments", None) or []
    parsed: list[TranscriptSegment] = []
    for segment in segments:
        text = _segment_value(segment, "text")
        if not isinstance(text, str) or not text.strip():
            continue
        start = _segment_value(segment, "start")
        if start is None:
            start = _segment_value(segment, "start_time")
        end = _segment_value(segment, "end")
        if end is None:
            end = _segment_value(segment, "end_time")
        parsed.append(
            TranscriptSegment(
                text=text,
                start_seconds=float(start) if start is not None else None,
                end_seconds=float(end) if end is not None else None,
                speaker=_segment_value(segment, "speaker"),
            )
        )
    return parsed


def _segment_value(segment: Any, key: str) -> Any:
    if isinstance(segment, Mapping):
        return segment.get(key)
    return getattr(segment, key, None)
```

Add dependency hint mapping:

```python
def _dependency_error(
    exc: BaseException,
    *,
    selected_model: str,
    upstream_model: str,
    request_language: str | None = None,
) -> ProviderError:
    module = _missing_module(exc)
    text = str(exc)
    hint = _install_hint(
        module,
        text,
        selected_model=selected_model,
        upstream_model=upstream_model,
        request_language=request_language,
    )
    if hint is None:
        if module is None:
            return ProviderError(
                f"mlx_audio model {selected_model} ({upstream_model}) failed: {text}"
            )
        return ProviderError(
            f"mlx_audio model {selected_model} ({upstream_model}) is missing a dependency: "
            f"{module}. Original error: {text}"
        )
    message = (
        f"mlx_audio model {selected_model} ({upstream_model}) is missing a dependency"
    )
    if module:
        message = f"{message}: {module}"
    if hint:
        message = f"{message}; {hint}"
    if text:
        message = f"{message}. Original error: {text}"
    return ProviderError(message)


def _missing_module(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    while current is not None:
        name = getattr(current, "name", None)
        if isinstance(current, ModuleNotFoundError) and isinstance(name, str):
            return name
        if isinstance(current, ImportError) and isinstance(name, str):
            return name
        current = current.__cause__
    return None


def _install_hint(
    module: str | None,
    text: str,
    *,
    selected_model: str,
    upstream_model: str,
    request_language: str | None = None,
) -> str | None:
    lowered = text.lower()
    if module is not None and module.startswith("mlx_audio"):
        return "install voice-toolbox[mac]"
    if module == "misaki" or "misaki" in lowered:
        hint = "pip install misaki"
        if _is_kokoro_model(selected_model, upstream_model):
            language = (request_language or "").lower()
            if language in {"j", "ja", "japanese"}:
                hint = f"{hint}; Kokoro Japanese voices need pip install 'misaki[ja]'"
            elif language in {"z", "zh", "chinese", "mandarin"}:
                hint = f"{hint}; Kokoro Mandarin voices need pip install 'misaki[zh]'"
        return hint
    if module == "nagisa" or "nagisa" in lowered:
        return "pip install nagisa; needed by Qwen3 ForcedAligner Japanese alignment"
    if module == "soynlp" or "soynlp" in lowered:
        return "pip install soynlp; needed by Qwen3 ForcedAligner Korean alignment"
    if _is_bailingmm_model(selected_model, upstream_model) and (
        module in {"onnx", "safetensors"}
        or "campplus" in lowered
        or "onnx" in lowered
        or "safetensors" in lowered
    ):
        return "Ming Omni BailingMM campplus conversion may need pip install onnx safetensors"
    if module == "mistral_common" or "mistral-common" in lowered:
        return "install mlx-audio[tts] or voice-toolbox[mac]"
    return None
```

- [ ] **Step 4: Run provider tests**

Run:

```bash
rtk uv run pytest tests/test_mlx_audio_provider.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/providers/mlx_audio.py tests/test_mlx_audio_provider.py
rtk git commit -m "feat(providers): add mlx audio provider"
```

## Task 4: API And Web Local Provider Readiness

**Files:**
- Modify: `apps/api/src/voice_toolbox_api/main.py`
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/components/Topbar.tsx`
- Modify: `apps/web/src/components/ProviderDetails.tsx`
- Modify: `apps/web/src/i18n/dictionaries.ts`
- Create: `apps/web/src/lib/providerReadiness.ts`
- Create: `apps/web/src/lib/providerReadiness.test.ts`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/test_api.py`:

```python
class RecordingMlxAudioProvider(RecordingMimoProvider):
    id = "mlx-audio"
    name = "MLX Audio"


def test_mlx_audio_provider_summary_does_not_require_api_key(tmp_path: Path) -> None:
    provider = RecordingMlxAudioProvider(tmp_path)
    config = AppConfig(
        config_path=None,
        providers=[
            ConfiguredProvider(
                id="mlx-audio",
                type="mlx_audio",
                name="MLX Audio",
                base_url=None,
                api_key_env=None,
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
        env_values={},
    )
    client = TestClient(app)

    summary = client.get("/v1/providers").json()["providers"][0]

    assert summary["type"] == "mlx_audio"
    assert summary["base_url"] is None
    assert summary["api_key_env"] is None
    assert summary["requires_api_key"] is False
    assert summary["has_api_key"] is False
    assert summary["api_key_preview"] is None
```

Append this route-level readiness test:

```python
def test_mlx_audio_tts_route_skips_api_key_readiness(tmp_path: Path) -> None:
    provider = RecordingMlxAudioProvider(tmp_path)
    config = AppConfig(
        config_path=None,
        providers=[
            ConfiguredProvider(
                id="mlx-audio",
                type="mlx_audio",
                name="MLX Audio",
                base_url=None,
                api_key_env=None,
                default_voice="Mia",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
                voices=[VoiceInfo(id="Mia", name="Mia")],
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
        env_values={},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mlx-audio",
            "text": "hello",
            "voice_id": "Mia",
        },
    )

    assert response.status_code == 200
```

- [ ] **Step 2: Write failing web readiness tests**

Create `apps/web/src/lib/providerReadiness.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Provider } from "../api";
import { providerHasMissingApiKey, providerRequiresApiKey } from "./providerReadiness";

const baseProvider: Provider = {
  id: "mimo",
  name: "MiMo",
  capabilities: ["tts.builtin"],
  models: [],
};

describe("provider readiness", () => {
  it("treats local providers as not requiring API keys", () => {
    const provider: Provider = {
      ...baseProvider,
      id: "mlx-audio",
      type: "mlx_audio",
      requires_api_key: false,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(false);
    expect(providerHasMissingApiKey(provider)).toBe(false);
  });

  it("keeps network provider missing-key behavior", () => {
    const provider: Provider = {
      ...baseProvider,
      requires_api_key: true,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(true);
    expect(providerHasMissingApiKey(provider)).toBe(true);
  });

  it("defaults legacy summaries to key-required when has_api_key is present", () => {
    const provider: Provider = {
      ...baseProvider,
      has_api_key: false,
    };

    expect(providerRequiresApiKey(provider)).toBe(true);
    expect(providerHasMissingApiKey(provider)).toBe(true);
  });
});
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
rtk uv run pytest tests/test_api.py::test_mlx_audio_provider_summary_does_not_require_api_key tests/test_api.py::test_mlx_audio_tts_route_skips_api_key_readiness -q
rtk npm --prefix apps/web run test -- providerReadiness
```

Expected: FAIL because provider summary does not emit `requires_api_key`, readiness tries `env_values.get(None)`, and `providerReadiness.ts` does not exist.

- [ ] **Step 4: Update API provider summary**

Modify `_provider_summary()` in `apps/api/src/voice_toolbox_api/main.py`:

```python
    requires_api_key = provider_config.api_key_env is not None
    api_key = (
        env_values.get(provider_config.api_key_env)
        if provider_config.api_key_env is not None
        else None
    )
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider_config.type,
        "base_url": provider_config.base_url,
        "api_key_env": provider_config.api_key_env,
        "requires_api_key": requires_api_key,
        "has_api_key": bool(api_key),
        "api_key_preview": (
            mask_api_key_preview(api_key, trusted_local=trusted_local)
            if requires_api_key
            else None
        ),
    }
```

Keep the existing `config_path_preview`, `default_voice`, `default_models`,
`capabilities`, `options`, `models`, and `voices` keys in the same return dict.
Also add `"requires_api_key": False` to the unconfigured injected-provider summary branch.

- [ ] **Step 5: Update API operation readiness**

Modify `_ensure_provider_configured_for_operation()`:

```python
def _ensure_provider_configured_for_operation(request: Request, provider_id: str) -> None:
    config_provider = _configured_provider_for_id(request.app.state.config, provider_id)
    if config_provider is None:
        raise HTTPException(status_code=503, detail=f"provider {provider_id} is not configured")
    if config_provider.api_key_env is None:
        return
    value = request.app.state.env_values.get(config_provider.api_key_env)
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"{config_provider.api_key_env} is required for provider {provider_id}",
        )
```

- [ ] **Step 6: Update web local-provider readiness**

Modify `apps/web/src/api.ts` by adding this field to the existing `Provider` type:

```ts
requires_api_key?: boolean;
```

Create `apps/web/src/lib/providerReadiness.ts`:

```ts
import type { Provider } from "../api";

export function providerRequiresApiKey(provider: Provider | null | undefined): boolean {
  if (!provider) {
    return false;
  }
  if (provider.requires_api_key === false) {
    return false;
  }
  return provider.has_api_key !== undefined || Boolean(provider.api_key_env);
}

export function providerHasMissingApiKey(provider: Provider | null | undefined): boolean {
  return providerRequiresApiKey(provider) && provider?.has_api_key === false;
}
```

Modify `apps/web/src/components/Topbar.tsx`:

```ts
import { providerRequiresApiKey } from "../lib/providerReadiness";
```

Update `KeyStatus` so local providers render a ready local status before checking `has_api_key`:

```tsx
  if (!provider) {
    return <span className="status-badge">{t("keyStatus.unavailable")}</span>;
  }
  if (!providerRequiresApiKey(provider)) {
    return <span className="status-badge ok">{t("keyStatus.local")}</span>;
  }
  if (provider.has_api_key === undefined) {
    return <span className="status-badge">{t("keyStatus.unavailable")}</span>;
  }
```

Modify `apps/web/src/components/ProviderDetails.tsx`:

```ts
import { providerHasMissingApiKey, providerRequiresApiKey } from "../lib/providerReadiness";
```

Use those helpers:

```tsx
  const keyMissing = providerHasMissingApiKey(provider);
  const keyValue = providerRequiresApiKey(provider)
    ? provider.api_key_preview ??
      (provider.has_api_key ? t("providerDetails.configured") : t("providerDetails.missing"))
    : t("providerDetails.notRequired");
```

Then pass `keyValue` to the key `StatusItem`.

Add these keys to both English and Chinese dictionaries:

```ts
"keyStatus.local": "Local provider",
"providerDetails.notRequired": "not required",
```

```ts
"keyStatus.local": "本地提供方",
"providerDetails.notRequired": "无需密钥",
```

- [ ] **Step 7: Run tests and verify pass**

Run:

```bash
rtk uv run pytest tests/test_api.py::test_mlx_audio_provider_summary_does_not_require_api_key tests/test_api.py::test_mlx_audio_tts_route_skips_api_key_readiness -q
rtk npm --prefix apps/web run test -- providerReadiness
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
rtk git add apps/api/src/voice_toolbox_api/main.py tests/test_api.py apps/web/src/api.ts apps/web/src/components/Topbar.tsx apps/web/src/components/ProviderDetails.tsx apps/web/src/i18n/dictionaries.ts apps/web/src/lib/providerReadiness.ts apps/web/src/lib/providerReadiness.test.ts
rtk git commit -m "feat: support local provider readiness"
```

## Task 5: Docs And Smoke Guide

**Files:**
- Modify: `README.md`
- Modify: `voice_toolbox.toml.example`
- Create: `docs/smoke/mlx-audio.md`

- [ ] **Step 1: Write docs updates**

Add this section to `README.md` near provider setup:

````markdown
### MLX Audio on Apple Silicon

MLX Audio is optional and local-only. Install it only on Apple Silicon macOS:

```bash
rtk uv sync --extra mac
```

Enable it with a provider block:

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
default_voice = "Ryan"
```

The first MLX Audio version supports `tts.builtin`, `tts.clone`, and
`asr.transcribe`. Qwen3 clone requires `clone_reference_text` so the MLX model
takes its ICL voice-clone path.
````

Add this commented block to `voice_toolbox.toml.example`:

```toml
# Apple Silicon local provider. Requires: rtk uv sync --extra mac
# [[providers]]
# id = "mlx-audio"
# type = "mlx_audio"
# name = "MLX Audio"
# default_voice = "Ryan"
```

- [ ] **Step 2: Create smoke guide**

Create `docs/smoke/mlx-audio.md`:

````markdown
# MLX Audio Smoke Tests

These tests require Apple Silicon macOS and:

```bash
rtk uv sync --extra mac
```

## Provider Config

```toml
[[providers]]
id = "mlx-audio"
type = "mlx_audio"
name = "MLX Audio"
default_voice = "Ryan"
```

## Model-Specific Dependencies

| Model path | Extra dependency |
| --- | --- |
| Kokoro | `pip install misaki`; Japanese `pip install 'misaki[ja]'`; Mandarin `pip install 'misaki[zh]'` |
| Qwen3 ForcedAligner | Future alignment capability only; Japanese needs `pip install nagisa`, Korean needs `pip install soynlp` |
| Ming Omni BailingMM | May need `pip install onnx safetensors` if campplus conversion runs |
| Voxtral TTS | Covered by `mlx-audio[tts]` through `mistral-common[audio]` |
| Non-WAV encode/decode | Install host binary with `brew install ffmpeg` |

## Required Smoke Matrix

Run Qwen3 builtin TTS:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --text "Hello from MLX Audio." --voice Ryan
```

Run Qwen3 clone with transcript:

```bash
rtk uv run voice-toolbox tts clone --provider mlx-audio --text "This is the cloned voice." --sample ./reference.wav --reference-text "Exact transcript for the reference audio." --consent
```

Run Qwen3 ASR:

```bash
rtk uv run voice-toolbox asr transcribe --file ./speech.wav --provider mlx-audio --language auto
```

Run LongCat short WAV:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model longcat-audiodit-1b --text "Short LongCat smoke test." --voice default
```

Run Higgs Audio v3 only when memory allows:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model higgs-audio-v3-tts-4b --text "Short Higgs smoke test." --voice default
```

Run Ming Omni load/generate only on a machine with enough memory:

```bash
rtk uv run voice-toolbox tts synthesize --provider mlx-audio --model ming-omni-tts-16.8b-a3b --text "Short Ming Omni smoke test." --voice default
```
````

- [ ] **Step 3: Run docs checks**

Run:

```bash
rtk rg "mlx-audio|MLX Audio|voice-toolbox\\[mac\\]|Qwen3 ForcedAligner" README.md voice_toolbox.toml.example docs/smoke/mlx-audio.md
rtk uv run python - <<'PY'
from pathlib import Path
import re
import tomllib

smoke = Path("docs/smoke/mlx-audio.md").read_text(encoding="utf-8")
toml_blocks = re.findall(r"```toml\n(.*?)\n```", smoke, flags=re.S)
assert toml_blocks, "missing TOML block"
for block in toml_blocks:
    tomllib.loads(block)

example_lines = Path("voice_toolbox.toml.example").read_text(encoding="utf-8").splitlines()
start = next(
    index
    for index, line in enumerate(example_lines)
    if "Apple Silicon local provider" in line
)
example_block = []
for line in example_lines[start + 1 :]:
    if line == "#":
        if example_block:
            break
        continue
    if not line.startswith("# "):
        break
    example_block.append(line[2:])
tomllib.loads("\n".join(example_block))
PY
rtk uv run voice-toolbox tts synthesize --help
rtk uv run voice-toolbox tts clone --help
rtk uv run voice-toolbox asr transcribe --help
```

Expected: `rg` output includes all three docs files, TOML parsing succeeds, and CLI help commands exit 0.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add README.md voice_toolbox.toml.example docs/smoke/mlx-audio.md
rtk git commit -m "docs: document mlx audio provider"
```

## Task 6: Full Verification And Integration Review

**Files:**
- Verify all files changed by Tasks 1-5.

- [ ] **Step 1: Run focused tests**

Run:

```bash
rtk uv run pytest tests/test_mlx_audio_provider.py tests/test_provider_config.py tests/test_config.py tests/test_api.py -q
rtk npm --prefix apps/web run test -- providerReadiness
```

Expected: PASS.

- [ ] **Step 2: Run import tests**

Run:

```bash
rtk uv run pytest tests/test_imports.py -q
```

Expected: PASS, proving normal non-Mac imports do not require `mlx_audio`.

- [ ] **Step 3: Run lint**

Run:

```bash
rtk uv run ruff check packages/voice_toolbox/src apps/api/src tests
```

Expected: PASS.

- [ ] **Step 4: Run type check**

Run:

```bash
rtk uv run ty check
```

Expected: PASS.

- [ ] **Step 5: Inspect optional dependency metadata**

Run:

```bash
rtk uv run python - <<'PY'
import tomllib
data = tomllib.loads(open("pyproject.toml", "rb").read().decode())
print(data["project"]["optional-dependencies"]["mac"])
print(data["project"]["optional-dependencies"]["dev"])
PY
```

Expected: `mac` contains only the MLX Audio dependency, and `dev` contains no MLX dependency.

- [ ] **Step 6: Request review**

Dispatch an adversarial review with this scope:

```text
Review MLX Audio provider implementation against docs/superpowers/specs/2026-07-02-mlx-audio-provider-design.md and docs/superpowers/plans/2026-07-02-mlx-audio-provider.md. Focus on lazy imports, local provider config, model alias validation, clone ref_text enforcement, dependency hints, and non-Mac test safety.
```

Expected: reviewer returns no critical issues. Fix any verified critical or important issue before proceeding.

- [ ] **Step 7: Final commit if review fixes were needed**

If review fixes changed files, run:

```bash
rtk git add packages/voice_toolbox/src apps/api/src tests README.md voice_toolbox.toml.example docs/smoke/mlx-audio.md pyproject.toml
rtk git commit -m "fix: close mlx audio review gaps"
```

Expected: commit succeeds or no files are staged because no fixes were needed.

## Self-Review Checklist

- Spec coverage: dependency extra, local provider config, model aliases, TTS builtin, TTS clone, ASR, ForcedAligner rejection, dependency hints, API key skipping, docs, smoke tests, and verification all have tasks.
- Red-flag scan: no undefined markers, no vague edge handling, no unowned files.
- Type consistency: provider ids, method names, and request fields match existing `ConfiguredProvider`, `TTSRequest`, `ASRRequest`, `ProviderAudioResult`, and `TranscriptPayload`.
