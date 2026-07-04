from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment

from voice_toolbox.audio_conversion import DownloadAudioFormat
from voice_toolbox.chunking.audio import decode_audio_result, export_audio_segment
from voice_toolbox.models import ProviderAudioResult


@dataclass(frozen=True)
class PodcastAudioSegment:
    result: ProviderAudioResult
    pause_after_ms: int


@dataclass(frozen=True)
class PodcastAudioTiming:
    start_ms: int | None
    end_ms: int | None
    audio_duration_ms: int | None


@dataclass(frozen=True)
class PodcastAudioMergeResult:
    audio: ProviderAudioResult
    segments: list[PodcastAudioTiming]


def merge_podcast_audio(
    segments: list[PodcastAudioSegment],
    *,
    output_format: DownloadAudioFormat,
) -> PodcastAudioMergeResult:
    rendered = AudioSegment.silent(duration=0)
    cursor_ms = 0
    timings: list[PodcastAudioTiming] = []
    all_decoded = True
    for index, segment in enumerate(segments):
        try:
            audio = decode_audio_result(segment.result)
        except Exception:
            all_decoded = False
            timings.append(
                PodcastAudioTiming(
                    start_ms=None,
                    end_ms=None,
                    audio_duration_ms=None,
                )
            )
            continue
        start_ms = cursor_ms if all_decoded else None
        rendered += audio
        cursor_ms += len(audio)
        end_ms = cursor_ms if all_decoded else None
        timings.append(
            PodcastAudioTiming(
                start_ms=start_ms,
                end_ms=end_ms,
                audio_duration_ms=len(audio),
            )
        )
        if index < len(segments) - 1 and segment.pause_after_ms > 0:
            rendered += AudioSegment.silent(duration=segment.pause_after_ms)
            cursor_ms += segment.pause_after_ms
    if not segments:
        audio_result = export_audio_segment(
            AudioSegment.silent(duration=0),
            output_format=output_format,
        )
    elif all_decoded:
        audio_result = export_audio_segment(rendered, output_format=output_format)
    else:
        audio_result = segments[0].result
    return PodcastAudioMergeResult(audio=audio_result, segments=timings)
