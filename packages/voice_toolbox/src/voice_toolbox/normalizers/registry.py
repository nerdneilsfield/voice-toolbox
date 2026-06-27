from __future__ import annotations

from typing import Any

from voice_toolbox.normalizers.base import ContentNormalizer, NormalizedContent
from voice_toolbox.normalizers.markdown import (
    AutoTextNormalizer,
    MarkdownBasicNormalizer,
    PlainPassthroughNormalizer,
)


class NormalizerRegistry:
    def __init__(self, normalizers: list[ContentNormalizer]) -> None:
        self._normalizers = {normalizer.normalizer_id: normalizer for normalizer in normalizers}

    @classmethod
    def default(cls) -> NormalizerRegistry:
        plain = PlainPassthroughNormalizer()
        markdown = MarkdownBasicNormalizer()
        return cls([plain, markdown, AutoTextNormalizer(plain=plain, markdown=markdown)])

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        normalizer_id: str | None,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        if not content.strip():
            raise ValueError("content is required")
        selected_id = normalizer_id or self._default_normalizer_id(input_format)
        normalizer = self._normalizers.get(selected_id)
        if normalizer is None:
            raise ValueError(f"unknown normalizer: {selected_id}")
        if input_format not in normalizer.input_formats:
            raise ValueError(f"normalizer {selected_id} does not support {input_format}")
        result = normalizer.normalize(content, input_format=input_format, options=options)
        if not result.text.strip():
            raise ValueError("normalized text is empty")
        return result

    def _default_normalizer_id(self, input_format: str) -> str:
        if input_format == "plain":
            return "plain_passthrough"
        if input_format == "markdown":
            return "markdown_basic"
        if input_format == "auto":
            return "auto_text"
        raise ValueError(f"unsupported input format: {input_format}")
