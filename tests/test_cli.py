from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from voice_toolbox import cli
from voice_toolbox.models import (
    ASRRequest,
    ArtifactKind,
    AudioArtifact,
    TranscriptArtifact,
    TTSRequest,
)
from voice_toolbox.providers.registry import ProviderRegistry


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


def _install_recording_provider(monkeypatch: object, tmp_path: Path) -> RecordingProvider:
    provider = RecordingProvider(tmp_path)
    registry = ProviderRegistry([provider])
    monkeypatch.setattr(cli, "build_provider_registry", lambda: registry)
    return provider


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


def test_tts_synthesize_rejects_unsupported_format(monkeypatch, tmp_path: Path) -> None:
    provider = _install_recording_provider(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["tts", "synthesize", "--text", "hello", "--voice", "Mia", "--format", "mp3"],
    )

    assert result.exit_code != 0
    assert "format" in result.output.lower()
    assert "wav" in result.output
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
        ["tts", "clone", "--sample", str(sample), "--text", "hello", "--consent"],
    )

    assert result.exit_code == 0, result.output
    assert "audio-1" in result.output
    request = provider.tts_requests[0]
    assert request.clone_sample_path == sample
    assert request.clone_mime_type == "audio/wav"
    assert request.clone_raw_byte_size == 4
    assert request.clone_base64_size == 8
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
    assert "fake transcript" in result.output
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
