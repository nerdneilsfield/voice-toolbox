from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from voice_toolbox.audio_conversion import (
    AudioConversionError,
    AudioFormat,
    DownloadAudioFormat,
    PYDUB_EXPORT_FORMAT_BY_FORMAT,
    PYDUB_INPUT_FORMAT_BY_FORMAT,
    format_from_mime,
    mime_for_format,
    suffix_for_format,
)
from voice_toolbox.config_models import ASRChunkingConfig
from voice_toolbox.models import ProviderAudioResult


@dataclass(frozen=True)
class ASRAudioChunk:
    path: Path
    start_ms: int
    end_ms: int
    raw_byte_size: int
    base64_size: int
    mime_type: str
    suffix: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


class ASRAudioChunkingError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def decode_audio_result(result: ProviderAudioResult):
    try:
        audio_segment_cls = _audio_segment_class()
        audio_format = format_from_mime(result.mime_type)
        return audio_segment_cls.from_file(
            BytesIO(result.audio),
            format=PYDUB_INPUT_FORMAT_BY_FORMAT[audio_format],
        )
    except AudioConversionError:
        raise
    except Exception as exc:
        raise AudioConversionError(
            "audio merge failed; provider returned unsupported audio"
        ) from exc


def concat_audio_results(
    results: list[ProviderAudioResult],
    *,
    silence_ms: int,
):
    if not results:
        raise AudioConversionError("audio merge requires at least one chunk")
    audio_segment_cls = _audio_segment_class()
    merged = decode_audio_result(results[0])
    silence = audio_segment_cls.silent(duration=silence_ms)
    for result in results[1:]:
        if silence_ms:
            merged += silence
        merged += decode_audio_result(result)
    return merged


def export_audio_segment(segment, *, output_format: DownloadAudioFormat) -> ProviderAudioResult:
    try:
        output = BytesIO()
        segment.export(output, format=PYDUB_EXPORT_FORMAT_BY_FORMAT[output_format])
        return ProviderAudioResult(
            audio=output.getvalue(),
            mime_type=mime_for_format(output_format),
            suffix=suffix_for_format(output_format),
        )
    except Exception as exc:
        raise AudioConversionError("audio merge export failed") from exc


def plan_asr_audio_chunks(
    source_path: Path,
    *,
    source_format: AudioFormat,
    output_dir: Path,
    config: ASRChunkingConfig,
    target_seconds: int | None = None,
    overlap_ms: int | None = None,
    max_raw_bytes: int,
    max_base64_bytes: int,
) -> list[ASRAudioChunk]:
    target_ms = (target_seconds or config.target_seconds) * 1000
    resolved_overlap_ms = config.overlap_ms if overlap_ms is None else overlap_ms
    if target_ms <= 0:
        raise ASRAudioChunkingError("target_seconds must be greater than 0")
    if resolved_overlap_ms < 0:
        raise ASRAudioChunkingError("overlap_ms must be greater than or equal to 0")
    if resolved_overlap_ms >= target_ms / 2:
        raise ASRAudioChunkingError("overlap_ms must be less than half target_seconds")
    try:
        source = _decode_source_audio(source_path, source_format=source_format)
    except AudioConversionError:
        raise
    except Exception as exc:
        raise AudioConversionError("audio chunking failed; upload a supported audio file") from exc

    duration_ms = len(source)
    if duration_ms <= 0:
        raise ASRAudioChunkingError("audio duration is empty")
    ranges = _chunk_ranges(
        duration_ms=duration_ms,
        target_ms=target_ms,
        overlap_ms=resolved_overlap_ms,
        max_chunks=config.max_chunks,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[ASRAudioChunk] = []
    for index, (start_ms, end_ms) in enumerate(ranges):
        chunk_path = output_dir / f"asr-chunk-{index:04d}.wav"
        source[start_ms:end_ms].export(chunk_path, format="wav")
        raw_byte_size = chunk_path.stat().st_size
        base64_size = _base64_size(raw_byte_size)
        if raw_byte_size > max_raw_bytes or base64_size > max_base64_bytes:
            raise ASRAudioChunkingError(
                "audio chunk exceeds provider payload limit",
                status_code=413,
            )
        chunks.append(
            ASRAudioChunk(
                path=chunk_path,
                start_ms=start_ms,
                end_ms=end_ms,
                raw_byte_size=raw_byte_size,
                base64_size=base64_size,
                mime_type="audio/wav",
                suffix=".wav",
            )
        )
    return chunks


def _decode_source_audio(source_path: Path, *, source_format: AudioFormat):
    audio_segment_cls = _audio_segment_class()
    if source_format == "pcm":
        return audio_segment_cls(
            data=source_path.read_bytes(),
            sample_width=2,
            frame_rate=24_000,
            channels=1,
        )
    return audio_segment_cls.from_file(
        source_path,
        format=PYDUB_INPUT_FORMAT_BY_FORMAT[source_format],
    )


def inspect_audio_duration_ms(source_path: Path, *, source_format: AudioFormat) -> int:
    try:
        return len(_decode_source_audio(source_path, source_format=source_format))
    except AudioConversionError:
        raise
    except Exception as exc:
        raise AudioConversionError("audio duration inspection failed") from exc


def _chunk_ranges(
    *,
    duration_ms: int,
    target_ms: int,
    overlap_ms: int,
    max_chunks: int,
) -> list[tuple[int, int]]:
    step_ms = target_ms - overlap_ms
    ranges: list[tuple[int, int]] = []
    start_ms = 0
    while start_ms < duration_ms:
        end_ms = min(duration_ms, start_ms + target_ms)
        ranges.append((start_ms, end_ms))
        if len(ranges) > max_chunks:
            raise ASRAudioChunkingError("audio chunk count exceeds max_chunks")
        if end_ms >= duration_ms:
            break
        start_ms += step_ms
    return ranges


def _base64_size(raw_byte_size: int) -> int:
    return ((raw_byte_size + 2) // 3) * 4


def _audio_segment_class():
    try:
        from pydub import AudioSegment
    except Exception as exc:
        raise AudioConversionError("audio merge requires pydub and ffmpeg") from exc
    return AudioSegment
