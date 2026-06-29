from __future__ import annotations

import wave
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from typer.testing import CliRunner

from voice_toolbox.config import (
    APIConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    ChunkingConfig,
    LoggingConfig,
    ProviderDefaultModels,
    ASRChunkingConfig,
)
from voice_toolbox import cli
from voice_toolbox.models import (
    ASRRequest,
    ArtifactKind,
    AudioArtifact,
    ModelInfo,
    ProviderAudioResult,
    TranscriptCapabilities,
    TranscriptArtifact,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.registry import ProviderRegistry
from voice_toolbox.transcripts import TranscriptPayload


def _wav_silence(duration_ms: int) -> bytes:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


class RecordingProvider:
    id = "mimo"
    name = "Recording Provider"

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self.tts_requests: list[TTSRequest] = []
        self.asr_requests: list[ASRRequest] = []

    def capabilities(self) -> set[str]:
        return {"tts.builtin", "tts.design", "tts.clone", "asr.transcribe"}

    def list_models(self) -> list[object]:
        return []

    def list_voices(self) -> list[object]:
        return []

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self.tts_requests.append(request)
        return ProviderAudioResult(
            audio=f"WAV:{request.text}".encode(),
            mime_type="audio/wav",
            suffix=".wav",
            model=request.model,
        )

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        self.tts_requests.append(request)
        metadata = {"tts_mode": request.mode.value, **dict(artifact_metadata or {})}
        path = self.artifact_root / f"audio-{len(self.tts_requests)}.wav"
        path.write_bytes(b"WAV")
        return AudioArtifact(
            id=f"audio-{len(self.tts_requests)}",
            provider_id=self.id,
            operation="tts",
            path=path,
            mime_type="audio/wav",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            metadata=metadata,
        )

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        self.asr_requests.append(request)
        path = self.artifact_root / f"transcript-{len(self.asr_requests)}.txt"
        path.write_text("fake transcript", encoding="utf-8")
        return TranscriptArtifact(
            id=f"transcript-{len(self.asr_requests)}",
            kind=ArtifactKind.TRANSCRIPT,
            provider_id=self.id,
            operation="asr",
            path=path,
            mime_type="text/plain; charset=utf-8",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            metadata={"language": request.language},
        )

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        self.asr_requests.append(request)
        return TranscriptPayload(text=f"chunk {len(self.asr_requests)}")


def _install_recording_provider(monkeypatch: object, tmp_path: Path) -> RecordingProvider:
    provider = RecordingProvider(tmp_path)
    registry = ProviderRegistry([provider])
    monkeypatch.setattr(cli, "build_provider_registry", lambda: registry)
    return provider


def _install_cli_config(monkeypatch: object, *, asr_chunking: ASRChunkingConfig | None = None):
    config = AppConfig(
        api=APIConfig(host="127.0.0.1", port=8000),
        logging=LoggingConfig(console=ConsoleLoggingConfig(enabled=False)),
        chunking=ChunkingConfig(asr=asr_chunking or ASRChunkingConfig()),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
                default_models=ProviderDefaultModels(asr="fake-asr"),
                models=[
                    ModelInfo(
                        id="fake-asr",
                        name="Fake ASR",
                        capability="asr.transcribe",
                        transcript_capabilities=TranscriptCapabilities(
                            timestamps=True,
                            speakers=True,
                            segments=True,
                        ),
                    )
                ],
                voices=[VoiceInfo(id="Mia", name="Mia")],
            )
        ],
    )
    monkeypatch.setattr(cli, "_load_cli_context", lambda *, refresh=False: (config, {}))
    return config


def test_tts_synthesize_prints_audio_artifact(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia"],
    )

    assert result.exit_code == 0, result.output
    assert "audio-1" in result.output
    assert "path:" not in result.output
    assert "audio/wav" in result.output
    assert provider.tts_requests[0].text == "hello"
    assert provider.tts_requests[0].voice_id == "Mia"
    assert provider.tts_requests[0].output_format == "wav"


def test_tts_synthesize_accepts_format_wav(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia", "--format", "wav"],
    )

    assert result.exit_code == 0, result.output
    assert provider.tts_requests[0].output_format == "wav"


def test_tts_synthesize_accepts_format_mp3(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia", "--format", "mp3"],
    )

    assert result.exit_code == 0, result.output
    assert provider.tts_requests[0].output_format == "mp3"


def test_cli_tts_accepts_text_format_markdown(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "# Title", "--text-format", "markdown", "--voice", "Mia"],
    )

    assert result.exit_code == 0, result.output
    assert "audio" in result.output.lower()
    assert provider.tts_requests[0].text == "Title"


def test_cli_tts_synthesize_accepts_file_and_chunk_options(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    source = tmp_path / "script.md"
    source.write_text("# Title\n\n" + ("One. " * 80), encoding="utf-8")

    def fake_merge(results, *, silence_ms, output_format):
        assert len(results) > 1
        assert silence_ms == 25
        assert output_format == "wav"
        return ProviderAudioResult(
            audio=b"merged",
            mime_type="audio/wav",
            suffix=".wav",
            model=None,
        )

    monkeypatch.setattr(cli, "merge_audio_results", fake_merge, raising=False)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "synthesize",
            "--file",
            str(source),
            "--voice",
            "Mia",
            "--chunking",
            "force",
            "--chunk-max-chars",
            "200",
            "--chunk-silence-ms",
            "25",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(provider.tts_requests) > 1
    assert provider.tts_requests[0].text.startswith("Title")
    assert "chunks:" in result.output


def test_cli_tts_rejects_text_and_file(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    source = tmp_path / "script.txt"
    source.write_text("from file", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "synthesize",
            "--text",
            "inline",
            "--file",
            str(source),
            "--voice",
            "Mia",
        ],
    )

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output
    assert provider.tts_requests == []


def test_tts_synthesize_rejects_unknown_format(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia", "--format", "flac"],
    )

    assert result.exit_code != 0
    assert "format" in result.output.lower()
    assert "wav or mp3" in result.output
    assert provider.tts_requests == []


def test_default_mimo_provider_fails_fast_without_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia"],
    )

    assert result.exit_code != 0
    assert "MIMO_API_KEY" in result.output
    assert ".env" in result.output
    assert "Traceback" not in result.output


def test_tts_design_optimized_preview_works_without_text(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "design",
            "--description",
            "warm narrator",
            "--text",
            "   ",
            "--optimize-text-preview",
        ],
    )

    assert result.exit_code == 0, result.output
    assert provider.tts_requests[0].voice_description == "warm narrator"
    assert provider.tts_requests[0].optimize_text_preview is True
    assert provider.tts_requests[0].text is None


def test_tts_design_accepts_format_wav(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "design",
            "--description",
            "warm narrator",
            "--optimize-text-preview",
            "--format",
            "wav",
        ],
    )

    assert result.exit_code == 0, result.output
    assert provider.tts_requests[0].output_format == "wav"


def test_tts_design_rejects_force_chunking(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "design",
            "--description",
            "warm narrator",
            "--text",
            "preview",
            "--chunking",
            "force",
        ],
    )

    assert result.exit_code != 0
    assert "design mode does not support force chunking" in result.output
    assert provider.tts_requests == []


def test_tts_design_rejects_file_with_optimized_preview(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    source = tmp_path / "preview.txt"
    source.write_text("preview", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "design",
            "--description",
            "warm narrator",
            "--file",
            str(source),
            "--optimize-text-preview",
        ],
    )

    assert result.exit_code != 0
    assert "text_file is not allowed" in result.output
    assert provider.tts_requests == []


def test_tts_clone_fails_without_consent_in_non_tty(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"abcd")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "clone", "--sample", str(sample), "--text", "hello"],
    )

    assert result.exit_code != 0
    assert "consent" in result.output.lower()
    assert provider.tts_requests == []


def test_tts_clone_succeeds_with_consent(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"abcd")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "clone",
            "--sample",
            str(sample),
            "--reference-text",
            "sample words",
            "--text",
            "hello",
            "--consent",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "audio-1" in result.output
    request = provider.tts_requests[0]
    assert request.clone_sample_path == sample
    assert request.clone_mime_type == "audio/wav"
    assert request.clone_raw_byte_size == 4
    assert request.clone_base64_size == 8
    assert request.clone_reference_text == "sample words"
    assert request.consent_confirmed is True


def test_tts_clone_accepts_format_wav(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"abcd")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "clone",
            "--sample",
            str(sample),
            "--text",
            "hello",
            "--consent",
            "--format",
            "wav",
        ],
    )

    assert result.exit_code == 0, result.output
    assert provider.tts_requests[0].output_format == "wav"


def test_tts_clone_accepts_text_file_and_chunk_options(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    sample = tmp_path / "voice.wav"
    source = tmp_path / "script.txt"
    sample.write_bytes(b"abcd")
    source.write_text("One. " * 80, encoding="utf-8")

    def fake_merge(results, *, silence_ms, output_format):
        assert len(results) > 1
        assert silence_ms == 25
        assert output_format == "wav"
        return ProviderAudioResult(
            audio=b"merged",
            mime_type="audio/wav",
            suffix=".wav",
            model=None,
        )

    monkeypatch.setattr(cli, "merge_audio_results", fake_merge, raising=False)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "tts",
            "clone",
            "--sample",
            str(sample),
            "--file",
            str(source),
            "--consent",
            "--chunking",
            "force",
            "--chunk-max-chars",
            "200",
            "--chunk-silence-ms",
            "25",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(provider.tts_requests) > 1
    assert provider.tts_requests[0].clone_sample_path == sample


def test_asr_transcribe_auto_language_succeeds(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"abcde")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["asr", "transcribe", "--file", str(audio), "--language", "auto"],
    )

    assert result.exit_code == 0, result.output
    assert "transcript-1" in result.output
    assert "fake transcript" not in result.output
    request = provider.asr_requests[0]
    assert request.audio_path == audio
    assert request.mime_type == "audio/mpeg"
    assert request.raw_byte_size == 5
    assert request.base64_size == 8
    assert request.language == "auto"
    assert request.model is None


def test_cli_asr_model_can_be_omitted(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    runner = CliRunner()

    result = runner.invoke(cli.app, ["asr", "transcribe", "--file", str(audio)])

    assert result.exit_code == 0, result.output
    assert provider.asr_requests[0].model is None


def test_cli_asr_accepts_chunking_flags(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    _install_cli_config(
        monkeypatch,
        asr_chunking=ASRChunkingConfig(target_seconds=10, overlap_ms=0, max_chunks=10),
    )
    audio = tmp_path / "speech.wav"
    audio.write_bytes(_wav_silence(21_000))
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "asr",
            "transcribe",
            "--file",
            str(audio),
            "--chunking",
            "force",
            "--chunk-seconds",
            "10",
            "--chunk-overlap-ms",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(provider.asr_requests) == 3
    assert all(
        request.audio_path.name.startswith("asr-chunk-") for request in provider.asr_requests
    )


def test_cli_asr_accepts_timestamps_and_speakers_flags(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    _install_cli_config(monkeypatch)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "asr",
            "transcribe",
            "--file",
            str(audio),
            "--timestamps",
            "--speakers",
        ],
    )

    assert result.exit_code == 0, result.output
    assert provider.asr_requests[0].transcript_timestamps is True
    assert provider.asr_requests[0].transcript_speakers is True
