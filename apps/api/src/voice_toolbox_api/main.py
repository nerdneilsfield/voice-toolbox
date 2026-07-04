from __future__ import annotations

import json
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha1
from hashlib import sha256
from uuid import uuid4
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal, cast

from fastapi.exceptions import RequestValidationError
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
from voice_toolbox.chunking.audio import (
    ASRAudioChunkingError,
    inspect_audio_duration_ms,
    plan_asr_audio_chunks,
)
from voice_toolbox.chunking.merge import merge_audio_results
from voice_toolbox.chunking.merge import TranscriptChunk, merge_transcript_chunks
from voice_toolbox.chunking.models import TextSource
from voice_toolbox.chunking.options import (
    build_provider_option_metadata,
    merge_provider_options,
    parse_provider_options_json,
    validate_provider_options,
)
from voice_toolbox.chunking.sessions import (
    ASRChunkRecord,
    ASRChunkSessionError,
    ASRChunkSessionMetadata,
    ASRChunkSessionStore,
    provider_options_fingerprint,
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
    ASRLanguage,
    ASRRequest,
    Artifact,
    OperationResult,
    OperationStatus,
    ProviderAudioResult,
    TranscriptCapabilities,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
)
from voice_toolbox.normalizers.base import NormalizationRequest
from voice_toolbox.normalizers.registry import NormalizerRegistry
from voice_toolbox.pipeline import PreparedTTSRequest, prepare_tts_request
from voice_toolbox.podcast.audio import PodcastAudioSegment, merge_podcast_audio
from voice_toolbox.podcast.jobs import (
    PodcastFailedSegment,
    PodcastJobStatus,
    PodcastJobStore,
    PodcastJobStoreError,
)
from voice_toolbox.podcast.models import (
    PodcastManifest,
    PodcastManifestSegment,
    PodcastManifestSpeaker,
    PodcastScript,
    PodcastScriptFormat,
    PodcastSegment,
    PodcastSpeaker,
)
from voice_toolbox.podcast.parser import PodcastParseError, parse_podcast_script
from voice_toolbox.logging_config import configure_logging, sanitize_log_metadata
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE
from voice_toolbox.providers.registry import ASR_CAPABILITY, TTS_MODE_CAPABILITIES, ProviderRegistry
from voice_toolbox.transcripts import render_json, render_srt, render_txt, render_vtt

CORS_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
CORS_METHODS = ["GET", "POST", "DELETE"]
CORS_HEADERS = ["Accept", "Content-Type"]
MAX_UPLOAD_RAW_BYTES = (MAX_BASE64_AUDIO_SIZE // 4) * 3
MAX_TEXT_INPUT_LENGTH = 200_000
MAX_PODCAST_PAUSE_MS = 60_000
MAX_PODCAST_TOTAL_PAUSE_MS = 3_600_000
MAX_PODCAST_WORKERS = 8
DEFAULT_PODCAST_SEGMENT_WORKERS = 8
MAX_PODCAST_SEGMENT_WORKERS = 16
LOCAL_PODCAST_PROVIDER_IDS = {"mlx-audio", "mlx_audio"}
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
BROWSER_BACKEND_ACCEPT_FORMATS = sorted(DOWNLOAD_AUDIO_FORMATS - {"pcm"})
BROWSER_CHUNK_DURATION_TOLERANCE_MS = 1000


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
    app.state.asr_chunk_sessions = ASRChunkSessionStore(
        root,
        ttl_seconds=config.chunking.asr.session_ttl_seconds,
        max_upload_mb=config.chunking.asr.max_upload_mb,
    )
    app.state.asr_chunk_sessions.cleanup_expired()
    app.state.podcast_jobs = PodcastJobStore()
    app.state.podcast_executor = ThreadPoolExecutor(
        max_workers=MAX_PODCAST_WORKERS,
        thread_name_prefix="voice-toolbox-podcast",
    )
    app.router.add_event_handler(
        "shutdown",
        lambda: app.state.podcast_executor.shutdown(wait=False, cancel_futures=True),
    )

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
        voice_id: Annotated[str | None, Form()] = None,
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
        if voice_id is not None and not voice_id.strip():
            raise HTTPException(status_code=422, detail="voice_id must not be empty")
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
        language: Annotated[ASRLanguage, Form()] = "auto",
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_seconds: Annotated[int | None, Form()] = None,
        chunk_overlap_ms: Annotated[int | None, Form()] = None,
        transcript_timestamps: Annotated[bool, Form()] = False,
        transcript_speakers: Annotated[bool, Form()] = False,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        model = (model or "").strip() or None
        config = _config_from_request(http_request)
        validated_options, option_metadata = _validate_asr_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            raw_provider_options=provider_options,
        )
        _ensure_transcript_richness_supported(
            http_request,
            provider_id=provider_id,
            model_id=model,
            timestamps=transcript_timestamps,
            speakers=transcript_speakers,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = _save_upload_to_temp(
                file,
                output_dir=temp_root,
                max_upload_mb=config.chunking.asr.max_upload_mb,
            )
            mime_type = _normalize_mime_type(file.content_type)
            suffix = _suffix_for_upload(file.filename)
            source_prefix = _read_file_prefix(source_path, 16)
            if not _file_fits_provider_limit(
                source_path
            ) and not _looks_like_supported_audio_upload(
                source_prefix,
                mime_type,
                suffix,
            ):
                raise HTTPException(status_code=413, detail="audio base64 payload exceeds 10 MiB")
            source_format = _validate_upload_signature(
                source_prefix,
                mime_type,
                suffix,
            )
            return _run_asr_upload(
                http_request=http_request,
                provider_id=provider_id,
                model=model,
                language=language,
                source_path=source_path,
                source_format=source_format,
                source_mime_type=mime_type,
                source_suffix=suffix,
                chunking_mode=chunking_mode,
                chunk_seconds=chunk_seconds,
                chunk_overlap_ms=chunk_overlap_ms,
                transcript_timestamps=transcript_timestamps,
                transcript_speakers=transcript_speakers,
                provider_options=validated_options,
                option_metadata=option_metadata,
            )

    @app.post("/v1/asr/chunk-sessions")
    def create_asr_chunk_session(
        http_request: Request,
        source_duration_ms: Annotated[int, Form()],
        total_chunks: Annotated[int, Form()],
        provider_id: Annotated[str, Form()] = "mimo",
        model: Annotated[str | None, Form()] = None,
        language: Annotated[ASRLanguage, Form()] = "auto",
        source_file_name: Annotated[str | None, Form()] = None,
        transcript_timestamps: Annotated[bool, Form()] = False,
        transcript_speakers: Annotated[bool, Form()] = False,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_browser_asr_chunking_enabled(http_request)
        _ensure_provider_configured_for_operation(http_request, provider_id)
        model = (model or "").strip() or None
        config = _config_from_request(http_request)
        validated_options, option_metadata = _validate_asr_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            raw_provider_options=provider_options,
        )
        _ensure_transcript_richness_supported(
            http_request,
            provider_id=provider_id,
            model_id=model,
            timestamps=transcript_timestamps,
            speakers=transcript_speakers,
        )
        registry = _registry_from_request(http_request)
        provider = _ensure_asr_provider(registry, provider_id, None)
        _ensure_model_allowed(provider, model, expected_capability=ASR_CAPABILITY)
        try:
            session = _asr_chunk_session_store(http_request).create(
                provider_id=provider_id,
                model=model,
                language=language,
                total_chunks=total_chunks,
                source_duration_ms=source_duration_ms,
                source_file_name=source_file_name,
                transcript_timestamps=transcript_timestamps,
                transcript_speakers=transcript_speakers,
                provider_options=validated_options,
                option_metadata=option_metadata,
                max_chunks=config.chunking.asr.max_chunks,
            )
        except ASRChunkSessionError as exc:
            raise _chunk_session_http_error(exc) from exc
        return _asr_chunk_session_create_payload(session, config=config)

    @app.post("/v1/asr/chunk-sessions/{session_id}/chunks")
    def upload_asr_chunk_session_chunk(
        session_id: str,
        http_request: Request,
        file: Annotated[UploadFile, File()],
        chunk_index: Annotated[int, Form()],
        offset_ms: Annotated[int, Form()],
        duration_ms: Annotated[int, Form()],
    ) -> dict[str, Any]:
        _ensure_browser_asr_chunking_enabled(http_request)
        store = _asr_chunk_session_store(http_request)
        try:
            quota_session = store.load(session_id)
        except ASRChunkSessionError as exc:
            raise _chunk_session_http_error(exc) from exc
        remaining_quota = quota_session.max_upload_bytes - quota_session.uploaded_bytes
        remaining_bytes = min(remaining_quota, MAX_UPLOAD_RAW_BYTES)
        contents = _read_upload_stream_limited(
            file,
            max_bytes=remaining_bytes,
            too_large_detail=(
                "audio chunk exceeds provider payload limit"
                if MAX_UPLOAD_RAW_BYTES <= remaining_quota
                else "session upload quota exceeded"
            ),
        )
        mime_type = _normalize_mime_type(file.content_type)
        suffix = _suffix_for_upload(file.filename)
        audio_format = _validate_upload_signature(contents, mime_type, suffix)
        if audio_format != "wav":
            raise HTTPException(status_code=422, detail="browser ASR chunks must be wav")
        if not _is_pcm_wav(contents):
            raise HTTPException(status_code=422, detail="browser ASR chunks must be PCM WAV")
        with tempfile.NamedTemporaryFile(suffix=".wav") as temp_chunk:
            temp_chunk.write(contents)
            temp_chunk.flush()
            try:
                actual_duration_ms = inspect_audio_duration_ms(
                    Path(temp_chunk.name),
                    source_format="wav",
                )
            except AudioConversionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if abs(actual_duration_ms - duration_ms) > BROWSER_CHUNK_DURATION_TOLERANCE_MS:
            raise HTTPException(status_code=422, detail="chunk duration does not match audio")
        try:
            session = store.write_chunk(
                session_id,
                chunk_index=chunk_index,
                data=contents,
                offset_ms=offset_ms,
                duration_ms=actual_duration_ms,
                mime_type="audio/wav",
                suffix=".wav",
                max_raw_bytes=MAX_UPLOAD_RAW_BYTES,
                max_base64_bytes=MAX_BASE64_AUDIO_SIZE,
            )
        except ASRChunkSessionError as exc:
            raise _chunk_session_http_error(exc) from exc
        return {
            "session_id": session.session_id,
            "received_chunks": len(session.chunks),
            "total_chunks": session.total_chunks,
        }

    @app.post("/v1/asr/chunk-sessions/{session_id}/finish")
    def finish_asr_chunk_session(
        session_id: str,
        http_request: Request,
        provider_id: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
        language: Annotated[ASRLanguage | None, Form()] = None,
        transcript_timestamps: Annotated[bool | None, Form()] = None,
        transcript_speakers: Annotated[bool | None, Form()] = None,
        provider_options: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        _ensure_browser_asr_chunking_enabled(http_request)
        store = _asr_chunk_session_store(http_request)
        try:
            session = store.load(session_id)
            finish_provider_options = _reject_mismatched_session_finish(
                session,
                provider_id=provider_id,
                model=(model or "").strip() or None if model is not None else None,
                language=language,
                transcript_timestamps=transcript_timestamps,
                transcript_speakers=transcript_speakers,
                provider_options=provider_options,
            )
            finish_provider_options, _finish_option_metadata = _validate_asr_provider_options(
                http_request,
                provider_id=session.provider_id,
                model_id=session.model,
                raw_provider_options=json.dumps(finish_provider_options),
            )
            session = session.model_copy(update={"provider_options": finish_provider_options})
            chunks = store.finish_chunks(session_id)
        except ASRChunkSessionError as exc:
            raise _chunk_session_http_error(exc) from exc
        result = _run_asr_chunk_session_finish(
            http_request=http_request,
            session=session,
            chunks=chunks,
        )
        store.delete(session_id)
        return result

    @app.delete("/v1/asr/chunk-sessions/{session_id}")
    def delete_asr_chunk_session(session_id: str, http_request: Request) -> dict[str, bool]:
        _ensure_browser_asr_chunking_enabled(http_request)
        try:
            deleted = _asr_chunk_session_store(http_request).delete(session_id)
        except ASRChunkSessionError as exc:
            raise _chunk_session_http_error(exc) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="chunk session not found")
        return {"deleted": True}

    @app.post("/v1/podcast/jobs")
    def create_podcast_job(
        http_request: Request,
        provider_id: Annotated[str, Form()] = "mimo",
        model: Annotated[str | None, Form()] = None,
        script: Annotated[str, Form()] = "",
        script_format: Annotated[PodcastScriptFormat, Form()] = "auto",
        default_pause_ms: Annotated[int, Form()] = 350,
        speaker_voices: Annotated[str, Form()] = "{}",
        provider_options: Annotated[str | None, Form()] = None,
        chunking_mode: Annotated[Literal["off", "auto", "force"] | None, Form()] = None,
        chunk_max_chars: Annotated[int | None, Form()] = None,
        chunk_silence_ms: Annotated[int | None, Form()] = None,
        segment_workers: Annotated[
            int, Form(ge=1, le=MAX_PODCAST_SEGMENT_WORKERS)
        ] = DEFAULT_PODCAST_SEGMENT_WORKERS,
    ) -> dict[str, Any]:
        _ensure_provider_configured_for_operation(http_request, provider_id)
        provider = _get_provider(_registry_from_request(http_request), provider_id)
        _ensure_model_allowed(provider, model, expected_capability="tts.builtin")
        if len(script) > MAX_TEXT_INPUT_LENGTH:
            raise HTTPException(
                status_code=413,
                detail=f"script exceeds {MAX_TEXT_INPUT_LENGTH} characters",
            )
        parsed = _parse_podcast_script_or_422(script, script_format, default_pause_ms)
        _validate_podcast_pauses(parsed, default_pause_ms)
        voices_by_key = _parse_speaker_voices(speaker_voices)
        speaker_voice_ids = _resolve_podcast_voice_ids(parsed.speakers, voices_by_key)
        _validate_podcast_voice_ids(provider, model, speaker_voice_ids)
        validated_options, option_metadata = _validate_tts_provider_options(
            http_request,
            provider_id=provider_id,
            model_id=model,
            capability="tts.builtin",
            raw_provider_options=provider_options,
        )
        try:
            job = http_request.app.state.podcast_jobs.create(total_segments=len(parsed.segments))
        except PodcastJobStoreError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        try:
            future = http_request.app.state.podcast_executor.submit(
                _run_podcast_job,
                app=http_request.app,
                job_id=job.job_id,
                provider=provider,
                provider_id=provider_id,
                model=model,
                parsed=parsed,
                default_pause_ms=default_pause_ms,
                speaker_voice_ids=speaker_voice_ids,
                provider_options=validated_options,
                option_metadata=option_metadata,
                chunking_mode=chunking_mode,
                chunk_max_chars=chunk_max_chars,
                chunk_silence_ms=chunk_silence_ms,
                segment_workers=segment_workers,
                script_preview_source=script,
            )
        except RuntimeError as exc:
            http_request.app.state.podcast_jobs.update(
                job.job_id,
                status="failed",
                error_summary="podcast executor is unavailable",
            )
            raise HTTPException(status_code=503, detail="podcast executor is unavailable") from exc
        future.add_done_callback(_log_podcast_future_error)
        return _podcast_job_payload(http_request.app.state.podcast_jobs.get(job.job_id))

    @app.get("/v1/podcast/jobs/{job_id}")
    def get_podcast_job(job_id: str, http_request: Request) -> dict[str, Any]:
        job = http_request.app.state.podcast_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="podcast job not found")
        return _podcast_job_payload(job)

    @app.delete("/v1/podcast/jobs/{job_id}")
    def cancel_podcast_job(job_id: str, http_request: Request) -> dict[str, Any]:
        job = http_request.app.state.podcast_jobs.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="podcast job not found")
        return _podcast_job_payload(job)

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
            if sidecar_path.name.endswith((".transcript.json", ".podcast.json")):
                continue
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

    @app.get("/v1/artifacts/{artifact_id}/transcript", response_model=None)
    def artifact_transcript(
        http_request: Request,
        artifact_id: str,
        format: Annotated[Literal["txt", "srt", "vtt", "json"], Query()] = "txt",
        timestamps: Annotated[bool, Query()] = False,
        speakers: Annotated[bool, Query()] = False,
    ) -> Response:
        _ensure_trusted_artifact_request(http_request)
        artifact = _read_artifact_sidecar(root, artifact_id)
        if artifact.kind.value != "transcript":
            raise HTTPException(status_code=422, detail="artifact is not a transcript")
        try:
            payload = ArtifactStore(root).read_transcript_payload(
                cast(TranscriptArtifact, artifact)
            )
            if format == "json":
                return JSONResponse(render_json(payload))
            if format == "srt":
                rendered = render_srt(payload)
                media_type = "application/x-subrip; charset=utf-8"
                suffix = ".srt"
            elif format == "vtt":
                rendered = render_vtt(payload)
                media_type = "text/vtt; charset=utf-8"
                suffix = ".vtt"
            else:
                rendered = render_txt(payload, timestamps=timestamps, speakers=speakers)
                media_type = "text/plain; charset=utf-8"
                suffix = ".txt"
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            rendered,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_download_filename(artifact, suffix)}"'
                )
            },
        )

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
        if artifact.kind.value == "transcript":
            if format.strip().lower() != "source":
                raise HTTPException(
                    status_code=422,
                    detail="transcript formats are available from the transcript endpoint",
                )
            return FileResponse(
                path,
                media_type=artifact.mime_type,
                filename=_source_download_filename(artifact),
            )
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


def _asr_chunk_session_store(request: Request) -> ASRChunkSessionStore:
    return cast(ASRChunkSessionStore, request.app.state.asr_chunk_sessions)


def _ensure_browser_asr_chunking_enabled(request: Request) -> None:
    if not _config_from_request(request).chunking.asr.browser_upload:
        raise HTTPException(status_code=422, detail="browser ASR chunk upload is disabled")


def _chunk_session_http_error(exc: ASRChunkSessionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _asr_chunk_session_create_payload(
    session: ASRChunkSessionMetadata,
    *,
    config: AppConfig,
) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "browser_slice_formats": ["wav"],
        "backend_accept_formats": BROWSER_BACKEND_ACCEPT_FORMATS,
        "max_chunks": config.chunking.asr.max_chunks,
        "expires_at": session.expires_at.isoformat(),
    }


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
            "requires_api_key": False,
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
            mask_api_key_preview(api_key, trusted_local=trusted_local) if requires_api_key else None
        ),
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
    request: ASRRequest | None,
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


def _validate_asr_provider_options(
    request: Request,
    *,
    provider_id: str,
    model_id: str | None,
    raw_provider_options: str | None,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        submitted = parse_provider_options_json(raw_provider_options)
        provider_config = _configured_provider_for_id(_config_from_request(request), provider_id)
        model_options: list[Any] = []
        resolved_model_id = (
            model_id
            if model_id is not None
            else _default_model_for_capability(provider_config, ASR_CAPABILITY)
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
            capability=ASR_CAPABILITY,
        )
        validated = validate_provider_options(submitted, specs, capability=ASR_CAPABILITY)
        metadata = build_provider_option_metadata(validated, specs)
        return validated, metadata
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ensure_transcript_richness_supported(
    request: Request,
    *,
    provider_id: str,
    model_id: str | None,
    timestamps: bool,
    speakers: bool,
) -> None:
    if not timestamps and not speakers:
        return
    capabilities = _transcript_capabilities_for_model(
        _config_from_request(request),
        provider_id=provider_id,
        model_id=model_id,
    )
    if timestamps and not capabilities.timestamps:
        raise HTTPException(status_code=422, detail="model does not support transcript timestamps")
    if speakers and not capabilities.speakers:
        raise HTTPException(status_code=422, detail="model does not support transcript speakers")


def _transcript_capabilities_for_model(
    config: AppConfig,
    *,
    provider_id: str,
    model_id: str | None,
) -> TranscriptCapabilities:
    provider_config = _configured_provider_for_id(config, provider_id)
    resolved_model_id = (
        model_id
        if model_id is not None
        else _default_model_for_capability(provider_config, ASR_CAPABILITY)
    )
    if provider_config is None or resolved_model_id is None:
        return TranscriptCapabilities()
    configured_model = next(
        (model for model in provider_config.models if model.id == resolved_model_id),
        None,
    )
    if configured_model is None or configured_model.transcript_capabilities is None:
        return TranscriptCapabilities()
    return configured_model.transcript_capabilities


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
    if config_provider.api_key_env is None:
        return
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
    # Generate an 80-char preview for the history list. By this point
    # prepared.request.text holds the resolved text whether the source was
    # inline or an uploaded text file, so the file-source guard that used to
    # live here starved every file upload of a preview.
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


def _reject_mismatched_session_finish(
    session: ASRChunkSessionMetadata,
    *,
    provider_id: str | None,
    model: str | None,
    language: ASRLanguage | None,
    transcript_timestamps: bool | None,
    transcript_speakers: bool | None,
    provider_options: str | None,
) -> dict[str, object]:
    if provider_id is not None and provider_id != session.provider_id:
        raise ASRChunkSessionError("provider_id does not match chunk session", status_code=409)
    if model is not None and model != session.model:
        raise ASRChunkSessionError("model does not match chunk session", status_code=409)
    if language is not None and language != session.language:
        raise ASRChunkSessionError("language does not match chunk session", status_code=409)
    if transcript_timestamps is not None and transcript_timestamps != session.transcript_timestamps:
        raise ASRChunkSessionError(
            "transcript_timestamps does not match chunk session",
            status_code=409,
        )
    if transcript_speakers is not None and transcript_speakers != session.transcript_speakers:
        raise ASRChunkSessionError(
            "transcript_speakers does not match chunk session",
            status_code=409,
        )
    if provider_options is None:
        if session.provider_options:
            return session.provider_options
        if session.provider_options_hash:
            raise ASRChunkSessionError(
                "provider_options are required to finish this chunk session",
                status_code=409,
            )
        return {}
    try:
        submitted = parse_provider_options_json(provider_options)
    except ValueError as exc:
        raise ASRChunkSessionError(str(exc)) from exc
    if provider_options_fingerprint(submitted) != session.provider_options_hash:
        raise ASRChunkSessionError(
            "provider_options do not match chunk session",
            status_code=409,
        )
    return submitted


def _run_asr_chunk_session_finish(
    *,
    http_request: Request,
    session: ASRChunkSessionMetadata,
    chunks: list[ASRChunkRecord],
) -> dict[str, Any]:
    _ensure_provider_configured_for_operation(http_request, session.provider_id)
    provider_registry = _registry_from_request(http_request)
    provider = _get_provider(provider_registry, session.provider_id)
    try:
        provider_registry.ensure_asr_capability(session.provider_id)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _ensure_model_allowed(provider, session.model, expected_capability=ASR_CAPABILITY)
    config = _config_from_request(http_request)
    store = _asr_chunk_session_store(http_request)
    transcript_chunks: list[TranscriptChunk] = []
    started_at = datetime.now(UTC)
    model_used = session.model
    try:
        for chunk in chunks:
            request = _build_asr_request(
                provider_id=session.provider_id,
                model=session.model,
                audio_path=store.chunk_path(session.session_id, chunk.index),
                mime_type=chunk.mime_type,
                raw_byte_size=chunk.raw_byte_size,
                base64_size=chunk.base64_size,
                language=session.language,
                provider_options=session.provider_options,
                transcript_timestamps=session.transcript_timestamps,
                transcript_speakers=session.transcript_speakers,
            )
            asr_provider = _ensure_asr_provider(provider_registry, session.provider_id, request)
            payload = asr_provider.transcribe_payload(request)
            transcript_chunks.append(
                TranscriptChunk(payload=payload, start_seconds=chunk.offset_ms / 1000)
            )
            model_used = request.model or model_used
    except ProviderError as exc:
        _log_operation(
            operation="asr",
            status="failed",
            provider_id=session.provider_id,
            model=session.model,
            error_summary=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    merged = merge_transcript_chunks(
        transcript_chunks,
        dedupe_min_chars=config.chunking.asr.dedupe_min_chars,
        dedupe_max_chars=config.chunking.asr.dedupe_max_chars,
    )
    operation_id = f"asr-{uuid4().hex}"
    artifact = ArtifactStore(http_request.app.state.artifact_root).write_transcript(
        operation_id=operation_id,
        provider_id=session.provider_id,
        operation="asr",
        text=merged.payload.text,
        payload=merged.payload,
        metadata={
            **session.option_metadata,
            "base64_size": sum(chunk.base64_size for chunk in chunks),
            "chunking_audio_durations_ms": [chunk.duration_ms for chunk in chunks],
            "chunking_chunk_count": len(chunks),
            "chunking_dedupe_removed_chars": merged.dedupe_removed_chars,
            "chunking_enabled": True,
            "chunking_mode": "browser",
            "chunking_operation": "asr",
            "chunking_overlap_ms": _max_chunk_overlap_ms(chunks),
            "chunking_strategy": "browser_upload",
            "chunking_transcript_lengths": [len(chunk.payload.text) for chunk in transcript_chunks],
            "language": session.language,
            "model": model_used,
            "operation": "asr",
            "provider_id": session.provider_id,
            "raw_byte_size": sum(chunk.raw_byte_size for chunk in chunks),
            "source_file_name_hash": session.source_file_name_hash,
            "source_file_suffix": session.source_file_suffix,
            "uploaded_file_mime_type": "audio/wav",
            "uploaded_file_suffix": ".wav",
        },
    )
    finished_at = datetime.now(UTC)
    ArtifactStore(http_request.app.state.artifact_root).record_operation(
        OperationResult(
            operation_id=operation_id,
            operation="asr",
            status=OperationStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            artifact_ids=[artifact.id],
        )
    )
    _log_operation(
        operation="asr",
        status="completed",
        provider_id=session.provider_id,
        model=artifact.metadata.get("model") if isinstance(artifact.metadata, dict) else None,
        artifact_id=artifact.id,
        elapsed_ms=int((finished_at - started_at).total_seconds() * 1000),
    )
    return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)


def _run_asr_upload(
    *,
    http_request: Request,
    provider_id: str,
    model: str | None,
    language: ASRLanguage,
    source_path: Path,
    source_format: AudioFormat,
    source_mime_type: str,
    source_suffix: str,
    chunking_mode: Literal["off", "auto", "force"] | None,
    chunk_seconds: int | None,
    chunk_overlap_ms: int | None,
    transcript_timestamps: bool,
    transcript_speakers: bool,
    provider_options: dict[str, object],
    option_metadata: Mapping[str, object],
) -> dict[str, Any]:
    config = _config_from_request(http_request)
    resolved_mode = chunking_mode or config.chunking.asr.mode
    if chunk_seconds is not None and not 10 <= chunk_seconds <= 600:
        raise HTTPException(status_code=422, detail="chunk_seconds must be between 10 and 600")
    if chunk_overlap_ms is not None and not 0 <= chunk_overlap_ms <= 10000:
        raise HTTPException(status_code=422, detail="chunk_overlap_ms must be between 0 and 10000")
    provider_registry = _registry_from_request(http_request)
    provider = _get_provider(provider_registry, provider_id)
    try:
        provider_registry.ensure_asr_capability(provider_id)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _ensure_model_allowed(provider, model, expected_capability=ASR_CAPABILITY)
    started_at = datetime.now(UTC)
    try:
        if resolved_mode != "force" and _file_fits_provider_limit(source_path):
            provider_audio = _convert_upload_for_provider(
                source_path.read_bytes(),
                source_format=source_format,
                provider_id=provider_id,
                operation="asr",
            )
            request_path = source_path.with_name(f"provider{provider_audio.suffix}")
            request_path.write_bytes(provider_audio.data)
            request = _build_asr_request(
                provider_id=provider_id,
                model=model,
                audio_path=request_path,
                mime_type=provider_audio.mime_type,
                raw_byte_size=len(provider_audio.data),
                base64_size=_base64_size(provider_audio.data),
                language=language,
                provider_options=provider_options,
                artifact_metadata=dict(option_metadata),
                transcript_timestamps=transcript_timestamps,
                transcript_speakers=transcript_speakers,
            )
            provider = _ensure_asr_provider(provider_registry, provider_id, request)
            artifact = provider.transcribe(request)
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
        if resolved_mode == "off":
            raise HTTPException(status_code=413, detail="audio base64 payload exceeds 10 MiB")
    except HTTPException as exc:
        if resolved_mode == "off" or exc.status_code != 413:
            raise
    except ProviderError as exc:
        _log_operation(
            operation="asr",
            status="failed",
            provider_id=provider_id,
            model=model,
            error_summary=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        artifact = _run_chunked_asr(
            provider=provider,
            provider_id=provider_id,
            model=model,
            language=language,
            source_path=source_path,
            source_format=source_format,
            source_mime_type=source_mime_type,
            source_suffix=source_suffix,
            chunk_seconds=chunk_seconds,
            chunk_overlap_ms=chunk_overlap_ms,
            transcript_timestamps=transcript_timestamps,
            transcript_speakers=transcript_speakers,
            provider_options=provider_options,
            option_metadata=option_metadata,
            artifact_root=http_request.app.state.artifact_root,
            started_at=started_at,
            chunking_mode=resolved_mode,
            config=config,
        )
    except ASRAudioChunkingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except AudioConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        _log_operation(
            operation="asr",
            status="failed",
            provider_id=provider_id,
            model=model,
            error_summary=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finished_at = datetime.now(UTC)
    _log_operation(
        operation="asr",
        status="completed",
        provider_id=provider_id,
        model=artifact.metadata.get("model") if isinstance(artifact.metadata, dict) else None,
        artifact_id=artifact.id,
        elapsed_ms=int((finished_at - started_at).total_seconds() * 1000),
    )
    return _operation_payload(artifact, started_at=started_at, finished_at=finished_at)


def _max_chunk_overlap_ms(chunks: list[ASRChunkRecord]) -> int:
    overlap = 0
    previous_end = 0
    for chunk in sorted(chunks, key=lambda item: item.offset_ms):
        if chunk.offset_ms < previous_end:
            overlap = max(overlap, previous_end - chunk.offset_ms)
        previous_end = max(previous_end, chunk.end_ms)
    return overlap


def _run_chunked_asr(
    *,
    provider: Any,
    provider_id: str,
    model: str | None,
    language: ASRLanguage,
    source_path: Path,
    source_format: AudioFormat,
    source_mime_type: str,
    source_suffix: str,
    chunk_seconds: int | None,
    chunk_overlap_ms: int | None,
    transcript_timestamps: bool,
    transcript_speakers: bool,
    provider_options: dict[str, object],
    option_metadata: Mapping[str, object],
    artifact_root: Path,
    started_at: datetime,
    chunking_mode: str,
    config: AppConfig,
) -> TranscriptArtifact:
    chunk_dir = source_path.parent / "asr-chunks"
    chunks = plan_asr_audio_chunks(
        source_path,
        source_format=source_format,
        output_dir=chunk_dir,
        config=config.chunking.asr,
        target_seconds=chunk_seconds,
        overlap_ms=chunk_overlap_ms,
        max_raw_bytes=MAX_UPLOAD_RAW_BYTES,
        max_base64_bytes=MAX_BASE64_AUDIO_SIZE,
    )
    transcript_chunks: list[TranscriptChunk] = []
    model_used = model
    for chunk in chunks:
        request = _build_asr_request(
            provider_id=provider_id,
            model=model,
            audio_path=chunk.path,
            mime_type=chunk.mime_type,
            raw_byte_size=chunk.raw_byte_size,
            base64_size=chunk.base64_size,
            language=language,
            provider_options=provider_options,
            transcript_timestamps=transcript_timestamps,
            transcript_speakers=transcript_speakers,
        )
        payload = provider.transcribe_payload(request)
        transcript_chunks.append(
            TranscriptChunk(payload=payload, start_seconds=chunk.start_ms / 1000)
        )
        model_used = request.model or model_used
    merged = merge_transcript_chunks(
        transcript_chunks,
        dedupe_min_chars=config.chunking.asr.dedupe_min_chars,
        dedupe_max_chars=config.chunking.asr.dedupe_max_chars,
    )
    operation_id = f"asr-{uuid4().hex}"
    store = ArtifactStore(artifact_root)
    artifact = store.write_transcript(
        operation_id=operation_id,
        provider_id=provider_id,
        operation="asr",
        text=merged.payload.text,
        payload=merged.payload,
        metadata={
            **dict(option_metadata),
            "base64_size": sum(chunk.base64_size for chunk in chunks),
            "chunking_audio_durations_ms": [chunk.duration_ms for chunk in chunks],
            "chunking_chunk_count": len(chunks),
            "chunking_dedupe_removed_chars": merged.dedupe_removed_chars,
            "chunking_enabled": True,
            "chunking_mode": chunking_mode,
            "chunking_operation": "asr",
            "chunking_overlap_ms": (
                config.chunking.asr.overlap_ms if chunk_overlap_ms is None else chunk_overlap_ms
            ),
            "chunking_strategy": "audio_overlap",
            "chunking_target_seconds": (
                config.chunking.asr.target_seconds if chunk_seconds is None else chunk_seconds
            ),
            "chunking_transcript_lengths": [len(chunk.payload.text) for chunk in transcript_chunks],
            "language": language,
            "model": model_used,
            "operation": "asr",
            "provider_id": provider_id,
            "raw_byte_size": sum(chunk.raw_byte_size for chunk in chunks),
            "source_file_name_hash": _file_name_hash(source_path.name),
            "source_file_suffix": source_suffix,
            "uploaded_file_mime_type": source_mime_type,
            "uploaded_file_suffix": source_suffix,
        },
    )
    store.record_operation(
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


def _podcast_job_payload(job: PodcastJobStatus | None) -> dict[str, Any]:
    if job is None:
        raise HTTPException(status_code=404, detail="podcast job not found")
    payload = job.model_dump(mode="json", exclude={"artifact"})
    payload["artifact"] = _safe_artifact_payload(job.artifact) if job.artifact is not None else None
    return payload


def _parse_speaker_voices(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="speaker_voices must be JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="speaker_voices must be an object")
    voices: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise HTTPException(
                status_code=422,
                detail="speaker_voices values must be non-empty strings",
            )
        voices[key.strip()] = value.strip()
    return voices


def _parse_podcast_script_or_422(
    script: str,
    script_format: PodcastScriptFormat,
    default_pause_ms: int,
) -> PodcastScript:
    try:
        return parse_podcast_script(
            script,
            script_format=script_format,
            default_pause_ms=default_pause_ms,
        )
    except PodcastParseError as exc:
        detail = f"line {exc.line}: {exc}" if exc.line is not None else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc


def _resolve_podcast_voice_ids(
    speakers: list[PodcastSpeaker],
    voices_by_key: dict[str, str],
) -> dict[str, str]:
    allowed_keys = {speaker.id for speaker in speakers} | {speaker.name for speaker in speakers}
    unknown = sorted(key for key in voices_by_key if key not in allowed_keys)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown speaker voice mapping for: {', '.join(unknown)}",
        )
    missing = [
        speaker.name
        for speaker in speakers
        if speaker.id not in voices_by_key and speaker.name not in voices_by_key
    ]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"missing voice mapping for: {', '.join(missing)}"
        )
    return {
        speaker.id: voices_by_key.get(speaker.id) or voices_by_key[speaker.name]
        for speaker in speakers
    }


def _validate_podcast_pauses(parsed: PodcastScript, default_pause_ms: int) -> None:
    if default_pause_ms > MAX_PODCAST_PAUSE_MS:
        raise HTTPException(
            status_code=422,
            detail=f"default_pause_ms must be less than or equal to {MAX_PODCAST_PAUSE_MS}",
        )
    total_pause_ms = 0
    for index, segment in enumerate(parsed.segments):
        pause_ms = (
            segment.pause_after_ms if segment.pause_after_ms is not None else default_pause_ms
        )
        if index < len(parsed.segments) - 1 and pause_ms > MAX_PODCAST_PAUSE_MS:
            raise HTTPException(
                status_code=422,
                detail=f"pause must be less than or equal to {MAX_PODCAST_PAUSE_MS}",
            )
        if index < len(parsed.segments) - 1:
            total_pause_ms += pause_ms
    if total_pause_ms > MAX_PODCAST_TOTAL_PAUSE_MS:
        raise HTTPException(
            status_code=422,
            detail=f"total podcast pause must be less than or equal to {MAX_PODCAST_TOTAL_PAUSE_MS}",
        )


def _validate_podcast_voice_ids(
    provider: Any,
    model_id: str | None,
    speaker_voice_ids: Mapping[str, str],
) -> None:
    available_voice_ids = {voice.id for voice in provider.list_voices()}
    selected_model_voice_ids: set[str] | None = None
    for model_info in provider.list_models():
        if model_id is None or model_info.id == model_id:
            model_voice_ids = {voice.id for voice in model_info.voices}
            if model_id is not None and model_voice_ids:
                selected_model_voice_ids = model_voice_ids
                break
            available_voice_ids.update(model_voice_ids)
    if selected_model_voice_ids is not None:
        available_voice_ids = selected_model_voice_ids
    if not available_voice_ids:
        return
    unknown = sorted(
        {voice_id for voice_id in speaker_voice_ids.values() if voice_id not in available_voice_ids}
    )
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown voice_id for podcast: {', '.join(unknown)}",
        )


@dataclass(frozen=True)
class _PodcastSegmentSynthesis:
    index: int
    speaker_name: str
    text_preview: str
    duration_ms: int
    audio_segment: PodcastAudioSegment
    manifest_segment: PodcastManifestSegment


class _PodcastJobCancelled(RuntimeError):
    pass


def _run_podcast_job(
    *,
    app: FastAPI,
    job_id: str,
    provider: Any,
    provider_id: str,
    model: str | None,
    parsed: PodcastScript,
    default_pause_ms: int,
    speaker_voice_ids: dict[str, str],
    provider_options: dict[str, object],
    option_metadata: Mapping[str, object],
    chunking_mode: Literal["off", "auto", "force"] | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
    segment_workers: int,
    script_preview_source: str,
) -> None:
    store: PodcastJobStore = app.state.podcast_jobs
    config: AppConfig = app.state.config
    started_at = datetime.now(UTC)
    try:
        store.update(job_id, status="running", total_segments=len(parsed.segments))
        voice_lookup = {voice.id: voice.name for voice in provider.list_voices()}
        segment_results = _synthesize_podcast_segments(
            store=store,
            job_id=job_id,
            provider=provider,
            provider_id=provider_id,
            config=config,
            model=model,
            parsed=parsed,
            default_pause_ms=default_pause_ms,
            speaker_voice_ids=speaker_voice_ids,
            provider_options=provider_options,
            option_metadata=option_metadata,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
            requested_workers=segment_workers,
        )
        audio_segments = [result.audio_segment for result in segment_results]
        manifest_segments = [result.manifest_segment for result in segment_results]
        if store.is_cancelled(job_id):
            store.update(job_id, status="cancelled")
            return
        merged = merge_podcast_audio(audio_segments, output_format="wav")
        if store.is_cancelled(job_id):
            store.update(job_id, status="cancelled")
            return
        for segment, timing in zip(manifest_segments, merged.segments, strict=True):
            segment.start_ms = timing.start_ms
            segment.end_ms = timing.end_ms
            segment.audio_duration_ms = timing.audio_duration_ms
        manifest = PodcastManifest(
            provider_id=provider_id,
            model=model,
            default_pause_ms=default_pause_ms,
            speakers=[
                PodcastManifestSpeaker(
                    id=speaker.id,
                    name=speaker.name,
                    voice_id=speaker_voice_ids[speaker.id],
                    voice_name=voice_lookup.get(speaker_voice_ids[speaker.id]),
                )
                for speaker in parsed.speakers
            ],
            segments=manifest_segments,
        )
        operation_id = job_id
        artifact_store = ArtifactStore(app.state.artifact_root)
        artifact = artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=provider_id,
            operation="podcast",
            audio=merged.audio.audio,
            mime_type=merged.audio.mime_type,
            suffix=merged.audio.suffix,
            metadata={
                **dict(option_metadata),
                "operation": "podcast",
                "model": model,
                "source_text": script_preview_source,
                "source_text_preview": _preview_text(script_preview_source),
                "podcast_mode": "builtin",
                "podcast_default_pause_ms": default_pause_ms,
                "podcast_manifest_version": 1,
                "podcast_manifest_sidecar": True,
                "podcast_speaker_count": len(parsed.speakers),
                "podcast_segment_count": len(parsed.segments),
                "podcast_speakers": [speaker.name for speaker in parsed.speakers],
                "podcast_voice_ids": list(speaker_voice_ids.values()),
            },
        )
        _write_podcast_manifest(artifact.path, manifest)
        artifact_store.record_operation(
            OperationResult(
                operation_id=operation_id,
                operation="podcast",
                status=OperationStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                artifact_ids=[artifact.id],
            )
        )
        store.update(job_id, status="completed", artifact=artifact)
    except _PodcastJobCancelled:
        store.update(job_id, status="cancelled")
    except AudioConversionError as exc:
        current = store.get(job_id)
        store.update(
            job_id,
            status="failed",
            error_summary=str(exc),
            failed_segment=PodcastFailedSegment(
                index=max(0, (current.current_segment if current else 1) - 1),
                speaker=(current.current_speaker if current else "") or "",
            ),
        )
    except ProviderError as exc:
        current = store.get(job_id)
        store.update(
            job_id,
            status="failed",
            error_summary=str(exc),
            failed_segment=PodcastFailedSegment(
                index=max(0, (current.current_segment if current else 1) - 1),
                speaker=(current.current_speaker if current else "") or "",
            ),
        )
    except Exception as exc:
        logger.exception("podcast job {} failed unexpectedly: {}", job_id, exc)
        store.update(job_id, status="failed", error_summary="podcast generation failed")


def _log_podcast_future_error(future: Future[None]) -> None:
    try:
        future.result()
    except Exception as exc:  # pragma: no cover - _run_podcast_job catches normal failures.
        logger.exception("podcast executor task failed outside job handler: {}", exc)


def _synthesize_podcast_segments(
    *,
    store: PodcastJobStore,
    job_id: str,
    provider: Any,
    provider_id: str,
    config: AppConfig,
    model: str | None,
    parsed: PodcastScript,
    default_pause_ms: int,
    speaker_voice_ids: dict[str, str],
    provider_options: dict[str, object],
    option_metadata: Mapping[str, object],
    chunking_mode: Literal["off", "auto", "force"] | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
    requested_workers: int,
) -> list[_PodcastSegmentSynthesis]:
    segment_count = len(parsed.segments)
    worker_count = _podcast_segment_worker_count(
        provider_id,
        provider,
        segment_count,
        requested_workers,
    )
    if worker_count == 1:
        results: list[_PodcastSegmentSynthesis] = []
        for index, segment in enumerate(parsed.segments):
            if store.is_cancelled(job_id):
                raise _PodcastJobCancelled
            result = _synthesize_podcast_segment(
                index=index,
                segment_count=segment_count,
                segment=segment,
                provider=provider,
                provider_id=provider_id,
                config=config,
                model=model,
                default_pause_ms=default_pause_ms,
                voice_id=speaker_voice_ids[segment.speaker_id],
                provider_options=provider_options,
                option_metadata=option_metadata,
                chunking_mode=chunking_mode,
                chunk_max_chars=chunk_max_chars,
                chunk_silence_ms=chunk_silence_ms,
            )
            results.append(result)
            _record_podcast_segment_progress(store, job_id, result, len(results), segment_count)
        return results

    results: list[_PodcastSegmentSynthesis | None] = [None] * segment_count
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="voice-toolbox-podcast-segment",
    ) as executor:
        futures: dict[Future[_PodcastSegmentSynthesis], int] = {}
        for index, segment in enumerate(parsed.segments):
            if store.is_cancelled(job_id):
                raise _PodcastJobCancelled
            futures[
                executor.submit(
                    _synthesize_podcast_segment,
                    index=index,
                    segment_count=segment_count,
                    segment=segment,
                    provider=provider,
                    provider_id=provider_id,
                    config=config,
                    model=model,
                    default_pause_ms=default_pause_ms,
                    voice_id=speaker_voice_ids[segment.speaker_id],
                    provider_options=provider_options,
                    option_metadata=option_metadata,
                    chunking_mode=chunking_mode,
                    chunk_max_chars=chunk_max_chars,
                    chunk_silence_ms=chunk_silence_ms,
                )
            ] = index

        completed_count = 0
        for future in as_completed(futures):
            if store.is_cancelled(job_id):
                _cancel_pending_futures(futures)
                raise _PodcastJobCancelled
            try:
                result = future.result()
            except (AudioConversionError, ProviderError):
                failed_index = futures[future]
                failed_segment = parsed.segments[failed_index]
                store.update(
                    job_id,
                    current_segment=failed_index + 1,
                    current_speaker=failed_segment.speaker_name,
                    current_text_preview=_preview_text(failed_segment.text, 80),
                )
                _cancel_pending_futures(futures)
                raise
            completed_count += 1
            results[result.index] = result
            _record_podcast_segment_progress(
                store,
                job_id,
                result,
                completed_count,
                segment_count,
            )
    return [cast(_PodcastSegmentSynthesis, result) for result in results]


def _synthesize_podcast_segment(
    *,
    index: int,
    segment_count: int,
    segment: PodcastSegment,
    provider: Any,
    provider_id: str,
    config: AppConfig,
    model: str | None,
    default_pause_ms: int,
    voice_id: str,
    provider_options: dict[str, object],
    option_metadata: Mapping[str, object],
    chunking_mode: Literal["off", "auto", "force"] | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
) -> _PodcastSegmentSynthesis:
    segment_started_at = perf_counter()
    prepared = _prepare_tts_or_422(
        raw_text=TextSource(text=segment.text),
        text_format=None,
        config=config,
        chunking_mode=chunking_mode,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
        fields={
            "provider_id": provider_id,
            "mode": TTSMode.BUILTIN,
            "model": model,
            "voice_id": voice_id,
            "provider_options": provider_options,
        },
        artifact_metadata=option_metadata,
    )
    result = _synthesize_prepared_segment(provider, prepared)
    pause_after_ms = (
        segment.pause_after_ms if segment.pause_after_ms is not None else default_pause_ms
    )
    if index == segment_count - 1:
        pause_after_ms = 0
    return _PodcastSegmentSynthesis(
        index=index,
        speaker_name=segment.speaker_name,
        text_preview=_preview_text(segment.text, 80),
        duration_ms=round((perf_counter() - segment_started_at) * 1000),
        audio_segment=PodcastAudioSegment(result=result, pause_after_ms=pause_after_ms),
        manifest_segment=PodcastManifestSegment(
            index=index,
            speaker_id=segment.speaker_id,
            speaker_name=segment.speaker_name,
            voice_id=voice_id,
            text=segment.text,
            source_line=segment.source_line,
            pause_after_ms=pause_after_ms,
        ),
    )


def _record_podcast_segment_progress(
    store: PodcastJobStore,
    job_id: str,
    result: _PodcastSegmentSynthesis,
    completed_count: int,
    segment_count: int,
) -> None:
    store.record_segment_duration_ms(job_id, result.duration_ms)
    store.update(
        job_id,
        current_segment=min(completed_count + 1, segment_count),
        completed_segments=completed_count,
        current_speaker=result.speaker_name,
        current_text_preview=result.text_preview,
    )


def _cancel_pending_futures(futures: Mapping[Future[_PodcastSegmentSynthesis], int]) -> None:
    for pending in futures:
        pending.cancel()


def _podcast_segment_worker_count(
    provider_id: str,
    provider: Any,
    segment_count: int,
    requested_workers: int,
) -> int:
    if segment_count <= 0:
        return 1
    if provider_id in LOCAL_PODCAST_PROVIDER_IDS or provider.__class__.__module__.endswith(
        ".mlx_audio"
    ):
        return 1
    return min(MAX_PODCAST_SEGMENT_WORKERS, max(1, requested_workers), segment_count)


def _synthesize_prepared_segment(
    provider: Any,
    prepared: PreparedTTSRequest,
) -> ProviderAudioResult:
    if prepared.chunk_plan is None or not prepared.chunk_plan.chunking_enabled:
        return provider.synthesize_bytes(prepared.request)
    results = [
        provider.synthesize_bytes(prepared.request.model_copy(update={"text": chunk.text}))
        for chunk in prepared.chunk_plan.chunks
    ]
    return merge_audio_results(
        results,
        silence_ms=prepared.chunk_plan.silence_ms,
        output_format="wav",
    )


def _write_podcast_manifest(audio_path: Path, manifest: PodcastManifest) -> None:
    manifest_path = audio_path.with_suffix(".podcast.json").resolve(strict=False)
    if manifest_path.parent != audio_path.parent.resolve(strict=False):
        raise ValueError("podcast manifest path escapes artifact directory")
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    with manifest_path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
    manifest_path.chmod(0o600)


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


def _read_upload_stream_limited(
    upload: UploadFile,
    *,
    max_bytes: int,
    too_large_detail: str,
) -> bytes:
    if max_bytes <= 0:
        if upload.file.read(1):
            raise HTTPException(status_code=413, detail=too_large_detail)
        raise HTTPException(status_code=422, detail="upload file is empty")
    chunks: list[bytes] = []
    total = 0
    while True:
        read_size = max(1, min(1024 * 1024, max_bytes + 1 - total))
        chunk = upload.file.read(read_size)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail)
    if total == 0:
        raise HTTPException(status_code=422, detail="upload file is empty")
    return b"".join(chunks)


def _read_file_prefix(path: Path, byte_count: int) -> bytes:
    with path.open("rb") as file:
        return file.read(byte_count)


def _file_fits_provider_limit(path: Path) -> bool:
    raw_size = path.stat().st_size
    return (
        raw_size <= MAX_UPLOAD_RAW_BYTES
        and _base64_size_by_length(raw_size) <= MAX_BASE64_AUDIO_SIZE
    )


def _looks_like_supported_audio_upload(contents: bytes, mime_type: str, suffix: str) -> bool:
    try:
        audio_format = validate_mime_suffix_match(mime_type, suffix)
    except AudioConversionError:
        return False
    if audio_format == "wav":
        return contents.startswith(b"RIFF") and contents[8:12] == b"WAVE"
    if audio_format == "mp3":
        return contents.startswith(b"ID3") or _looks_like_adts_or_mpeg_frame(contents)
    if audio_format == "flac":
        return contents.startswith(b"fLaC")
    if audio_format == "m4a":
        return len(contents) >= 12 and contents[4:8] == b"ftyp"
    if audio_format == "ogg":
        return contents.startswith(b"OggS")
    if audio_format == "webm":
        return contents.startswith(b"\x1a\x45\xdf\xa3")
    if audio_format == "aac":
        return _looks_like_adts_or_mpeg_frame(contents)
    return audio_format == "pcm"


def _looks_like_adts_or_mpeg_frame(contents: bytes) -> bool:
    return len(contents) >= 2 and contents[0] == 0xFF and contents[1] & 0xE0 == 0xE0


def _save_upload_to_temp(
    upload: UploadFile,
    *,
    output_dir: Path,
    max_upload_mb: int,
) -> Path:
    suffix = _suffix_for_upload(upload.filename)
    output_path = output_dir / _safe_upload_filename(upload.filename, suffix)
    max_bytes = max_upload_mb * 1024 * 1024
    total = 0
    with output_path.open("xb") as output_file:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"audio upload exceeds {max_upload_mb} MiB",
                )
            output_file.write(chunk)
    if total == 0:
        raise HTTPException(status_code=422, detail="upload file is empty")
    output_path.chmod(0o600)
    return output_path


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


def _is_pcm_wav(contents: bytes) -> bool:
    if not (contents.startswith(b"RIFF") and contents[8:12] == b"WAVE"):
        return False
    offset = 12
    while offset + 8 <= len(contents):
        chunk_id = contents[offset : offset + 4]
        chunk_size = int.from_bytes(contents[offset + 4 : offset + 8], "little")
        payload_offset = offset + 8
        if payload_offset + chunk_size > len(contents):
            return False
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                return False
            return int.from_bytes(contents[payload_offset : payload_offset + 2], "little") == 1
        offset = payload_offset + chunk_size + (chunk_size % 2)
    return False


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
    return _base64_size_by_length(len(contents))


def _base64_size_by_length(raw_byte_size: int) -> int:
    return ((raw_byte_size + 2) // 3) * 4


def _file_name_hash(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:12]


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
        try:
            return _preview_text(artifact.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return ""
    if isinstance(artifact.metadata, dict):
        return _preview_text(artifact.metadata.get("source_text_preview"))
    return ""
