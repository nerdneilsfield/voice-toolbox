from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from voice_toolbox.chunking.models import TextChunkPlan, TextSource, TTSChunkingRequest
from voice_toolbox.chunking.text import plan_tts_text_chunks
from voice_toolbox.config_models import ChunkingMode, TTSChunkingConfig
from voice_toolbox.models import TTSRequest
from voice_toolbox.normalizers.base import NormalizedContent
from voice_toolbox.normalizers.registry import NormalizerRegistry


class PreparedTTSRequest(BaseModel):
    request: TTSRequest
    source: TextSource | None = None
    normalized: NormalizedContent | None = None
    chunk_plan: TextChunkPlan | None = None
    artifact_metadata: dict[str, object] = Field(default_factory=dict)


def prepare_tts_request(
    raw_text: str | TextSource | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
    fields: dict[str, object],
    *,
    normalizers: NormalizerRegistry | None = None,
    chunking_config: TTSChunkingConfig | None = None,
    chunking_mode: ChunkingMode | None = None,
    chunk_max_chars: int | None = None,
    chunk_silence_ms: int | None = None,
) -> PreparedTTSRequest:
    source = _text_source(raw_text, text_format)
    if source.text is None:
        request = _tts_request(text=None, fields=fields)
        chunk_plan = _plan_chunks(
            request,
            chunking_config=chunking_config,
            chunking_mode=chunking_mode,
            chunk_max_chars=chunk_max_chars,
            chunk_silence_ms=chunk_silence_ms,
        )
        return PreparedTTSRequest(
            request=request,
            source=source,
            chunk_plan=chunk_plan,
            artifact_metadata={**source.metadata, **chunk_plan.metadata()},
        )
    registry = normalizers or NormalizerRegistry.default()
    normalized = registry.normalize(
        source.text,
        input_format=source.text_format,
        normalizer_id=None,
    )
    request = _tts_request(text=normalized.text, fields=fields)
    chunk_plan = _plan_chunks(
        request,
        chunking_config=chunking_config,
        chunking_mode=chunking_mode,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
    )
    return PreparedTTSRequest(
        request=request,
        source=source,
        normalized=normalized,
        chunk_plan=chunk_plan,
        artifact_metadata={
            **source.metadata,
            **_normalization_metadata(normalized),
            **chunk_plan.metadata(),
        },
    )


def _tts_request(*, text: str | None, fields: dict[str, object]) -> TTSRequest:
    return TTSRequest.model_validate({"text": text, **fields})


def _text_source(
    raw_text: str | TextSource | None,
    text_format: Literal["plain", "markdown", "auto"] | None,
) -> TextSource:
    if isinstance(raw_text, TextSource):
        return raw_text
    return TextSource(
        text=raw_text,
        text_format=text_format or "plain",
        source_kind="inline",
        metadata={
            "source_kind": "inline",
            "source_text_raw_char_count": len(raw_text or ""),
        },
    )


def _plan_chunks(
    request: TTSRequest,
    *,
    chunking_config: TTSChunkingConfig | None,
    chunking_mode: ChunkingMode | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
) -> TextChunkPlan:
    config = _resolved_chunking_config(
        chunking_config=chunking_config,
        chunk_max_chars=chunk_max_chars,
        chunk_silence_ms=chunk_silence_ms,
    )
    return plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=request.mode,
            text=request.text,
            chunking_mode=chunking_mode if chunking_mode is not None else config.mode,
            max_chars=config.max_chars,
            max_chunks=config.max_chunks,
            silence_ms=config.silence_ms,
            repeat_leading_audio_tags=config.repeat_leading_audio_tags,
            optimize_text_preview=request.optimize_text_preview,
        )
    )


def _resolved_chunking_config(
    *,
    chunking_config: TTSChunkingConfig | None,
    chunk_max_chars: int | None,
    chunk_silence_ms: int | None,
) -> TTSChunkingConfig:
    config = chunking_config or TTSChunkingConfig()
    updates: dict[str, int] = {}
    if chunk_max_chars is not None:
        updates["max_chars"] = chunk_max_chars
    if chunk_silence_ms is not None:
        updates["silence_ms"] = chunk_silence_ms
    if not updates:
        return config
    return TTSChunkingConfig.model_validate({**config.model_dump(), **updates})


def _normalization_metadata(normalized: NormalizedContent) -> dict[str, object]:
    return {
        "normalization_normalizer_id": normalized.normalizer_id,
        "normalization_input_format": normalized.input_format,
        "normalization_output_format": normalized.output_format,
        "normalization_changed": normalized.changed,
        "normalization_input_length": normalized.metadata.get("input_length", 0),
        "normalization_output_length": normalized.metadata.get(
            "output_length", len(normalized.text)
        ),
        "normalization_ignored_options": normalized.metadata.get("ignored_options", []),
    }
