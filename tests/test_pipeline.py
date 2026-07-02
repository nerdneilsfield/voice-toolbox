from __future__ import annotations

from typing import cast

from voice_toolbox.chunking.models import TextSource
import pytest

from voice_toolbox.models import TTSMode
from voice_toolbox.pipeline import prepare_tts_request


def test_prepare_tts_request_normalizes_text_and_metadata() -> None:
    prepared = prepare_tts_request(
        "# Title\nHello **world**",
        "markdown",
        {"mode": TTSMode.BUILTIN, "voice_id": "Mia"},
    )

    assert prepared.request.text == "Title\nHello world"
    assert prepared.normalized is not None
    assert prepared.normalized.normalizer_id == "markdown_basic"
    assert prepared.artifact_metadata == {
        "source_kind": "inline",
        "source_text_raw_char_count": 23,
        "normalization_normalizer_id": "markdown_basic",
        "normalization_input_format": "markdown",
        "normalization_output_format": "plain",
        "normalization_changed": True,
        "normalization_input_length": 23,
        "normalization_output_length": 17,
        "normalization_ignored_options": [],
        "chunking_enabled": False,
        "chunking_operation": "tts",
        "chunking_mode": "auto",
        "chunking_strategy": "text",
        "chunking_chunk_count": 1,
        "chunking_max_chars": 1500,
        "chunking_silence_ms": 120,
        "chunking_text_lengths": [17],
        "chunking_repeated_leading_audio_tags": False,
    }


def test_prepare_tts_request_skips_none_text_for_optimized_design() -> None:
    prepared = prepare_tts_request(
        None,
        "plain",
        {
            "mode": TTSMode.DESIGN,
            "voice_description": "warm alto",
            "optimize_text_preview": True,
        },
    )

    assert prepared.request.text is None
    assert prepared.artifact_metadata == {
        "source_kind": "inline",
        "source_text_raw_char_count": 0,
        "chunking_enabled": False,
        "chunking_operation": "tts",
        "chunking_mode": "auto",
        "chunking_strategy": "text",
        "chunking_chunk_count": 0,
        "chunking_max_chars": 1500,
        "chunking_silence_ms": 120,
        "chunking_text_lengths": [],
        "chunking_repeated_leading_audio_tags": False,
    }


def test_prepare_tts_request_adds_source_and_chunking_metadata_for_inline_text() -> None:
    prepared = prepare_tts_request(
        ("One. " * 45) + ("Two. " * 45),
        "plain",
        {"mode": TTSMode.BUILTIN, "voice_id": "Mia"},
        chunking_mode="force",
        chunk_max_chars=200,
    )

    assert prepared.request.text is not None
    assert prepared.chunk_plan is not None
    assert prepared.artifact_metadata["source_kind"] == "inline"
    assert prepared.artifact_metadata["source_text_raw_char_count"] == 450
    assert prepared.artifact_metadata["chunking_enabled"] is True
    lengths = cast(list[int], prepared.artifact_metadata["chunking_text_lengths"])
    assert all(length <= 200 for length in lengths)


def test_prepare_tts_request_rejects_invalid_chunk_override() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        prepare_tts_request(
            "One. Two.",
            "plain",
            {"mode": TTSMode.BUILTIN, "voice_id": "Mia"},
            chunking_mode="force",
            chunk_max_chars=1,
        )


def test_prepare_tts_request_omits_raw_preview_for_uploaded_file_source() -> None:
    source = TextSource(
        text="# Secret\nbody",
        text_format="markdown",
        source_kind="file",
        metadata={
            "source_kind": "file",
            "uploaded_text_file_name_hash": "abcdef123456",
            "uploaded_text_file_suffix": ".md",
            "uploaded_text_file_size_bytes": 13,
            "source_text_raw_char_count": 13,
        },
    )

    prepared = prepare_tts_request(
        source,
        None,
        {"mode": TTSMode.BUILTIN, "voice_id": "Mia"},
        chunking_mode="auto",
        chunk_max_chars=200,
    )

    assert prepared.request.text == "Secret\nbody"
    assert prepared.source is source
    assert prepared.artifact_metadata["source_kind"] == "file"
    assert prepared.artifact_metadata["uploaded_text_file_name_hash"] == "abcdef123456"
    assert "source_text_preview" not in prepared.artifact_metadata
