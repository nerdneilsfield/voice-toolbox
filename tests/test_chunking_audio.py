from __future__ import annotations

import io
import wave

from pydub import AudioSegment

from voice_toolbox.chunking.merge import merge_audio_results
from voice_toolbox.models import ProviderAudioResult


def _wav_silence(duration_ms: int) -> bytes:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def test_merge_audio_results_inserts_silence_and_exports_wav() -> None:
    result = merge_audio_results(
        [
            ProviderAudioResult(audio=_wav_silence(100), mime_type="audio/wav", suffix=".wav"),
            ProviderAudioResult(audio=_wav_silence(120), mime_type="audio/wav", suffix=".wav"),
        ],
        silence_ms=50,
        output_format="wav",
    )

    merged = AudioSegment.from_file(io.BytesIO(result.audio), format="wav")

    assert result.mime_type == "audio/wav"
    assert result.suffix == ".wav"
    assert 260 <= len(merged) <= 280
