from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from voice_toolbox.audio_conversion import DownloadAudioFormat
from voice_toolbox.chunking.audio import concat_audio_results, export_audio_segment
from voice_toolbox.models import ProviderAudioResult
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment


def merge_audio_results(
    results: list[ProviderAudioResult],
    *,
    silence_ms: int,
    output_format: DownloadAudioFormat,
) -> ProviderAudioResult:
    merged = concat_audio_results(results, silence_ms=silence_ms)
    exported = export_audio_segment(merged, output_format=output_format)
    return exported.model_copy(update={"model": results[-1].model if results else None})


@dataclass(frozen=True)
class TranscriptChunk:
    payload: TranscriptPayload
    start_seconds: float


@dataclass(frozen=True)
class TranscriptMergeResult:
    payload: TranscriptPayload
    dedupe_removed_chars: int


def merge_transcript_chunks(
    chunks: Sequence[TranscriptChunk],
    *,
    dedupe_min_chars: int,
    dedupe_max_chars: int,
) -> TranscriptMergeResult:
    if not chunks:
        return TranscriptMergeResult(payload=TranscriptPayload(text=""), dedupe_removed_chars=0)
    merged_text = chunks[0].payload.text
    removed_chars = 0
    for chunk in chunks[1:]:
        overlap = exact_suffix_prefix_overlap(
            merged_text,
            chunk.payload.text,
            min_chars=dedupe_min_chars,
            max_chars=dedupe_max_chars,
        )
        if overlap:
            merged_text += chunk.payload.text[overlap:]
            removed_chars += overlap
        else:
            if merged_text and chunk.payload.text:
                merged_text += "\n"
            merged_text += chunk.payload.text

    segments: list[TranscriptSegment] = []
    for chunk in chunks:
        offset = chunk.start_seconds
        for segment in chunk.payload.segments:
            segments.append(
                TranscriptSegment(
                    text=segment.text or "",
                    start_seconds=(
                        segment.start_seconds + offset
                        if segment.start_seconds is not None
                        else None
                    ),
                    end_seconds=(
                        segment.end_seconds + offset if segment.end_seconds is not None else None
                    ),
                    speaker=segment.speaker,
                )
            )
    return TranscriptMergeResult(
        payload=TranscriptPayload(text=merged_text, segments=segments),
        dedupe_removed_chars=removed_chars,
    )


def exact_suffix_prefix_overlap(
    previous: str,
    current: str,
    *,
    min_chars: int,
    max_chars: int,
) -> int:
    upper = min(len(previous), len(current), max_chars)
    for size in range(upper, min_chars - 1, -1):
        if previous[-size:] == current[:size]:
            return size
    return 0
