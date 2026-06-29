from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from typing import Protocol

from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    ProviderAudioResult,
    TranscriptArtifact,
    TTSRequest,
    VoiceInfo,
)


class ProviderError(Exception):
    """Base provider failure."""

    def __init__(
        self,
        message: str,
        *,
        provider_id: str | None = None,
        operation: str | None = None,
        status_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.operation = operation
        self.status_code = status_code
        self.metadata = metadata or {}


class UnsupportedCapability(ProviderError):
    """Provider cannot satisfy requested capability."""


class VoiceProvider(Protocol):
    id: str
    name: str

    def capabilities(self) -> set[str]:
        raise NotImplementedError

    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def list_voices(self) -> list[VoiceInfo]:
        raise NotImplementedError

    def synthesize(
        self,
        request: TTSRequest,
        *,
        artifact_metadata: Mapping[str, object] | None = None,
    ) -> AudioArtifact:
        raise NotImplementedError

    def synthesize_bytes(self, request: TTSRequest) -> ProviderAudioResult:
        raise NotImplementedError

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        raise NotImplementedError
