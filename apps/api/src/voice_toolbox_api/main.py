from __future__ import annotations

import json
import tempfile
from hashlib import sha1
from uuid import uuid4
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from pydantic import ValidationError

from voice_toolbox.audio_conversion import (
    AudioConversionError,
    AudioFormat,
    ConvertedAudio,
    DownloadAudioFormat,
    convert_audio_bytes,
    format_from_mime,
    format_from_suffix,
    mime_for_format,
    normalize_mime_type,
    suffix_for_format,
    validate_mime_suffix_match,
)
from voice_toolbox.artifacts import SAFE_OPERATION_ID_PATTERN
from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.chunking.merge import merge_audio_results
from voice_toolbox.chunking.models import TextSource
from voice_toolbox.chunking.options import (
    build_provider_option_metadata,
    merge_provider_options,
    parse_provider_options_json,
    validate_provider_options,
)
from voice_toolbox.chunking.text import (
    TextSourceError,
    infer_text_format_from_upload,
    resolve_text_source,
)
from voice_toolbox.config import (
    AppConfig,
    ConfiguredProvider,
    load_app_config,
    load_env_values,
    mask_api_key_preview,
    preview_config_path,
    replay_config_warnings,
)
from voice_toolbox.models import (
    ASRRequest,
    Artifact,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TTSMode,
    TTSRequest,
)
from voice_toolbox.normalizers.base import NormalizationRequest
from voice_toolbox.normalizers.registry import NormalizerRegistry
from voice_toolbox.pipeline import PreparedTTSRequest, prepare_tts_request
from voice_toolbox.logging_config import configure_logging, sanitize_log_metadata
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE
from voice_toolbox.providers.registry import TTS_MODE_CAPABILITIES, ProviderRegistry

CORS_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
CORS_METHODS = ["GET", "POST"]
CORS_HEADERS = ["Accept", "Content-Type"]
MAX_UPLOAD_RAW_BYTES = (MAX_BASE64_AUDIO_SIZE // 4) * 3
MAX_TEXT_INPUT_LENGTH = 200_000
PROVIDER_NATIVE_UPLOAD_FORMATS = {"wav", "mp3"}
DOWNLOAD_AUDIO_FORMATS: set[DownloadAudioFormat] = {
    "wav",
    "mp3",
    "pcm",
    "m4a",
    "aac",
    "flac",
    "ogg",
    "webm",
}


def create_app(
    *,
    registry: ProviderRegistry | None = None,
    artifact_root: Path | str | None = None,
    config: AppConfig | None = None,
    env_path: Path | str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> FastAPI:
    resolved_env_values = dict(env_values) if env_values is not None else load_env_values(env_path)
    if config is None:
        config = load_app_config(
            env_path=env_path,
            env_values=resolved_env_values,
            emit_warnings=False,
        )
    configure_logging(config.logging, config_path=config.config_path)
    replay_config_warnings(config, resolved_env_values)
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
        allow_credentials=False,
        allow_methods=CORS_METHODS,
        allow_headers=CORS_HEADERS,
    )

    @app.exception_handler(RequestValidationError)
    def request_validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": _safe_request_errors(exc)})

    @app.exception_handler(Exception)
    def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        request_id = uuid4().hex
        logger.bind(request_id=request_id).error("unhandled API error: {}", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "request_id": request_id},
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
                _provider_summary(
                    provider,
                    config=config,
                    env_values=env_values,
                    trusted_local=_trusted_local_request(http_request, config=config),
                )
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
        config = _config_from_request(http_request)
        provider = _get_provider(provider_registry, provider_id)
        return {
            "models": _model_summaries(
                provider.list_models(),
                _configured_provider_for_id(config, provider_id),
            )
        }

    @app.post("/v1/normalize/text")
    def normalize_text(request: NormalizationRequest) -> dict[str, Any]:
        if not request.content.strip():
            raise HTTPException(status_code=422, detail="content is required")
        if len(request.content) > MAX_TEXT_INPUT_LENGTH:
            raise HTTPException(
                status_code=413,
                detail=f"content exceeds {MAX_TEXT_INPUT_LENGTH} characters",
            )
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

    @app.post("/v1/tts/synthesize")
    def synthesize(
        http_request: Request,
        sample: Annotated[UploadFile | None, File()] = None,
        text_file: Annotated[UploadFile | None, File()] = None,
        provider_id: Annotated[str, Form()] = "mimo",
        mode: Annotated[TTSMode, Form()] = TTSMode.BUILTIN,
        text: Annotated[str | None, Form()] = None,
        text_format: Annotated[Literal["plain", "markdown", "auto"] | None, Form()] = None,
        voice_id: Annotated[str | None, Form()] = None,
        voice_description: Annotated[str | None, Form()] = None,
        optimize_text_preview: Annotated[bool, Form()] = False,
        consent_confirmed: Annotated[bool, Form()] = False,
        style_instruction: Annotated[str | None, Form()] = None,
        clone_reference_text: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        if sample is not None and mode != TTSMode.CLONE:
            raise HTTPException(
                status_code=422, detail="sample upload is only valid for clone mode"
            )
        if mode == TTSMode.BUILTIN:
            validated_options, option_metadata = _validate_tts_provider_options(
                http_request,
                provider_id=provider_id,
                model_id=model,
                capability="tts.builtin",
                raw_provider_options=provider_options,
            )
            source = _prepare_tts_source(
                text=text,
                text_file=text_file,
                text_format=text_format,
                config=_config_from_request(http_request),
                mode=TTSMode.BUILTIN,
            )
            prepared = _prepare_tts_or_422(
                raw_text=source,
                text_format=None,
                config=_config_from_request(http_request),
                chunking_mode=chunking_mode,
                chunk_max_chars=chunk_max_chars,
                chunk_silence_ms=chunk_silence_ms,
                fields={
                    "provider_id": provider_id,
                    "mode": TTSMode.BUILTIN,
                    "model": model,
                    "voice_id": voice_id,
                    "style_instruction": style_instruction,
                    "provider_options": validated_options,
                },
                artifact_metadata=option_metadata,
            )
            return _run_tts(http_request, provider_id, prepared)
        if mode == TTSMode.DESIGN:
            validated_options, option_metadata = _validate_tts_provider_options(
                http_request,
                provider_id=provider_id,
                model_id=model,
                capability="tts.design",
                raw_provider_options=provider_options,
            )
            raw_text = _design_raw_text(text, optimize_text_preview=optimize_text_preview)
            source = _prepare_tts_source(
                text=raw_text,
                text_file=text_file,
                text_format=text_format,
                config=_config_from_request(http_request),
                mode=TTSMode.DESIGN,
                optimize_text_preview=optimize_text_preview,
            )
            prepared = _prepare_tts_or_422(
                raw_text=source,
                text_format=None,
                config=_config_from_request(http_request),
                chunking_mode=chunking_mode,
                chunk_max_chars=chunk_max_chars,
                chunk_silence_ms=chunk_silence_ms,
                fields={
                    "provider_id": provider_id,
                    "mode": TTSMode.DESIGN,
                    "model": model,
                    "voice_description": voice_description,
                    "optimize_text_preview": optimize_text_preview,
                    "provider_options": validated_options,
                },
                artifact_metadata=option_metadata,
            )
            return _run_tts(http_request, provider_id, prepared)
        if sample is None:
            raise HTTPException(status_code=422, detail="clone mode requires sample upload")
        return _run_clone_upload(
            http_request=http_request,
            sample=sample,
            text_file=text_file,
            provider_id=provider_id,
            text=text or "",
            text_format=text_format,
            consent_confirmed=consent_confirmed,
            style_instruction=style_instruction,
            clone_reference_text=clone_reference_text,
            model=model,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            provider_options=provider_options,
        )

    @app.post("/v1/tts/builtin")
    def synthesize_builtin(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        text: Annotated[str | None, Form()] = None,
        text_file: Annotated[UploadFile | None, File()] = None,
        text_format: Annotated[Literal["plain", "markdown", "auto"] | None, Form()] = None,
        voice_id: Annotated[str, Form()] = "",
        style_instruction: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        validated_options, option_metadata = _validate_tts_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            capability="tts.builtin",
            raw_provider_options=provider_options,
        )
        source = _prepare_tts_source(
            text=text,
            text_file=text_file,
            text_format=text_format,
            config=_config_from_request(http_request),
            mode=TTSMode.BUILTIN,
        )
        prepared = _prepare_tts_or_422(
            raw_text=source,
            text_format=None,
            config=_config_from_request(http_request),
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            fields={
                "provider_id": provider_id,
                "mode": TTSMode.BUILTIN,
                "model": model,
                "voice_id": voice_id,
                "style_instruction": style_instruction,
                "provider_options": validated_options,
            },
            artifact_metadata=option_metadata,
        )
        return _run_tts(http_request, provider_id, prepared)

    @app.post("/v1/tts/design")
    def synthesize_design(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        voice_description: Annotated[str, Form()] = "",
        text: Annotated[str | None, Form()] = None,
        text_file: Annotated[UploadFile | None, File()] = None,
        text_format: Annotated[Literal["plain", "markdown", "auto"] | None, Form()] = None,
        optimize_text_preview: Annotated[bool, Form()] = False,
        model: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        validated_options, option_metadata = _validate_tts_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            capability="tts.design",
            raw_provider_options=provider_options,
        )
        raw_text = _design_raw_text(text, optimize_text_preview=optimize_text_preview)
        source = _prepare_tts_source(
            text=raw_text,
            text_file=text_file,
            text_format=text_format,
            config=_config_from_request(http_request),
            mode=TTSMode.DESIGN,
            optimize_text_preview=optimize_text_preview,
        )
        prepared = _prepare_tts_or_422(
            raw_text=source,
            text_format=None,
            config=_config_from_request(http_request),
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            fields={
                "provider_id": provider_id,
                "mode": TTSMode.DESIGN,
                "model": model,
                "voice_description": voice_description,
                "optimize_text_preview": optimize_text_preview,
                "provider_options": validated_options,
            },
            artifact_metadata=option_metadata,
        )
        return _run_tts(http_request, provider_id, prepared)

    @app.post("/v1/tts/clone")
    def synthesize_clone(
        http_request: Request,
        sample: Annotated[UploadFile, File()],
        provider_id: Annotated[str, Form()] = "mimo",
        text: Annotated[str | None, Form()] = None,
        text_file: Annotated[UploadFile | None, File()] = None,
        text_format: Annotated[Literal["plain", "markdown", "auto"] | None, Form()] = None,
        consent_confirmed: Annotated[bool, Form()] = False,
        style_instruction: Annotated[str | None, Form()] = None,
        clone_reference_text: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        return _run_clone_upload(
            http_request=http_request,
            sample=sample,
            text_file=text_file,
            provider_id=provider_id,
            text=text or "",
            text_format=text_format,
            consent_confirmed=consent_confirmed,
            style_instruction=style_instruction,
            clone_reference_text=clone_reference_text,
            model=model,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            provider_options=provider_options,
        )

    @app.post("/v1/asr/transcribe")
    def transcribe(
        http_request: Request,
        file: Annotated[UploadFile, File()],
        provider_id: Annotated[str, Form()] = "mimo",
        model: Annotated[str | None, Form()] = None,
        language: Annotated[Literal["auto", "zh", "en"], Form()] = "auto",
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        contents = _read_upload(file)
        mime_type = _normalize_mime_type(file.content_type)
        suffix = _suffix_for_upload(file.filename)
        source_format = _validate_upload_signature(contents, mime_type, suffix)
        provider_audio = _convert_upload_for_provider(
            contents,
            source_format=source_format,
            provider_id=provider_id,
            operation="asr",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / _safe_upload_filename(
                file.filename,
                provider_audio.suffix,
            )
            temp_path.write_bytes(provider_audio.data)
            request = _build_asr_request(
                provider_id=provider_id,
                model=model,
                audio_path=temp_path,
                mime_type=provider_audio.mime_type,
                raw_byte_size=len(provider_audio.data),
                base64_size=_base64_size(provider_audio.data),
                language=language,
            )
            provider_registry = _registry_from_request(http_request)
            provider = _ensure_asr_provider(provider_registry, provider_id, request)
            _ensure_model_allowed(provider, request.model, expected_capability="asr.transcribe")
            started_at = datetime.now(UTC)
            try:
                artifact = provider.transcribe(request)
            except ProviderError as exc:
                _log_operation(
                    operation="asr",
                    status="failed",
                    provider_id=provider_id,
                    model=request.model,
                    error_summary=str(exc),
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            finished_at = datetime.now(UTC)
            _log_operation(
                operation="asr",
                status="completed",
                provider_id=provider_id,
                model=artifact.metadata.get("model")
                if isinstance(artifact.metadata, dict)
                else None,
                artifact_id=artifact.id,
                elapsed_ms=int((finished_at - started_at).total_seconds() * 1000),
            )
            return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)

    @app.get("/v1/artifacts")
    def list_artifacts(
        http_request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, list[dict[str, Any]]]:
        _ensure_trusted_artifact_request(http_request)
        artifact_root = (root / "data" / "artifacts").resolve(strict=False)
        if not artifact_root.exists():
            return {"artifacts": []}
        sidecars = artifact_root.glob("*/*.json")
        artifacts: list[Artifact] = []
        for sidecar_path in sidecars:
            try:
                artifacts.append(_read_artifact_sidecar_path(sidecar_path, root))
            # Listing is intentionally lenient: a single corrupt/malformed sidecar
            # must not 500 the whole list. All per-sidecar failures (invalid JSON,
            # schema validation, path-escape guard, IO errors) are logged and skipped.
            except (
                HTTPException,
                ValidationError,
                json.JSONDecodeError,
                OSError,
                ValueError,
            ) as exc:
                logger.warning("skipping unreadable artifact sidecar: {} - {}", sidecar_path, exc)
                continue
        artifacts.sort(key=lambda artifact: artifact.created_at, reverse=True)
        return {
            "artifacts": [
                {
                    **_safe_artifact_payload(artifact),
                    "preview": _artifact_preview(artifact),
                }
                for artifact in artifacts[:limit]
            ]
        }

    @app.get("/v1/artifacts/{artifact_id}")
    def artifact_metadata(artifact_id: str, http_request: Request) -> dict[str, Any]:
        _ensure_trusted_artifact_request(http_request)
        artifact = _read_artifact_sidecar(root, artifact_id)
        return _safe_artifact_payload(artifact)

    @app.get("/v1/artifacts/{artifact_id}/download", response_model=None)
    def artifact_download(
        http_request: Request,
        artifact_id: str,
        format: Annotated[str, Query()] = "source",
    ) -> Response:
        _ensure_trusted_artifact_request(http_request)
        artifact = _read_artifact_sidecar(root, artifact_id)
        path = artifact.path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact file not found")
        download_format = _normalize_download_format(format)
        if download_format is not None:
            if artifact.kind.value != "audio":
                raise HTTPException(status_code=422, detail="format conversion is only for audio")
            return _converted_audio_response(artifact, target_format=download_format)
        return FileResponse(
            path,
            media_type=artifact.mime_type,
            filename=_source_download_filename(artifact),
        )

    return app


def _infer_artifact_root(registry: ProviderRegistry | None) -> Path:
    if registry is not None:
        for provider in registry.list_providers():
            artifact_root = getattr(provider, "artifact_root", None)
            if artifact_root is not None:
                return Path(artifact_root)
    return Path.cwd()


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
    trusted_local: bool,
) -> dict[str, Any]:
    provider_config = _configured_provider_for_id(config, provider.id)
    if provider_config is None:
        return {
            "id": provider.id,
            "name": provider.name,
            "type": "test",
            "base_url": None,
            "api_key_env": None,
            "has_api_key": False,
            "api_key_preview": None,
            "config_path_preview": preview_config_path(config.config_path),
            "default_voice": None,
            "default_models": {},
            "capabilities": sorted(provider.capabilities()),
            "options": [],
            "models": _model_summaries(provider.list_models(), None),
            "voices": [voice.model_dump(mode="json") for voice in provider.list_voices()],
        }

    api_key = env_values.get(provider_config.api_key_env)
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
        "options": [option.model_dump(mode="json") for option in provider_config.options],
        "models": _model_summaries(provider.list_models(), provider_config),
        "voices": [voice.model_dump(mode="json") for voice in provider.list_voices()],
    }


def _model_summaries(
    models: list[Any],
    provider_config: ConfiguredProvider | None,
) -> list[dict[str, Any]]:
    configured_by_id = (
        {model.id: model for model in provider_config.models} if provider_config is not None else {}
    )
    summaries: list[dict[str, Any]] = []
    for model in models:
        payload = model.model_dump(mode="json")
        configured = configured_by_id.get(model.id)
        if configured is not None:
            payload["options"] = [option.model_dump(mode="json") for option in configured.options]
            payload["transcript_capabilities"] = (
                configured.transcript_capabilities.model_dump(mode="json")
                if configured.transcript_capabilities is not None
                else None
            )
        else:
            payload.setdefault("options", [])
            payload.setdefault("transcript_capabilities", None)
        summaries.append(payload)
    return summaries


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


def _build_asr_request(**kwargs: Any) -> ASRRequest:
    try:
        return ASRRequest(**kwargs)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_safe_validation_errors(exc)) from exc


def _prepare_tts_or_422(
    *,
    raw_text: str | TextSource | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    fields: dict[str, object],
    config: AppConfig | None = None,
    chunking_mode: Literal["off", "auto", "force"] | None = None,
    chunk_max_chars: int | None = None,
    chunk_silence_ms: int | None = None,
    artifact_metadata: Mapping[str, object] | None = None,
) -> PreparedTTSRequest:
    text_length = (
        len(raw_text.text)
        if isinstance(raw_text, TextSource) and raw_text.text
        else (len(raw_text) if isinstance(raw_text, str) else 0)
    )
    if text_length > MAX_TEXT_INPUT_LENGTH:
        raise HTTPException(status_code=413, detail="text exceeds 200000 characters")
    try:
        prepared = prepare_tts_request(
            raw_text,
            text_format,
            fields,
            chunking_config=(config.chunking.tts if config is not None else None),
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
        )
        prepared.artifact_metadata.update(dict(artifact_metadata or {}))
        return prepared
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_safe_validation_errors(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _read_text_source(
    *,
    text: str | None,
    text_file: UploadFile | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    config: AppConfig,
    mode: TTSMode | None = None,
    optimize_text_preview: bool = False,
) -> TextSource:
    try:
        return resolve_text_source(
            text=text,
            text_file=text_file,
            text_format=text_format,
            max_text_file_bytes=config.chunking.tts.max_text_file_bytes,
            mode=mode,
            optimize_text_preview=optimize_text_preview,
        )
    except TextSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _infer_text_format_from_upload(upload: UploadFile) -> Literal["plain", "markdown"]:
    try:
        return infer_text_format_from_upload(upload.filename, upload.content_type)
    except TextSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _prepare_tts_source(
    *,
    text: str | None,
    text_file: UploadFile | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    config: AppConfig,
    mode: TTSMode | None = None,
    optimize_text_preview: bool = False,
) -> TextSource:
    return _read_text_source(
        text=text,
        text_file=text_file,
        text_format=text_format,
        config=config,
        mode=mode,
        optimize_text_preview=optimize_text_preview,
    )


def _design_raw_text(text: str | None, *, optimize_text_preview: bool) -> str | None:
    if not optimize_text_preview:
        return text
    return (text or "").strip() or None


def _validate_tts_provider_options(
    request: Request,
    *,
    provider_id: str,
    model_id: str | None,
    capability: str,
    raw_provider_options: str | None,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        submitted = parse_provider_options_json(raw_provider_options)
        provider_config = _configured_provider_for_id(_config_from_request(request), provider_id)
        model_options: list[Any] = []
        resolved_model_id = (
            model_id
            if model_id is not None
            else _default_model_for_capability(provider_config, capability)
        )
        if provider_config is not None and resolved_model_id is not None:
            configured_model = next(
                (model for model in provider_config.models if model.id == resolved_model_id),
                None,
            )
            if configured_model is not None:
                model_options = list(configured_model.options)
        specs = merge_provider_options(
            provider_config.options if provider_config is not None else [],
            model_options,
            capability=capability,
        )
        validated = validate_provider_options(submitted, specs, capability=capability)
        metadata = build_provider_option_metadata(validated, specs)
        return validated, metadata
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _default_model_for_capability(
    provider_config: ConfiguredProvider | None,
    capability: str,
) -> str | None:
    if provider_config is None or provider_config.default_models is None:
        return None
    field_by_capability = {
        "tts.builtin": "tts_builtin",
        "tts.design": "tts_design",
        "tts.clone": "tts_clone",
        "asr.transcribe": "asr",
    }
    field_name = field_by_capability.get(capability)
    if field_name is None:
        return None
    return cast(str | None, getattr(provider_config.default_models, field_name))


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {key: error[key] for key in ("loc", "msg", "type") if key in error}
        for error in exc.errors()
    ]


def _safe_request_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    return [
        {key: error[key] for key in ("loc", "msg", "type") if key in error}
        for error in exc.errors()
    ]


def _ensure_provider_configured_for_operation(request: Request, provider_id: str) -> None:
    config_provider = _configured_provider_for_id(request.app.state.config, provider_id)
    if config_provider is None:
        raise HTTPException(status_code=503, detail=f"provider {provider_id} is not configured")
    value = request.app.state.env_values.get(config_provider.api_key_env)
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"{config_provider.api_key_env} is required for provider {provider_id}",
        )


def _trusted_local_request(request: Request, *, config: AppConfig) -> bool:
    if config.api.host not in {"127.0.0.1", "localhost"}:
        return False
    client_host = request.client.host if request.client is not None else ""
    return client_host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _ensure_trusted_artifact_request(request: Request) -> None:
    if not _trusted_local_request(request, config=_config_from_request(request)):
        raise HTTPException(status_code=403, detail="artifact access requires trusted local API")


def _run_clone_upload(
    *,
    http_request: Request,
    sample: UploadFile,
    text_file: UploadFile | None,
    provider_id: str,
    text: str,
    text_format: Literal["plain", "markdown", "auto"] | None,
    consent_confirmed: bool,
    style_instruction: str | None,
    clone_reference_text: str | None,
    model: str | None,
    chunking_mode: Literal["off", "auto", "force"] | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
    provider_options: str | None,
) -> dict[str, Any]:
    registry = _registry_from_request(http_request)
    _ensure_tts_provider(
        registry,
        provider_id,
        TTSRequest(
            provider_id=provider_id,
            mode=TTSMode.CLONE,
            text="preflight",
            clone_sample_path=Path("preflight.wav"),
            clone_mime_type="audio/wav",
            consent_confirmed=True,
        ),
    )
    validated_options, option_metadata = _validate_tts_provider_options(
        http_request,
        provider_id=provider_id,
        model_id=model,
        capability="tts.clone",
        raw_provider_options=provider_options,
    )
    contents = _read_upload(sample)
    mime_type = _normalize_mime_type(sample.content_type)
    suffix = _suffix_for_upload(sample.filename)
    source_format = _validate_upload_signature(contents, mime_type, suffix)
    provider_audio = _convert_upload_for_provider(
        contents,
        source_format=source_format,
        provider_id=provider_id,
        operation="clone",
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / _safe_upload_filename(sample.filename, provider_audio.suffix)
        temp_path.write_bytes(provider_audio.data)
        source = _prepare_tts_source(
            text=text,
            text_file=text_file,
            text_format=text_format,
            config=_config_from_request(http_request),
            mode=TTSMode.CLONE,
        )
        prepared = _prepare_tts_or_422(
            raw_text=source,
            text_format=None,
            config=_config_from_request(http_request),
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            fields={
                "provider_id": provider_id,
                "mode": TTSMode.CLONE,
                "model": model,
                "style_instruction": style_instruction,
                "clone_reference_text": clone_reference_text,
                "clone_sample_path": temp_path,
                "clone_mime_type": provider_audio.mime_type,
                "clone_raw_byte_size": len(provider_audio.data),
                "clone_base64_size": _base64_size(provider_audio.data),
                "consent_confirmed": consent_confirmed,
                "provider_options": validated_options,
            },
            artifact_metadata=option_metadata,
        )
        return _run_tts(http_request, provider_id, prepared)


def _run_tts(
    http_request: Request,
    provider_id: str,
    prepared: PreparedTTSRequest,
) -> dict[str, Any]:
    provider_registry = _registry_from_request(http_request)
    provider = _ensure_tts_provider(provider_registry, provider_id, prepared.request)
    _ensure_model_allowed(
        provider,
        prepared.request.model,
        expected_capability=TTS_MODE_CAPABILITIES[prepared.request.mode],
    )
    started_at = datetime.now(UTC)
    mode_metadata = {
        **prepared.artifact_metadata,
        "tts_mode": prepared.request.mode.value,
    }
    if prepared.artifact_metadata.get("source_kind") != "file":
        mode_metadata["source_text_preview"] = _preview_text(prepared.request.text)
    try:
        if prepared.chunk_plan is not None and prepared.chunk_plan.chunking_enabled:
            artifact = _run_chunked_tts(
                provider,
                prepared=prepared,
                metadata=mode_metadata,
                artifact_root=http_request.app.state.artifact_root,
                started_at=started_at,
            )
        else:
            artifact = provider.synthesize(
                prepared.request,
                artifact_metadata=mode_metadata,
            )
    except (ProviderError, AudioConversionError) as exc:
        _log_operation(
            operation="tts",
            status="failed",
            provider_id=provider_id,
            model=prepared.request.model,
            tts_mode=prepared.request.mode.value,
            error_summary=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finished_at = datetime.now(UTC)
    _log_operation(
        operation="tts",
        status="completed",
        provider_id=provider_id,
        model=artifact.metadata.get("model") if isinstance(artifact.metadata, dict) else None,
        tts_mode=prepared.request.mode.value,
        artifact_id=artifact.id,
        elapsed_ms=int((finished_at - started_at).total_seconds() * 1000),
    )
    return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)


def _run_chunked_tts(
    provider: Any,
    *,
    prepared: PreparedTTSRequest,
    metadata: dict[str, object],
    artifact_root: Path,
    started_at: datetime,
) -> Artifact:
    if prepared.chunk_plan is None:
        raise ProviderError("chunk plan is required")
    results: list[ProviderAudioResult] = []
    for chunk in prepared.chunk_plan.chunks:
        chunk_request = prepared.request.model_copy(update={"text": chunk.text})
        results.append(provider.synthesize_bytes(chunk_request))
    merged = merge_audio_results(
        results,
        silence_ms=prepared.chunk_plan.silence_ms,
        output_format=prepared.request.output_format,
    )
    operation_id = f"tts-{uuid4().hex}"
    final_metadata = {
        **metadata,
        "model": merged.model or prepared.request.model,
        "operation": "tts",
        "output_format": prepared.request.output_format,
        "provider_id": prepared.request.provider_id,
    }
    store = ArtifactStore(artifact_root)
    artifact = store.write_audio(
        operation_id=operation_id,
        provider_id=prepared.request.provider_id,
        operation="tts",
        audio=merged.audio,
        mime_type=merged.mime_type,
        suffix=merged.suffix,
        metadata=final_metadata,
    )
    store.record_operation(
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


def _ensure_model_allowed(provider: Any, model_id: str | None, *, expected_capability: str) -> None:
    if model_id is None:
        return
    matches = [model for model in provider.list_models() if model.id == model_id]
    if not matches:
        raise HTTPException(status_code=422, detail=f"model {model_id} is not configured")
    if matches[0].capability != expected_capability:
        raise HTTPException(
            status_code=422,
            detail=f"model {model_id} does not support {expected_capability}",
        )


def _log_operation(**metadata: object) -> None:
    sanitized = sanitize_log_metadata(metadata)
    logger.bind(**sanitized).info("voice operation")


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


def _normalize_mime_type(mime_type: str | None) -> str:
    try:
        return normalize_mime_type(mime_type)
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _suffix_for_upload(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    try:
        format_from_suffix(suffix)
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return suffix


def _validate_upload_signature(contents: bytes, mime_type: str, suffix: str) -> AudioFormat:
    try:
        audio_format = validate_mime_suffix_match(mime_type, suffix)
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if audio_format == "wav" and not (contents.startswith(b"RIFF") and contents[8:12] == b"WAVE"):
        raise HTTPException(status_code=422, detail="wav upload must start with RIFF/WAVE header")
    if audio_format == "mp3" and not (
        contents.startswith(b"ID3")
        or (len(contents) >= 2 and contents[0] == 0xFF and contents[1] & 0xE0 == 0xE0)
    ):
        raise HTTPException(status_code=422, detail="mp3 upload must start with ID3 or frame sync")
    return audio_format


def _convert_upload_for_provider(
    contents: bytes,
    *,
    source_format: AudioFormat,
    provider_id: str,
    operation: Literal["asr", "clone"],
) -> ConvertedAudio:
    del provider_id, operation
    target_format: DownloadAudioFormat = (
        source_format if source_format in PROVIDER_NATIVE_UPLOAD_FORMATS else "wav"
    )
    try:
        converted = convert_audio_bytes(
            contents,
            source_format=source_format,
            target_format=target_format,
        )
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if (
        len(converted.data) > MAX_UPLOAD_RAW_BYTES
        or _base64_size(converted.data) > MAX_BASE64_AUDIO_SIZE
    ):
        raise HTTPException(status_code=413, detail="converted audio base64 payload exceeds 10 MiB")
    return converted


def _normalize_download_format(value: str) -> DownloadAudioFormat | None:
    normalized = value.strip().lower()
    if normalized == "source":
        return None
    if normalized not in DOWNLOAD_AUDIO_FORMATS:
        supported = ", ".join(["source", *sorted(DOWNLOAD_AUDIO_FORMATS)])
        raise HTTPException(status_code=422, detail=f"download format must be one of: {supported}")
    return cast(DownloadAudioFormat, normalized)


def _converted_audio_response(
    artifact: Artifact,
    *,
    target_format: DownloadAudioFormat,
) -> Response:
    source_format = _audio_format_for_artifact(artifact)
    try:
        converted = convert_audio_bytes(
            artifact.path.read_bytes(),
            source_format=source_format,
            target_format=target_format,
        )
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = _download_filename(artifact, suffix_for_format(target_format))
    return Response(
        converted.data,
        media_type=mime_for_format(target_format),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _source_download_filename(artifact: Artifact) -> str:
    suffix = artifact.path.suffix
    if artifact.kind.value == "audio":
        try:
            suffix = suffix_for_format(_audio_format_for_artifact(artifact))
        except HTTPException:
            pass
    return _download_filename(artifact, suffix)


def _download_filename(artifact: Artifact, suffix: str) -> str:
    safe_suffix = suffix if suffix.startswith(".") and "/" not in suffix else ".bin"
    time_str = artifact.created_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    digest = sha1(artifact.id.encode("utf-8")).hexdigest()[:8]
    return f"{time_str}-{digest}{safe_suffix}"


def _audio_format_for_artifact(artifact: Artifact) -> AudioFormat:
    try:
        return format_from_mime(artifact.mime_type)
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _safe_upload_filename(filename: str | None, suffix: str) -> str:
    del filename
    return f"upload-{uuid4().hex}{suffix}"


def _base64_size(contents: bytes) -> int:
    return ((len(contents) + 2) // 3) * 4


def _read_artifact_sidecar(root: Path, artifact_id: str) -> Artifact:
    if not SAFE_OPERATION_ID_PATTERN.fullmatch(artifact_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    matches = sorted(artifact_root.glob(f"*/{artifact_id}.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact = _read_artifact_sidecar_path(matches[-1], root)
    if artifact.id != artifact_id:
        raise HTTPException(status_code=422, detail="artifact sidecar id mismatch")
    return artifact


def _read_artifact_sidecar_path(sidecar_path: Path, root: Path) -> Artifact:
    artifact_root = (root / "data" / "artifacts").resolve(strict=False)
    # Resolve before any read so symlink/relative-glob cases are normalized once.
    resolved_sidecar = sidecar_path.resolve(strict=False)
    if not resolved_sidecar.is_relative_to(artifact_root):
        raise HTTPException(status_code=422, detail="artifact sidecar is outside artifact root")
    try:
        with resolved_sidecar.open(encoding="utf-8") as sidecar_file:
            payload = json.load(sidecar_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    if "path" not in payload:
        payload["path"] = str(_artifact_path_for_sidecar(resolved_sidecar, payload))
    try:
        artifact = Artifact.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="artifact sidecar is invalid") from exc
    raw_path = artifact.path
    path = (
        (resolved_sidecar.parent / raw_path).resolve(strict=False)
        if not raw_path.is_absolute()
        else raw_path.resolve(strict=False)
    )
    if not path.is_relative_to(artifact_root):
        raise HTTPException(status_code=422, detail="artifact path is outside artifact root")
    return artifact.model_copy(update={"path": path})


def _artifact_path_for_sidecar(sidecar_path: Path, payload: dict[str, Any]) -> Path:
    mime_type = payload.get("mime_type")
    suffix_by_mime = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "text/plain; charset=utf-8": ".txt",
    }
    suffix = suffix_by_mime.get(str(mime_type), ".wav")
    return sidecar_path.with_suffix(suffix)


def _preview_text(text: str | None, max_length: int = 80) -> str:
    if not text:
        return ""
    normalized = text.replace("\n", " ").replace("\r", " ").strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}…"


def _artifact_preview(artifact: Artifact) -> str:
    if artifact.kind.value == "transcript":
        return ""
    if isinstance(artifact.metadata, dict):
        return _preview_text(artifact.metadata.get("source_text_preview"))
    return ""
