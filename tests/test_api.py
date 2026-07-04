from __future__ import annotations

import json
import wave
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Event
from time import monotonic, sleep

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
    ASRChunkingConfig,
    TTSChunkingConfig,
)
from voice_toolbox.chunking.audio import ASRAudioChunk
from voice_toolbox.models import (
    ASRRequest,
    ModelInfo,
    ProviderAudioResult,
    ProviderOptionOverride,
    ProviderOptionSpec,
    TranscriptCapabilities,
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


def _wav_non_pcm() -> bytes:
    fmt = b"".join(
        [
            (3).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            (8000).to_bytes(4, "little"),
            (16000).to_bytes(4, "little"),
            (2).to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
        ]
    )
    data = b"\x00" * 16
    return (
        b"RIFF"
        + (4 + 8 + len(fmt) + 8 + len(data)).to_bytes(4, "little")
        + b"WAVE"
        + b"fmt "
        + len(fmt).to_bytes(4, "little")
        + fmt
        + b"data"
        + len(data).to_bytes(4, "little")
        + data
    )


class RecordingMimoProvider(FakeProvider):
    id = "mimo"
    name = "MiMo"

    def __init__(self, artifact_root: Path) -> None:
        super().__init__(artifact_root=artifact_root)
        self.tts_requests: list[TTSRequest] = []
        self.asr_requests: list[ASRRequest] = []
        self.asr_uploaded_bytes: list[bytes] = []
        self.asr_payloads: list[TranscriptPayload] = []
        self._inside_transcribe = False
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
        self._inside_transcribe = True
        try:
            return super().transcribe(request)
        finally:
            self._inside_transcribe = False

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        if self.asr_error is not None:
            raise self.asr_error
        if self._inside_transcribe:
            return super().transcribe_payload(request)
        self.asr_requests.append(request)
        self.asr_uploaded_bytes.append(request.audio_path.read_bytes())
        payload = (
            self.asr_payloads.pop(0)
            if self.asr_payloads
            else TranscriptPayload(text=f"chunk {len(self.asr_requests)}")
        )
        return payload


class RecordingWavProvider(RecordingMimoProvider):
    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self.tts_requests.append(request)
        return ProviderAudioResult(
            audio=_wav_silence(100),
            mime_type="audio/wav",
            suffix=".wav",
            model=request.model,
        )


class BlockingWavProvider(RecordingWavProvider):
    def __init__(self, artifact_root: Path) -> None:
        super().__init__(artifact_root)
        self.started = Event()
        self.release = Event()

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        self.started.set()
        self.release.wait(timeout=2)
        return super().synthesize_bytes(request)


class RecordingMlxAudioProvider(RecordingMimoProvider):
    id = "mlx-audio"
    name = "MLX Audio"


class ExplodingProvider(RecordingMimoProvider):
    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ):
        raise RuntimeError("raw traceback secret /Users/private/path")


class ExplodingBytesProvider(RecordingMimoProvider):
    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        raise RuntimeError("raw traceback secret /Users/private/path")


class NoCloneProvider(RecordingMimoProvider):
    def capabilities(self) -> set[str]:
        return {"tts.builtin", "asr.transcribe"}


def _test_config(
    *,
    host: str = "127.0.0.1",
    tts_chunking: TTSChunkingConfig | None = None,
    asr_chunking: ASRChunkingConfig | None = None,
    provider_options: list[ProviderOptionSpec] | None = None,
    models: list[ModelInfo] | None = None,
) -> AppConfig:
    return AppConfig(
        api=APIConfig(host=host, port=8000),
        logging=LoggingConfig(console=ConsoleLoggingConfig(enabled=False)),
        chunking=ChunkingConfig(
            tts=tts_chunking or TTSChunkingConfig(),
            asr=asr_chunking or ASRChunkingConfig(),
        ),
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


def _poll_podcast_job(client: TestClient, job_id: str) -> dict[str, object]:
    for _ in range(20):
        payload = client.get(f"/v1/podcast/jobs/{job_id}").json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        sleep(0.05)
    raise AssertionError("podcast job did not reach a terminal state")


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


def test_mlx_audio_provider_summary_does_not_require_api_key(tmp_path: Path) -> None:
    provider = RecordingMlxAudioProvider(tmp_path)
    config = AppConfig(
        config_path=None,
        providers=[
            ConfiguredProvider(
                id="mlx-audio",
                type="mlx_audio",
                name="MLX Audio",
                base_url=None,
                api_key_env=None,
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
        env_values={},
    )
    client = TestClient(app)

    summary = client.get("/v1/providers").json()["providers"][0]

    assert summary["type"] == "mlx_audio"
    assert summary["base_url"] is None
    assert summary["api_key_env"] is None
    assert summary["requires_api_key"] is False
    assert summary["has_api_key"] is False
    assert summary["api_key_preview"] is None


def test_mlx_audio_tts_route_skips_api_key_readiness(tmp_path: Path) -> None:
    provider = RecordingMlxAudioProvider(tmp_path)
    config = AppConfig(
        config_path=None,
        providers=[
            ConfiguredProvider(
                id="mlx-audio",
                type="mlx_audio",
                name="MLX Audio",
                base_url=None,
                api_key_env=None,
                default_voice="Mia",
                default_models=ProviderDefaultModels(tts_builtin="fake-tts", asr="fake-asr"),
                models=[
                    ModelInfo(
                        id="fake-tts",
                        name="Fake TTS",
                        capability="tts.builtin",
                        voices=[VoiceInfo(id="Mia", name="Mia")],
                    ),
                    ModelInfo(id="fake-asr", name="Fake ASR", capability="asr.transcribe"),
                ],
                voices=[],
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
        env_values={},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mlx-audio",
            "text": "hello",
            "voice_id": "Mia",
        },
    )

    assert response.status_code == 200


def test_mlx_audio_builtin_route_allows_model_without_voice(tmp_path: Path) -> None:
    provider = RecordingMlxAudioProvider(tmp_path)
    config = AppConfig(
        config_path=None,
        providers=[
            ConfiguredProvider(
                id="mlx-audio",
                type="mlx_audio",
                name="MLX Audio",
                base_url=None,
                api_key_env=None,
                default_models=ProviderDefaultModels(tts_builtin="fake-tts"),
                models=[
                    ModelInfo(
                        id="fake-tts",
                        name="Fake TTS",
                        capability="tts.builtin",
                    ),
                ],
                voices=[],
            )
        ],
    )
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=config,
        env_values={},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/tts/builtin",
        data={
            "provider_id": "mlx-audio",
            "text": "hello",
            "model": "fake-tts",
        },
    )

    assert response.status_code == 200
    assert provider.tts_requests[0].voice_id is None


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


def test_asr_upload_uses_temp_path_even_when_chunking_off(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    monkeypatch.setattr(
        api_main,
        "_read_upload",
        lambda upload: (_ for _ in ()).throw(AssertionError("_read_upload used")),
    )

    response = client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "chunking_mode": "off"},
        files={"file": ("private-name.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert provider.asr_requests[0].audio_path.name.startswith("provider")
    assert "private-name" not in provider.asr_requests[0].audio_path.name


def test_asr_upload_above_configured_limit_returns_413(tmp_path: Path) -> None:
    config = _test_config(asr_chunking=ASRChunkingConfig(max_upload_mb=1))
    client, provider = _client(tmp_path, config=config)

    response = client.post(
        "/v1/asr/transcribe",
        files={"file": ("speech.wav", b"RIFF0000WAVE" + b"x" * (1024 * 1024), "audio/wav")},
    )

    assert response.status_code == 413
    assert provider.asr_requests == []


def test_asr_whole_file_path_when_converted_payload_fits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    monkeypatch.setattr(
        api_main,
        "plan_asr_audio_chunks",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chunked")),
    )

    response = client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "chunking_mode": "auto"},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert len(provider.asr_requests) == 1
    assert "chunking_enabled" not in response.json()["artifact"]["metadata"]


def test_asr_auto_chunks_when_provider_payload_exceeds_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _test_config(
        asr_chunking=ASRChunkingConfig(
            target_seconds=10,
            overlap_ms=100,
            max_chunks=10,
            dedupe_min_chars=3,
        )
    )
    client, provider = _client(tmp_path, config=config)
    provider.asr_payloads = [
        TranscriptPayload(text="hello overlap"),
        TranscriptPayload(text="overlap world"),
    ]

    def fake_convert_upload_for_provider(*args, **kwargs):
        raise api_main.HTTPException(status_code=413, detail="too large")

    monkeypatch.setattr(api_main, "_convert_upload_for_provider", fake_convert_upload_for_provider)

    response = client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "chunking_mode": "auto"},
        files={"file": ("speech.wav", _wav_silence(18000), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert len(provider.asr_requests) == 2
    artifact = response.json()["artifact"]
    assert artifact["metadata"]["chunking_enabled"] is True
    assert artifact["metadata"]["chunking_chunk_count"] == 2
    assert artifact["metadata"]["chunking_dedupe_removed_chars"] == len("overlap")
    listed = client.get("/v1/artifacts").json()["artifacts"]
    assert [item["id"] for item in listed] == [artifact["id"]]
    transcript = client.get(f"/v1/artifacts/{artifact['id']}/transcript?format=json").json()
    assert transcript["text"] == "hello overlap world"


def test_asr_auto_chunks_valid_large_container_audio_before_provider_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    chunk_path = tmp_path / "chunk.wav"
    chunk_path.write_bytes(WAV_BYTES)

    def fake_plan_asr_audio_chunks(source_path: Path, **kwargs: object) -> list[ASRAudioChunk]:
        assert source_path.stat().st_size > (MAX_BASE64_AUDIO_SIZE // 4) * 3
        return [
            ASRAudioChunk(
                path=chunk_path,
                start_ms=0,
                end_ms=1000,
                raw_byte_size=len(WAV_BYTES),
                base64_size=api_main._base64_size(WAV_BYTES),
                mime_type="audio/wav",
                suffix=".wav",
            )
        ]

    monkeypatch.setattr(api_main, "plan_asr_audio_chunks", fake_plan_asr_audio_chunks)

    large_m4a = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * ((MAX_BASE64_AUDIO_SIZE // 4) * 3 + 1)
    response = client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "chunking_mode": "auto"},
        files={"file": ("speech.m4a", large_m4a, "audio/mp4")},
    )

    assert response.status_code == 200, response.text
    assert len(provider.asr_requests) == 1
    assert provider.asr_requests[0].audio_path == chunk_path
    assert response.json()["artifact"]["metadata"]["chunking_enabled"] is True


def test_asr_auto_chunk_rejects_corrupt_large_container_as_bad_input(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    large_m4a = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * ((MAX_BASE64_AUDIO_SIZE // 4) * 3 + 1)

    response = client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "chunking_mode": "auto"},
        files={"file": ("speech.m4a", large_m4a, "audio/mp4")},
    )

    assert response.status_code == 422
    assert provider.asr_requests == []


def test_asr_force_chunks_and_copies_options_to_each_chunk(tmp_path: Path) -> None:
    config = _test_config(
        asr_chunking=ASRChunkingConfig(target_seconds=10, overlap_ms=0, max_chunks=10),
        provider_options=[
            ProviderOptionSpec(
                key="hint",
                label="Hint",
                type="string",
                capability="asr.transcribe",
                safe_metadata=False,
            )
        ],
    )
    client, provider = _client(tmp_path, config=config)

    response = client.post(
        "/v1/asr/transcribe",
        data={
            "provider_id": "mimo",
            "chunking_mode": "force",
            "provider_options": json.dumps({"hint": "secret"}),
        },
        files={"file": ("speech.wav", _wav_silence(21000), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert len(provider.asr_requests) == 3
    assert {request.provider_options["hint"] for request in provider.asr_requests} == {"secret"}
    metadata = response.json()["artifact"]["metadata"]
    assert metadata["provider_option_keys"] == ["hint"]
    assert "secret" not in json.dumps(metadata)


def test_asr_richness_flags_are_validated_and_passed_to_chunks(tmp_path: Path) -> None:
    supported = _test_config(
        asr_chunking=ASRChunkingConfig(target_seconds=10, overlap_ms=0, max_chunks=10),
        models=[
            ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
            ModelInfo(
                id="fake-asr",
                name="Fake ASR",
                capability="asr.transcribe",
                transcript_capabilities=TranscriptCapabilities(
                    timestamps=True,
                    speakers=True,
                    segments=True,
                ),
            ),
        ],
    )
    client, provider = _client(tmp_path, config=supported)
    provider.asr_payloads = [
        TranscriptPayload(
            text="hello",
            segments=[
                TranscriptSegment(text="hello", start_seconds=0, end_seconds=0.25, speaker="A")
            ],
        ),
        TranscriptPayload(
            text="world",
            segments=[
                TranscriptSegment(text="world", start_seconds=0, end_seconds=0.25, speaker="B")
            ],
        ),
    ]

    response = client.post(
        "/v1/asr/transcribe",
        data={
            "provider_id": "mimo",
            "chunking_mode": "force",
            "chunk_seconds": "10",
            "chunk_overlap_ms": "0",
            "transcript_timestamps": "true",
            "transcript_speakers": "true",
        },
        files={"file": ("speech.wav", _wav_silence(12000), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert all(request.transcript_timestamps for request in provider.asr_requests)
    assert all(request.transcript_speakers for request in provider.asr_requests)
    artifact = response.json()["artifact"]
    assert artifact["metadata"]["transcript_has_timestamps"] is True
    assert artifact["metadata"]["transcript_has_speakers"] is True
    rendered = client.get(f"/v1/artifacts/{artifact['id']}/transcript?format=json").json()
    assert rendered["segments"][1]["start_seconds"] == 10

    unsupported_client, unsupported_provider = _client(tmp_path / "unsupported")
    rejected = unsupported_client.post(
        "/v1/asr/transcribe",
        data={"provider_id": "mimo", "transcript_timestamps": "true"},
        files={"file": ("speech.wav", WAV_BYTES, "audio/wav")},
    )
    assert rejected.status_code == 422
    assert unsupported_provider.asr_requests == []


def test_asr_chunk_session_create_contract_and_validation(tmp_path: Path) -> None:
    config = _test_config(
        asr_chunking=ASRChunkingConfig(max_chunks=2),
        provider_options=[
            ProviderOptionSpec(
                key="hint",
                label="Hint",
                type="string",
                capability="asr.transcribe",
            )
        ],
        models=[
            ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
            ModelInfo(
                id="fake-asr",
                name="Fake ASR",
                capability="asr.transcribe",
                transcript_capabilities=TranscriptCapabilities(timestamps=True),
            ),
        ],
    )
    client, _ = _client(tmp_path, config=config)

    missing_duration = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1"},
    )
    too_many = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "3", "source_duration_ms": "1000"},
    )
    created = client.post(
        "/v1/asr/chunk-sessions",
        data={
            "provider_id": "mimo",
            "model": "fake-asr",
            "language": "zh",
            "total_chunks": "2",
            "source_duration_ms": "2000",
            "source_file_name": "speech.wav",
            "transcript_timestamps": "true",
            "provider_options": json.dumps({"hint": "secret"}),
        },
    )
    malicious_name = client.post(
        "/v1/asr/chunk-sessions",
        data={
            "provider_id": "mimo",
            "total_chunks": "1",
            "source_duration_ms": "1000",
            "source_file_name": "../../private/speech.wav",
        },
    )

    assert missing_duration.status_code == 422
    assert too_many.status_code == 422
    assert malicious_name.status_code == 422
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["session_id"]
    assert payload["browser_slice_formats"] == ["wav"]
    assert "wav" in payload["backend_accept_formats"]
    assert "pcm" not in payload["backend_accept_formats"]
    assert payload["max_chunks"] == 2
    store = client.app.state.asr_chunk_sessions
    metadata = store.load(payload["session_id"])
    assert metadata.provider_id == "mimo"
    assert metadata.model == "fake-asr"
    assert metadata.language == "zh"
    assert metadata.transcript_timestamps is True
    assert metadata.provider_options == {"hint": "secret"}
    assert metadata.source_file_suffix == ".wav"
    raw_metadata = store.metadata_path(payload["session_id"]).read_text(encoding="utf-8")
    assert "private" not in raw_metadata
    assert "speech.wav" not in raw_metadata
    assert "secret" not in raw_metadata
    assert '"provider_options":' not in raw_metadata

    disabled_client, _ = _client(
        tmp_path / "disabled",
        config=_test_config(asr_chunking=ASRChunkingConfig(browser_upload=False)),
    )
    disabled = disabled_client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    assert disabled.status_code == 422
    assert disabled.json()["detail"] == "browser ASR chunk upload is disabled"


def test_asr_chunk_session_upload_validation_and_quota(tmp_path: Path) -> None:
    client, provider = _client(
        tmp_path,
        config=_test_config(asr_chunking=ASRChunkingConfig(max_upload_mb=1)),
    )
    created = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "2", "source_duration_ms": "2000"},
    )
    session_id = created.json()["session_id"]

    invalid_signature = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", b"not wav", "audio/wav")},
    )
    bad_index = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "2", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
    )
    non_pcm = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_non_pcm(), "audio/wav")},
    )
    bad_offset = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "-1", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
    )
    first = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
    )
    duplicate = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
    )
    non_monotonic = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/chunks",
        data={"chunk_index": "1", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
    )

    assert invalid_signature.status_code == 422
    assert non_pcm.status_code == 422
    assert "PCM WAV" in non_pcm.text
    assert bad_index.status_code == 422
    assert bad_offset.status_code == 422
    assert first.status_code == 200, first.text
    assert first.json() == {"session_id": session_id, "received_chunks": 1, "total_chunks": 2}
    assert duplicate.status_code == 409
    assert non_monotonic.status_code == 422
    assert provider.asr_requests == []

    duration_session = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    duration_id = duration_session.json()["session_id"]
    wrong_duration = client.post(
        f"/v1/asr/chunk-sessions/{duration_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "2000"},
        files={"file": ("chunk.wav", _wav_silence(100), "audio/wav")},
    )
    assert wrong_duration.status_code == 422
    assert "duration" in wrong_duration.text

    quota = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    quota_id = quota.json()["session_id"]
    too_large = client.post(
        f"/v1/asr/chunk-sessions/{quota_id}/chunks",
        data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"},
        files={"file": ("chunk.wav", b"RIFF0000WAVE" + (b"x" * (1024 * 1024)), "audio/wav")},
    )
    assert too_large.status_code == 413


def test_asr_chunk_session_finish_mismatch_coverage_and_success(tmp_path: Path) -> None:
    config = _test_config(
        asr_chunking=ASRChunkingConfig(max_upload_mb=2),
        provider_options=[
            ProviderOptionSpec(
                key="hint",
                label="Hint",
                type="string",
                capability="asr.transcribe",
                safe_metadata=False,
            )
        ],
    )
    client, provider = _client(tmp_path, config=config)
    created = client.post(
        "/v1/asr/chunk-sessions",
        data={
            "provider_id": "mimo",
            "total_chunks": "2",
            "source_duration_ms": "2000",
            "provider_options": json.dumps({"hint": "secret"}),
        },
    )
    session_id = created.json()["session_id"]
    missing = client.post(f"/v1/asr/chunk-sessions/{session_id}/finish")
    assert missing.status_code == 422

    for index, offset in enumerate([0, 1000]):
        uploaded = client.post(
            f"/v1/asr/chunk-sessions/{session_id}/chunks",
            data={"chunk_index": str(index), "offset_ms": str(offset), "duration_ms": "1000"},
            files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
        )
        assert uploaded.status_code == 200, uploaded.text

    mismatch = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/finish",
        data={"provider_options": json.dumps({"hint": "other"})},
    )
    assert mismatch.status_code == 409
    assert provider.asr_requests == []

    client.app.state.asr_chunk_sessions._provider_options_by_session.clear()
    missing_options_after_restart = client.post(f"/v1/asr/chunk-sessions/{session_id}/finish")
    assert missing_options_after_restart.status_code == 409
    assert "provider_options" in missing_options_after_restart.text

    provider.asr_error = ProviderError("temporary upstream failure")
    failed = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/finish",
        data={"provider_options": json.dumps({"hint": "secret"})},
    )
    assert failed.status_code == 502
    assert client.app.state.asr_chunk_sessions.session_dir(session_id).exists()
    provider.asr_error = None

    provider.asr_payloads = [TranscriptPayload(text="hello "), TranscriptPayload(text="world")]
    finished = client.post(
        f"/v1/asr/chunk-sessions/{session_id}/finish",
        data={"provider_options": json.dumps({"hint": "secret"})},
    )
    assert finished.status_code == 200, finished.text
    repeated = client.post(f"/v1/asr/chunk-sessions/{session_id}/finish")
    assert repeated.status_code == 404
    assert len(provider.asr_requests) == 2
    assert {request.provider_options["hint"] for request in provider.asr_requests} == {"secret"}
    artifact = finished.json()["artifact"]
    assert artifact["metadata"]["chunking_strategy"] == "browser_upload"
    assert artifact["metadata"]["chunking_chunk_count"] == 2
    assert "secret" not in json.dumps(artifact["metadata"])
    transcript = client.get(f"/v1/artifacts/{artifact['id']}/transcript?format=json").json()
    assert transcript["text"] == "hello\nworld"

    gap = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "2", "source_duration_ms": "3600"},
    )
    gap_id = gap.json()["session_id"]
    for index, offset in enumerate([0, 2600]):
        client.post(
            f"/v1/asr/chunk-sessions/{gap_id}/chunks",
            data={"chunk_index": str(index), "offset_ms": str(offset), "duration_ms": "1000"},
            files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")},
        )
    coverage = client.post(f"/v1/asr/chunk-sessions/{gap_id}/finish")
    assert coverage.status_code == 422


def test_asr_chunk_session_delete_and_expiry_cleanup(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    session_id = created.json()["session_id"]
    store = client.app.state.asr_chunk_sessions
    assert store.session_dir(session_id).exists()
    deleted = client.delete(f"/v1/asr/chunk-sessions/{session_id}")
    assert deleted.status_code == 200
    assert not store.session_dir(session_id).exists()

    expired = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    expired_id = expired.json()["session_id"]
    metadata_path = store.metadata_path(expired_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    create_cleanup = client.post(
        "/v1/asr/chunk-sessions",
        data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
    )
    assert create_cleanup.status_code == 200
    assert not store.session_dir(expired_id).exists()

    def create_expired_session() -> str:
        response = client.post(
            "/v1/asr/chunk-sessions",
            data={"provider_id": "mimo", "total_chunks": "1", "source_duration_ms": "1000"},
        )
        created_id = response.json()["session_id"]
        created_metadata_path = store.metadata_path(created_id)
        created_metadata = json.loads(created_metadata_path.read_text(encoding="utf-8"))
        created_metadata["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        created_metadata_path.write_text(json.dumps(created_metadata), encoding="utf-8")
        return created_id

    for method, url in (
        ("post", f"/v1/asr/chunk-sessions/{create_expired_session()}/chunks"),
        ("post", f"/v1/asr/chunk-sessions/{create_expired_session()}/finish"),
        ("delete", f"/v1/asr/chunk-sessions/{create_expired_session()}"),
    ):
        expired_route_id = url.split("/")[4]
        if method == "delete":
            response = client.delete(url)
        else:
            response = client.post(
                url,
                data={"chunk_index": "0", "offset_ms": "0", "duration_ms": "1000"}
                if url.endswith("/chunks")
                else {},
                files={"file": ("chunk.wav", _wav_silence(1000), "audio/wav")}
                if url.endswith("/chunks")
                else None,
            )
        assert response.status_code == 404
        assert not store.session_dir(expired_route_id).exists()


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
    # File sources now get the same history preview as inline text — the
    # resolved (normalized) text is available at this point, so an 80-char
    # preview is safe and is what the history list shows.
    assert metadata["source_text_preview"].startswith("Title")


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
                    ProviderOptionOverride(
                        key="speed",
                        capability="tts.builtin",
                        max_value=1.5,
                    )
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
    assert (
        txt.text == "[00:00:00.000 - 00:00:01.250] A: hello\n[00:00:01.250 - 00:00:02.500] B: world"
    )
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
    (op_dir / "test2.txt").write_text("hello\ntranscript world", encoding="utf-8")

    response = client.get("/v1/artifacts?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["artifacts"]) == 2
    assert data["artifacts"][0]["id"] == "test-artifact-2"  # newest first
    assert data["artifacts"][0]["preview"] == "hello transcript world"
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


def test_podcast_job_generates_audio_and_manifest(tmp_path: Path) -> None:
    provider = RecordingWavProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "model": "fake-tts",
            "script": "Alice: Hello [pause:25]\nBob: Hi",
            "script_format": "speaker_colon",
            "default_pause_ms": "40",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] in {"queued", "running", "completed"}
    job = _poll_podcast_job(client, payload["job_id"])
    assert job["status"] == "completed"
    assert job["artifact"]["operation"] == "podcast"  # type: ignore[index]
    assert job["artifact"]["metadata"]["podcast_segment_count"] == 2  # type: ignore[index]
    assert len(job["recent_segment_durations_ms"]) == 2
    assert all(isinstance(duration, int) for duration in job["recent_segment_durations_ms"])
    assert [request.voice_id for request in provider.tts_requests] == ["Mia", "Dean"]

    artifact_id = job["artifact"]["id"]  # type: ignore[index]
    sidecar = next((tmp_path / "data" / "artifacts").glob(f"*/{artifact_id}.podcast.json"))
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    assert manifest["segments"][0]["speaker_name"] == "Alice"
    assert manifest["segments"][0]["pause_after_ms"] == 25
    assert manifest["segments"][1]["pause_after_ms"] == 0


def test_podcast_job_returns_before_generation_finishes(tmp_path: Path) -> None:
    provider = BlockingWavProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    with TestClient(app) as client:
        start = monotonic()
        created = client.post(
            "/v1/podcast/jobs",
            data={
                "provider_id": "mimo",
                "model": "fake-tts",
                "script": "Alice: Hello",
                "speaker_voices": json.dumps({"alice": "Mia"}),
            },
        )
        elapsed = monotonic() - start
        assert created.status_code == 200
        assert elapsed < 1
        payload = created.json()
        assert payload["status"] in {"queued", "running"}
        assert payload["artifact"] is None
        assert provider.started.wait(timeout=1)
        provider.release.set()
        job = _poll_podcast_job(client, payload["job_id"])

    assert job["status"] == "completed"


def test_podcast_job_manifest_records_decoded_timing(tmp_path: Path) -> None:
    provider = RecordingWavProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "model": "fake-tts",
            "script": "Alice: Hello [pause:25]\nBob: Hi",
            "script_format": "speaker_colon",
            "default_pause_ms": "40",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )
    job = _poll_podcast_job(client, created.json()["job_id"])

    artifact_id = job["artifact"]["id"]  # type: ignore[index]
    sidecar = next((tmp_path / "data" / "artifacts").glob(f"*/{artifact_id}.podcast.json"))
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    assert manifest["segments"][0]["start_ms"] == 0
    assert manifest["segments"][0]["audio_duration_ms"] > 0
    assert manifest["segments"][1]["start_ms"] == (
        manifest["segments"][0]["end_ms"] + manifest["segments"][0]["pause_after_ms"]
    )


def test_podcast_job_rejects_missing_voice_mapping(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello\nBob: Hi",
            "speaker_voices": json.dumps({"alice": "Mia"}),
        },
    )

    assert response.status_code == 422
    assert "Bob" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_rejects_unknown_voice_mapping(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )

    assert response.status_code == 422
    assert "unknown speaker" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_rejects_unknown_voice_id(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello",
            "speaker_voices": json.dumps({"alice": "not-a-real-voice"}),
        },
    )

    assert response.status_code == 422
    assert "unknown voice_id" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_rejects_provider_voice_when_model_has_scoped_voices(
    tmp_path: Path,
) -> None:
    class ModelScopedVoiceProvider(RecordingMimoProvider):
        def list_models(self) -> list[ModelInfo]:
            return [
                ModelInfo(
                    id="fake-tts",
                    name="Fake TTS",
                    capability="tts.builtin",
                    voices=[VoiceInfo(id="model_voice", name="Model Voice")],
                )
            ]

    provider = ModelScopedVoiceProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "model": "fake-tts",
            "script": "Alice: Hello",
            "speaker_voices": json.dumps({"alice": "Mia"}),
        },
    )

    assert response.status_code == 422
    assert "unknown voice_id" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_rejects_large_pause(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello [pause:60001]\nBob: Hi",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )

    assert response.status_code == 422
    assert "pause" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_rejects_oversized_script(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)

    response = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "A: " + ("x" * 200_001),
            "speaker_voices": json.dumps({"a": "Mia"}),
        },
    )

    assert response.status_code == 413
    assert "script exceeds" in response.json()["detail"]
    assert provider.tts_requests == []


def test_podcast_job_records_provider_failure(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)
    provider.tts_error_after_calls = 2

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello\nBob: Hi",
            "speaker_voices": json.dumps({"alice": "Mia", "bob": "Dean"}),
        },
    )
    job = _poll_podcast_job(client, created.json()["job_id"])

    assert job["status"] == "failed"
    assert job["failed_segment"]["index"] == 1  # type: ignore[index]
    assert "chunk failed" in str(job["error_summary"])


def test_podcast_job_hides_unexpected_error_details(tmp_path: Path) -> None:
    provider = ExplodingBytesProvider(tmp_path)
    app = create_app(
        registry=ProviderRegistry([provider]),
        artifact_root=tmp_path,
        config=_test_config(),
        env_values={"MIMO_API_KEY": "test-key"},
    )
    client = TestClient(app)

    created = client.post(
        "/v1/podcast/jobs",
        data={
            "provider_id": "mimo",
            "script": "Alice: Hello",
            "speaker_voices": json.dumps({"alice": "Mia"}),
        },
    )
    job = _poll_podcast_job(client, created.json()["job_id"])

    assert job["status"] == "failed"
    assert job["error_summary"] == "podcast generation failed"
    assert "secret" not in json.dumps(job)
