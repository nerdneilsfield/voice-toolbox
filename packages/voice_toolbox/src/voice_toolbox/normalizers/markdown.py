from __future__ import annotations

import re
from typing import Any

from voice_toolbox.normalizers.base import NormalizedContent

MARKDOWN_SIGNAL_PATTERNS = {
    "heading": re.compile(r"^#{1,6}\s+\S", re.MULTILINE),
    "fence": re.compile(r"^```", re.MULTILINE),
    "link": re.compile(r"\[.+?\]\(.+?\)"),
    "image": re.compile(r"!\[.*?\]\(.+?\)"),
    "unordered_list": re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE),
    "ordered_list": re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE),
    "table_separator": re.compile(
        r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
        re.MULTILINE,
    ),
}
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*)?\s*/?>")
CODE_FENCE_PATTERN = re.compile(r"^```[^\n]*\n?(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
HEADING_PATTERN = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
UNORDERED_LIST_PATTERN = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
ORDERED_LIST_PATTERN = re.compile(r"^[ \t]*\d+\.[ \t]+", re.MULTILINE)
BLOCKQUOTE_PATTERN = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
TABLE_SEPARATOR_LINE_PATTERN = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$\n?",
    re.MULTILINE,
)
STRONG_EMPHASIS_PATTERN = re.compile(r"(\*\*|__)(?=\S)(.*?\S)\1")
STAR_EMPHASIS_PATTERN = re.compile(r"(?<!\*)\*(?=\S)([^*\n]*?\S)\*(?!\*)")
UNDERSCORE_EMPHASIS_PATTERN = re.compile(r"(?<![\w_])_(?=\S)([^_\n]*?\S)_(?![\w_])")
THREE_OR_MORE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
KNOWN_MARKDOWN_OPTIONS = {"preserve_code_blocks"}


def markdown_signal_count(content: str) -> int:
    return sum(1 for pattern in MARKDOWN_SIGNAL_PATTERNS.values() if pattern.search(content))


class PlainPassthroughNormalizer:
    normalizer_id = "plain_passthrough"
    input_formats = {"plain", "auto"}
    output_format = "plain"

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        return NormalizedContent(
            text=content,
            input_format=input_format,
            normalizer_id=self.normalizer_id,
            changed=False,
            metadata=_metadata(
                content,
                content,
                ignored_options=_ignored_options(options, known_options=set()),
            ),
        )


class MarkdownBasicNormalizer:
    normalizer_id = "markdown_basic"
    input_formats = {"markdown"}
    output_format = "plain"

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        normalization_options = options or {}
        preserve_code_blocks = bool(normalization_options.get("preserve_code_blocks", True))
        text = _strip_code_fences(content, preserve_code_blocks=preserve_code_blocks)
        text = IMAGE_PATTERN.sub(r"\1", text)
        text = LINK_PATTERN.sub(r"\1", text)
        text = HTML_TAG_PATTERN.sub("", text)
        text = HEADING_PATTERN.sub("", text)
        text = UNORDERED_LIST_PATTERN.sub("", text)
        text = ORDERED_LIST_PATTERN.sub("", text)
        text = BLOCKQUOTE_PATTERN.sub("", text)
        text = STRONG_EMPHASIS_PATTERN.sub(r"\2", text)
        text = STAR_EMPHASIS_PATTERN.sub(r"\1", text)
        text = UNDERSCORE_EMPHASIS_PATTERN.sub(r"\1", text)
        text = TABLE_SEPARATOR_LINE_PATTERN.sub("", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = THREE_OR_MORE_BLANK_LINES_PATTERN.sub("\n\n", text).strip()

        return NormalizedContent(
            text=text,
            input_format=input_format,
            normalizer_id=self.normalizer_id,
            changed=text != content,
            metadata=_metadata(
                content,
                text,
                ignored_options=_ignored_options(
                    normalization_options,
                    known_options=KNOWN_MARKDOWN_OPTIONS,
                ),
            ),
        )


class AutoTextNormalizer:
    normalizer_id = "auto_text"
    input_formats = {"auto"}
    output_format = "plain"

    def __init__(
        self,
        *,
        plain: PlainPassthroughNormalizer,
        markdown: MarkdownBasicNormalizer,
    ) -> None:
        self._plain = plain
        self._markdown = markdown

    def normalize(
        self,
        content: str,
        *,
        input_format: str,
        options: dict[str, Any] | None = None,
    ) -> NormalizedContent:
        if markdown_signal_count(content) >= 2:
            return self._markdown.normalize(content, input_format="markdown", options=options)
        return self._plain.normalize(content, input_format=input_format, options=options)


def _strip_code_fences(content: str, *, preserve_code_blocks: bool) -> str:
    if preserve_code_blocks:
        return CODE_FENCE_PATTERN.sub(lambda match: match.group(1).strip("\n"), content)
    return CODE_FENCE_PATTERN.sub("", content)


def _ignored_options(
    options: dict[str, Any] | None,
    *,
    known_options: set[str],
) -> list[str]:
    return sorted((options or {}).keys() - known_options)


def _metadata(content: str, text: str, *, ignored_options: list[str]) -> dict[str, Any]:
    return {
        "input_length": len(content),
        "output_length": len(text),
        "ignored_options": ignored_options,
    }
