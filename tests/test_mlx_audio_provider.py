from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, cast

import pytest

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ASRRequest, ModelInfo, TTSMode, TTSRequest, VoiceInfo
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability
from voice_toolbox.providers.mlx_audio import MlxAudioProvider, _dependency_error


def _config() -> ConfiguredProvider:
    return ConfiguredProvider(
        id="mlx-audio",
        type="mlx_audio",
        name="MLX Audio",
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=ProviderDefaultModels(
            tts_builtin="qwen3-tts-0.6b-base",
            tts_clone="qwen3-tts-0.6b-base-clone",
            asr="mlx-community/Qwen3-ASR-0.6B-8bit",
        ),
        models=[
            ModelInfo(id="qwen3-tts-0.6b-base", name="Qwen3 TTS", capability="tts.builtin"),
            ModelInfo(
                id="qwen3-tts-0.6b-base-clone",
                name="Qwen3 TTS Clone",
                capability="tts.clone",
            ),
            ModelInfo(
                id="ming-omni-tts-16.8b-a3b",
                name="Ming Omni TTS",
                capability="tts.builtin",
            ),
            ModelInfo(
                id="mlx-community/Qwen3-ASR-0.6B-8bit",
                name="Qwen3 ASR",
                capability="asr.transcribe",
            ),
        ],
        voices=[VoiceInfo(id="Ryan", name="Ryan")],
    )


class FakeTTSModel:
    sample_rate = 24000

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object):
        self.calls.append(kwargs)
        yield SimpleNamespace(audio=[0.0, 0.25], sample_rate=24000)
        yield SimpleNamespace(audio=[-0.25], sample_rate=24000)


class FakeASRModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, audio: str, **kwargs: object) -> object:
        self.calls.append({"audio": audio, **kwargs})
        return SimpleNamespace(
            text="hello world",
            segments=[{"text": "hello world", "start": 0.0, "end": 1.2}],
        )


def _writer(audio: object, sample_rate: int) -> bytes:
    return f"WAV:{sample_rate}:{list(cast(Iterable[object], audio))}".encode()


def _provider(
    tmp_path: Path,
    *,
    config: ConfiguredProvider | None = None,
    tts_model: FakeTTSModel | None = None,
    asr_model: FakeASRModel | None = None,
):
    tts = tts_model or FakeTTSModel()
    asr = asr_model or FakeASRModel()
    tts_calls: list[dict[str, object]] = []
    asr_calls: list[dict[str, object]] = []

    def tts_loader(model_id: str, **kwargs: object) -> FakeTTSModel:
        tts_calls.append({"model_id": model_id, **kwargs})
        return tts

    def asr_loader(model_id: str, **kwargs: object) -> FakeASRModel:
        asr_calls.append({"model_id": model_id, **kwargs})
        return asr

    provider = MlxAudioProvider(
        config=config or _config(),
        artifact_root=tmp_path,
        tts_loader=tts_loader,
        stt_loader=asr_loader,
        wav_writer=_writer,
        platform_check=lambda: None,
    )
    return provider, tts, asr, tts_calls, asr_calls


def test_tts_builtin_uses_alias_and_generation_kwargs(tmp_path: Path) -> None:
    provider, model, _, tts_calls, _ = _provider(tmp_path)

    result = provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            text="hello",
            voice_id="Ryan",
            provider_options={"lang_code": "English", "temperature": 0.1},
        )
    )

    assert result.audio == b"WAV:24000:[0.0, 0.25, -0.25]"
    assert result.model == "qwen3-tts-0.6b-base"
    assert tts_calls[0]["model_id"] == "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
    assert model.calls[0]["text"] == "hello"
    assert model.calls[0]["voice"] == "Ryan"
    assert model.calls[0]["lang_code"] == "English"
    assert model.calls[0]["temperature"] == 0.1


def test_tts_provider_options_cannot_override_core_kwargs(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)

    with pytest.raises(ProviderError, match="provider option text collides"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.BUILTIN,
                text="hello",
                voice_id="Ryan",
                provider_options={"text": "override"},
            )
        )


def test_tts_design_is_unsupported(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)

    with pytest.raises(UnsupportedCapability, match="design"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.DESIGN,
                text="hello",
                voice_description="warm narrator",
            )
        )


def test_tts_clone_requires_reference_text(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="clone_reference_text"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.CLONE,
                text="hello",
                clone_sample_path=sample,
                clone_mime_type="audio/wav",
                consent_confirmed=True,
            )
        )


def test_tts_clone_passes_reference_audio_and_text(tmp_path: Path) -> None:
    provider, model, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.CLONE,
            text="hello",
            clone_sample_path=sample,
            clone_mime_type="audio/wav",
            clone_reference_text="reference words",
            consent_confirmed=True,
        )
    )

    assert model.calls[0]["ref_audio"] == str(sample)
    assert model.calls[0]["ref_text"] == "reference words"


def test_tts_artifact_metadata_keeps_trusted_values_and_no_raw_clone_text(
    tmp_path: Path,
) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF0000WAVEfmt ")

    artifact = provider.synthesize(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.CLONE,
            text="hello",
            clone_sample_path=sample,
            clone_mime_type="audio/wav",
            clone_raw_byte_size=16,
            clone_base64_size=24,
            clone_reference_text="reference words",
            consent_confirmed=True,
        ),
        artifact_metadata={"provider_id": "spoofed", "source_text_length": 999},
    )

    assert artifact.metadata["provider_id"] == "mlx-audio"
    assert artifact.metadata["source_text_length"] == 5
    assert artifact.metadata["clone_reference_text_length"] == len("reference words")
    assert artifact.metadata["raw_byte_size"] == 16
    assert artifact.metadata["base64_size"] == 24
    assert artifact.metadata["uploaded_file_mime_type"] == "audio/wav"
    assert artifact.metadata["uploaded_file_suffix"] == ".wav"
    assert isinstance(artifact.metadata["uploaded_file_name_hash"], str)
    assert "clone_reference_text" not in artifact.metadata


def test_ming_loader_includes_onnx_allow_pattern(tmp_path: Path) -> None:
    provider, _, _, tts_calls, _ = _provider(tmp_path)

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            model="ming-omni-tts-16.8b-a3b",
            text="hello",
            voice_id="Ryan",
        )
    )

    assert tts_calls[0]["model_id"] == "mlx-community/Ming-omni-tts-16.8B-A3B-bf16"
    assert "*.onnx" in tts_calls[0]["allow_patterns"]
    for pattern in ("*.json", "*.model", "*.tiktoken", "*.npz", "*.pth"):
        assert pattern in tts_calls[0]["allow_patterns"]


def test_bailingmm_upstream_model_includes_onnx_allow_pattern(tmp_path: Path) -> None:
    config = _config()
    config = config.model_copy(
        update={
            "models": [
                *config.models,
                ModelInfo(
                    id="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
                    name="Custom BailingMM",
                    capability="tts.builtin",
                ),
            ]
        }
    )
    provider, _, _, tts_calls, _ = _provider(tmp_path, config=config)

    provider.synthesize_bytes(
        TTSRequest(
            provider_id="mlx-audio",
            mode=TTSMode.BUILTIN,
            model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
            text="hello",
            voice_id="Ryan",
        )
    )

    assert "*.onnx" in tts_calls[0]["allow_patterns"]


def test_asr_maps_language_and_segments(tmp_path: Path) -> None:
    provider, _, asr, _, asr_calls = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    payload = provider.transcribe_payload(
        ASRRequest(
            provider_id="mlx-audio",
            audio_path=audio,
            mime_type="audio/wav",
            raw_byte_size=16,
            base64_size=24,
            language="zh",
        )
    )

    assert asr_calls == [{"model_id": "mlx-community/Qwen3-ASR-0.6B-8bit"}]
    assert asr.calls[0]["audio"] == str(audio)
    assert asr.calls[0]["language"] == "Chinese"
    assert payload.text == "hello world"
    assert payload.segments[0].start_seconds == 0.0
    assert payload.segments[0].end_seconds == 1.2


def test_asr_artifact_metadata_keeps_trusted_values(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    artifact = provider.transcribe(
        ASRRequest(
            provider_id="mlx-audio",
            audio_path=audio,
            mime_type="audio/wav",
            raw_byte_size=16,
            base64_size=24,
            artifact_metadata={"base64_size": 999, "provider_id": "spoofed"},
        )
    )

    assert artifact.metadata["base64_size"] == 24
    assert artifact.metadata["provider_id"] == "mlx-audio"
    assert artifact.metadata["raw_byte_size"] == 16


def test_asr_provider_options_cannot_override_core_audio_arg(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="provider option audio collides"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
                provider_options={"audio": "override"},
            )
        )

    with pytest.raises(ProviderError, match="provider option language collides"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
                provider_options={"language": "Japanese"},
            )
        )


def test_unknown_asr_model_is_rejected_before_loader(tmp_path: Path) -> None:
    provider, _, _, _, asr_calls = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(ProviderError, match="unsupported MLX Audio model"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                model="attacker/custom-asr",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
            )
        )

    assert asr_calls == []


def test_forced_aligner_model_is_not_asr_transcribe(tmp_path: Path) -> None:
    provider, _, _, _, _ = _provider(tmp_path)
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")

    with pytest.raises(UnsupportedCapability, match="forced alignment"):
        provider.transcribe_payload(
            ASRRequest(
                provider_id="mlx-audio",
                model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
                audio_path=audio,
                mime_type="audio/wav",
                raw_byte_size=16,
                base64_size=24,
            )
        )


def test_missing_dependency_error_has_install_hint(tmp_path: Path) -> None:
    def broken_loader(model_id: str, **kwargs: object) -> object:
        raise ImportError("Japanese tokenization requires nagisa. Install with: pip install nagisa")

    provider = MlxAudioProvider(
        config=_config(),
        artifact_root=tmp_path,
        tts_loader=broken_loader,
        stt_loader=lambda model_id, **kwargs: FakeASRModel(),
        wav_writer=_writer,
        platform_check=lambda: None,
    )

    with pytest.raises(ProviderError, match="pip install nagisa"):
        provider.synthesize_bytes(
            TTSRequest(
                provider_id="mlx-audio",
                mode=TTSMode.BUILTIN,
                text="hello",
                voice_id="Ryan",
            )
        )


def test_kokoro_dependency_error_includes_request_language_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'misaki'", name="misaki"),
        selected_model="custom-kokoro",
        upstream_model="hexgrad/Kokoro-82M",
        request_language="j",
    )

    assert "pip install misaki" in str(error)
    assert "misaki[ja]" in str(error)


def test_kokoro_dependency_error_includes_mandarin_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'misaki'", name="misaki"),
        selected_model="custom-kokoro",
        upstream_model="hexgrad/Kokoro-82M",
        request_language="zh",
    )

    assert "misaki[zh]" in str(error)


def test_forced_aligner_dependency_error_mentions_korean_extra() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'soynlp'", name="soynlp"),
        selected_model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
        upstream_model="mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
    )

    assert "pip install soynlp" in str(error)
    assert "Korean" in str(error)


def test_bailingmm_dependency_error_mentions_onnx_safetensors() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'onnx'", name="onnx"),
        selected_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
        upstream_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    )

    assert "pip install onnx safetensors" in str(error)


def test_bailingmm_non_dependency_error_preserves_original_failure() -> None:
    error = _dependency_error(
        RuntimeError("download timed out"),
        selected_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
        upstream_model="mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    )

    assert "missing a dependency" not in str(error)
    assert "download timed out" in str(error)


def test_non_bailingmm_onnx_error_is_not_labeled_bailingmm() -> None:
    error = _dependency_error(
        ModuleNotFoundError("No module named 'onnx'", name="onnx"),
        selected_model="qwen3-tts-0.6b-base",
        upstream_model="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    )

    assert "BailingMM" not in str(error)
    assert "onnx" in str(error)
