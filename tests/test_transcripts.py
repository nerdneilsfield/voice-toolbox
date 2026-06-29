from __future__ import annotations

import pytest

from voice_toolbox.transcripts import (
    TranscriptPayload,
    TranscriptSegment,
    render_json,
    render_srt,
    render_txt,
    render_vtt,
)


def test_plain_transcript_payload_renders_txt() -> None:
    payload = TranscriptPayload(text="hello transcript")

    assert render_txt(payload) == "hello transcript"


def test_txt_can_render_timestamps_and_speakers() -> None:
    payload = TranscriptPayload(
        text="hello\nworld",
        segments=[
            TranscriptSegment(text="hello", start_seconds=0, end_seconds=1.25, speaker="A"),
            TranscriptSegment(text="world", start_seconds=1.25, end_seconds=2.5, speaker="B"),
        ],
    )

    assert render_txt(payload, timestamps=True, speakers=True) == (
        "[00:00.000 - 00:01.250] A: hello\n[00:01.250 - 00:02.500] B: world"
    )


def test_srt_and_vtt_render_timestamped_segments() -> None:
    payload = TranscriptPayload(
        text="hello\nworld",
        segments=[
            TranscriptSegment(text="hello", start_seconds=0, end_seconds=1.25),
            TranscriptSegment(text="world", start_seconds=61.5, end_seconds=62.75),
        ],
    )

    assert render_srt(payload) == (
        "1\n00:00:00,000 --> 00:00:01,250\nhello\n\n2\n00:01:01,500 --> 00:01:02,750\nworld\n"
    )
    assert render_vtt(payload) == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.250\nhello\n\n00:01:01.500 --> 00:01:02.750\nworld\n"
    )


def test_srt_and_vtt_reject_missing_timestamps() -> None:
    payload = TranscriptPayload(
        text="hello\nworld",
        segments=[
            TranscriptSegment(text="hello", start_seconds=0, end_seconds=1),
            TranscriptSegment(text="world"),
        ],
    )

    with pytest.raises(ValueError, match="timestamps"):
        render_srt(payload)
    with pytest.raises(ValueError, match="timestamps"):
        render_vtt(payload)


def test_json_renderer_returns_full_payload() -> None:
    payload = TranscriptPayload(
        text="hello",
        segments=[TranscriptSegment(text="hello", start_seconds=0, end_seconds=1)],
    )

    assert render_json(payload) == {
        "text": "hello",
        "segments": [{"text": "hello", "start_seconds": 0.0, "end_seconds": 1.0}],
    }


def test_mixed_timestamped_and_plain_payload_disables_srt_vtt() -> None:
    payload = TranscriptPayload(
        text="hello\nworld",
        segments=[
            TranscriptSegment(text="hello", start_seconds=0, end_seconds=1),
            TranscriptSegment(text="world"),
        ],
    )

    assert payload.has_complete_timestamps is False
    with pytest.raises(ValueError, match="timestamps"):
        render_srt(payload)
    with pytest.raises(ValueError, match="timestamps"):
        render_vtt(payload)


def test_partial_speakers_disable_speaker_prefixed_txt() -> None:
    payload = TranscriptPayload(
        text="hello\nworld",
        segments=[
            TranscriptSegment(text="hello", start_seconds=0, end_seconds=1, speaker="A"),
            TranscriptSegment(text="world", start_seconds=1, end_seconds=2),
        ],
    )

    assert payload.has_complete_speakers is False
    with pytest.raises(ValueError, match="speaker"):
        render_txt(payload, speakers=True)
