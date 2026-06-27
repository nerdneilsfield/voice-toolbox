from __future__ import annotations

import pytest

from voice_toolbox.normalizers.registry import NormalizerRegistry


def test_markdown_basic_cleans_markup_and_preserves_tags() -> None:
    result = NormalizerRegistry.default().normalize(
        "# Title\n\n- Hello **world**\n- (唱歌)啦啦啦[breath]\n[site](https://example.com)",
        input_format="markdown",
        normalizer_id=None,
    )

    assert result.text == "Title\n\nHello world\n(唱歌)啦啦啦[breath]\nsite"
    assert result.normalizer_id == "markdown_basic"
    assert result.changed is True


def test_auto_keeps_math_and_script_literals() -> None:
    registry = NormalizerRegistry.default()
    for text in ["5 * 4 = 20", "5 * 4 * 3 = 60 * 2", "会议 #1 重点", "a < b 且 c > d"]:
        result = registry.normalize(text, input_format="auto", normalizer_id=None)
        assert result.text == text
        assert result.normalizer_id == "plain_passthrough"


def test_auto_uses_markdown_for_structural_signals() -> None:
    result = NormalizerRegistry.default().normalize(
        "# Title\n\n- one\n- two",
        input_format="auto",
        normalizer_id=None,
    )

    assert result.normalizer_id == "markdown_basic"
    assert result.text == "Title\n\none\ntwo"


def test_html_tag_stripping_does_not_strip_comparisons() -> None:
    result = NormalizerRegistry.default().normalize(
        '<em>Hello</em><br><img src="x"> a < b 且 c > d',
        input_format="markdown",
        normalizer_id=None,
    )

    assert result.text == "Hello a < b 且 c > d"


def test_unknown_normalizer_fails() -> None:
    with pytest.raises(ValueError, match="unknown normalizer"):
        NormalizerRegistry.default().normalize("hello", input_format="plain", normalizer_id="missing")
