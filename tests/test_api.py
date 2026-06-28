from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from voice_toolbox.config import (
    APIConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    LoggingConfig,
    ProviderDefaultModels,
)
from voice_toolbox.models import ASRRequest, ModelInfo, TTSRequest, VoiceInfo
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.fake import FakeProvider
from voice_toolbox.providers.mimo import MAX_BASE64_AUDIO_SIZE, MIMO_VOICES
from voice_toolbox.providers.registry import ProviderRegistry
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
        self.clone_sample_exists_during_call: list[bool] = []
        self.asr_error: ProviderError | None = None

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in MIMO_VOICES]

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ):
        self.tts_requests.append(request)
        if request.clone_sample_path is not None:
            self.clone_sample_paths.append(request.clone_sample_path)
            self.clone_sample_exists_during_call.append(request.clone_sample_path.exists())
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


def _test_config(*, host: str = "127.0.0.1") -> AppConfig:
    return AppConfig(
        api=APIConfig(host=host, port=8000),
        logging=LoggingConfig(console=ConsoleLoggingConfig(enabled=False)),
        providers=[
            ConfiguredProvider(
                id="mimo",
                type="mimo",
                name="MiMo",
                base_url="https://api.xiaomimimo.com/v1",
                api_key_env="MIMO_API_KEY",
                default_voice="mimo_default",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
                voices=[VoiceInfo(id="mimo_default", name="MiMo-默认")],
            )
        ],
    )


def _client(
    tmp_path: Path, *, has_api_key: bool = True
) -> tuple[TestClient, RecordingMimoProvider]:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key" if has_api_key else ""},
    )
    return TestClient(app), provider


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
