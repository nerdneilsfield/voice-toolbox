from __future__ import annotations

from voice_toolbox.models import ASRRequest, TTSMode, TTSRequest
from voice_toolbox.providers.base import ProviderError, UnsupportedCapability, VoiceProvider

TTS_MODE_CAPABILITIES = {
    TTSMode.BUILTIN: "tts.builtin",
    TTSMode.DESIGN: "tts.design",
    TTSMode.CLONE: "tts.clone",
}
ASR_CAPABILITY = "asr.transcribe"


class ProviderRegistry:
    def __init__(self, providers: list[VoiceProvider]) -> None:
        self._providers: dict[str, VoiceProvider] = {}
        for provider in providers:
            if provider.id in self._providers:
                raise ProviderError(f"duplicate provider: {provider.id}")
            self._providers[provider.id] = provider

    def get(self, provider_id: str) -> VoiceProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderError(f"unknown provider: {provider_id}") from exc

    def ensure_tts_capability(self, provider_id: str, request: TTSRequest) -> VoiceProvider:
        if request.provider_id != provider_id:
            raise ProviderError(
                f"provider_id mismatch: requested {request.provider_id}, got {provider_id}"
            )
        provider = self.get(provider_id)
        capability = TTS_MODE_CAPABILITIES[request.mode]
        if capability not in provider.capabilities():
            raise UnsupportedCapability(
                f"provider {provider_id} does not support capability: {capability}"
            )
        return provider

    def ensure_asr_capability(
        self, provider_id: str, request: ASRRequest | None = None
    ) -> VoiceProvider:
        if request is not None and request.provider_id != provider_id:
            raise ProviderError(
                f"provider_id mismatch: requested {request.provider_id}, got {provider_id}"
            )
        provider = self.get(provider_id)
        if ASR_CAPABILITY not in provider.capabilities():
            raise UnsupportedCapability(
                f"provider {provider_id} does not support capability: {ASR_CAPABILITY}"
            )
        return provider
