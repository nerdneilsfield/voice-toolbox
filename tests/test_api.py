from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from voice_toolbox.models import ASRRequest, TTSRequest, VoiceInfo
from voice_toolbox.providers.fake import FakeProvider
from voice_toolbox.providers.mimo import MIMO_VOICES
from voice_toolbox.providers.registry import ProviderRegistry
from voice_toolbox_api.main import create_app


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

    def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(**voice) for voice in MIMO_VOICES]

    def synthesize(self, request: TTSRequest):
        self.tts_requests.append(request)
        if request.clone_sample_path is not None:
            self.clone_sample_paths.append(request.clone_sample_path)
            self.clone_sample_exists_during_call.append(request.clone_sample_path.exists())
        return super().synthesize(request)

    def transcribe(self, request: ASRRequest):
        self.asr_requests.append(request)
        self.asr_uploaded_bytes.append(request.audio_path.read_bytes())
        return super().transcribe(request)


def _client(tmp_path: Path, *, has_api_key: bool = False) -> tuple[TestClient, RecordingMimoProvider]:
    provider = RecordingMimoProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        has_mimo_api_key_func=lambda: has_api_key,
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


def test_mimo_voices_are_hard_coded(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/v1/providers/mimo/voices")

    assert response.status_code == 200
    voices = response.json()["voices"]
    assert {voice["id"] for voice in voices} >= {"冰糖", "Mia", "Dean"}
    assert voices[0]["id"] == "mimo_default"


def test_asr_transcribe_accepts_multipart_and_returns_operation_result(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/asr/transcribe",
        data={"language": "zh", "provider_id": "mimo"},
        files={"file": ("speech.wav", b"abcde", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"]["operation"] == "asr"
    assert payload["operation"]["status"] == "completed"
    assert payload["operation"]["artifact_ids"] == [payload["artifact"]["id"]]
    assert payload["artifact"]["kind"] == "transcript"
    assert payload["artifact"]["metadata"]["uploaded_file_mime_type"] == "audio/wav"

    request = provider.asr_requests[0]
    assert request.provider_id == "mimo"
    assert request.language == "zh"
    assert request.mime_type == "audio/wav"
    assert request.raw_byte_size == 5
    assert request.base64_size == 8
    assert provider.asr_uploaded_bytes == [b"abcde"]


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
        data={"provider_id": "mimo", "text": "clone hello", "consent_confirmed": "true"},
        files={"sample": ("sample.wav", b"voice", "audio/wav")},
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
    assert provider.tts_requests[2].clone_raw_byte_size == 5
    assert provider.tts_requests[2].clone_base64_size == 8
    assert provider.tts_requests[2].consent_confirmed is True
    assert provider.clone_sample_exists_during_call == [True]
    assert not provider.clone_sample_paths[0].exists()
    assert "data:" not in str(clone.json())
    assert "base64," not in str(clone.json())


def test_artifact_metadata_and_download_read_sidecar(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.mp3", b"abcde", "audio/mpeg")},
    ).json()
    artifact_id = created["artifact"]["id"]

    metadata = client.get(f"/v1/artifacts/{artifact_id}")
    download = client.get(f"/v1/artifacts/{artifact_id}/download")

    assert metadata.status_code == 200
    assert metadata.json()["id"] == artifact_id
    assert metadata.json()["metadata"]["operation"] == "asr"
    assert download.status_code == 200
    assert download.content == b"fake transcript"
    assert download.headers["content-type"].startswith("text/plain")


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
