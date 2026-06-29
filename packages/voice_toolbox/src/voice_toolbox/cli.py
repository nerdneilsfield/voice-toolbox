from __future__ import annotations

import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Literal, NoReturn, cast
from uuid import uuid4

import typer
from loguru import logger
from pydantic import ValidationError

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.audio_conversion import AudioConversionError, format_from_mime
from voice_toolbox.chunking.audio import ASRAudioChunkingError, plan_asr_audio_chunks
from voice_toolbox.chunking.merge import (
    TranscriptChunk,
    merge_audio_results,
    merge_transcript_chunks,
)
from voice_toolbox.chunking.models import TextSource
from voice_toolbox.chunking.text import TextSourceError, resolve_text_source
from voice_toolbox.config import AppConfig, load_app_config, load_env_values, replay_config_warnings
from voice_toolbox.logging_config import configure_logging, sanitize_log_metadata
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    OperationResult,
    OperationStatus,
    TranscriptArtifact,
    TranscriptCapabilities,
    TTSMode,
)
from voice_toolbox.models import TTSOutputFormat
from voice_toolbox.pipeline import PreparedTTSRequest, prepare_tts_request
from voice_toolbox.providers import ProviderError, ProviderRegistry
from voice_toolbox.providers.factory import (
    build_provider_registry as build_configured_provider_registry,
)
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE

app = typer.Typer(help="Voice Toolbox")
tts_app = typer.Typer(help="Text-to-speech commands")
asr_app = typer.Typer(help="Speech-to-text commands")

DEFAULT_OUTPUT_FORMAT: Literal["wav"] = "wav"
SUPPORTED_AUDIO_MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}
AudioMime = Literal["audio/wav", "audio/mpeg", "audio/mp3"]
_CLI_CONFIG: AppConfig | None = None
_CLI_ENV_VALUES: dict[str, str] | None = None
_CLI_LOGGING_SIGNATURE: tuple[str | None, str] | None = None


class _PathTextUpload:
    filename: str | None
    content_type: str | None
    file: BinaryIO

    def __init__(self, path: Path, file: BinaryIO) -> None:
        resolved = path.expanduser()
        self.filename = resolved.name
        self.content_type: str | None = None
        self.file = file


ProviderOption = Annotated[str | None, typer.Option("--provider", help="Provider id.")]
TextOption = Annotated[str, typer.Option("--text", help="Text to synthesize.")]
OptionalTextOption = Annotated[str | None, typer.Option("--text", help="Text to synthesize.")]
TextFormatOption = Annotated[
    Literal["plain", "markdown", "auto"] | None,
    typer.Option("--text-format", help="Input text format."),
]
TextFileOption = Annotated[Path | None, typer.Option("--file", help="Text file: .txt/.md.")]
ChunkingOption = Annotated[
    Literal["off", "auto", "force"] | None,
    typer.Option("--chunking", help="TTS chunking mode."),
]
ChunkMaxCharsOption = Annotated[
    int | None,
    typer.Option("--chunk-max-chars", help="Max chars per TTS chunk."),
]
ChunkSilenceMsOption = Annotated[
    int | None,
    typer.Option("--chunk-silence-ms", help="Silence between TTS chunks in milliseconds."),
]
ASRChunkingOption = Annotated[
    Literal["off", "auto", "force"] | None,
    typer.Option("--chunking", help="ASR chunking mode."),
]
ASRChunkSecondsOption = Annotated[
    int | None,
    typer.Option("--chunk-seconds", help="Target seconds per ASR chunk."),
]
ASRChunkOverlapMsOption = Annotated[
    int | None,
    typer.Option("--chunk-overlap-ms", help="ASR chunk overlap in milliseconds."),
]
ModelOption = Annotated[str | None, typer.Option("--model", help="Provider model id.")]
FormatOption = Annotated[str, typer.Option("--format", help="Output format: wav or mp3.")]
StyleOption = Annotated[
    str | None,
    typer.Option("--style", help="Optional style instruction."),
]


def build_provider_registry() -> ProviderRegistry:
    config, env_values = _load_cli_context()
    return build_configured_provider_registry(
        config,
        artifact_root=Path.cwd(),
        env_values=env_values,
    )


@app.callback()
def main() -> None:
    """Run Voice Toolbox commands."""
    _load_cli_context(refresh=True)


@tts_app.command()
def synthesize(
    voice: Annotated[str, typer.Option("--voice", help="Voice id.")],
    text: OptionalTextOption = None,
    file: TextFileOption = None,
    provider: ProviderOption = None,
    text_format: TextFormatOption = None,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
    style: StyleOption = None,
    chunking: ChunkingOption = None,
    chunk_max_chars: ChunkMaxCharsOption = None,
    chunk_silence_ms: ChunkSilenceMsOption = None,
) -> None:
    config, _ = _load_cli_context()
    registry = build_provider_registry()
    provider_id = _resolve_provider_id(registry, provider)
    source = _prepare_text_source_or_fail(
        text=text,
        file=file,
        text_format=text_format,
        config=config,
        mode=TTSMode.BUILTIN,
    )
    prepared = _prepare_tts_or_fail(
        raw_text=source,
        text_format=None,
        config=config,
        chunking_mode=chunking,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
        fields={
            "provider_id": provider_id,
            "mode": TTSMode.BUILTIN,
            "model": model,
            "style_instruction": style,
            "voice_id": voice,
            "output_format": _normalize_output_format(output_format),
        },
    )
    artifact = _synthesize(registry, provider_id, prepared)
    _print_audio_artifact(artifact)


@tts_app.command()
def design(
    description: Annotated[str, typer.Option("--description", help="Voice description.")],
    text: OptionalTextOption = None,
    file: TextFileOption = None,
    optimize_text_preview: Annotated[
        bool,
        typer.Option("--optimize-text-preview", help="Let provider optimize preview text."),
    ] = False,
    provider: ProviderOption = None,
    text_format: TextFormatOption = None,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
    chunking: ChunkingOption = None,
    chunk_max_chars: ChunkMaxCharsOption = None,
    chunk_silence_ms: ChunkSilenceMsOption = None,
) -> None:
    config, _ = _load_cli_context()
    registry = build_provider_registry()
    provider_id = _resolve_provider_id(registry, provider)
    raw_text = _design_raw_text(text, optimize_text_preview=optimize_text_preview)
    source = _prepare_text_source_or_fail(
        text=raw_text,
        file=file,
        text_format=text_format,
        config=config,
        mode=TTSMode.DESIGN,
        optimize_text_preview=optimize_text_preview,
    )
    prepared = _prepare_tts_or_fail(
        raw_text=source,
        text_format=None,
        config=config,
        chunking_mode=chunking,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
        fields={
            "provider_id": provider_id,
            "mode": TTSMode.DESIGN,
            "model": model,
            "voice_description": description,
            "optimize_text_preview": optimize_text_preview,
            "output_format": _normalize_output_format(output_format),
        },
    )
    artifact = _synthesize(registry, provider_id, prepared)
    _print_audio_artifact(artifact)


@tts_app.command()
def clone(
    sample: Annotated[Path | None, typer.Option("--sample", help="Voice sample wav/mp3.")] = None,
    reference_text: Annotated[
        str | None,
        typer.Option(
            "--reference-text",
            help="Transcript of clone sample; required by Fish Audio direct clone.",
        ),
    ] = None,
    text: OptionalTextOption = None,
    consent: Annotated[
        bool,
        typer.Option("--consent", help="Confirm rights and consent for uploaded voice sample."),
    ] = False,
    provider: ProviderOption = None,
    file: TextFileOption = None,
    text_format: TextFormatOption = None,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
    style: StyleOption = None,
    chunking: ChunkingOption = None,
    chunk_max_chars: ChunkMaxCharsOption = None,
    chunk_silence_ms: ChunkSilenceMsOption = None,
) -> None:
    if sample is None:
        _fail("--sample is required")
    config, _ = _load_cli_context()
    source = _prepare_text_source_or_fail(
        text=text,
        file=file,
        text_format=text_format,
        config=config,
        mode=TTSMode.CLONE,
    )
    sample = _normalize_existing_audio_path(sample)
    consent_confirmed = _confirm_clone_consent(consent)
    mime_type, raw_byte_size, base64_size = _audio_upload_metadata(sample)
    registry = build_provider_registry()
    provider_id = _resolve_provider_id(registry, provider)
    prepared = _prepare_tts_or_fail(
        raw_text=source,
        text_format=None,
        config=config,
        chunking_mode=chunking,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
        fields={
            "provider_id": provider_id,
            "mode": TTSMode.CLONE,
            "model": model,
            "style_instruction": style,
            "clone_reference_text": reference_text,
            "clone_sample_path": sample,
            "clone_mime_type": mime_type,
            "clone_raw_byte_size": raw_byte_size,
            "clone_base64_size": base64_size,
            "consent_confirmed": consent_confirmed,
            "output_format": _normalize_output_format(output_format),
        },
    )
    artifact = _synthesize(registry, provider_id, prepared)
    _print_audio_artifact(artifact)


@asr_app.command()
def transcribe(
    file: Annotated[Path | None, typer.Option("--file", help="Audio file wav/mp3.")] = None,
    language: Annotated[
        Literal["auto", "zh", "en"],
        typer.Option("--language", help="Language hint."),
    ] = "auto",
    provider: ProviderOption = None,
    model: Annotated[str | None, typer.Option("--model", help="Provider ASR model id.")] = None,
    chunking: ASRChunkingOption = None,
    chunk_seconds: ASRChunkSecondsOption = None,
    chunk_overlap_ms: ASRChunkOverlapMsOption = None,
    timestamps: Annotated[
        bool,
        typer.Option("--timestamps", help="Request transcript timestamps."),
    ] = False,
    speakers: Annotated[
        bool,
        typer.Option("--speakers", help="Request transcript speaker labels."),
    ] = False,
) -> None:
    if file is None:
        _fail("--file is required")
    config, _ = _load_cli_context()
    file = _normalize_existing_audio_path(file)
    mime_type, raw_byte_size, base64_size = _audio_upload_metadata(file)
    registry = build_provider_registry()
    provider_id = _resolve_provider_id(registry, provider)
    _ensure_transcript_richness_supported_or_fail(
        config,
        provider_id=provider_id,
        model_id=model,
        timestamps=timestamps,
        speakers=speakers,
    )
    try:
        request = ASRRequest(
            provider_id=provider_id,
            model=model,
            audio_path=file,
            mime_type=mime_type,
            raw_byte_size=raw_byte_size,
            base64_size=base64_size,
            language=language,
            transcript_timestamps=timestamps,
            transcript_speakers=speakers,
        )
    except ValidationError as exc:
        _fail(_safe_validation_message(exc))

    artifact = _transcribe(
        registry,
        provider_id,
        request,
        config=config,
        chunking_mode=chunking,
        chunk_seconds=chunk_seconds,
        chunk_overlap_ms=chunk_overlap_ms,
    )
    _print_transcript_artifact(artifact)


def _prepare_tts_or_fail(
    *,
    raw_text: str | TextSource | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    fields: dict[str, object],
    config: AppConfig,
    chunking_mode: Literal["off", "auto", "force"] | None = None,
    chunk_max_chars: int | None = None,
    chunk_silence_ms: int | None = None,
) -> PreparedTTSRequest:
    try:
        return prepare_tts_request(
            raw_text,
            text_format,
            fields,
            chunking_config=config.chunking.tts,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
        )
    except ValidationError as exc:
        _fail(_safe_validation_message(exc))
    except ValueError as exc:
        _fail(str(exc))


def _prepare_text_source_or_fail(
    *,
    text: str | None,
    file: Path | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    config: AppConfig,
    mode: TTSMode,
    optimize_text_preview: bool = False,
) -> TextSource:
    try:
        if file is not None:
            with file.expanduser().open("rb") as file_obj:
                upload = _PathTextUpload(file, file_obj)
                return resolve_text_source(
                    text=text,
                    text_file=upload,
                    text_format=text_format,
                    max_text_file_bytes=config.chunking.tts.max_text_file_bytes,
                    mode=mode,
                    optimize_text_preview=optimize_text_preview,
                )
        return resolve_text_source(
            text=text,
            text_file=None,
            text_format=text_format,
            max_text_file_bytes=config.chunking.tts.max_text_file_bytes,
            mode=mode,
            optimize_text_preview=optimize_text_preview,
        )
    except TextSourceError as exc:
        _fail(exc.detail)
    except OSError:
        _fail(f"file not found: {file}")


def _design_raw_text(text: str | None, *, optimize_text_preview: bool) -> str | None:
    if not optimize_text_preview:
        return text
    return (text or "").strip() or None


def _synthesize(
    registry: ProviderRegistry,
    provider_id: str,
    prepared: PreparedTTSRequest,
) -> AudioArtifact:
    try:
        provider = registry.ensure_tts_capability(provider_id, prepared.request)
        if prepared.chunk_plan is not None and prepared.chunk_plan.chunking_enabled:
            artifact = _synthesize_chunked(provider, prepared)
        else:
            artifact = provider.synthesize(
                prepared.request,
                artifact_metadata=prepared.artifact_metadata,
            )
        _log_cli_operation(
            operation="tts",
            status="completed",
            provider_id=provider_id,
            model=artifact.metadata.get("model"),
            tts_mode=prepared.request.mode.value,
            artifact_id=artifact.id,
        )
        return artifact
    except (ProviderError, AudioConversionError) as exc:
        _log_cli_operation(
            operation="tts",
            status="failed",
            provider_id=provider_id,
            model=prepared.request.model,
            tts_mode=prepared.request.mode.value,
            error_summary=str(exc),
        )
        _fail(str(exc))


def _synthesize_chunked(provider: Any, prepared: PreparedTTSRequest) -> AudioArtifact:
    if prepared.chunk_plan is None:
        raise ProviderError("chunk plan is required")
    started_at = datetime.now(UTC)
    results = [
        provider.synthesize_bytes(prepared.request.model_copy(update={"text": chunk.text}))
        for chunk in prepared.chunk_plan.chunks
    ]
    merged = merge_audio_results(
        results,
        silence_ms=prepared.chunk_plan.silence_ms,
        output_format=prepared.request.output_format,
    )
    artifact_root = Path(getattr(provider, "artifact_root", Path.cwd()))
    store = ArtifactStore(artifact_root)
    operation_id = f"tts-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{id(merged):x}"
    artifact = store.write_audio(
        operation_id=operation_id,
        provider_id=prepared.request.provider_id,
        operation="tts",
        audio=merged.audio,
        mime_type=merged.mime_type,
        suffix=merged.suffix,
        metadata={
            **prepared.artifact_metadata,
            "model": merged.model or prepared.request.model,
            "operation": "tts",
            "output_format": prepared.request.output_format,
            "provider_id": prepared.request.provider_id,
            "tts_mode": prepared.request.mode.value,
        },
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


def _transcribe(
    registry: ProviderRegistry,
    provider_id: str,
    request: ASRRequest,
    *,
    config: AppConfig,
    chunking_mode: Literal["off", "auto", "force"] | None = None,
    chunk_seconds: int | None = None,
    chunk_overlap_ms: int | None = None,
) -> TranscriptArtifact:
    try:
        provider = registry.ensure_asr_capability(provider_id, request)
        resolved_mode = chunking_mode or config.chunking.asr.mode
        if resolved_mode == "force" or (
            resolved_mode == "auto" and request.base64_size > MAX_BASE64_AUDIO_SIZE
        ):
            artifact = _transcribe_chunked(
                provider,
                request,
                config=config,
                chunking_mode=resolved_mode,
                chunk_seconds=chunk_seconds,
                chunk_overlap_ms=chunk_overlap_ms,
            )
        else:
            artifact = provider.transcribe(request)
        _log_cli_operation(
            operation="asr",
            status="completed",
            provider_id=provider_id,
            model=artifact.metadata.get("model"),
            artifact_id=artifact.id,
        )
        return artifact
    except ProviderError as exc:
        _log_cli_operation(
            operation="asr",
            status="failed",
            provider_id=provider_id,
            model=request.model,
            error_summary=str(exc),
        )
        _fail(str(exc))
    except (ASRAudioChunkingError, AudioConversionError) as exc:
        _log_cli_operation(
            operation="asr",
            status="failed",
            provider_id=provider_id,
            model=request.model,
            error_summary=str(exc),
        )
        _fail(str(exc))


def _transcribe_chunked(
    provider: Any,
    request: ASRRequest,
    *,
    config: AppConfig,
    chunking_mode: str,
    chunk_seconds: int | None,
    chunk_overlap_ms: int | None,
) -> TranscriptArtifact:
    started_at = datetime.now(UTC)
    artifact_root = Path(getattr(provider, "artifact_root", Path.cwd()))
    with tempfile.TemporaryDirectory() as temp_dir:
        chunks = plan_asr_audio_chunks(
            request.audio_path,
            source_format=format_from_mime(request.mime_type),
            output_dir=Path(temp_dir),
            config=config.chunking.asr,
            target_seconds=chunk_seconds,
            overlap_ms=chunk_overlap_ms,
            max_raw_bytes=(MAX_BASE64_AUDIO_SIZE // 4) * 3,
            max_base64_bytes=MAX_BASE64_AUDIO_SIZE,
        )
        transcript_chunks: list[TranscriptChunk] = []
        for chunk in chunks:
            chunk_request = request.model_copy(
                update={
                    "audio_path": chunk.path,
                    "mime_type": chunk.mime_type,
                    "raw_byte_size": chunk.raw_byte_size,
                    "base64_size": chunk.base64_size,
                }
            )
            transcript_chunks.append(
                TranscriptChunk(
                    payload=provider.transcribe_payload(chunk_request),
                    start_seconds=chunk.start_ms / 1000,
                )
            )
        merged = merge_transcript_chunks(
            transcript_chunks,
            dedupe_min_chars=config.chunking.asr.dedupe_min_chars,
            dedupe_max_chars=config.chunking.asr.dedupe_max_chars,
        )
        store = ArtifactStore(artifact_root)
        operation_id = f"asr-{uuid4().hex}"
        artifact = store.write_transcript(
            operation_id=operation_id,
            provider_id=request.provider_id,
            operation="asr",
            text=merged.payload.text,
            payload=merged.payload,
            metadata={
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
                "chunking_transcript_lengths": [
                    len(chunk.payload.text) for chunk in transcript_chunks
                ],
                "language": request.language,
                "model": request.model,
                "operation": "asr",
                "provider_id": request.provider_id,
                "raw_byte_size": sum(chunk.raw_byte_size for chunk in chunks),
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_suffix": request.audio_path.suffix,
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


def _resolve_provider_id(registry: ProviderRegistry, requested: str | None) -> str:
    if requested:
        if not any(provider.id == requested for provider in registry.list_providers()):
            _fail(f"unknown provider: {requested}")
        return requested
    providers = registry.list_providers()
    if any(provider.id == "mimo" for provider in providers):
        return "mimo"
    if providers:
        return providers[0].id
    _fail("no providers configured")


def _ensure_transcript_richness_supported_or_fail(
    config: AppConfig,
    *,
    provider_id: str,
    model_id: str | None,
    timestamps: bool,
    speakers: bool,
) -> None:
    if not timestamps and not speakers:
        return
    capabilities = _transcript_capabilities_for_model(
        config,
        provider_id=provider_id,
        model_id=model_id,
    )
    if timestamps and not capabilities.timestamps:
        _fail("model does not support transcript timestamps")
    if speakers and not capabilities.speakers:
        _fail("model does not support transcript speakers")


def _transcript_capabilities_for_model(
    config: AppConfig,
    *,
    provider_id: str,
    model_id: str | None,
) -> TranscriptCapabilities:
    provider_config = next(
        (provider for provider in config.providers if provider.id == provider_id),
        None,
    )
    resolved_model_id = model_id
    if resolved_model_id is None and provider_config is not None:
        defaults = provider_config.default_models
        resolved_model_id = defaults.asr if defaults is not None else None
    if provider_config is None or resolved_model_id is None:
        return TranscriptCapabilities()
    configured_model = next(
        (model for model in provider_config.models if model.id == resolved_model_id),
        None,
    )
    if configured_model is None or configured_model.transcript_capabilities is None:
        return TranscriptCapabilities()
    return configured_model.transcript_capabilities


def _confirm_clone_consent(consent: bool) -> bool:
    if consent:
        return True
    if sys.stdin.isatty():
        if typer.confirm("Confirm rights and consent for this voice sample?"):
            return True
        _fail("consent not confirmed")
    _fail("consent required in non-TTY mode; rerun with --consent")


def _normalize_existing_audio_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_file():
        _fail(f"file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_MIME_BY_SUFFIX:
        _fail("unsupported audio suffix; expected .wav or .mp3")
    return path


def _audio_upload_metadata(path: Path) -> tuple[AudioMime, int, int]:
    suffix = path.suffix.lower()
    mime_type = SUPPORTED_AUDIO_MIME_BY_SUFFIX.get(suffix)
    if mime_type is None:
        _fail("unsupported audio suffix; expected .wav or .mp3")
    raw_byte_size = path.stat().st_size
    base64_size = ((raw_byte_size + 2) // 3) * 4
    return cast(AudioMime, mime_type), raw_byte_size, base64_size


def _normalize_output_format(output_format: str) -> TTSOutputFormat:
    if output_format not in {"wav", "mp3"}:
        _fail("unsupported output format; expected wav or mp3")
    return cast(TTSOutputFormat, output_format)


def _fail(message: str) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _load_cli_context(*, refresh: bool = False) -> tuple[AppConfig, Mapping[str, str]]:
    global _CLI_CONFIG, _CLI_ENV_VALUES, _CLI_LOGGING_SIGNATURE
    if refresh or _CLI_CONFIG is None or _CLI_ENV_VALUES is None:
        env_values = load_env_values()
        config = load_app_config(env_values=env_values, emit_warnings=False)
        signature = (
            str(config.config_path) if config.config_path is not None else None,
            config.logging.model_dump_json(),
        )
        if signature != _CLI_LOGGING_SIGNATURE:
            configure_logging(config.logging, config_path=config.config_path)
            _CLI_LOGGING_SIGNATURE = signature
        replay_config_warnings(config, dict(env_values))
        _CLI_CONFIG = config
        _CLI_ENV_VALUES = env_values
    return _CLI_CONFIG, _CLI_ENV_VALUES


def reset_cli_context() -> None:
    global _CLI_CONFIG, _CLI_ENV_VALUES, _CLI_LOGGING_SIGNATURE
    _CLI_CONFIG = None
    _CLI_ENV_VALUES = None
    _CLI_LOGGING_SIGNATURE = None


def _log_cli_operation(**metadata: object) -> None:
    sanitized = sanitize_log_metadata(metadata)
    bound_logger = logger.bind(**sanitized)
    if sanitized.get("status") == "failed":
        bound_logger.debug("voice operation {}", sanitized)
    else:
        bound_logger.info("voice operation {}", sanitized)


def _safe_validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error.get("loc", ())) or "request"
        msg = str(error.get("msg", "invalid value"))
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts) or "invalid request"


def _print_audio_artifact(artifact: AudioArtifact) -> None:
    typer.echo(f"id: {artifact.id}")
    typer.echo(f"mime: {artifact.mime_type}")
    chunk_count = artifact.metadata.get("chunking_chunk_count")
    if artifact.metadata.get("chunking_enabled") is True and isinstance(chunk_count, int):
        typer.echo(f"chunks: {chunk_count}")


def _print_transcript_artifact(artifact: TranscriptArtifact) -> None:
    typer.echo(f"id: {artifact.id}")
    typer.echo(f"mime: {artifact.mime_type}")
    try:
        text = artifact.path.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        typer.echo(f"text: {text}")


app.add_typer(tts_app, name="tts")
app.add_typer(asr_app, name="asr")
