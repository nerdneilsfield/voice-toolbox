from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from voice_toolbox.artifacts import SAFE_OPERATION_ID_PATTERN
from voice_toolbox.config import (
    AppConfig,
    ConfiguredProvider,
    load_app_config,
    load_env_values,
    mask_api_key_preview,
    preview_config_path,
)
from voice_toolbox.models import (
    ASRRequest,
    Artifact,
    OperationResult,
    OperationStatus,
    TTSMode,
    TTSRequest,
)
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE
from voice_toolbox.providers.registry import ProviderRegistry

CORS_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
DEFAULT_ARTIFACT_ROOT = Path.cwd()
SUPPORTED_UPLOAD_MIME_TYPES = {"audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3"}
MAX_UPLOAD_RAW_BYTES = (MAX_BASE64_AUDIO_SIZE // 4) * 3
MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}
SAFE_UPLOAD_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def create_app(
    *,
    registry: ProviderRegistry | None = None,
    artifact_root: Path | str | None = None,
    config: AppConfig | None = None,
    env_path: Path | str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> FastAPI:
    resolved_env_values = (
        dict(env_values) if env_values is not None else load_env_values(env_path)
    )
    if config is None:
        config = load_app_config(env_path=env_path, env_values=resolved_env_values)
    root = Path(artifact_root) if artifact_root is not None else _infer_artifact_root(registry)
    provider_registry = registry or build_provider_registry(
        config,
        artifact_root=root,
        env_values=resolved_env_values,
    )

    app = FastAPI(
        title="Voice Toolbox API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.provider_registry = provider_registry
    app.state.artifact_root = root
    app.state.config = config
    app.state.env_values = resolved_env_values

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/providers")
    def providers(http_request: Request) -> dict[str, list[dict[str, Any]]]:
        provider_registry = _registry_from_request(http_request)
        config = _config_from_request(http_request)
        env_values = _env_values_from_request(http_request)
        return {
            "providers": [
                _provider_summary(provider, config=config, env_values=env_values)
                for provider in provider_registry.list_providers()
            ]
        }

    @app.get("/v1/providers/{provider_id}/voices")
    def voices(provider_id: str, http_request: Request) -> dict[str, list[dict[str, Any]]]:
        provider_registry = _registry_from_request(http_request)
        provider = _get_provider(provider_registry, provider_id)
        return {"voices": [voice.model_dump(mode="json") for voice in provider.list_voices()]}

    @app.get("/v1/providers/{provider_id}/models")
    def models(provider_id: str, http_request: Request) -> dict[str, list[dict[str, Any]]]:
        provider_registry = _registry_from_request(http_request)
        provider = _get_provider(provider_registry, provider_id)
        return {"models": [model.model_dump(mode="json") for model in provider.list_models()]}

    @app.post("/v1/tts/synthesize")
    def synthesize(
        http_request: Request,
        sample: Annotated[UploadFile | None, File()] = None,
        provider_id: Annotated[str, Form()] = "mimo",
        mode: Annotated[TTSMode, Form()] = TTSMode.BUILTIN,
        text: Annotated[str | None, Form()] = None,
        voice_id: Annotated[str | None, Form()] = None,
        voice_description: Annotated[str | None, Form()] = None,
        optimize_text_preview: Annotated[bool, Form()] = False,
        consent_confirmed: Annotated[bool, Form()] = False,
        style_instruction: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        if sample is not None and mode != TTSMode.CLONE:
            raise HTTPException(
                status_code=422, detail="sample upload is only valid for clone mode"
            )
        if mode == TTSMode.BUILTIN:
            request = _build_tts_request(
                provider_id=provider_id,
                mode=TTSMode.BUILTIN,
                model=model,
                text=text,
                voice_id=voice_id,
                style_instruction=style_instruction,
            )
            return _run_tts(_registry_from_request(http_request), provider_id, request)
        if mode == TTSMode.DESIGN:
            request = _build_tts_request(
                provider_id=provider_id,
                mode=TTSMode.DESIGN,
                model=model,
                text=text,
                voice_description=voice_description,
                optimize_text_preview=optimize_text_preview,
            )
            return _run_tts(_registry_from_request(http_request), provider_id, request)
        if sample is None:
            raise HTTPException(status_code=422, detail="clone mode requires sample upload")
        return _run_clone_upload(
            http_request=http_request,
            sample=sample,
            provider_id=provider_id,
            text=text or "",
            consent_confirmed=consent_confirmed,
            style_instruction=style_instruction,
            model=model,
        )

    @app.post("/v1/tts/builtin")
    def synthesize_builtin(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        text: Annotated[str, Form()] = "",
        voice_id: Annotated[str, Form()] = "",
        style_instruction: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        request = _build_tts_request(
            provider_id=provider_id,
            mode=TTSMode.BUILTIN,
            model=model,
            text=text,
            voice_id=voice_id,
            style_instruction=style_instruction,
        )
        return _run_tts(_registry_from_request(http_request), provider_id, request)

    @app.post("/v1/tts/design")
    def synthesize_design(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        voice_description: Annotated[str, Form()] = "",
        text: Annotated[str | None, Form()] = None,
        optimize_text_preview: Annotated[bool, Form()] = False,
        model: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        request = _build_tts_request(
            provider_id=provider_id,
            mode=TTSMode.DESIGN,
            model=model,
            text=text,
            voice_description=voice_description,
            optimize_text_preview=optimize_text_preview,
        )
        return _run_tts(_registry_from_request(http_request), provider_id, request)

    @app.post("/v1/tts/clone")
    def synthesize_clone(
        http_request: Request,
        sample: Annotated[UploadFile, File()],
        provider_id: Annotated[str, Form()] = "mimo",
        text: Annotated[str, Form()] = "",
        consent_confirmed: Annotated[bool, Form()] = False,
        style_instruction: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        return _run_clone_upload(
            http_request=http_request,
            sample=sample,
            provider_id=provider_id,
            text=text,
            consent_confirmed=consent_confirmed,
            style_instruction=style_instruction,
            model=model,
        )

    @app.post("/v1/asr/transcribe")
    def transcribe(
        http_request: Request,
        file: Annotated[UploadFile, File()],
        provider_id: Annotated[str, Form()] = "mimo",
        model: Annotated[str, Form()] = "mimo-v2.5-asr",
        language: Annotated[Literal["auto", "zh", "en"], Form()] = "auto",
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        contents = _read_upload(file)
        mime_type = _normalize_mime_type(file.content_type)
        suffix = _suffix_for_upload(file.filename)
        _validate_upload_signature(contents, mime_type, suffix)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / _safe_upload_filename(file.filename, suffix)
            temp_path.write_bytes(contents)
            request = _build_asr_request(
                provider_id=provider_id,
                model=model,
                audio_path=temp_path,
                mime_type=mime_type,
                raw_byte_size=len(contents),
                base64_size=_base64_size(contents),
                language=language,
            )
            provider_registry = _registry_from_request(http_request)
            provider = _ensure_asr_provider(provider_registry, provider_id, request)
            started_at = datetime.now(UTC)
            try:
                artifact = provider.transcribe(request)
            except ProviderError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            finished_at = datetime.now(UTC)
            return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)

    @app.get("/v1/artifacts/{artifact_id}")
    def artifact_metadata(artifact_id: str) -> dict[str, Any]:
        artifact = _read_artifact_sidecar(root, artifact_id)
        return _safe_artifact_payload(artifact)

    @app.get("/v1/artifacts/{artifact_id}/download")
    def artifact_download(artifact_id: str) -> FileResponse:
        artifact = _read_artifact_sidecar(root, artifact_id)
        path = artifact.path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact file not found")
        return FileResponse(path, media_type=artifact.mime_type, filename=path.name)

    return app


def _infer_artifact_root(registry: ProviderRegistry | None) -> Path:
    if registry is not None:
        for provider in registry.list_providers():
            artifact_root = getattr(provider, "artifact_root", None)
            if artifact_root is not None:
                return Path(artifact_root)
    return DEFAULT_ARTIFACT_ROOT


def _registry_from_request(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


def _config_from_request(request: Request) -> AppConfig:
    return request.app.state.config


def _env_values_from_request(request: Request) -> dict[str, str]:
    return request.app.state.env_values


def _configured_provider_for_id(
    config: AppConfig,
    provider_id: str,
) -> ConfiguredProvider | None:
    return next((provider for provider in config.providers if provider.id == provider_id), None)


def _provider_summary(
    provider: Any,
    *,
    config: AppConfig,
    env_values: Mapping[str, str],
) -> dict[str, Any]:
    provider_config = _configured_provider_for_id(config, provider.id)
    if provider_config is None:
        return {
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
            "voices": [voice.model_dump(mode="json") for voice in provider.list_voices()],
        }

    api_key = env_values.get(provider_config.api_key_env)
    trusted_local = config.api.host in {"127.0.0.1", "localhost"}
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider_config.type,
        "base_url": provider_config.base_url,
        "api_key_env": provider_config.api_key_env,
        "has_api_key": bool(api_key),
        "api_key_preview": mask_api_key_preview(api_key, trusted_local=trusted_local),
        "config_path_preview": preview_config_path(config.config_path),
        "default_voice": provider_config.default_voice,
        "default_models": (
            provider_config.default_models.model_dump(mode="json")
            if provider_config.default_models is not None
            else {}
        ),
        "capabilities": sorted(provider.capabilities()),
        "models": [model.model_dump(mode="json") for model in provider.list_models()],
        "voices": [voice.model_dump(mode="json") for voice in provider.list_voices()],
    }


def _get_provider(provider_registry: ProviderRegistry, provider_id: str) -> Any:
    try:
        return provider_registry.get(provider_id)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _ensure_tts_provider(
    provider_registry: ProviderRegistry,
    provider_id: str,
    request: TTSRequest,
) -> Any:
    try:
        return provider_registry.ensure_tts_capability(provider_id, request)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ensure_asr_provider(
    provider_registry: ProviderRegistry,
    provider_id: str,
    request: ASRRequest,
) -> Any:
    try:
        return provider_registry.ensure_asr_capability(provider_id, request)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _build_tts_request(**kwargs: Any) -> TTSRequest:
    try:
        return TTSRequest(**kwargs)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_safe_validation_errors(exc)) from exc


def _build_asr_request(**kwargs: Any) -> ASRRequest:
    try:
        return ASRRequest(**kwargs)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_safe_validation_errors(exc)) from exc


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {key: error[key] for key in ("loc", "msg", "type") if key in error}
        for error in exc.errors()
    ]


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


def _run_clone_upload(
    *,
    http_request: Request,
    sample: UploadFile,
    provider_id: str,
    text: str,
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
        request = _build_tts_request(
            provider_id=provider_id,
            mode=TTSMode.CLONE,
            model=model,
            text=text,
            style_instruction=style_instruction,
            clone_sample_path=temp_path,
            clone_mime_type=mime_type,
            clone_raw_byte_size=len(contents),
            clone_base64_size=_base64_size(contents),
            consent_confirmed=consent_confirmed,
        )
        return _run_tts(_registry_from_request(http_request), provider_id, request)


def _run_tts(
    provider_registry: ProviderRegistry,
    provider_id: str,
    request: TTSRequest,
) -> dict[str, Any]:
    provider = _ensure_tts_provider(provider_registry, provider_id, request)
    started_at = datetime.now(UTC)
    try:
        artifact = provider.synthesize(request)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finished_at = datetime.now(UTC)
    return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)


def _operation_payload(
    artifact: Artifact,
    *,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    operation = OperationResult(
        operation_id=artifact.id,
        operation=artifact.operation,
        status=OperationStatus.COMPLETED,
        started_at=started_at,
        finished_at=finished_at,
        artifact_ids=[artifact.id],
    )
    return {
        "operation": operation.model_dump(mode="json"),
        "artifact": _safe_artifact_payload(artifact),
    }


def _safe_artifact_payload(artifact: Artifact) -> dict[str, Any]:
    payload = artifact.model_dump(mode="json", exclude={"path"})
    payload["download_url"] = f"/v1/artifacts/{artifact.id}/download"
    return payload


def _read_upload(upload: UploadFile) -> bytes:
    contents = upload.file.read(MAX_UPLOAD_RAW_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=422, detail="upload file is empty")
    if len(contents) > MAX_UPLOAD_RAW_BYTES or _base64_size(contents) > MAX_BASE64_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="audio base64 payload exceeds 10 MiB")
    return contents


def _normalize_mime_type(mime_type: str | None) -> Literal["audio/wav", "audio/mpeg", "audio/mp3"]:
    base_type = (mime_type or "").split(";", maxsplit=1)[0].strip().lower()
    if base_type in {"audio/x-wav", "audio/wave"}:
        normalized = "audio/wav"
    elif base_type == "audio/mp3":
        normalized = "audio/mpeg"
    else:
        normalized = base_type
    if normalized not in SUPPORTED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=422, detail="audio MIME type must be wav or mp3")
    return cast(Literal["audio/wav", "audio/mpeg", "audio/mp3"], normalized)


def _suffix_for_upload(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".wav", ".mp3"}:
        raise HTTPException(status_code=422, detail="audio file suffix must be .wav or .mp3")
    return suffix


def _validate_upload_signature(contents: bytes, mime_type: str, suffix: str) -> None:
    expected_mime = MIME_BY_SUFFIX[suffix]
    if mime_type != expected_mime:
        raise HTTPException(status_code=422, detail="audio MIME type does not match file suffix")
    if suffix == ".wav" and not (contents.startswith(b"RIFF") and contents[8:12] == b"WAVE"):
        raise HTTPException(status_code=422, detail="wav upload must start with RIFF/WAVE header")
    if suffix == ".mp3" and not (
        contents.startswith(b"ID3")
        or (len(contents) >= 2 and contents[0] == 0xFF and contents[1] & 0xE0 == 0xE0)
    ):
        raise HTTPException(status_code=422, detail="mp3 upload must start with ID3 or frame sync")


def _safe_upload_filename(filename: str | None, suffix: str) -> str:
    raw_name = Path(filename or f"upload{suffix}").name
    sanitized = SAFE_UPLOAD_NAME_PATTERN.sub("_", raw_name).strip("._")
    if not sanitized.lower().endswith(suffix):
        sanitized = f"{sanitized or 'upload'}{suffix}"
    return sanitized


def _base64_size(contents: bytes) -> int:
    return ((len(contents) + 2) // 3) * 4


def _read_artifact_sidecar(root: Path, artifact_id: str) -> Artifact:
    if not SAFE_OPERATION_ID_PATTERN.fullmatch(artifact_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    matches = sorted(artifact_root.glob(f"*/{artifact_id}.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        with matches[-1].open(encoding="utf-8") as sidecar_file:
            payload = json.load(sidecar_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    if "path" not in payload:
        payload["path"] = str(_artifact_path_for_sidecar(matches[-1], payload))
    try:
        artifact = Artifact.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    if artifact.id != artifact_id:
        raise HTTPException(status_code=422, detail="artifact sidecar id mismatch")
    path = artifact.path.resolve(strict=False)
    if not path.is_relative_to(artifact_root):
        raise HTTPException(status_code=422, detail="artifact path is outside artifact root")
    return artifact.model_copy(update={"path": path})


def _artifact_path_for_sidecar(sidecar_path: Path, payload: dict[str, Any]) -> Path:
    mime_type = payload.get("mime_type")
    suffix = ".txt" if mime_type == "text/plain; charset=utf-8" else ".wav"
    return sidecar_path.with_suffix(suffix)
