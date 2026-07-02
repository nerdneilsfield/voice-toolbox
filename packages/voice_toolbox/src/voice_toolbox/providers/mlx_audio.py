from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config_models import ConfiguredProvider
from voice_toolbox.defaults import make_default_mlx_audio_provider_config
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    ProviderAudioResult,
    TranscriptArtifact,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.transcripts import TranscriptPayload


class MlxAudioProvider:
    id = "mlx-audio"
    name = "MLX Audio"

    def __init__(
        self,
        *,
        config: ConfiguredProvider | None = None,
        artifact_root: Path | str | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        resolved_config = config or make_default_mlx_audio_provider_config()

        self._config = resolved_config
        self.id = resolved_config.id
        self.name = resolved_config.name
        self._models = [model.model_copy() for model in resolved_config.models]
        self._voices = [voice.model_copy() for voice in resolved_config.voices]
        if artifact_store is not None:
            self._artifact_store = artifact_store
            self._artifact_root = artifact_store.root
        else:
            root = artifact_root or Path.cwd() / ".voice-toolbox"
            self._artifact_store = ArtifactStore(root)
            self._artifact_root = self._artifact_store.root

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def capabilities(self) -> set[str]:
        return {model.capability for model in self._models if model.capability is not None}

    def list_models(self) -> list[ModelInfo]:
        return [model.model_copy() for model in self._models]

    def list_voices(self) -> list[VoiceInfo]:
        return [voice.model_copy() for voice in self._voices]

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        raise ProviderError("mlx_audio provider shell does not implement synthesis")

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        raise ProviderError("mlx_audio provider shell does not implement synthesis")

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        raise ProviderError("mlx_audio provider shell does not implement transcription")

    def transcribe_payload(self, request: ASRRequest) -> TranscriptPayload:
        raise ProviderError("mlx_audio provider shell does not implement transcription")
