# Voice Toolbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-first Voice Toolbox MVP with MiMo-backed TTS and ASR, CLI-first workflows, a FastAPI backend, and a React toolbox UI.

**Architecture:** A Python core package owns typed models, validation, MiMo provider calls, artifact storage, and CLI commands. FastAPI and React sit on top of that core without provider-specific logic in the UI. Provider calls are synchronous in v1; provider protocol methods are normal `def` methods, FastAPI handlers may also be normal `def` handlers, and artifacts plus redacted metadata are persisted locally.

**Tech Stack:** Python 3.11+, `uv`, Pydantic, OpenAI Python SDK, Typer, FastAPI, SQLite, pytest, React, TypeScript, Vite, bun.

---

## File Structure

- `pyproject.toml`: root Python package metadata, dependencies, console script, pytest config.
- `.env.example`: local MiMo config template.
- `.gitignore`: add local DB and artifact ignores while keeping `.gitkeep`.
- `packages/voice_toolbox/src/voice_toolbox/`: core Python package.
- `packages/voice_toolbox/src/voice_toolbox/models.py`: Pydantic models and enums.
- `packages/voice_toolbox/src/voice_toolbox/settings.py`: `.env` loading and API key status.
- `packages/voice_toolbox/src/voice_toolbox/artifacts.py`: artifact naming, writing, sidecar metadata redaction.
- `packages/voice_toolbox/src/voice_toolbox/storage.py`: SQLite setup with WAL and busy timeout.
- `packages/voice_toolbox/src/voice_toolbox/providers/base.py`: provider protocol and errors.
- `packages/voice_toolbox/src/voice_toolbox/providers/registry.py`: capability preflight and provider lookup.
- `packages/voice_toolbox/src/voice_toolbox/providers/fake.py`: fake provider for tests and API validation.
- `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`: MiMo request construction and synchronous calls.
- `packages/voice_toolbox/src/voice_toolbox/cli.py`: Typer CLI.
- `packages/voice_toolbox/src/voice_toolbox/__main__.py`: `python -m voice_toolbox` entry.
- `apps/api/src/voice_toolbox_api/main.py`: FastAPI app and `/v1` routes.
- Root `pyproject.toml` packages both `voice_toolbox` and `voice_toolbox_api` by including both source roots. There is no separate `apps/api/pyproject.toml` in v1.
- `apps/web/`: Vite React app.
- `tests/`: unit and integration tests.
- `docs/smoke/mimo.md`: real MiMo smoke test checklist.

## Task 1: Project Skeleton And Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `packages/voice_toolbox/src/voice_toolbox/__init__.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/__main__.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/cli.py`
- Create: `tests/test_imports.py`
- Create: `.env.example`
- Create: `data/artifacts/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Write the import smoke test**

Create `tests/test_imports.py`:

```python
def test_core_package_imports() -> None:
    import voice_toolbox

    assert voice_toolbox.__version__ == "0.1.0"
```

- [ ] **Step 2: Add package skeleton**

Create `packages/voice_toolbox/src/voice_toolbox/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `packages/voice_toolbox/src/voice_toolbox/cli.py`:

```python
import typer

app = typer.Typer(help="Voice Toolbox")


@app.callback()
def main() -> None:
    """Run Voice Toolbox commands."""
```

Create `packages/voice_toolbox/src/voice_toolbox/__main__.py`:

```python
from voice_toolbox.cli import app


if __name__ == "__main__":
    app()
```

- [ ] **Step 3: Add root Python project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "voice-toolbox"
version = "0.1.0"
description = "Local-first voice toolbox for TTS and ASR providers"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "openai>=1.0",
  "pydantic>=2.0",
  "python-dotenv>=1.0",
  "python-multipart>=0.0.9",
  "typer>=0.12",
  "uvicorn>=0.30",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project.optional-dependencies]
dev = [
  "httpx>=0.27",
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "ruff>=0.6",
]

[project.scripts]
voice-toolbox = "voice_toolbox.cli:app"

[tool.uv]
package = true

[tool.setuptools.packages.find]
where = ["packages/voice_toolbox/src", "apps/api/src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["packages/voice_toolbox/src", "apps/api/src"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 4: Add environment template and artifact ignore rules**

Create `.env.example`:

```dotenv
MIMO_API_KEY=
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
API_HOST=127.0.0.1
API_PORT=8000
```

Append these lines to `.gitignore`:

```gitignore
# Voice Toolbox local data
data/voice_toolbox.sqlite
data/voice_toolbox.sqlite-*
data/artifacts/*
!data/artifacts/.gitkeep
```

- [ ] **Step 5: Run the smoke test**

Run:

```bash
rtk uv run pytest tests/test_imports.py -v
```

Expected: one passing test.

- [ ] **Step 6: Commit**

```bash
rtk git add pyproject.toml .env.example .gitignore data/artifacts/.gitkeep packages/voice_toolbox/src/voice_toolbox tests/test_imports.py
rtk git commit -m "chore: scaffold voice toolbox project"
```

## Task 2: Domain Models, Settings, Storage, And Artifacts

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/models.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/settings.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/storage.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/artifacts.py`
- Create: `tests/test_models.py`
- Create: `tests/test_artifacts.py`

- [ ] **Step 1: Write model validation tests**

Create `tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from voice_toolbox.models import ASRRequest, ModelInfo, OperationResult, TTSMode, TTSRequest, VoiceInfo


def test_tts_design_allows_missing_text_when_optimized() -> None:
    request = TTSRequest(
        provider_id="mimo",
        mode=TTSMode.DESIGN,
        voice_description="young warm male voice",
        optimize_text_preview=True,
        output_format="wav",
    )

    assert request.text is None


def test_tts_design_requires_text_without_optimization() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(
            provider_id="mimo",
            mode=TTSMode.DESIGN,
            voice_description="young warm male voice",
            optimize_text_preview=False,
            output_format="wav",
        )


def test_tts_output_format_is_wav_only() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(
            provider_id="mimo",
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="Mia",
            output_format="mp3",
        )


def test_asr_language_is_limited() -> None:
    request = ASRRequest(
        provider_id="mimo",
        audio_path="sample.wav",
        mime_type="audio/wav",
        raw_byte_size=100,
        base64_size=136,
        language="auto",
    )

    assert request.language == "auto"


def test_provider_info_models_have_required_fields() -> None:
    model = ModelInfo(id="mimo-v2.5-tts", name="MiMo TTS")
    voice = VoiceInfo(id="mimo_default", name="MiMo-默认", note="cluster-dependent")

    assert model.id == "mimo-v2.5-tts"
    assert voice.note == "cluster-dependent"


def test_operation_result_has_timestamps() -> None:
    result = OperationResult(
        operation_id="op_123",
        operation="tts.synthesize",
        status="completed",
        started_at="2026-06-26T12:00:00Z",
        finished_at="2026-06-26T12:00:01Z",
    )

    assert result.started_at.endswith("Z")
```

- [ ] **Step 2: Implement domain models**

Create `packages/voice_toolbox/src/voice_toolbox/models.py`:

```python
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TTSMode(StrEnum):
    BUILTIN = "builtin"
    DESIGN = "design"
    CLONE = "clone"


class ArtifactKind(StrEnum):
    AUDIO = "audio"
    TRANSCRIPT = "transcript"


class OperationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderConfig(BaseModel):
    provider_id: str = "mimo"
    base_url: str = "https://api.xiaomimimo.com/v1"
    api_key_env: str = "MIMO_API_KEY"
    default_output_format: Literal["wav"] = "wav"


class ModelInfo(BaseModel):
    id: str
    name: str
    capability: str | None = None
    note: str | None = None


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    note: str | None = None


class TTSRequest(BaseModel):
    provider_id: str = "mimo"
    mode: TTSMode
    model: str | None = None
    text: str | None = None
    style_instruction: str | None = None
    output_format: Literal["wav"] = "wav"
    voice_id: str | None = None
    voice_description: str | None = None
    optimize_text_preview: bool = False
    clone_sample_path: Path | None = None
    clone_mime_type: str | None = None
    clone_raw_byte_size: int | None = Field(default=None, ge=0)
    clone_base64_size: int | None = Field(default=None, ge=0)
    consent_confirmed: bool = False

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "TTSRequest":
        if self.mode == TTSMode.BUILTIN:
            if not self.text:
                raise ValueError("text is required for built-in TTS")
            if not self.voice_id:
                raise ValueError("voice_id is required for built-in TTS")
        if self.mode == TTSMode.DESIGN:
            if not self.voice_description:
                raise ValueError("voice_description is required for voice design")
            if not self.optimize_text_preview and not self.text:
                raise ValueError("text is required unless optimize_text_preview is true")
        if self.mode == TTSMode.CLONE:
            if not self.text:
                raise ValueError("text is required for voice clone")
            if not self.clone_sample_path or not self.clone_mime_type:
                raise ValueError("clone sample path and MIME type are required")
            if not self.consent_confirmed:
                raise ValueError("consent is required for voice clone")
        return self


class ASRRequest(BaseModel):
    provider_id: str = "mimo"
    model: str = "mimo-v2.5-asr"
    audio_path: Path
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp3"]
    raw_byte_size: int = Field(ge=0)
    base64_size: int = Field(ge=0)
    language: Literal["auto", "zh", "en"] = "auto"


class Artifact(BaseModel):
    id: str
    kind: ArtifactKind
    provider_id: str
    operation: str
    path: Path
    mime_type: str
    created_at: str
    metadata: dict[str, str | int | bool | None]


class AudioArtifact(Artifact):
    kind: Literal[ArtifactKind.AUDIO] = ArtifactKind.AUDIO


class TranscriptArtifact(Artifact):
    kind: Literal[ArtifactKind.TRANSCRIPT] = ArtifactKind.TRANSCRIPT


class OperationResult(BaseModel):
    operation_id: str
    operation: str
    status: OperationStatus
    started_at: str
    finished_at: str
    artifact_ids: list[str] = Field(default_factory=list)
    error_summary: str | None = None
```

- [ ] **Step 3: Write artifact tests**

Create `tests/test_artifacts.py`:

```python
import json

from voice_toolbox.artifacts import ArtifactStore, redact_metadata


def test_redaction_allowlist_excludes_secret_and_data_url() -> None:
    result = redact_metadata(
        {
            "provider_id": "mimo",
            "api_key": "tp-secret",
            "data_url": "data:audio/wav;base64,abc",
            "source_text": "hello world",
            "base64_size": 128,
        }
    )

    assert result == {
        "provider_id": "mimo",
        "source_text_length": 11,
        "base64_size": 128,
    }


def test_artifact_store_writes_transcript_and_sidecar(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path)

    artifact = store.write_transcript(
        operation_id="op_123",
        provider_id="mimo",
        operation="asr.transcribe",
        text="hello",
        metadata={"provider_id": "mimo", "source_text": "hello"},
    )

    assert artifact.path.name == "op_123.txt"
    assert artifact.mime_type == "text/plain; charset=utf-8"
    assert artifact.path.read_text() == "hello"
    sidecar = artifact.path.with_suffix(".json")
    assert json.loads(sidecar.read_text())["metadata"]["source_text_length"] == 5


def test_storage_creates_tables(tmp_path) -> None:
    from voice_toolbox.storage import MetadataStore

    db_path = tmp_path / "voice_toolbox.sqlite"
    store = MetadataStore(db_path)
    tables = store.table_names()

    assert {"artifacts", "operations"}.issubset(tables)
```

- [ ] **Step 4: Implement settings, storage, and artifact helpers**

Create `packages/voice_toolbox/src/voice_toolbox/settings.py` with `.env` loading and key status. Create `storage.py` with `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `CREATE TABLE IF NOT EXISTS artifacts (...)`, `CREATE TABLE IF NOT EXISTS operations (...)`, and insert helpers for both tables. Create `artifacts.py` with `ArtifactStore`, `write_audio`, `write_transcript`, and `redact_metadata`. `ArtifactStore` receives `operation_id` from the caller and creates `data/artifacts/YYYYMMDD/` directories before writing. Redaction mapping must be explicit: `source_text -> source_text_length`, `style_instruction -> style_instruction_length`, and `voice_description -> voice_description_length`.

- [ ] **Step 5: Run tests**

```bash
rtk uv run pytest tests/test_models.py tests/test_artifacts.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox tests/test_models.py tests/test_artifacts.py
rtk git commit -m "feat: add core models and artifact storage"
```

## Task 3: Provider Contract, Registry, And Fake Provider

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/__init__.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/base.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/registry.py`
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/fake.py`
- Create: `tests/test_provider_registry.py`

- [ ] **Step 1: Write registry tests**

Create `tests/test_provider_registry.py`:

```python
import pytest

from voice_toolbox.models import TTSMode, TTSRequest
from voice_toolbox.providers.base import UnsupportedCapability
from voice_toolbox.providers.fake import FakeProvider
from voice_toolbox.providers.registry import ProviderRegistry


def test_registry_blocks_unsupported_tts_mode() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])
    request = TTSRequest(
        provider_id="fake",
        mode=TTSMode.DESIGN,
        voice_description="warm voice",
        optimize_text_preview=True,
    )

    with pytest.raises(UnsupportedCapability):
        registry.ensure_tts_capability("fake", request)


def test_registry_allows_supported_tts_mode() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])
    request = TTSRequest(
        provider_id="fake",
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="Mia",
    )

    assert registry.ensure_tts_capability("fake", request).id == "fake"


def test_registry_blocks_unsupported_asr() -> None:
    registry = ProviderRegistry([FakeProvider(capabilities={"tts.builtin"})])

    with pytest.raises(UnsupportedCapability):
        registry.ensure_asr_capability("fake")
```

- [ ] **Step 2: Implement provider protocol and registry**

Create `base.py` with synchronous `VoiceProvider` `Protocol`, `ProviderError`, and `UnsupportedCapability`. The protocol returns `list[ModelInfo]`, `list[VoiceInfo]`, `AudioArtifact`, and `TranscriptArtifact`. Create `registry.py` with mode-to-capability mapping:

```python
TTS_MODE_CAPABILITIES = {
    TTSMode.BUILTIN: "tts.builtin",
    TTSMode.DESIGN: "tts.design",
    TTSMode.CLONE: "tts.clone",
}
```

`ensure_tts_capability()` and `ensure_asr_capability()` return the provider or raise `UnsupportedCapability`.

- [ ] **Step 3: Implement fake provider**

Create `fake.py` with a provider that returns fixed models/voices and writes deterministic fake artifacts through an injected `ArtifactStore`.

- [ ] **Step 4: Run tests**

```bash
rtk uv run pytest tests/test_provider_registry.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/providers tests/test_provider_registry.py
rtk git commit -m "feat: add provider registry"
```

## Task 4: MiMo Provider Request Construction And Validation

**Files:**
- Create: `packages/voice_toolbox/src/voice_toolbox/providers/mimo.py`
- Create: `tests/test_mimo_provider.py`

- [ ] **Step 1: Write MiMo request construction tests**

Create `tests/test_mimo_provider.py` with tests for:

```python
def test_builtin_tts_places_tags_in_assistant_content() -> None:
    ...


def test_design_optimized_preview_omits_assistant_message_when_text_missing() -> None:
    ...


def test_clone_builds_data_url_and_never_metadata_payload(tmp_path) -> None:
    ...


def test_asr_uses_chat_completions_input_audio_and_extra_body(tmp_path) -> None:
    ...


def test_bearer_auth_client_is_created_from_api_key() -> None:
    ...
```

The optimized preview test must assert that when `optimize_text_preview=True` and `text is None`, the `messages` array contains only the `user` role and no empty assistant message.

- [ ] **Step 2: Implement MiMo constants and validators**

In `mimo.py`, define:

```python
MIMO_MODELS = [
    {"id": "mimo-v2.5-tts", "capability": "tts.builtin"},
    {"id": "mimo-v2.5-tts-voicedesign", "capability": "tts.design"},
    {"id": "mimo-v2.5-tts-voiceclone", "capability": "tts.clone"},
    {"id": "mimo-v2.5-asr", "capability": "asr.transcribe"},
]

MIMO_VOICES = [
    {"id": "mimo_default", "name": "MiMo-默认", "note": "cluster-dependent"},
    {"id": "冰糖", "name": "冰糖", "language": "zh", "gender": "female"},
    {"id": "茉莉", "name": "茉莉", "language": "zh", "gender": "female"},
    {"id": "苏打", "name": "苏打", "language": "zh", "gender": "male"},
    {"id": "白桦", "name": "白桦", "language": "zh", "gender": "male"},
    {"id": "Mia", "name": "Mia", "language": "en", "gender": "female"},
    {"id": "Chloe", "name": "Chloe", "language": "en", "gender": "female"},
    {"id": "Milo", "name": "Milo", "language": "en", "gender": "male"},
    {"id": "Dean", "name": "Dean", "language": "en", "gender": "male"},
]
```

Add a 10 MiB base64-size validator for clone and ASR. Keep `wav` as the only TTS output format.

Resolve TTS model IDs at provider entry: if `request.model` is set, use it; otherwise map `builtin -> mimo-v2.5-tts`, `design -> mimo-v2.5-tts-voicedesign`, and `clone -> mimo-v2.5-tts-voiceclone`.

- [ ] **Step 3: Implement request builders before live calls**

Implement pure builder methods:

- `_build_tts_body(request: TTSRequest) -> dict`
- `_build_asr_body(request: ASRRequest, audio_data_url: str) -> dict`
- `_audio_file_to_data_url(path: Path, mime_type: str) -> tuple[str, int, int]`

The TTS builder must keep audio tags inside `assistant.content`. It must put natural-language style instructions in `user.content`. It must not add an assistant message when design `optimize_text_preview=True` and `text is None`.

- [ ] **Step 4: Implement synchronous provider calls**

Implement `MimoProvider.synthesize()` and `MimoProvider.transcribe()` with the OpenAI SDK. Use SDK `api_key` and `base_url`. Do not add custom `api-key` header in v1. Use:

- TTS timeout: 60 seconds.
- ASR timeout: 90 seconds.
- Retry 429 once with bounded backoff.
- Do not retry `APIConnectionError`, `APITimeoutError`, HTTP 500/502/503/504, validation
  errors, or non-429 4xx errors for generation calls because the provider may have
  accepted the request body and a retry can double bill.

- [ ] **Step 5: Run provider tests**

```bash
rtk uv run pytest tests/test_mimo_provider.py -v
```

Expected: all tests pass without real MiMo credentials.

- [ ] **Step 6: Optionally run one early real MiMo smoke test**

Run only when `MIMO_API_KEY` is available:

```bash
rtk uv run voice-toolbox tts synthesize --text "你好，MiMo smoke test。" --voice 冰糖 --format wav
```

Expected: command writes a wav artifact. This verifies Bearer auth, default `https://api.xiaomimimo.com/v1`, and the Chat Completions body before API/UI work begins. If it fails due to auth header shape, add an `api-key` header fallback in `MimoProvider` and cover it with a test before proceeding.

- [ ] **Step 7: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/providers/mimo.py tests/test_mimo_provider.py
rtk git commit -m "feat: add mimo provider"
```

## Task 5: CLI Commands

**Files:**
- Modify: `packages/voice_toolbox/src/voice_toolbox/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI tests with fake provider**

Create tests for:

- `tts synthesize --text ... --voice ...`
- `tts design --description ... --optimize-text-preview` without `--text`
- `tts clone --sample ...` fails without consent in non-TTY mode
- `asr transcribe --file ... --language auto`

Use Typer `CliRunner` and monkeypatch provider registry to fake provider.

- [ ] **Step 2: Implement command groups**

Add Typer groups:

```text
voice-toolbox tts synthesize
voice-toolbox tts design
voice-toolbox tts clone
voice-toolbox asr transcribe
```

`tts clone` rules:

- If `--consent` is present, proceed.
- If `--consent` is absent and `sys.stdin.isatty()` is true, prompt for confirmation.
- If `--consent` is absent and there is no TTY, fail with a clear message.

- [ ] **Step 3: Run CLI tests**

```bash
rtk uv run pytest tests/test_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
rtk git add packages/voice_toolbox/src/voice_toolbox/cli.py tests/test_cli.py
rtk git commit -m "feat: add voice toolbox cli"
```

## Task 6: FastAPI Backend

**Files:**
- Create: `apps/api/src/voice_toolbox_api/__init__.py`
- Create: `apps/api/src/voice_toolbox_api/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write API tests**

Create tests for:

- `GET /v1/health`
- `GET /v1/providers`
- `GET /v1/providers` includes `has_api_key: bool` for MiMo setup status.
- `GET /v1/providers/mimo/voices` returns hard-coded MiMo voices.
- `POST /v1/asr/transcribe` accepts multipart upload, normalizes to provider model, and returns an operation result.
- `GET /v1/artifacts/{id}` returns JSON metadata.
- `GET /v1/artifacts/{id}/download` returns bytes.
- CORS allows `http://127.0.0.1:5173`.

- [ ] **Step 2: Implement FastAPI app**

In `main.py`, create `create_app()` and `app = create_app()`. Add CORS with `http://127.0.0.1:5173`. Bind address is a run command concern, but docs and scripts must use `127.0.0.1:8000`.

Routes must be under `/v1`. File-upload routes accept multipart form data and pass normalized models to the core provider layer. Do not expose provider base64 payloads through API responses.

- [ ] **Step 3: Run API tests**

```bash
rtk uv run pytest tests/test_api.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
rtk git add apps/api/src/voice_toolbox_api tests/test_api.py
rtk git commit -m "feat: add voice toolbox api"
```

## Task 7: React Toolbox UI

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/index.html`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/App.tsx`
- Create: `apps/web/src/api.ts`
- Create: `apps/web/src/styles.css`

- [ ] **Step 1: Scaffold Vite React app files**

Use `bun` with Vite + React + TypeScript. Configure Vite dev server host `127.0.0.1`, port `5173`, and proxy `/v1` to `http://127.0.0.1:8000`.

- [ ] **Step 2: Implement API client**

Create `api.ts` with functions:

- `getProviders()`
- `getVoices(providerId)`
- `synthesizeBuiltin(form)`
- `designVoice(form)`
- `cloneVoice(formData)`
- `transcribe(formData)`

All calls use `/v1/*` relative URLs so the dev proxy works and same-origin serving remains possible.

- [ ] **Step 3: Implement single-page UI**

In `App.tsx`, implement:

- Top-level tabs: TTS and ASR.
- TTS segmented modes: Built-in, Design, Clone.
- Built-in text area with tag insertion buttons.
- Style instruction field for natural-language control.
- Output format fixed to `wav`.
- Design mode with optional target text when optimize preview is enabled.
- Clone mode with file upload, consent checkbox, and base64-size warning copy.
- ASR mode with file upload and language selector `auto`, `zh`, `en`.
- Artifact download link and audio player for TTS results.
- Transcript viewer for ASR results.
- API key status display based on backend provider status, never the key value.

- [ ] **Step 4: Run frontend checks**

```bash
rtk bun install --cwd apps/web
rtk bun run --cwd apps/web build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
rtk git add apps/web
rtk git commit -m "feat: add voice toolbox web ui"
```

## Task 8: Smoke Test Documentation And Final Verification

**Files:**
- Create: `docs/smoke/mimo.md`
- Modify: `README.md`

- [ ] **Step 1: Write MiMo smoke checklist**

Create `docs/smoke/mimo.md` with commands for:

- Bearer-auth built-in TTS with `冰糖`.
- Built-in TTS with `(唱歌)` tag in Chinese lyrics.
- Voice design with `--optimize-text-preview` and no target text.
- Voice clone with a small wav sample and `--consent`.
- ASR with short wav.
- ASR with short mp3.
- Token Plan base URL smoke tests as optional advanced checks.
- Future mp3 output verification as a disabled check before enabling mp3 output.

- [ ] **Step 2: Update README**

Update `README.md` with:

- Setup using `uv`.
- Frontend setup using `bun`.
- `.env` setup from `.env.example`.
- API server command binding `127.0.0.1:8000`.
- Web dev command binding `127.0.0.1:5173`.
- CLI examples for TTS and ASR.
- Note that clone samples are temporary and not stored as artifacts.

- [ ] **Step 3: Run full tests and build**

```bash
rtk uv run pytest -v
rtk bun run --cwd apps/web build
```

Expected: all Python tests pass and web build succeeds.

- [ ] **Step 4: Commit**

```bash
rtk git add README.md docs/smoke/mimo.md
rtk git commit -m "docs: add smoke tests and setup guide"
```

## Self-Review Checklist

- Spec coverage: TTS built-in, design, clone, audio tags, ASR Chat Completions, `.env`, artifacts, CORS, WAL, timeout/retry, redaction, CLI, API, and UI each map to tasks above.
- Non-blocking review points handled in plan:
  - Generation retry semantics: Task 4 says to retry only 429 once and not retry
    connection/timeouts/5xx for TTS/ASR.
  - `optimize_text_preview`: Task 4 says omit assistant role when text is absent.
  - CLI consent: Task 5 says non-TTY without `--consent` fails.
  - CORS origin: Task 6 and Task 7 use `http://127.0.0.1:5173`.
  - Bearer auth: Task 4 and Task 8 smoke it first.
- Placeholder scan: no task relies on undefined later work.
- Type consistency: request model names, route names, CLI command names, artifact names, and provider methods match across tasks.
