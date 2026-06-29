from __future__ import annotations

from voice_toolbox.audio_conversion import DownloadAudioFormat
from voice_toolbox.chunking.audio import concat_audio_results, export_audio_segment
from voice_toolbox.models import ProviderAudioResult


def merge_audio_results(
    results: list[ProviderAudioResult],
    *,
    silence_ms: int,
    output_format: DownloadAudioFormat,
) -> ProviderAudioResult:
    merged = concat_audio_results(results, silence_ms=silence_ms)
    exported = export_audio_segment(merged, output_format=output_format)
    return exported.model_copy(update={"model": results[-1].model if results else None})
