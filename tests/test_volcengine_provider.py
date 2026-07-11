import base64
from pathlib import Path
from typing import Any, Mapping

import pytest

from voice_toolbox.config import AppConfig
from voice_toolbox.defaults import VOLCENGINE_VOICES, make_default_volcengine_provider_config
from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.factory import build_provider_registry
from voice_toolbox.providers.volcengine import VolcengineProvider


class FakeTTSClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize(self, body: Mapping[str, object], *, timeout: float):
        self.calls.append({"body": body, "timeout": timeout})
        yield {"code": 0, "data": base64.b64encode(b"MP3-A").decode()}
        yield {"code": 20000000, "data": base64.b64encode(b"MP3-B").decode()}


class FakeASRClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: bytes, *, options: Mapping[str, object], timeout: float):
        self.calls.append({"audio": audio, "options": dict(options), "timeout": timeout})
        return [
            {
                "result": {
                    "text": "你好世界",
                    "utterances": [
                        {"text": "你好", "start_time": 0, "end_time": 500},
                        {"text": "世界", "start_time": 500, "end_time": 1000},
                    ],
                },
                "_last": True,
            }
        ]


def test_volcengine_tts_uses_http_shape_and_collects_chunks(tmp_path: Path) -> None:
    client = FakeTTSClient()
    provider = VolcengineProvider(
        api_key="secret", artifact_root=tmp_path, tts_client=client, asr_client=FakeASRClient()
    )

    result = provider.synthesize_bytes(
        TTSRequest(
            provider_id="volcengine",
            mode=TTSMode.BUILTIN,
            text="你好",
            voice_id="zh_female_vv_uranus_bigtts",
            output_format="mp3",
        )
    )

    assert result.audio == b"MP3-AMP3-B"
    assert result.model == "seed-tts-2.0"
    assert client.calls[0]["body"] == {
        "req_params": {
            "text": "你好",
            "speaker": "zh_female_vv_uranus_bigtts",
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        }
    }


def test_volcengine_asr_extracts_timestamped_utterances(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")
    client = FakeASRClient()
    provider = VolcengineProvider(
        api_key="secret", artifact_root=tmp_path, tts_client=FakeTTSClient(), asr_client=client
    )

    payload = provider.transcribe_payload(
        ASRRequest(
            provider_id="volcengine",
            audio_path=audio,
            mime_type="audio/wav",
            raw_byte_size=16,
            base64_size=24,
        )
    )

    assert payload.text == "你好世界"
    assert payload.segments[1].start_seconds == 0.5
    assert client.calls[0]["options"]["model_name"] == "bigmodel"


def test_volcengine_rejects_resource_id_override(tmp_path: Path) -> None:
    provider = VolcengineProvider(
        api_key="secret",
        artifact_root=tmp_path,
        tts_client=FakeTTSClient(),
        asr_client=FakeASRClient(),
    )

    with pytest.raises(ProviderError, match="unsupported Volcengine model"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="volcengine",
                mode=TTSMode.BUILTIN,
                model="auto",
                text="你好",
                voice_id="zh_female_vv_uranus_bigtts",
            )
        )


def test_factory_builds_volcengine_provider(tmp_path: Path) -> None:
    registry = build_provider_registry(
        AppConfig(config_path=None, providers=[make_default_volcengine_provider_config()]),
        artifact_root=tmp_path,
        env_values={"VOLCENGINE_SPEECH_API_KEY": "secret"},
    )

    assert isinstance(registry.get("volcengine"), VolcengineProvider)


def test_volcengine_uranus_voice_catalog_is_unique() -> None:
    voice_ids = [voice.id for voice in VOLCENGINE_VOICES]

    assert len(voice_ids) == 93
    assert len(voice_ids) == len(set(voice_ids))
    assert voice_ids[0] == "zh_female_vv_uranus_bigtts"
    assert "en_male_tim_uranus_bigtts" in voice_ids
    assert "zh_female_shaoergushi_uranus_bigtts" in voice_ids
