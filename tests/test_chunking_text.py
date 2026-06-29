from __future__ import annotations

from io import BytesIO

import pytest

from voice_toolbox.chunking.models import TTSChunkingRequest
from voice_toolbox.chunking.text import (
    TextSourceError,
    infer_text_format_from_upload,
    plan_tts_text_chunks,
    read_text_upload,
    resolve_text_source,
)
from voice_toolbox.models import TTSMode


class Upload:
    def __init__(
        self,
        data: bytes,
        *,
        filename: str = "script.txt",
        content_type: str = "text/plain",
    ) -> None:
        self.file = BytesIO(data)
        self.filename = filename
        self.content_type = content_type


def test_text_upload_decodes_txt_and_markdown_utf8_with_bom() -> None:
    txt = read_text_upload(Upload("hello".encode()), max_bytes=100)
    md = read_text_upload(
        Upload("\ufeff# Title".encode(), filename="notes.md", content_type="text/markdown"),
        max_bytes=100,
    )

    assert txt.text == "hello"
    assert txt.text_format == "plain"
    assert md.text == "# Title"
    assert md.text_format == "markdown"


def test_text_upload_accepts_markdown_mime_and_octet_stream_with_valid_suffix() -> None:
    markdown = read_text_upload(
        Upload(b"# Title", filename="notes.markdown", content_type="text/x-markdown"),
        max_bytes=100,
    )
    octet = read_text_upload(
        Upload(b"# Title", filename="notes.md", content_type="application/octet-stream"),
        max_bytes=100,
    )

    assert markdown.text_format == "markdown"
    assert octet.text_format == "markdown"


def test_text_upload_rejects_unsupported_suffix_and_mismatched_mime() -> None:
    with pytest.raises(TextSourceError, match="unsupported text file suffix"):
        read_text_upload(Upload(b"hello", filename="notes.rtf"), max_bytes=100)

    with pytest.raises(TextSourceError, match="does not match"):
        read_text_upload(
            Upload(b"hello", filename="notes.txt", content_type="text/markdown"),
            max_bytes=100,
        )


def test_text_upload_above_limit_returns_413_before_decode() -> None:
    with pytest.raises(TextSourceError) as exc_info:
        read_text_upload(Upload(b"\xff" * 6), max_bytes=5)

    assert exc_info.value.status_code == 413


def test_text_upload_rejects_invalid_utf8_and_nul() -> None:
    with pytest.raises(TextSourceError, match="valid UTF-8"):
        read_text_upload(Upload(b"\xff"), max_bytes=100)

    with pytest.raises(TextSourceError, match="NUL"):
        read_text_upload(Upload(b"hello\x00world"), max_bytes=100)


def test_text_plus_text_file_rejected() -> None:
    with pytest.raises(TextSourceError, match="mutually exclusive"):
        resolve_text_source(
            text="hello",
            text_file=Upload(b"file text"),
            text_format=None,
            max_text_file_bytes=100,
        )


def test_file_suffix_infers_format_and_inline_default_stays_plain() -> None:
    assert infer_text_format_from_upload("notes.txt", "text/plain") == "plain"
    assert infer_text_format_from_upload("notes.markdown", "text/markdown") == "markdown"

    inline = resolve_text_source(
        text="**not markdown by default**",
        text_file=None,
        text_format=None,
        max_text_file_bytes=100,
    )

    assert inline.text_format == "plain"
    assert inline.metadata == {"source_kind": "inline", "source_text_raw_char_count": 27}


def test_tts_chunker_splits_by_paragraphs_before_sentences() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="One short paragraph.\n\nSecond paragraph. Third paragraph.",
            chunking_mode="force",
            max_chars=36,
            max_chunks=10,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "One short paragraph.",
        "Second paragraph. Third paragraph.",
    ]


def test_tts_chunker_splits_chinese_and_ascii_sentence_boundaries() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="你好世界。今天很好！Alpha beta. Gamma delta?",
            chunking_mode="force",
            max_chars=20,
            max_chunks=10,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "你好世界。今天很好！",
        "Alpha beta.",
        "Gamma delta?",
    ]


def test_tts_chunker_splits_clause_boundaries_before_hard_split() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="alpha beta, gamma delta，epsilon zeta、eta theta: iota kappa",
            chunking_mode="force",
            max_chars=24,
            max_chunks=10,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "alpha beta, gamma delta，",
        "epsilon zeta、eta theta:",
        "iota kappa",
    ]


def test_tts_chunker_hard_splits_overlong_spans() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="abcdefghij",
            chunking_mode="force",
            max_chars=4,
            max_chunks=10,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == ["abcd", "efgh", "ij"]


def test_tts_chunker_propagates_leading_audio_tag() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="(唱歌) 第一段很長很長。第二段也很長很長。",
            chunking_mode="force",
            max_chars=14,
            max_chunks=10,
            repeat_leading_audio_tags=True,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "(唱歌) 第一段很長很長。",
        "(唱歌) 第二段也很長很長。",
    ]
    assert plan.repeated_leading_audio_tags is True
    assert all(chunk.char_count <= plan.max_chars for chunk in plan.chunks)


def test_tts_chunker_keeps_repeated_audio_tag_chunks_within_limit() -> None:
    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.BUILTIN,
            text="(唱歌) 第一段很長很長。第二段也很長很長。",
            chunking_mode="force",
            max_chars=12,
            max_chunks=10,
            repeat_leading_audio_tags=True,
        )
    )

    assert [chunk.text for chunk in plan.chunks] == [
        "(唱歌) 第一段很長很長",
        "(唱歌) 。第二段也很長",
        "(唱歌) 很長。",
    ]
    assert all(chunk.char_count <= plan.max_chars for chunk in plan.chunks)


def test_tts_chunker_enforces_max_chunk_count() -> None:
    with pytest.raises(ValueError, match="chunk count exceeds"):
        plan_tts_text_chunks(
            TTSChunkingRequest(
                mode=TTSMode.BUILTIN,
                text="a b c d e f",
                chunking_mode="force",
                max_chars=1,
                max_chunks=3,
            )
        )


def test_design_mode_never_chunks_and_rejects_force() -> None:
    with pytest.raises(ValueError, match="design mode does not support force"):
        plan_tts_text_chunks(
            TTSChunkingRequest(
                mode=TTSMode.DESIGN,
                text="short",
                chunking_mode="force",
                max_chars=10,
                max_chunks=10,
            )
        )

    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.DESIGN,
            text="short",
            chunking_mode="auto",
            max_chars=10,
            max_chunks=10,
        )
    )
    assert plan.chunking_enabled is False
    assert [chunk.text for chunk in plan.chunks] == ["short"]


def test_design_text_source_file_rules_and_empty_optimized_preview() -> None:
    file_source = resolve_text_source(
        text=None,
        text_file=Upload(b"preview"),
        text_format=None,
        max_text_file_bytes=100,
        mode=TTSMode.DESIGN,
        optimize_text_preview=False,
    )
    assert file_source.text == "preview"

    with pytest.raises(TextSourceError, match="text_file is not allowed"):
        resolve_text_source(
            text=None,
            text_file=Upload(b"preview"),
            text_format=None,
            max_text_file_bytes=100,
            mode=TTSMode.DESIGN,
            optimize_text_preview=True,
        )

    plan = plan_tts_text_chunks(
        TTSChunkingRequest(
            mode=TTSMode.DESIGN,
            text=None,
            chunking_mode="auto",
            max_chars=10,
            max_chunks=10,
            optimize_text_preview=True,
        )
    )
    assert plan.chunks == []
