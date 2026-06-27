from __future__ import annotations

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ModelInfo, VoiceInfo

DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"

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
