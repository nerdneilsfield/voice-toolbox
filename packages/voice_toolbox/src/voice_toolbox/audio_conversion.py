from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal, cast

AudioFormat = Literal["wav", "mp3", "pcm", "flac", "m4a", "ogg", "webm", "aac"]
DownloadAudioFormat = AudioFormat

MIME_BY_FORMAT: Mapping[AudioFormat, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "pcm": "audio/pcm",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "aac": "audio/aac",
}
FORMAT_BY_MIME: Mapping[str, AudioFormat] = cast(
    Mapping[str, AudioFormat],
    {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/pcm": "pcm",
        "audio/l16": "pcm",
        "audio/flac": "flac",
        "audio/x-flac": "flac",
        "audio/mp4": "m4a",
        "audio/m4a": "m4a",
        "audio/x-m4a": "m4a",
        "audio/ogg": "ogg",
        "application/ogg": "ogg",
        "audio/webm": "webm",
        "video/webm": "webm",
        "audio/aac": "aac",
        "audio/x-aac": "aac",
    },
)
FORMAT_BY_SUFFIX: Mapping[str, AudioFormat] = cast(
    Mapping[str, AudioFormat],
    {
        ".wav": "wav",
        ".mp3": "mp3",
        ".pcm": "pcm",
        ".flac": "flac",
        ".m4a": "m4a",
        ".ogg": "ogg",
        ".webm": "webm",
        ".aac": "aac",
    },
)
SUFFIX_BY_FORMAT: Mapping[AudioFormat, str] = {
    "wav": ".wav",
    "mp3": ".mp3",
    "pcm": ".pcm",
    "flac": ".flac",
    "m4a": ".m4a",
    "ogg": ".ogg",
    "webm": ".webm",
    "aac": ".aac",
}
PYDUB_INPUT_FORMAT_BY_FORMAT: Mapping[AudioFormat, str] = {
    "wav": "wav",
    "mp3": "mp3",
    "pcm": "s16le",
    "flac": "flac",
    "m4a": "m4a",
    "ogg": "ogg",
    "webm": "webm",
    "aac": "aac",
}
PYDUB_EXPORT_FORMAT_BY_FORMAT: Mapping[AudioFormat, str] = {
    "wav": "wav",
    "mp3": "mp3",
    "pcm": "s16le",
    "flac": "flac",
    "m4a": "mp4",
    "ogg": "ogg",
    "webm": "webm",
    "aac": "adts",
}


class AudioConversionError(ValueError):
    pass


@dataclass(frozen=True)
class ConvertedAudio:
    data: bytes
    format: AudioFormat
    mime_type: str
    suffix: str


def normalize_mime_type(mime_type: str | None) -> str:
    base_type = (mime_type or "").split(";", maxsplit=1)[0].strip().lower()
    if not base_type:
        raise AudioConversionError("audio MIME type is required")
    if base_type not in FORMAT_BY_MIME:
        supported = ", ".join(sorted(set(FORMAT_BY_MIME)))
        raise AudioConversionError(f"unsupported audio MIME type; expected one of: {supported}")
    return MIME_BY_FORMAT[FORMAT_BY_MIME[base_type]]


def format_from_mime(mime_type: str) -> AudioFormat:
    try:
        return FORMAT_BY_MIME[mime_type]
    except KeyError as exc:
        raise AudioConversionError(f"unsupported audio MIME type: {mime_type}") from exc


def format_from_suffix(suffix: str) -> AudioFormat:
    normalized = suffix.lower()
    try:
        return FORMAT_BY_SUFFIX[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(FORMAT_BY_SUFFIX))
        raise AudioConversionError(
            f"unsupported audio suffix; expected one of: {supported}"
        ) from exc


def mime_for_format(audio_format: AudioFormat) -> str:
    return MIME_BY_FORMAT[audio_format]


def suffix_for_format(audio_format: AudioFormat) -> str:
    return SUFFIX_BY_FORMAT[audio_format]


def validate_mime_suffix_match(mime_type: str, suffix: str) -> AudioFormat:
    mime_format = format_from_mime(mime_type)
    suffix_format = format_from_suffix(suffix)
    if mime_format != suffix_format:
        raise AudioConversionError("audio MIME type does not match file suffix")
    return mime_format


def convert_audio_bytes(
    data: bytes,
    *,
    source_format: AudioFormat,
    target_format: DownloadAudioFormat,
) -> ConvertedAudio:
    if source_format == target_format:
        return ConvertedAudio(
            data=data,
            format=target_format,
            mime_type=mime_for_format(target_format),
            suffix=suffix_for_format(target_format),
        )
    try:
        audio_segment_cls = _audio_segment_class()
        if source_format == "pcm":
            segment = audio_segment_cls(
                data=data,
                sample_width=2,
                frame_rate=24_000,
                channels=1,
            )
        else:
            segment = audio_segment_cls.from_file(
                BytesIO(data),
                format=PYDUB_INPUT_FORMAT_BY_FORMAT[source_format],
            )
        if target_format == "pcm":
            pcm_segment = segment.set_frame_rate(24_000).set_channels(1).set_sample_width(2)
            output_data = pcm_segment.raw_data
        else:
            output = BytesIO()
            segment.export(output, format=PYDUB_EXPORT_FORMAT_BY_FORMAT[target_format])
            output_data = output.getvalue()
    except AudioConversionError:
        raise
    except Exception as exc:
        raise AudioConversionError(
            "audio conversion failed; install ffmpeg and upload a supported audio file"
        ) from exc
    return ConvertedAudio(
        data=output_data,
        format=target_format,
        mime_type=mime_for_format(target_format),
        suffix=suffix_for_format(target_format),
    )


def _audio_segment_class() -> Any:
    try:
        from pydub import AudioSegment
    except Exception as exc:
        raise AudioConversionError("audio conversion requires pydub and ffmpeg") from exc
    return AudioSegment
