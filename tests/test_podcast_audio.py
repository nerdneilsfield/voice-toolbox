from __future__ import annotations

import io
import wave

from pydub import AudioSegment

from voice_toolbox.models import ProviderAudioResult
from voice_toolbox.podcast.audio import PodcastAudioSegment, merge_podcast_audio


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


def test_merge_podcast_audio_uses_per_segment_pauses() -> None:
    merged = merge_podcast_audio(
        [
            PodcastAudioSegment(
                result=ProviderAudioResult(
                    audio=_wav_silence(100),
                    mime_type="audio/wav",
                    suffix=".wav",
                ),
                pause_after_ms=30,
            ),
            PodcastAudioSegment(
                result=ProviderAudioResult(
                    audio=_wav_silence(120),
                    mime_type="audio/wav",
                    suffix=".wav",
                ),
                pause_after_ms=90,
            ),
        ],
        output_format="wav",
    )

    audio = AudioSegment.from_file(io.BytesIO(merged.audio.audio), format="wav")

    assert 245 <= len(audio) <= 265
    assert [segment.audio_duration_ms for segment in merged.segments] == [100, 120]
    assert merged.segments[0].start_ms == 0
    assert 95 <= (merged.segments[0].end_ms or 0) <= 105
    assert 125 <= (merged.segments[1].start_ms or 0) <= 135


def test_merge_podcast_audio_omits_timing_for_unreadable_audio() -> None:
    merged = merge_podcast_audio(
        [
            PodcastAudioSegment(
                result=ProviderAudioResult(
                    audio=b"not-audio",
                    mime_type="audio/mpeg",
                    suffix=".mp3",
                ),
                pause_after_ms=10,
            )
        ],
        output_format="mp3",
    )

    assert merged.segments[0].start_ms is None
    assert merged.segments[0].end_ms is None
    assert merged.segments[0].audio_duration_ms is None
