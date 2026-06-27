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
