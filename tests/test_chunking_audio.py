from __future__ import annotations

import io
from pathlib import Path
import wave

import pytest
from pydub import AudioSegment

from voice_toolbox.chunking.audio import ASRAudioChunkingError, plan_asr_audio_chunks
from voice_toolbox.chunking.merge import merge_audio_results
from voice_toolbox.chunking.merge import TranscriptChunk, exact_suffix_prefix_overlap
from voice_toolbox.chunking.merge import merge_transcript_chunks
from voice_toolbox.config_models import ASRChunkingConfig
from voice_toolbox.models import ProviderAudioResult
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment


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


def test_transcript_merge_exact_dedupe_newline_and_bounds() -> None:
    merged = merge_transcript_chunks(
        [
            TranscriptChunk(TranscriptPayload(text="alpha overlap"), start_seconds=0),
            TranscriptChunk(TranscriptPayload(text="overlap beta"), start_seconds=9.5),
        ],
        dedupe_min_chars=3,
        dedupe_max_chars=20,
    )
    no_overlap = merge_transcript_chunks(
        [
            TranscriptChunk(TranscriptPayload(text="alpha"), start_seconds=0),
            TranscriptChunk(TranscriptPayload(text="beta"), start_seconds=10),
        ],
        dedupe_min_chars=3,
        dedupe_max_chars=20,
    )

    assert merged.payload.text == "alpha overlap beta"
    assert merged.dedupe_removed_chars == len("overlap")
    assert no_overlap.payload.text == "alpha\nbeta"
    assert (
        exact_suffix_prefix_overlap(
            "xx12345678",
            "12345678yy",
            min_chars=8,
            max_chars=8,
        )
        == 8
    )
    assert (
        exact_suffix_prefix_overlap(
            "1234567890",
            "1234567890",
            min_chars=11,
            max_chars=20,
        )
        == 0
    )


def test_transcript_merge_offsets_segments_and_preserves_speakers() -> None:
    merged = merge_transcript_chunks(
        [
            TranscriptChunk(
                TranscriptPayload(
                    text="hello",
                    segments=[
                        TranscriptSegment(
                            text="hello",
                            start_seconds=0.1,
                            end_seconds=0.4,
                            speaker="A",
                        )
                    ],
                ),
                start_seconds=0,
            ),
            TranscriptChunk(
                TranscriptPayload(
                    text="world",
                    segments=[
                        TranscriptSegment(
                            text="world",
                            start_seconds=0.2,
                            end_seconds=0.6,
                            speaker="B",
                        )
                    ],
                ),
                start_seconds=10,
            ),
        ],
        dedupe_min_chars=3,
        dedupe_max_chars=20,
    )

    assert merged.payload.segments[1].start_seconds == 10.2
    assert merged.payload.segments[1].end_seconds == 10.6
    assert merged.payload.segments[1].speaker == "B"


def test_plan_asr_audio_chunks_overlap_bounds_and_limits(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(_wav_silence(21_000))
    config = ASRChunkingConfig(target_seconds=10, overlap_ms=1000, max_chunks=4)

    chunks = plan_asr_audio_chunks(
        source,
        source_format="wav",
        output_dir=tmp_path / "chunks",
        config=config,
        max_raw_bytes=1_000_000,
        max_base64_bytes=1_400_000,
    )

    assert [(chunk.start_ms, chunk.end_ms) for chunk in chunks] == [
        (0, 10_000),
        (9_000, 19_000),
        (18_000, 21_000),
    ]
    assert all(chunk.raw_byte_size <= 1_000_000 for chunk in chunks)
    assert all(chunk.base64_size <= 1_400_000 for chunk in chunks)

    with pytest.raises(ASRAudioChunkingError, match="overlap_ms"):
        plan_asr_audio_chunks(
            source,
            source_format="wav",
            output_dir=tmp_path / "bad-overlap",
            config=config,
            overlap_ms=5000,
            max_raw_bytes=1_000_000,
            max_base64_bytes=1_400_000,
        )
    with pytest.raises(ASRAudioChunkingError, match="max_chunks"):
        plan_asr_audio_chunks(
            source,
            source_format="wav",
            output_dir=tmp_path / "too-many",
            config=ASRChunkingConfig(target_seconds=10, overlap_ms=0, max_chunks=2),
            max_raw_bytes=1_000_000,
            max_base64_bytes=1_400_000,
        )
    with pytest.raises(ASRAudioChunkingError, match="payload limit"):
        plan_asr_audio_chunks(
            source,
            source_format="wav",
            output_dir=tmp_path / "too-big",
            config=config,
            max_raw_bytes=100,
            max_base64_bytes=200,
        )
