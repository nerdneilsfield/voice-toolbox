from __future__ import annotations

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
        "normalization_normalizer_id": "markdown_basic",
        "normalization_input_format": "markdown",
        "normalization_output_format": "plain",
        "normalization_changed": True,
        "normalization_input_length": 23,
        "normalization_output_length": 17,
        "normalization_ignored_options": [],
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
    assert prepared.artifact_metadata == {}
