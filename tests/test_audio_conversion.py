from __future__ import annotations

from io import BytesIO

import pytest

from voice_toolbox import audio_conversion
from voice_toolbox.audio_conversion import (
    AudioConversionError,
    convert_audio_bytes,
    normalize_mime_type,
    validate_mime_suffix_match,
)


class FakeSegment:
    def __init__(self, data: bytes, source_format: str) -> None:
        self.data = data
        self.source_format = source_format

    @classmethod
    def from_file(cls, stream: BytesIO, *, format: str) -> FakeSegment:
        return cls(stream.read(), format)

    def export(self, output: BytesIO, *, format: str) -> None:
        output.write(f"{self.source_format}->{format}:".encode())
        output.write(self.data)


def test_convert_audio_bytes_uses_pydub_for_different_formats(monkeypatch) -> None:
    monkeypatch.setattr(audio_conversion, "_audio_segment_class", lambda: FakeSegment)

    converted = convert_audio_bytes(b"M4A", source_format="m4a", target_format="wav")

    assert converted.data == b"m4a->wav:M4A"
    assert converted.format == "wav"
    assert converted.mime_type == "audio/wav"
    assert converted.suffix == ".wav"


def test_convert_audio_bytes_keeps_matching_format_without_decoder(monkeypatch) -> None:
    monkeypatch.setattr(
        audio_conversion,
        "_audio_segment_class",
        lambda: (_ for _ in ()).throw(AssertionError("decoder should not be used")),
    )

    converted = convert_audio_bytes(b"MP3", source_format="mp3", target_format="mp3")

    assert converted.data == b"MP3"
    assert converted.mime_type == "audio/mpeg"


def test_upload_mime_and_suffix_normalization() -> None:
    assert normalize_mime_type("audio/x-m4a; codecs=mp4a") == "audio/mp4"
    assert validate_mime_suffix_match("audio/mp4", ".m4a") == "m4a"

    with pytest.raises(AudioConversionError, match="does not match"):
        validate_mime_suffix_match("audio/wav", ".mp3")
