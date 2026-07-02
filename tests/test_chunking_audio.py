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
from voice_toolbox.chunking.sessions import ASRChunkSessionError, ASRChunkSessionStore
from voice_toolbox.config_models import ASRChunkingConfig
from voice_toolbox.models import ProviderAudioResult
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment, render_txt


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


def test_transcript_merge_dedupes_collapsed_whitespace_and_keeps_timestamps() -> None:
    merged = merge_transcript_chunks(
        [
            TranscriptChunk(
                TranscriptPayload(
                    text="alpha overlap",
                    segments=[
                        TranscriptSegment(text="alpha overlap", start_seconds=0, end_seconds=1)
                    ],
                ),
                start_seconds=0,
            ),
            TranscriptChunk(
                TranscriptPayload(
                    text="overlap\n beta",
                    segments=[
                        TranscriptSegment(text="overlap\n beta", start_seconds=0, end_seconds=1)
                    ],
                ),
                start_seconds=0.8,
            ),
        ],
        dedupe_min_chars=7,
        dedupe_max_chars=20,
    )

    assert merged.payload.text == "alpha overlap\n beta"
    assert merged.payload.has_complete_timestamps is True
    assert render_txt(merged.payload, timestamps=True).startswith("[00:00:00.000 - ")


def test_txt_timestamp_renders_hours() -> None:
    payload = TranscriptPayload(
        text="later",
        segments=[TranscriptSegment(text="later", start_seconds=3661.25, end_seconds=3662.5)],
    )

    assert render_txt(payload, timestamps=True) == "[01:01:01.250 - 01:01:02.500] later"


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


def test_transcript_merge_dedupes_overlapping_segments() -> None:
    merged = merge_transcript_chunks(
        [
            TranscriptChunk(
                TranscriptPayload(
                    text="alpha overlap",
                    segments=[
                        TranscriptSegment(text="alpha", start_seconds=0, end_seconds=1),
                        TranscriptSegment(text="overlap", start_seconds=1, end_seconds=2),
                    ],
                ),
                start_seconds=0,
            ),
            TranscriptChunk(
                TranscriptPayload(
                    text="overlap beta",
                    segments=[
                        TranscriptSegment(text="overlap", start_seconds=0, end_seconds=1),
                        TranscriptSegment(text="beta", start_seconds=1, end_seconds=2),
                    ],
                ),
                start_seconds=1,
            ),
        ],
        dedupe_min_chars=3,
        dedupe_max_chars=20,
    )

    assert merged.payload.text == "alpha overlap beta"
    assert [segment.text for segment in merged.payload.segments] == ["alpha", "overlap", "beta"]


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
    with pytest.raises(ASRAudioChunkingError, match="overlap_ms"):
        plan_asr_audio_chunks(
            source,
            source_format="wav",
            output_dir=tmp_path / "negative-overlap",
            config=config,
            overlap_ms=-1,
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


def test_plan_asr_audio_chunks_caps_duration_to_provider_payload_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(_wav_silence(21_000))
    config = ASRChunkingConfig(target_seconds=10, overlap_ms=0, max_chunks=10)

    chunks = plan_asr_audio_chunks(
        source,
        source_format="wav",
        output_dir=tmp_path / "byte-capped",
        config=config,
        max_raw_bytes=80_100,
        max_base64_bytes=120_000,
    )

    assert len(chunks) > 3
    assert all(chunk.raw_byte_size <= 80_100 for chunk in chunks)
    assert all(chunk.base64_size <= 120_000 for chunk in chunks)


def test_asr_chunk_session_store_validates_uploads_and_privacy(tmp_path: Path) -> None:
    store = ASRChunkSessionStore(tmp_path, ttl_seconds=3600, max_upload_mb=1)
    with pytest.raises(ASRChunkSessionError, match="plain filename"):
        store.create(
            provider_id="mimo",
            model="fake-asr",
            language="zh",
            total_chunks=2,
            source_duration_ms=2000,
            source_file_name="../../private/speech.wav",
            transcript_timestamps=True,
            transcript_speakers=False,
            provider_options={"hint": "secret"},
            option_metadata={"provider_option_keys": ["hint"]},
            max_chunks=4,
        )

    session = store.create(
        provider_id="mimo",
        model="fake-asr",
        language="zh",
        total_chunks=2,
        source_duration_ms=2000,
        source_file_name="speech.wav",
        transcript_timestamps=True,
        transcript_speakers=False,
        provider_options={"hint": "secret"},
        option_metadata={"provider_option_keys": ["hint"]},
        max_chunks=4,
    )

    assert session.session_id
    assert session.source_file_suffix == ".wav"
    assert "private" not in store.metadata_path(session.session_id).read_text(encoding="utf-8")
    assert "speech.wav" not in store.metadata_path(session.session_id).read_text(encoding="utf-8")
    metadata_json = store.metadata_path(session.session_id).read_text(encoding="utf-8")
    assert "secret" not in metadata_json
    assert '"provider_options":' not in metadata_json
    assert "provider_options_hash" in metadata_json
    assert store.load(session.session_id).provider_options == {"hint": "secret"}
    reloaded_store = ASRChunkSessionStore(tmp_path, ttl_seconds=3600, max_upload_mb=1)
    reloaded = reloaded_store.load(session.session_id)
    assert reloaded.provider_options == {}
    assert reloaded.provider_options_hash == session.provider_options_hash

    with pytest.raises(ASRChunkSessionError, match="chunk_index"):
        store.write_chunk(
            session.session_id,
            chunk_index=2,
            data=_wav_silence(1000),
            offset_ms=0,
            duration_ms=1000,
            mime_type="audio/wav",
            suffix=".wav",
        )
    store.write_chunk(
        session.session_id,
        chunk_index=0,
        data=_wav_silence(1000),
        offset_ms=0,
        duration_ms=1000,
        mime_type="audio/wav",
        suffix=".wav",
    )
    with pytest.raises(ASRChunkSessionError, match="duplicate"):
        store.write_chunk(
            session.session_id,
            chunk_index=0,
            data=_wav_silence(1000),
            offset_ms=0,
            duration_ms=1000,
            mime_type="audio/wav",
            suffix=".wav",
        )
    with pytest.raises(ASRChunkSessionError, match="non-monotonic"):
        store.write_chunk(
            session.session_id,
            chunk_index=1,
            data=_wav_silence(1000),
            offset_ms=0,
            duration_ms=1000,
            mime_type="audio/wav",
            suffix=".wav",
        )


def test_asr_chunk_session_store_quota_coverage_delete_and_expiry(tmp_path: Path) -> None:
    store = ASRChunkSessionStore(tmp_path, ttl_seconds=60, max_upload_mb=1)
    session = store.create(
        provider_id="mimo",
        model=None,
        language="auto",
        total_chunks=2,
        source_duration_ms=2500,
        source_file_name="speech.wav",
        transcript_timestamps=False,
        transcript_speakers=False,
        provider_options={},
        option_metadata={},
        max_chunks=4,
    )
    with pytest.raises(ASRChunkSessionError, match="quota"):
        store.write_chunk(
            session.session_id,
            chunk_index=0,
            data=b"RIFF0000WAVE" + (b"x" * (1024 * 1024)),
            offset_ms=0,
            duration_ms=1000,
            mime_type="audio/wav",
            suffix=".wav",
        )
    with pytest.raises(ASRChunkSessionError, match="duration_ms"):
        store.write_chunk(
            session.session_id,
            chunk_index=0,
            data=_wav_silence(1000),
            offset_ms=0,
            duration_ms=0,
            mime_type="audio/wav",
            suffix=".wav",
        )
    store.write_chunk(
        session.session_id,
        chunk_index=0,
        data=_wav_silence(1000),
        offset_ms=0,
        duration_ms=1000,
        mime_type="audio/wav",
        suffix=".wav",
    )
    store.write_chunk(
        session.session_id,
        chunk_index=1,
        data=_wav_silence(1000),
        offset_ms=1500,
        duration_ms=1000,
        mime_type="audio/wav",
        suffix=".wav",
    )
    assert len(store.finish_chunks(session.session_id)) == 2

    gap_session = store.create(
        provider_id="mimo",
        model=None,
        language="auto",
        total_chunks=2,
        source_duration_ms=4000,
        source_file_name="speech.wav",
        transcript_timestamps=False,
        transcript_speakers=False,
        provider_options={},
        option_metadata={},
        max_chunks=4,
    )
    store.write_chunk(
        gap_session.session_id,
        chunk_index=0,
        data=_wav_silence(1000),
        offset_ms=0,
        duration_ms=1000,
        mime_type="audio/wav",
        suffix=".wav",
    )
    store.write_chunk(
        gap_session.session_id,
        chunk_index=1,
        data=_wav_silence(1000),
        offset_ms=3000,
        duration_ms=1000,
        mime_type="audio/wav",
        suffix=".wav",
    )
    with pytest.raises(ASRChunkSessionError, match="coverage gap"):
        store.finish_chunks(gap_session.session_id)

    assert store.delete(session.session_id) is True
    assert not store.session_dir(session.session_id).exists()

    expired = ASRChunkSessionStore(tmp_path / "expired", ttl_seconds=1, max_upload_mb=1)
    old_session = expired.create(
        provider_id="mimo",
        model=None,
        language="auto",
        total_chunks=1,
        source_duration_ms=1000,
        source_file_name="speech.wav",
        transcript_timestamps=False,
        transcript_speakers=False,
        provider_options={},
        option_metadata={},
        max_chunks=4,
    )
    expired.cleanup_expired(now=old_session.expires_at)
    assert not expired.session_dir(old_session.session_id).exists()

    load_expired = expired.create(
        provider_id="mimo",
        model=None,
        language="auto",
        total_chunks=1,
        source_duration_ms=1000,
        source_file_name="speech.wav",
        transcript_timestamps=False,
        transcript_speakers=False,
        provider_options={},
        option_metadata={},
        max_chunks=4,
        now=old_session.created_at,
    )
    with pytest.raises(ASRChunkSessionError, match="not found"):
        expired.load(load_expired.session_id, now=load_expired.expires_at)
    assert not expired.session_dir(load_expired.session_id).exists()
