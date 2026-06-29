from __future__ import annotations

from io import BytesIO

from voice_toolbox.audio_conversion import (
    AudioConversionError,
    DownloadAudioFormat,
    PYDUB_EXPORT_FORMAT_BY_FORMAT,
    PYDUB_INPUT_FORMAT_BY_FORMAT,
    format_from_mime,
    mime_for_format,
    suffix_for_format,
)
from voice_toolbox.models import ProviderAudioResult


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


def _audio_segment_class():
    try:
        from pydub import AudioSegment
    except Exception as exc:
        raise AudioConversionError("audio merge requires pydub and ffmpeg") from exc
    return AudioSegment
