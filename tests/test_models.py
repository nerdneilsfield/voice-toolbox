from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from voice_toolbox.models import (
    ASRRequest,
    ModelInfo,
    OperationResult,
    OperationStatus,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)


def test_design_mode_allows_missing_text_when_optimize_text_preview_true() -> None:
    request = TTSRequest(
        mode=TTSMode.DESIGN,
        voice_description="warm and calm",
        optimize_text_preview=True,
    )

    assert request.text is None


def test_design_mode_requires_text_when_optimize_text_preview_false() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(mode=TTSMode.DESIGN, voice_description="warm and calm")


def test_output_format_rejects_mp3_v1_only_wav() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="voice-1", output_format="mp3")


def test_asr_language_supports_auto() -> None:
    request = ASRRequest(
        audio_path=Path("input.wav"),
        mime_type="audio/wav",
        raw_byte_size=10,
        base64_size=16,
    )

    assert request.language == "auto"


def test_model_info_and_voice_info_have_required_fields() -> None:
    model = ModelInfo(id="mimo-tts", name="Mimo TTS")
    voice = VoiceInfo(id="voice-1", name="Voice One")

    assert model.id == "mimo-tts"
    assert model.name == "Mimo TTS"
    assert voice.id == "voice-1"
    assert voice.name == "Voice One"


def test_operation_result_has_started_at_and_finished_at() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)

    result = OperationResult(
        operation_id="op_123",
        operation="tts",
        status=OperationStatus.COMPLETED,
        started_at=started_at,
        finished_at=finished_at,
    )

    assert result.started_at == started_at
    assert result.finished_at == finished_at
    assert result.artifact_ids == []
