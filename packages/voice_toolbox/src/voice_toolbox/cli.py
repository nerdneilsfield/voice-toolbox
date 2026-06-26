from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

import typer
from pydantic import ValidationError

from voice_toolbox.models import ASRRequest, AudioArtifact, TranscriptArtifact, TTSMode, TTSRequest
from voice_toolbox.providers import ProviderError, ProviderRegistry
from voice_toolbox.providers.mimo import MimoProvider
from voice_toolbox.settings import has_mimo_api_key

app = typer.Typer(help="Voice Toolbox")
tts_app = typer.Typer(help="Text-to-speech commands")
asr_app = typer.Typer(help="Speech-to-text commands")

DEFAULT_PROVIDER = "mimo"
DEFAULT_OUTPUT_FORMAT: Literal["wav"] = "wav"
SUPPORTED_AUDIO_MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}
AudioMime = Literal["audio/wav", "audio/mpeg", "audio/mp3"]

ProviderOption = Annotated[str, typer.Option("--provider", help="Provider id.")]
TextOption = Annotated[str, typer.Option("--text", help="Text to synthesize.")]
OptionalTextOption = Annotated[str | None, typer.Option("--text", help="Text to synthesize.")]
ModelOption = Annotated[str | None, typer.Option("--model", help="Provider model id.")]
FormatOption = Annotated[str, typer.Option("--format", help="Output format; v1 supports wav.")]
StyleOption = Annotated[
    str | None,
    typer.Option("--style", help="Optional style instruction."),
]


def build_provider_registry() -> ProviderRegistry:
    _ensure_default_provider_configured()
    return ProviderRegistry([MimoProvider(artifact_root=Path.cwd())])


@app.callback()
def main() -> None:
    """Run Voice Toolbox commands."""


@tts_app.command()
def synthesize(
    text: TextOption,
    voice: Annotated[str, typer.Option("--voice", help="Voice id.")],
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
    style: StyleOption = None,
) -> None:
    request = _build_tts_request(
        provider_id=provider,
        mode=TTSMode.BUILTIN,
        model=model,
        text=text,
        style_instruction=style,
        voice_id=voice,
        output_format=output_format,
    )
    artifact = _synthesize(provider, request)
    _print_audio_artifact(artifact)


@tts_app.command()
def design(
    description: Annotated[str, typer.Option("--description", help="Voice description.")],
    text: OptionalTextOption = None,
    optimize_text_preview: Annotated[
        bool,
        typer.Option("--optimize-text-preview", help="Let provider optimize preview text."),
    ] = False,
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
) -> None:
    request = _build_tts_request(
        provider_id=provider,
        mode=TTSMode.DESIGN,
        model=model,
        text=text,
        voice_description=description,
        optimize_text_preview=optimize_text_preview,
        output_format=output_format,
    )
    artifact = _synthesize(provider, request)
    _print_audio_artifact(artifact)


@tts_app.command()
def clone(
    sample: Annotated[Path | None, typer.Option("--sample", help="Voice sample wav/mp3.")] = None,
    text: OptionalTextOption = None,
    consent: Annotated[
        bool,
        typer.Option("--consent", help="Confirm rights and consent for uploaded voice sample."),
    ] = False,
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: ModelOption = None,
    output_format: FormatOption = DEFAULT_OUTPUT_FORMAT,
    style: StyleOption = None,
) -> None:
    if sample is None:
        _fail("--sample is required")
    if text is None:
        _fail("--text is required")
    sample = _normalize_existing_audio_path(sample)
    consent_confirmed = _confirm_clone_consent(consent)
    mime_type, raw_byte_size, base64_size = _audio_upload_metadata(sample)
    request = _build_tts_request(
        provider_id=provider,
        mode=TTSMode.CLONE,
        model=model,
        text=text,
        style_instruction=style,
        clone_sample_path=sample,
        clone_mime_type=mime_type,
        clone_raw_byte_size=raw_byte_size,
        clone_base64_size=base64_size,
        consent_confirmed=consent_confirmed,
        output_format=output_format,
    )
    artifact = _synthesize(provider, request)
    _print_audio_artifact(artifact)


@asr_app.command()
def transcribe(
    file: Annotated[Path | None, typer.Option("--file", help="Audio file wav/mp3.")] = None,
    language: Annotated[
        Literal["auto", "zh", "en"],
        typer.Option("--language", help="Language hint."),
    ] = "auto",
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: Annotated[str, typer.Option("--model", help="Provider ASR model id.")] = "mimo-v2.5-asr",
) -> None:
    if file is None:
        _fail("--file is required")
    file = _normalize_existing_audio_path(file)
    mime_type, raw_byte_size, base64_size = _audio_upload_metadata(file)
    try:
        request = ASRRequest(
            provider_id=provider,
            model=model,
            audio_path=file,
            mime_type=mime_type,
            raw_byte_size=raw_byte_size,
            base64_size=base64_size,
            language=language,
        )
    except ValidationError as exc:
        _fail(str(exc))

    artifact = _transcribe(provider, request)
    _print_transcript_artifact(artifact)


def _build_tts_request(*, output_format: str = DEFAULT_OUTPUT_FORMAT, **fields: Any) -> TTSRequest:
    try:
        return TTSRequest(output_format=_normalize_output_format(output_format), **fields)
    except ValidationError as exc:
        _fail(str(exc))


def _synthesize(provider_id: str, request: TTSRequest) -> AudioArtifact:
    try:
        provider = build_provider_registry().ensure_tts_capability(provider_id, request)
        return provider.synthesize(request)
    except ProviderError as exc:
        _fail(str(exc))


def _transcribe(provider_id: str, request: ASRRequest) -> TranscriptArtifact:
    try:
        provider = build_provider_registry().ensure_asr_capability(provider_id, request)
        return provider.transcribe(request)
    except ProviderError as exc:
        _fail(str(exc))


def _confirm_clone_consent(consent: bool) -> bool:
    if consent:
        return True
    if sys.stdin.isatty():
        if typer.confirm("Confirm rights and consent for this voice sample?"):
            return True
        _fail("consent not confirmed")
    _fail("consent required in non-TTY mode; rerun with --consent")


def _normalize_existing_audio_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_file():
        _fail(f"file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_MIME_BY_SUFFIX:
        _fail("unsupported audio suffix; expected .wav or .mp3")
    return path


def _audio_upload_metadata(path: Path) -> tuple[AudioMime, int, int]:
    suffix = path.suffix.lower()
    mime_type = SUPPORTED_AUDIO_MIME_BY_SUFFIX.get(suffix)
    if mime_type is None:
        _fail("unsupported audio suffix; expected .wav or .mp3")
    raw_byte_size = path.stat().st_size
    base64_size = ((raw_byte_size + 2) // 3) * 4
    return cast(AudioMime, mime_type), raw_byte_size, base64_size


def _normalize_output_format(output_format: str) -> Literal["wav"]:
    if output_format != DEFAULT_OUTPUT_FORMAT:
        _fail("unsupported output format; expected wav")
    return DEFAULT_OUTPUT_FORMAT


def _ensure_default_provider_configured() -> None:
    if not has_mimo_api_key():
        _fail("MIMO_API_KEY is required for provider mimo; set it in environment or .env")


def _fail(message: str) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _print_audio_artifact(artifact: AudioArtifact) -> None:
    typer.echo(f"id: {artifact.id}")
    typer.echo(f"path: {artifact.path}")
    typer.echo(f"mime: {artifact.mime_type}")


def _print_transcript_artifact(artifact: TranscriptArtifact) -> None:
    typer.echo(f"id: {artifact.id}")
    typer.echo(f"path: {artifact.path}")
    typer.echo(f"mime: {artifact.mime_type}")
    try:
        text = artifact.path.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        typer.echo(f"text: {text}")


app.add_typer(tts_app, name="tts")
app.add_typer(asr_app, name="asr")
