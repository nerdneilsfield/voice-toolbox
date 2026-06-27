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
        return PreparedTTSRequest(request=_tts_request(text=None, fields=fields))
    registry = normalizers or NormalizerRegistry.default()
    normalized = registry.normalize(raw_text, input_format=text_format, normalizer_id=None)
    request = _tts_request(text=normalized.text, fields=fields)
    return PreparedTTSRequest(
        request=request,
        normalized=normalized,
        artifact_metadata=_normalization_metadata(normalized),
    )


def _tts_request(*, text: str | None, fields: dict[str, object]) -> TTSRequest:
    return TTSRequest.model_validate({"text": text, **fields})


def _normalization_metadata(normalized: NormalizedContent) -> dict[str, object]:
    return {
        "normalizer_id": normalized.normalizer_id,
        "normalization_input_format": normalized.input_format,
        "normalization_output_format": normalized.output_format,
        "normalization_changed": normalized.changed,
        "normalization_input_length": normalized.metadata.get("input_length", 0),
        "normalization_output_length": normalized.metadata.get("output_length", len(normalized.text)),
        "normalization_ignored_options": normalized.metadata.get("ignored_options", []),
    }
