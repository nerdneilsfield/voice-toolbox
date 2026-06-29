from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config import (
    APIConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    ChunkingConfig,
    LoggingConfig,
    ProviderDefaultModels,
    TTSChunkingConfig,
)
from voice_toolbox.models import (
    ASRRequest,
    ModelInfo,
    ProviderAudioResult,
    ProviderOptionSpec,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.fake import FakeProvider
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE, MIMO_VOICES
from voice_toolbox.providers.registry import ProviderRegistry
from voice_toolbox.transcripts import TranscriptPayload, TranscriptSegment
import voice_toolbox_api.main as api_main
from voice_toolbox_api.main import create_app

WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVEfmt "
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00"


class RecordingMimoProvider(FakeProvider):
    id = "mimo"
    name = "MiMo"

    def __init__(self, artifact_root: Path) -> None:
        super().__init__(artifact_root=artifact_root)
        self.tts_requests: list[TTSRequest] = []
        self.asr_requests: list[ASRRequest] = []
        self.asr_uploaded_bytes: list[bytes] = []
        self.clone_sample_paths: list[Path] = []
        self.clone_sample_bytes: list[bytes] = []
        self.clone_sample_exists_during_call: list[bool] = []
        self.asr_error: ProviderError | None = None
        self.tts_error_after_calls: int | None = None

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in MIMO_VOICES]

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self.tts_requests.append(request)
        if request.clone_sample_path is not None:
            self.clone_sample_paths.append(request.clone_sample_path)
            self.clone_sample_exists_during_call.append(request.clone_sample_path.exists())
            self.clone_sample_bytes.append(request.clone_sample_path.read_bytes())
        if self.tts_error_after_calls is not None and (
            len(self.tts_requests) >= self.tts_error_after_calls
        ):
            raise ProviderError("chunk failed")
        return super().synthesize_bytes(request)

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ):
        return super().synthesize(request, artifact_metadata=artifact_metadata)

    def transcribe(self, request: ASRRequest):
        if self.asr_error is not None:
            raise self.asr_error
        self.asr_requests.append(request)
        self.asr_uploaded_bytes.append(request.audio_path.read_bytes())
        return super().transcribe(request)


class ExplodingProvider(RecordingMimoProvider):
    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ):
        raise RuntimeError("raw traceback secret /Users/private/path")


class NoCloneProvider(RecordingMimoProvider):
    def capabilities(self) -> set[str]:
        return {"tts.builtin", "asr.transcribe"}


def _test_config(
    *,
    host: str = "127.0.0.1",
    tts_chunking: TTSChunkingConfig | None = None,
    provider_options: list[ProviderOptionSpec] | None = None,
    models: list[ModelInfo] | None = None,
) -> AppConfig:
    return AppConfig(
        api=APIConfig(host=host, port=8000),
        logging=LoggingConfig(console=ConsoleLoggingConfig(enabled=False)),
        chunking=ChunkingConfig(tts=tts_chunking or TTSChunkingConfig()),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
                default_voice="mimo_default",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=models
                or [
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
                voices=[VoiceInfo(id="mimo_default", name="MiMo-默认")],
                options=provider_options or [],
            )
        ],
    )


def _client(
    tmp_path: Path,
    *,
    has_api_key: bool = True,
    config: AppConfig | None = None,
) -> tuple[TestClient, RecordingMimoProvider]:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config or _test_config(),
        env_values={"MIMO_API_KEY": "test-key" if has_api_key else ""},
    )
    return TestClient(app), provider


def _write_rich_transcript_artifact(tmp_path: Path) -> str:
    artifact = ArtifactStore(tmp_path).write_transcript(
        operation_id="op_transcript",
        provider_id="mimo",
        operation="asr",
        text="hello\nworld",
        payload=TranscriptPayload(
            text="hello\nworld",
            segments=[
                TranscriptSegment(
                    text="hello",
                    start_seconds=0,
                    end_seconds=1.25,
                    speaker="A",
                ),
                TranscriptSegment(
                    text="world",
                    start_seconds=1.25,
                    end_seconds=2.5,
                    speaker="B",
                ),
            ],
        ),
    )
    return artifact.id


def test_health() -> None:
    client, _ = _client(Path.cwd())

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_providers_include_mimo_and_api_key_status(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, has_api_key=True)

    response = client.get("/v1/providers")

    assert response.status_code == 200
    providers = response.json()["providers"]
    mimo = next(provider for provider in providers if provider["id"] == "mimo")
    assert mimo["name"] == "MiMo"
    assert mimo["has_api_key"] is True
    assert isinstance(mimo["has_api_key"], bool)
    assert "api_key" not in mimo


def test_create_app_accepts_config_and_provider_summary_masks_key(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    mimo = response.json()["providers"][0]
    assert mimo["api_key_env"] == "MIMO_API_KEY"
    assert mimo["api_key_preview"] == "tp-...abcd"
    assert mimo["config_path_preview"] == "built-in default"
    assert mimo["base_url"] == "https://api.xiaomimimo.com/v1"
    assert mimo["default_voice"] == "mimo_default"
    assert mimo["default_models"]["tts_builtin"] == "fake-tts"
    assert {voice["id"] for voice in mimo["voices"]} >= {"mimo_default", "Mia"}


def test_provider_summary_non_local_host_hides_key_preview(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(host="0.0.0.0"),
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    assert response.json()["providers"][0]["api_key_preview"] == "configured"


def test_provider_summary_remote_client_hides_key_preview(tmp_path: Path) -> None:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "tp-1234567890abcd"},
    )
    client = TestClient(app, client=("203.0.113.10", 50000))

    response = client.get("/v1/providers")

    assert response.json()["providers"][0]["api_key_preview"] == "configured"


def test_provider_summary_falls_back_for_unconfigured_injected_provider(tmp_path: Path) -> None:
    provider = FakeProvider(artifact_root=tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={},
    )
    client = TestClient(app)

    response = client.get("/v1/providers")

    summary = response.json()["providers"][0]
    assert summary["id"] == "fake"
    assert summary["type"] == "test"
    assert summary["base_url"] is None
    assert summary["api_key_env"] is None
    assert summary["has_api_key"] is False
    assert summary["default_models"] == {}
    assert summary["config_path_preview"] == "built-in default"
    assert summary["capabilities"] == sorted(provider.capabilities())
    assert {voice["id"] for voice in summary["voices"]} == {"Mia", "Chen"}


def test_missing_key_blocks_only_operation_not_listing(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, has_api_key=False)

    listed = client.get("/v1/providers")
    blocked = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello", "voice_id": "Mia"},
    )

    assert listed.status_code == 200
    assert listed.json()["providers"][0]["has_api_key"] is False
    assert blocked.status_code == 503


def test_request_validation_error_does_not_echo_raw_input(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.post(
        "/v1/tts/synthesize",
        data={"mode": "not-a-real-mode", "provider_id": "mimo", "text": "secret text"},
    )

    assert response.status_code == 422
    assert "not-a-real-mode" not in response.text
    assert "secret text" not in response.text


def test_unhandled_exception_returns_generic_error(tmp_path: Path) -> None:
    provider = ExplodingProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello", "voice_id": "Mia"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "internal server error"
    assert response.json()["request_id"]
    assert "raw traceback secret" not in response.text
    assert "/Users/private/path" not in response.text


def test_provider_models_route_lists_models(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/v1/providers/mimo/models")

    assert response.status_code == 200
    models = response.json()["models"]
    assert {model["id"] for model in models} >= {"fake-tts", "fake-asr"}


def test_mimo_voices_are_hard_coded(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/v1/providers/mimo/voices")

    assert response.status_code == 200
    voices = response.json()["voices"]
    assert {voice["id"] for voice in voices} >= {"冰糖", "Mia", "Dean"}
    assert voices[0]["id"] == "mimo_default"


def test_normalize_text_endpoint(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.post(
        "/v1/normalize/text",
        json={"content": "# Title\nHello **world**", "input_format": "markdown"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Title\nHello world"
    assert response.json()["normalizer_id"] == "markdown_basic"


def test_normalize_text_endpoint_rejects_empty_and_too_large(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    empty = client.post(
        "/v1/normalize/text",
        json={"content": " ", "input_format": "plain"},
    )
    large = client.post(
        "/v1/normalize/text",
        json={"content": "x" * 200001, "input_format": "plain"},
    )

    assert empty.status_code == 422
    assert empty.json()["detail"] == "content is required"
    assert large.status_code == 413
    assert large.json()["detail"] == "content exceeds 200000 characters"


def test_asr_transcribe_accepts_multipart_and_returns_operation_result(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        data={"language": "zh", "provider_id": "mimo"},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"]["operation"] == "asr"
    assert payload["operation"]["status"] == "completed"
    assert payload["operation"]["artifact_ids"] == [payload["artifact"]["id"]]
    assert payload["operation"]["started_at"] < payload["operation"]["finished_at"]
    assert payload["artifact"]["kind"] == "transcript"
    assert payload["artifact"]["metadata"]["uploaded_file_mime_type"] == "audio/wav"
    assert "path" not in payload["artifact"]
    assert payload["artifact"]["download_url"].endswith(
        f"/v1/artifacts/{payload['artifact']['id']}/download"
    )

    request = provider.asr_requests[0]
    assert request.provider_id == "mimo"
    assert request.language == "zh"
    assert request.mime_type == "audio/wav"
    assert request.raw_byte_size == len(WAV_BYTES)
    assert request.base64_size == 24
    assert provider.asr_uploaded_bytes == [WAV_BYTES]


def test_asr_model_omitted_passes_none_to_provider(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        data={"language": "auto", "provider_id": "mimo"},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[-1].model is None


def test_asr_empty_model_is_normalized_to_none(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        data={"language": "auto", "provider_id": "mimo", "model": "   "},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[-1].model is None


def test_asr_upload_converts_non_native_audio_before_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)

    def fake_convert_audio_bytes(contents, *, source_format, target_format):
        assert contents == b"M4A"
        assert source_format == "m4a"
        assert target_format == "wav"
        return api_main.ConvertedAudio(
            data=WAV_BYTES,
            format="wav",
            mime_type="audio/wav",
            suffix=".wav",
        )

    monkeypatch.setattr(api_main, "convert_audio_bytes", fake_convert_audio_bytes)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.m4a", b"M4A", "audio/mp4")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[0].mime_type == "audio/wav"
    assert provider.asr_uploaded_bytes == [WAV_BYTES]


def test_tts_builtin_design_and_clone_routes_normalize_requests(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    builtin = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
            "style_instruction": "warm",
        },
    )
    design = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "bright narrator",
            "optimize_text_preview": "true",
        },
    )
    clone = client.post(
        "/v1/tts/clone",
        data={
            "provider_id": "mimo",
            "text": "clone hello",
            "clone_reference_text": "sample words",
            "consent_confirmed": "true",
        },
        files={"sample": ("sample.wav", WAV_BYTES, "audio/wav")},
    )

    assert builtin.status_code == 200
    assert design.status_code == 200
    assert clone.status_code == 200
    assert [request.mode.value for request in provider.tts_requests] == [
        "builtin",
        "design",
        "clone",
    ]
    assert provider.tts_requests[0].text == "hello"
    assert provider.tts_requests[0].voice_id == "Mia"
    assert provider.tts_requests[1].voice_description == "bright narrator"
    assert provider.tts_requests[1].optimize_text_preview is True
    assert provider.tts_requests[2].clone_mime_type == "audio/wav"
    assert provider.tts_requests[2].clone_raw_byte_size == len(WAV_BYTES)
    assert provider.tts_requests[2].clone_base64_size == 24
    assert provider.tts_requests[2].clone_reference_text == "sample words"
    assert provider.tts_requests[2].consent_confirmed is True
    assert provider.clone_sample_exists_during_call == [True]
    assert not provider.clone_sample_paths[0].exists()
    assert "data:" not in str(clone.json())
    assert "base64," not in str(clone.json())
    assert "path" not in clone.json()["artifact"]


def test_tts_rejects_oversized_text_before_provider_call(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "x" * 200001, "voice_id": "Mia"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "text exceeds 200000 characters"
    assert provider.tts_requests == []


def test_tts_rejects_unknown_model_before_provider_call(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello", "voice_id": "Mia", "model": "missing"},
    )

    assert response.status_code == 422
    assert "model missing is not configured" in response.text
    assert provider.tts_requests == []


def test_tts_endpoint_normalizes_markdown_and_writes_metadata(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "# Title\nHello **world**",
            "text_format": "markdown",
            "voice_id": "Mia",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text == "Title\nHello world"
    assert (
        response.json()["artifact"]["metadata"]["normalization_normalizer_id"] == "markdown_basic"
    )
    assert "Hello **world**" not in str(response.json())


def test_tts_builtin_accepts_text_file(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "voice_id": "Mia"},
        files={"text_file": ("script.md", b"# Title\nHello **file**", "text/markdown")},
    )

    assert response.status_code == 200, response.text
    assert provider.tts_requests[-1].text == "Title\nHello file"
    metadata = response.json()["artifact"]["metadata"]
    assert metadata["source_kind"] == "file"
    assert metadata["uploaded_text_file_suffix"] == ".md"
    assert "source_text_preview" not in metadata


def test_clone_endpoint_normalizes_markdown(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/clone",
        data={
            "provider_id": "mimo",
            "text": "# Clone",
            "text_format": "markdown",
            "consent_confirmed": "true",
        },
        files={"sample": ("sample.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text == "Clone"
    assert (
        response.json()["artifact"]["metadata"]["normalization_normalizer_id"] == "markdown_basic"
    )


def test_tts_clone_accepts_text_file(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/clone",
        data={"provider_id": "mimo", "consent_confirmed": "true"},
        files={
            "sample": ("sample.wav", WAV_BYTES, "audio/wav"),
            "text_file": ("script.txt", b"clone from file", "text/plain"),
        },
    )

    assert response.status_code == 200, response.text
    assert provider.tts_requests[-1].text == "clone from file"


def test_tts_design_text_file_rules(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    accepted = client.post(
        "/v1/tts/design",
        data={"provider_id": "mimo", "voice_description": "warm narrator"},
        files={"text_file": ("preview.txt", b"preview from file", "text/plain")},
    )
    rejected_preview = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "warm narrator",
            "optimize_text_preview": "true",
        },
        files={"text_file": ("preview.txt", b"preview from file", "text/plain")},
    )
    rejected_force = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "warm narrator",
            "text": "preview",
            "chunking_mode": "force",
        },
    )
    rejected_long = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "warm narrator",
            "text": "x" * 250,
            "chunk_max_chars": "200",
        },
    )

    assert accepted.status_code == 200, accepted.text
    assert provider.tts_requests[-1].text == "preview from file"
    assert rejected_preview.status_code == 422
    assert rejected_force.status_code == 422
    assert rejected_long.status_code == 422


def test_long_builtin_tts_chunks_without_visible_intermediate_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)

    def fake_merge(results, *, silence_ms, output_format):
        assert len(results) > 1
        assert silence_ms == 25
        return ProviderAudioResult(
            audio=b"|".join(result.audio for result in results),
            mime_type="audio/wav",
            suffix=".wav",
            model=results[-1].model,
        )

    monkeypatch.setattr(api_main, "merge_audio_results", fake_merge, raising=False)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "One. " * 80,
            "voice_id": "Mia",
            "chunk_max_chars": "200",
            "chunk_silence_ms": "25",
        },
    )

    assert response.status_code == 200, response.text
    assert len(provider.tts_requests) > 1
    artifact = response.json()["artifact"]
    assert artifact["metadata"]["chunking_enabled"] is True
    assert artifact["metadata"]["chunking_chunk_count"] == len(provider.tts_requests)
    assert "chunk text" not in json.dumps(artifact["metadata"])
    listed = client.get("/v1/artifacts").json()["artifacts"]
    assert [item["id"] for item in listed] == [artifact["id"]]


def test_provider_options_reach_every_tts_chunk(monkeypatch, tmp_path: Path) -> None:
    config = _test_config(
        provider_options=[
            ProviderOptionSpec(
                key="speed",
                label="Speed",
                type="number",
                capability="tts.builtin",
                min_value=0.5,
                max_value=2.0,
            )
        ]
    )
    client, provider = _client(tmp_path, config=config)
    monkeypatch.setattr(
        api_main,
        "merge_audio_results",
        lambda results, *, silence_ms, output_format: ProviderAudioResult(
            audio=b"merged",
            mime_type="audio/wav",
            suffix=".wav",
            model=None,
        ),
        raising=False,
    )

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "One. " * 80,
            "voice_id": "Mia",
            "chunk_max_chars": "200",
            "provider_options": json.dumps({"speed": 1.25}),
        },
    )

    assert response.status_code == 200, response.text
    assert len(provider.tts_requests) > 1
    assert {request.provider_options["speed"] for request in provider.tts_requests} == {1.25}
    metadata = response.json()["artifact"]["metadata"]
    assert metadata["provider_option_keys"] == ["speed"]
    assert "1.25" not in json.dumps(metadata)


def test_default_model_provider_options_are_merged(tmp_path: Path) -> None:
    config = _test_config(
        provider_options=[
            ProviderOptionSpec(
                key="speed",
                label="Speed",
                type="number",
                capability="tts.builtin",
                min_value=0.5,
                max_value=2.0,
            )
        ],
        models=[
            ModelInfo(
                id="fake-tts",
                name="Fake TTS",
                capability="tts.builtin",
                options=[
                    {
                        "key": "speed",
                        "capability": "tts.builtin",
                        "max_value": 1.5,
                    }
                ],
            ),
            ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
        ],
    )
    client, provider = _client(tmp_path, config=config)

    rejected = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
            "provider_options": json.dumps({"speed": 1.75}),
        },
    )
    accepted = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
            "provider_options": json.dumps({"speed": 1.25}),
        },
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 200, accepted.text
    assert provider.tts_requests[-1].provider_options == {"speed": 1.25}


def test_tts_chunk_max_chars_override_uses_config_bounds(tmp_path: Path) -> None:
    client, _provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
            "chunking_mode": "force",
            "chunk_max_chars": "1",
        },
    )

    assert response.status_code == 422
    assert "max_chars" in response.text


def test_chunked_clone_reuses_temp_sample_and_cleans_on_provider_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    provider.tts_error_after_calls = 2
    monkeypatch.setattr(
        api_main,
        "merge_audio_results",
        lambda results, *, silence_ms, output_format: ProviderAudioResult(
            audio=b"merged",
            mime_type="audio/wav",
            suffix=".wav",
            model=None,
        ),
        raising=False,
    )

    response = client.post(
        "/v1/tts/clone",
        data={
            "provider_id": "mimo",
            "text": "One. " * 80,
            "consent_confirmed": "true",
            "chunk_max_chars": "200",
        },
        files={"sample": ("sample.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 502
    assert len(provider.clone_sample_paths) == 2
    assert len({path for path in provider.clone_sample_paths}) == 1
    assert provider.clone_sample_exists_during_call == [True, True]
    assert not provider.clone_sample_paths[0].parent.exists()


def test_clone_upload_converts_non_native_audio_before_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)

    def fake_convert_audio_bytes(contents, *, source_format, target_format):
        assert contents == b"FLAC"
        assert source_format == "flac"
        assert target_format == "wav"
        return api_main.ConvertedAudio(
            data=WAV_BYTES,
            format="wav",
            mime_type="audio/wav",
            suffix=".wav",
        )

    monkeypatch.setattr(api_main, "convert_audio_bytes", fake_convert_audio_bytes)

    response = client.post(
        "/v1/tts/clone",
        data={"text": "hello", "consent_confirmed": "true"},
        files={"sample": ("sample.flac", b"FLAC", "audio/flac")},
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].clone_mime_type == "audio/wav"
    assert provider.tts_requests[-1].clone_sample_path is not None
    assert provider.clone_sample_bytes[-1] == WAV_BYTES


def test_design_optimize_preview_empty_text_skips_normalization(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/design",
        data={
            "provider_id": "mimo",
            "voice_description": "warm narrator",
            "text": "   ",
            "text_format": "markdown",
            "optimize_text_preview": "true",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].text is None


def test_tts_synthesize_route_dispatches_builtin(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/synthesize",
        data={
            "mode": "builtin",
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[-1].mode.value == "builtin"
    assert provider.tts_requests[-1].text == "hello"
    assert response.json()["artifact"]["kind"] == "audio"
    assert "path" not in response.json()["artifact"]


def test_tts_synthesize_rejects_sample_for_non_clone_mode(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/tts/synthesize",
        data={
            "mode": "builtin",
            "provider_id": "mimo",
            "text": "hello",
            "voice_id": "Mia",
        },
        files={"sample": ("sample.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 422
    assert "sample" in response.json()["detail"]
    assert provider.tts_requests == []


def test_clone_route_checks_capability_before_reading_upload(tmp_path: Path) -> None:
    provider = NoCloneProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/tts/clone",
        data={"text": "hello", "consent_confirmed": "true"},
        files={"sample": ("sample.wav", b"not a valid wav", "audio/wav")},
    )

    assert response.status_code == 400
    assert "tts.clone" in response.json()["detail"]
    assert provider.tts_requests == []


def test_upload_routes_reject_base64_payloads_over_10_mib_before_provider(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    oversized = b"x" * ((MAX_BASE64_AUDIO_SIZE // 4) * 3 + 1)

    asr = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", oversized, "audio/wav")},
    )
    clone = client.post(
        "/v1/tts/clone",
        data={"text": "hello", "consent_confirmed": "true"},
        files={"sample": ("sample.wav", oversized, "audio/wav")},
    )

    assert asr.status_code in {413, 422}
    assert clone.status_code in {413, 422}
    assert provider.asr_requests == []
    assert provider.tts_requests == []


def test_upload_routes_reject_base64_padding_overflow_before_provider(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)
    raw_size = (MAX_BASE64_AUDIO_SIZE // 4) * 3 + 1
    oversized = b"x" * raw_size

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", oversized, "audio/wav")},
    )

    assert response.status_code == 413
    assert provider.asr_requests == []


def test_asr_provider_error_returns_502_without_traceback(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)
    provider.asr_error = ProviderError("backend unavailable")

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "backend unavailable"}
    assert "Traceback" not in response.text


def test_missing_mimo_api_key_fails_operations_but_not_provider_listing(tmp_path: Path) -> None:
    client, provider = _client(tmp_path, has_api_key=False)

    providers = client.get("/v1/providers")
    tts = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello", "voice_id": "Mia"},
    )
    asr = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    mimo = next(provider for provider in providers.json()["providers"] if provider["id"] == "mimo")
    assert providers.status_code == 200
    assert mimo["has_api_key"] is False
    assert tts.status_code == 503
    assert asr.status_code == 503
    assert "MIMO_API_KEY" in tts.json()["detail"]
    assert provider.tts_requests == []
    assert provider.asr_requests == []


def test_artifact_metadata_and_download_read_sidecar(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.mp3", MP3_BYTES, "audio/mpeg")},
    ).json()
    artifact_id = created["artifact"]["id"]

    metadata = client.get(f"/v1/artifacts/{artifact_id}")
    download = client.get(f"/v1/artifacts/{artifact_id}/download")

    assert metadata.status_code == 200
    assert metadata.json()["id"] == artifact_id
    assert metadata.json()["metadata"]["operation"] == "asr"
    assert "path" not in metadata.json()
    assert metadata.json()["download_url"].endswith(f"/v1/artifacts/{artifact_id}/download")
    assert download.status_code == 200
    assert download.content == b"fake transcript"
    assert download.headers["content-type"].startswith("text/plain")


def test_transcript_endpoint_json_is_only_explicit_payload_renderer(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.mp3", MP3_BYTES, "audio/mpeg")},
    ).json()
    artifact_id = created["artifact"]["id"]

    metadata = client.get(f"/v1/artifacts/{artifact_id}")
    download_json = client.get(f"/v1/artifacts/{artifact_id}/download?format=json")
    transcript_json = client.get(f"/v1/artifacts/{artifact_id}/transcript?format=json")

    assert metadata.status_code == 200
    assert "fake transcript" not in metadata.text
    assert download_json.status_code == 422
    assert transcript_json.status_code == 200
    assert transcript_json.json() == {"text": "fake transcript", "segments": []}


def test_transcript_endpoint_renders_txt_srt_and_vtt(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_id = _write_rich_transcript_artifact(tmp_path)

    txt = client.get(
        f"/v1/artifacts/{artifact_id}/transcript?format=txt&timestamps=true&speakers=true"
    )
    srt = client.get(f"/v1/artifacts/{artifact_id}/transcript?format=srt")
    vtt = client.get(f"/v1/artifacts/{artifact_id}/transcript?format=vtt")

    assert txt.status_code == 200
    assert txt.text == "[00:00.000 - 00:01.250] A: hello\n[00:01.250 - 00:02.500] B: world"
    assert srt.status_code == 200
    assert "00:00:00,000 --> 00:00:01,250" in srt.text
    assert vtt.status_code == 200
    assert vtt.text.startswith("WEBVTT\n\n")


def test_transcript_endpoint_rejects_audio_artifacts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact = ArtifactStore(tmp_path).write_audio(
        operation_id="op_audio",
        provider_id="mimo",
        operation="tts",
        audio=WAV_BYTES,
    )

    response = client.get(f"/v1/artifacts/{artifact.id}/transcript")

    assert response.status_code == 422
    assert "transcript" in response.json()["detail"]


def test_download_format_txt_rejects_transcript_artifacts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.mp3", MP3_BYTES, "audio/mpeg")},
    ).json()

    response = client.get(f"/v1/artifacts/{created['artifact']['id']}/download?format=txt")

    assert response.status_code == 422
    assert "transcript" in response.json()["detail"]


def test_artifact_routes_require_trusted_local_api(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, config=_test_config(host="0.0.0.0"))

    listing = client.get("/v1/artifacts")
    metadata = client.get("/v1/artifacts/missing")
    download = client.get("/v1/artifacts/missing/download")

    assert listing.status_code == 403
    assert metadata.status_code == 403
    assert download.status_code == 403


def test_artifact_download_infers_mp3_path_from_audio_mpeg_sidecar(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_dir = tmp_path / "data" / "artifacts" / "20260101"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "op_mp3.mp3").write_bytes(b"MP3")
    (artifact_dir / "op_mp3.json").write_text(
        json.dumps(
            {
                "id": "op_mp3",
                "kind": "audio",
                "provider_id": "openrouter",
                "operation": "tts",
                "mime_type": "audio/mpeg",
                "created_at": "2026-01-01T00:00:00Z",
                "metadata": {"operation": "tts", "output_format": "mp3"},
            }
        ),
        encoding="utf-8",
    )

    download = client.get("/v1/artifacts/op_mp3/download")

    assert download.status_code == 200
    assert download.content == b"MP3"
    assert download.headers["content-type"].startswith("audio/mpeg")
    content_disposition = download.headers["content-disposition"]
    assert 'filename="20260101-000000-' in content_disposition
    assert content_disposition.endswith('.mp3"')


def test_artifact_download_converts_audio_format(monkeypatch, tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_dir = tmp_path / "data" / "artifacts" / "20260101"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "op_audio.mp3").write_bytes(b"MP3")
    (artifact_dir / "op_audio.json").write_text(
        json.dumps(
            {
                "id": "op_audio",
                "kind": "audio",
                "provider_id": "openrouter",
                "operation": "tts",
                "mime_type": "audio/mpeg",
                "created_at": "2026-01-01T00:00:00Z",
                "metadata": {"operation": "tts", "output_format": "mp3"},
            }
        ),
        encoding="utf-8",
    )

    def fake_convert_audio_bytes(contents, *, source_format, target_format):
        assert contents == b"MP3"
        assert source_format == "mp3"
        assert target_format == "m4a"
        return api_main.ConvertedAudio(
            data=b"M4A",
            format="m4a",
            mime_type="audio/mp4",
            suffix=".m4a",
        )

    monkeypatch.setattr(api_main, "convert_audio_bytes", fake_convert_audio_bytes)

    download = client.get("/v1/artifacts/op_audio/download?format=m4a")

    assert download.status_code == 200
    assert download.content == b"M4A"
    assert download.headers["content-type"].startswith("audio/mp4")
    assert 'filename="20260101-000000-' in download.headers["content-disposition"]
    assert download.headers["content-disposition"].endswith('.m4a"')


def test_artifact_download_rejects_unknown_format(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_dir = tmp_path / "data" / "artifacts" / "20260101"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "op_audio.mp3").write_bytes(b"MP3")
    (artifact_dir / "op_audio.json").write_text(
        json.dumps(
            {
                "id": "op_audio",
                "kind": "audio",
                "provider_id": "openrouter",
                "operation": "tts",
                "mime_type": "audio/mpeg",
                "created_at": "2026-01-01T00:00:00Z",
                "metadata": {"operation": "tts", "output_format": "mp3"},
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/v1/artifacts/op_audio/download?format=docx")

    assert response.status_code == 422
    assert "download format" in response.json()["detail"]


def test_artifact_download_rejects_transcript_format_conversion(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.mp3", MP3_BYTES, "audio/mpeg")},
    ).json()

    response = client.get(f"/v1/artifacts/{created['artifact']['id']}/download?format=mp3")

    assert response.status_code == 422
    assert "transcript" in response.json()["detail"]


def test_artifact_download_rejects_sidecar_path_outside_artifact_root(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve", encoding="utf-8")
    sidecar_dir = tmp_path / "data" / "artifacts" / "20260101"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "evil.json").write_text(
        json.dumps(
            {
                "id": "evil",
                "kind": "transcript",
                "provider_id": "mimo",
                "operation": "asr",
                "path": str(secret),
                "mime_type": "text/plain; charset=utf-8",
                "created_at": "2026-01-01T00:00:00Z",
                "metadata": {"operation": "asr"},
            }
        ),
        encoding="utf-8",
    )

    metadata = client.get("/v1/artifacts/evil")
    download = client.get("/v1/artifacts/evil/download")

    assert metadata.status_code == 422
    assert download.status_code == 422
    assert download.content != b"do not serve"


def test_upload_routes_reject_unsupported_suffix_even_when_mime_allowed(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    asr = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.flac", WAV_BYTES, "audio/wav")},
    )
    clone = client.post(
        "/v1/tts/clone",
        data={"text": "hello", "consent_confirmed": "true"},
        files={"sample": ("sample.flac", WAV_BYTES, "audio/wav")},
    )

    assert asr.status_code == 422
    assert clone.status_code == 422
    assert provider.asr_requests == []
    assert provider.tts_requests == []


def test_upload_routes_reject_mime_suffix_mismatch(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", b"RIFFxxxxWAVE", "audio/mpeg")},
    )

    assert response.status_code == 422
    assert provider.asr_requests == []


def test_upload_routes_accept_wav_mime_alias_with_parameters(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", WAV_BYTES, "audio/x-wav; charset=binary")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[0].mime_type == "audio/wav"


def test_upload_routes_reject_l16_without_pcm_contract(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.pcm", b"\x00\x00" * 8, "audio/L16; rate=8000; channels=1")},
    )

    assert response.status_code == 422
    assert "rate=24000" in response.json()["detail"]
    assert provider.asr_requests == []


def test_upload_routes_accept_l16_with_explicit_pcm_contract(monkeypatch, tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    def fake_convert_audio_bytes(contents, *, source_format, target_format):
        assert contents == b"\x00\x00" * 8
        assert source_format == "pcm"
        assert target_format == "wav"
        return api_main.ConvertedAudio(
            data=WAV_BYTES,
            format="wav",
            mime_type="audio/wav",
            suffix=".wav",
        )

    monkeypatch.setattr(api_main, "convert_audio_bytes", fake_convert_audio_bytes)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.pcm", b"\x00\x00" * 8, "audio/L16; rate=24000; channels=1")},
    )

    assert response.status_code == 200
    assert provider.asr_requests[0].mime_type == "audio/wav"


def test_validation_errors_do_not_echo_raw_input(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "secret text", "voice_id": "   "},
    )

    assert response.status_code == 422
    assert "input" not in response.text
    assert "secret text" not in response.text


def test_cors_allows_vite_origin(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.options(
        "/v1/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_list_artifacts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_root = tmp_path / "data" / "artifacts"
    artifact_root.mkdir(parents=True)
    op_dir = artifact_root / "20260628"
    op_dir.mkdir()
    sidecars = [
        {
            "id": "test-artifact-1",
            "provider_id": "mimo",
            "operation": "tts",
            "kind": "audio",
            "mime_type": "audio/wav",
            "created_at": "2026-06-28T12:00:00+00:00",
            "path": "test1.wav",
            "metadata": {"tts_mode": "builtin"},
        },
        {
            "id": "test-artifact-2",
            "provider_id": "mimo",
            "operation": "asr",
            "kind": "transcript",
            "mime_type": "text/plain; charset=utf-8",
            "created_at": "2026-06-28T13:00:00+00:00",
            "path": "test2.txt",
        },
        {
            "id": "test-artifact-3",
            "provider_id": "mimo",
            "operation": "tts",
            "kind": "audio",
            "mime_type": "audio/wav",
            "created_at": "2026-06-28T11:00:00+00:00",
            "path": "test3.wav",
            "metadata": {"tts_mode": "design"},
        },
    ]
    for sidecar in sidecars:
        (op_dir / f"{sidecar['id']}.json").write_text(json.dumps(sidecar))

    response = client.get("/v1/artifacts?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["artifacts"]) == 2
    assert data["artifacts"][0]["id"] == "test-artifact-2"  # newest first
    assert data["artifacts"][1]["id"] == "test-artifact-1"


def test_list_artifacts_empty_root(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/v1/artifacts")
    assert response.status_code == 200
    assert response.json() == {"artifacts": []}


def test_list_artifacts_skips_invalid_sidecars(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    artifact_root = tmp_path / "data" / "artifacts"
    artifact_root.mkdir(parents=True)
    op_dir = artifact_root / "20260628"
    op_dir.mkdir()
    (op_dir / "bad.json").write_text("not json")
    response = client.get("/v1/artifacts")
    assert response.status_code == 200
    assert response.json() == {"artifacts": []}


def test_list_artifacts_limit_validation(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/v1/artifacts?limit=0").status_code == 422
    assert client.get("/v1/artifacts?limit=101").status_code == 422


class MetadataStrippingProvider(RecordingMimoProvider):
    """Proves _run_tts injects tts_mode itself. This provider bypasses
    FakeProvider.synthesize (which would add tts_mode from request.mode) and
    persists ONLY the injected artifact_metadata, so the only way tts_mode can
    appear in the sidecar is the _run_tts injection."""

    def synthesize(self, request, *, artifact_metadata=None):
        self.tts_requests.append(request)
        self._ensure_open()
        operation_id = self._next_operation_id("tts")
        return self._artifact_store.write_audio(
            operation_id=operation_id,
            provider_id=self.id,
            operation="tts",
            audio=self._audio_bytes(request),
            metadata=dict(artifact_metadata or {}),
        )


def test_tts_mode_persisted_in_artifact_metadata(tmp_path: Path) -> None:
    """_run_tts injects tts_mode into artifact_metadata before synthesize, so the
    listing endpoint can label each artifact even when the provider omits it."""
    provider = MetadataStrippingProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    builtin_response = client.post(
        "/v1/tts/builtin",
        data={"provider_id": "mimo", "text": "hello world", "voice_id": "Mia"},
    )
    assert builtin_response.status_code == 200
    builtin_id = builtin_response.json()["artifact"]["id"]

    listed = client.get("/v1/artifacts").json()["artifacts"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[builtin_id]["metadata"]["tts_mode"] == "builtin"
