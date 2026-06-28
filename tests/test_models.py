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


def test_output_format_accepts_wav_and_mp3() -> None:
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        text="hello",
        voice_id="voice-1",
        output_format="mp3",
    )

    assert request.output_format == "mp3"


def test_output_format_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(mode=TTSMode.BUILTIN, text="hello", voice_id="voice-1", output_format="flac")


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


def test_tts_request_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="voice-1",
            unexpected="nope",
        )


def test_tts_request_rejects_whitespace_only_required_text_fields() -> None:
    with pytest.raises(ValidationError):
        TTSRequest(mode=TTSMode.BUILTIN, text="   ", voice_id="voice-1")
    with pytest.raises(ValidationError):
        TTSRequest(mode=TTSMode.DESIGN, voice_description="   ", optimize_text_preview=True)
    with pytest.raises(ValidationError):
        TTSRequest(
            mode=TTSMode.CLONE,
            text="\t\n",
            clone_sample_path=Path("sample.wav"),
            clone_mime_type="audio/wav",
            consent_confirmed=True,
        )


def test_tts_request_strips_prompt_fields() -> None:
    request = TTSRequest(
        mode=TTSMode.BUILTIN,
        text="  hello  ",
        voice_id="  Mia  ",
        style_instruction="  warm  ",
    )

    assert request.text == "hello"
    assert request.voice_id == "Mia"
    assert request.style_instruction == "warm"


def test_asr_request_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        ASRRequest(
            audio_path=Path("input.wav"),
            mime_type="audio/wav",
            raw_byte_size=10,
            base64_size=16,
            unexpected="nope",
        )
