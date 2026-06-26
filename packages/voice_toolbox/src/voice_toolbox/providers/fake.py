from __future__ import annotations

import tempfile
from pathlib import Path

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.models import (
    ASRRequest,
    AudioArtifact,
    ModelInfo,
    TranscriptArtifact,
    TTSMode,
    TTSRequest,
    VoiceInfo,
)
from voice_toolbox.providers.base import UnsupportedCapability
from voice_toolbox.providers.registry import TTS_MODE_CAPABILITIES


class FakeProvider:
    id = "fake"
    name = "Fake Provider"

    def __init__(
        self,
        *,
        capabilities: set[str] | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_root: Path | str | None = None,
    ) -> None:
        self._capabilities = capabilities or {"tts.builtin", "tts.design", "tts.clone", "asr"}
        if artifact_store is not None:
            self._artifact_store = artifact_store
        else:
            root = Path(artifact_root) if artifact_root is not None else Path(tempfile.mkdtemp())
            self._artifact_store = ArtifactStore(root)

    def capabilities(self) -> set[str]:
        return set(self._capabilities)

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id="fake-tts", name="Fake TTS", capability="tts.builtin"),
            ModelInfo(id="fake-design", name="Fake Voice Design", capability="tts.design"),
            ModelInfo(id="fake-clone", name="Fake Voice Clone", capability="tts.clone"),
            ModelInfo(id="fake-asr", name="Fake ASR", capability="asr"),
        ]

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id="Mia", name="Mia", language="en", gender="female"),
            VoiceInfo(id="Chen", name="Chen", language="zh", gender="male"),
        ]

    def synthesize(self, request: TTSRequest) -> AudioArtifact:
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in self._capabilities:
            raise UnsupportedCapability(f"fake provider does not support capability: {capability}")

        return self._artifact_store.write_audio(
            operation_id=f"fake-tts-{request.mode.value}",
            provider_id=self.id,
            operation="tts",
            audio=self._audio_bytes(request),
            metadata={
                "operation": "tts",
                "output_format": request.output_format,
                "provider_id": self.id,
                "source_text": request.text,
                "tts_mode": request.mode.value,
                "voice_description": request.voice_description,
                "voice_id": request.voice_id,
            },
        )

    def transcribe(self, request: ASRRequest) -> TranscriptArtifact:
        if "asr" not in self._capabilities:
            raise UnsupportedCapability("fake provider does not support capability: asr")

        return self._artifact_store.write_transcript(
            operation_id="fake-asr",
            provider_id=self.id,
            operation="asr",
            text="fake transcript",
            metadata={
                "base64_size": request.base64_size,
                "language": request.language,
                "model": request.model,
                "operation": "asr",
                "provider_id": self.id,
                "raw_byte_size": request.raw_byte_size,
                "uploaded_file_mime_type": request.mime_type,
                "uploaded_file_name": request.audio_path.name,
            },
        )

    def _audio_bytes(self, request: TTSRequest) -> bytes:
        if request.mode == TTSMode.BUILTIN:
            return f"FAKE_WAV:{request.text}:{request.voice_id}".encode()
        if request.mode == TTSMode.DESIGN:
            return f"FAKE_WAV:{request.text or ''}:{request.voice_description}".encode()
        return f"FAKE_WAV:{request.text}:{request.clone_mime_type}".encode()
