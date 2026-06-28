from __future__ import annotations

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ModelInfo, VoiceInfo

DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_FISH_AUDIO_BASE_URL = "https://api.fish.audio"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MIMO_MODELS: list[ModelInfo] = [
    ModelInfo(id="mimo-v2.5-tts", name="MiMo TTS", capability="tts.builtin"),
    ModelInfo(
        id="mimo-v2.5-tts-voicedesign",
        name="MiMo Voice Design",
        capability="tts.design",
    ),
    ModelInfo(
        id="mimo-v2.5-tts-voiceclone",
        name="MiMo Voice Clone",
        capability="tts.clone",
    ),
    ModelInfo(id="mimo-v2.5-asr", name="MiMo ASR", capability="asr.transcribe"),
]

MIMO_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="mimo_default", name="MiMo-默认", note="cluster-dependent"),
    VoiceInfo(id="冰糖", name="冰糖", language="zh", gender="female"),
    VoiceInfo(id="茉莉", name="茉莉", language="zh", gender="female"),
    VoiceInfo(id="苏打", name="苏打", language="zh", gender="male"),
    VoiceInfo(id="白桦", name="白桦", language="zh", gender="male"),
    VoiceInfo(id="Mia", name="Mia", language="en", gender="female"),
    VoiceInfo(id="Chloe", name="Chloe", language="en", gender="female"),
    VoiceInfo(id="Milo", name="Milo", language="en", gender="male"),
    VoiceInfo(id="Dean", name="Dean", language="en", gender="male"),
]

DEFAULT_MIMO_MODELS = ProviderDefaultModels(
    tts_builtin="mimo-v2.5-tts",
    tts_design="mimo-v2.5-tts-voicedesign",
    tts_clone="mimo-v2.5-tts-voiceclone",
    asr="mimo-v2.5-asr",
)

FISH_AUDIO_MODELS: list[ModelInfo] = [
    ModelInfo(id="s1", name="Fish Audio S1", capability="tts.builtin"),
    ModelInfo(
        id="s1-design",
        name="Fish Audio Voice Design",
        capability="tts.design",
        note="uses Fish Audio model header s1",
    ),
    ModelInfo(
        id="s1-clone",
        name="Fish Audio Direct Clone",
        capability="tts.clone",
        note="uses Fish Audio model header s1 with MessagePack references",
    ),
    ModelInfo(id="fish-audio-asr", name="Fish Audio ASR", capability="asr.transcribe"),
]

FISH_AUDIO_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id="e58b0d7efca34eb38d5c4985e378abcb",
        name="Fish Audio default reference",
        note="public reference_id from Fish Audio docs; replace with your own model/reference id",
    )
]

DEFAULT_FISH_AUDIO_MODELS = ProviderDefaultModels(
    tts_builtin="s1",
    tts_design="s1-design",
    tts_clone="s1-clone",
    asr="fish-audio-asr",
)

OPENROUTER_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="openai/gpt-4o-mini-tts-2025-12-15",
        name="OpenAI GPT-4o Mini TTS",
        capability="tts.builtin",
        note="OpenRouter TTS endpoint; response_format mp3",
    ),
    ModelInfo(id="openai/whisper-1", name="OpenAI Whisper", capability="asr.transcribe"),
]

OPENROUTER_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="alloy", name="Alloy"),
    VoiceInfo(id="ash", name="Ash"),
    VoiceInfo(id="ballad", name="Ballad"),
    VoiceInfo(id="coral", name="Coral"),
    VoiceInfo(id="echo", name="Echo"),
    VoiceInfo(id="fable", name="Fable"),
    VoiceInfo(id="nova", name="Nova"),
    VoiceInfo(id="onyx", name="Onyx"),
    VoiceInfo(id="sage", name="Sage"),
    VoiceInfo(id="shimmer", name="Shimmer"),
]

DEFAULT_OPENROUTER_MODELS = ProviderDefaultModels(
    tts_builtin="openai/gpt-4o-mini-tts-2025-12-15",
    asr="openai/whisper-1",
)


def make_default_mimo_provider_config(
    *,
    provider_id: str = "mimo",
    name: str = "MiMo",
    base_url: str = DEFAULT_MIMO_BASE_URL,
    api_key_env: str = "MIMO_API_KEY",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="mimo",
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice="mimo_default",
        default_models=DEFAULT_MIMO_MODELS,
        models=[model.model_copy() for model in MIMO_MODELS],
        voices=[voice.model_copy() for voice in MIMO_VOICES],
    )


def make_default_fish_audio_provider_config(
    *,
    provider_id: str = "fish-audio",
    name: str = "Fish Audio",
    base_url: str = DEFAULT_FISH_AUDIO_BASE_URL,
    api_key_env: str = "FISH_AUDIO_API_KEY",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="fish_audio",
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice=FISH_AUDIO_VOICES[0].id,
        default_models=DEFAULT_FISH_AUDIO_MODELS,
        models=[model.model_copy() for model in FISH_AUDIO_MODELS],
        voices=[voice.model_copy() for voice in FISH_AUDIO_VOICES],
    )


def make_default_openrouter_provider_config(
    *,
    provider_id: str = "openrouter",
    name: str = "OpenRouter",
    base_url: str = DEFAULT_OPENROUTER_BASE_URL,
    api_key_env: str = "OPENROUTER_API_KEY",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="openrouter",
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice="alloy",
        default_models=DEFAULT_OPENROUTER_MODELS,
        models=[model.model_copy() for model in OPENROUTER_MODELS],
        voices=[voice.model_copy() for voice in OPENROUTER_VOICES],
    )
