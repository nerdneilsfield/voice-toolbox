from __future__ import annotations

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import ModelInfo, ProviderOptionSpec, VoiceInfo

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
    ModelInfo(
        id="s2.1-pro-free",
        name="Fish Audio S2.1 Pro Free",
        capability="tts.builtin",
        note="free tier under Fair Use; 83 languages; default built-in model",
    ),
    ModelInfo(
        id="s2.1-pro",
        name="Fish Audio S2.1 Pro",
        capability="tts.builtin",
        note="latest paid Pro model",
    ),
    ModelInfo(
        id="s2-pro",
        name="Fish Audio S2 Pro",
        capability="tts.builtin",
        note="paid Pro model; supports multi-speaker dialogue",
    ),
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
    ModelInfo(
        id="s2.1-pro-clone",
        name="Fish Audio S2.1 Pro Clone",
        capability="tts.clone",
        note="uses Fish Audio model header s2.1-pro with MessagePack references",
    ),
    ModelInfo(
        id="s2-pro-clone",
        name="Fish Audio S2 Pro Clone",
        capability="tts.clone",
        note="uses Fish Audio model header s2-pro with MessagePack references",
    ),
    ModelInfo(id="fish-audio-asr", name="Fish Audio ASR", capability="asr.transcribe"),
]

FISH_AUDIO_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id="e58b0d7efca34eb38d5c4985e378abcb",
        name="Fish Audio default reference",
        note="public reference_id from Fish Audio docs; replace with your own model/reference id",
    ),
    VoiceInfo(id="bf6c479f5a384b8d857310030035824b", name="活泼女声", language="zh", gender="female"),
    VoiceInfo(id="7f92f8afb8ec43bf81429cc1c9199cb1", name="AD 学姐", language="zh", gender="female"),
    VoiceInfo(id="54a5170264694bfc8e9ad98df7bd89c3", name="丁真", language="zh", gender="male"),
    VoiceInfo(id="aebaa2305aa2452fbdc8f41eec852a79", name="雷军", language="zh", gender="male"),
    VoiceInfo(id="59cb5986671546eaa6ca8ae6f29f6d22", name="央视配音", language="zh", gender="male"),
    VoiceInfo(id="e80ea225770f42f79d50aa98be3cedfc", name="孙笑川", language="zh", gender="male"),
    VoiceInfo(id="f6f293aabfe24e46aff0fc309c233d31", name="曹操", language="zh", gender="male"),
    VoiceInfo(id="5c353fdb312f4888836a9a5680099ef0", name="女大学生", language="zh", gender="female"),
    VoiceInfo(id="57eab548c7ed4ddc974c4c153cb015b2", name="女主播", language="zh", gender="female"),
    VoiceInfo(id="af495c47b4484b2b92244872bbabd9af", name="张琦震惊", language="zh", gender="female"),
    VoiceInfo(id="0d6c092805a04e53aef4848f77d5c366", name="白发女教授", language="zh", gender="female"),
    VoiceInfo(id="dd43b30d04d9446a94ebe41f301229b5", name="纪录片男声", language="zh", gender="male"),
]

DEFAULT_FISH_AUDIO_MODELS = ProviderDefaultModels(
    tts_builtin="s2.1-pro-free",
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

MLX_AUDIO_MODEL_ALIASES = {
    "qwen3-tts-0.6b-base": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    "qwen3-tts-0.6b-base-clone": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
    "qwen3-tts-1.7b-base-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "longcat-audiodit-1b": "mlx-community/LongCat-AudioDiT-1B-bf16",
    "ming-omni-tts-16.8b-a3b": "mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    "higgs-audio-v3-tts-4b": "bosonai/higgs-audio-v3-tts-4b",
}

MLX_AUDIO_TTS_OPTIONS: list[ProviderOptionSpec] = [
    ProviderOptionSpec(
        key="lang_code",
        label="Language",
        type="string",
        capability=capability,
        default="auto",
        advanced=True,
        safe_metadata=True,
    )
    for capability in ("tts.builtin", "tts.clone")
] + [
    ProviderOptionSpec(
        key=key,
        label=label,
        type="number",
        capability=capability,
        default=default,
        min_value=min_value,
        max_value=max_value,
        step=0.05,
        advanced=True,
        safe_metadata=True,
    )
    for capability in ("tts.builtin", "tts.clone")
    for key, label, default, min_value, max_value in (
        ("temperature", "Temperature", 0.7, 0.0, 2.0),
        ("speed", "Speed", 1.0, 0.25, 4.0),
    )
]

MLX_AUDIO_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="qwen3-tts-0.6b-base",
        name="Qwen3 TTS 0.6B Base",
        capability="tts.builtin",
    ),
    ModelInfo(
        id="qwen3-tts-0.6b-base-clone",
        name="Qwen3 TTS 0.6B Clone",
        capability="tts.clone",
        note="uses upstream Qwen3 TTS base model with clone_reference_text",
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base-8bit",
        name="Qwen3 TTS 1.7B 8-bit",
        capability="tts.builtin",
    ),
    ModelInfo(
        id="longcat-audiodit-1b",
        name="LongCat AudioDiT 1B",
        capability="tts.builtin",
    ),
    ModelInfo(
        id="ming-omni-tts-16.8b-a3b",
        name="Ming Omni TTS 16.8B A3B",
        capability="tts.builtin",
        note="requires onnx and safetensors conversion artifacts",
    ),
    ModelInfo(
        id="higgs-audio-v3-tts-4b",
        name="Higgs Audio v3 TTS 4B",
        capability="tts.builtin",
        note="large model; expect higher memory and startup cost",
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-0.6B-8bit",
        name="Qwen3 ASR 0.6B 8-bit",
        capability="asr.transcribe",
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-1.7B-8bit",
        name="Qwen3 ASR 1.7B 8-bit",
        capability="asr.transcribe",
    ),
]

MLX_AUDIO_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="Ryan", name="Ryan", language="en", gender="male"),
    VoiceInfo(id="Aiden", name="Aiden", language="en", gender="male"),
    VoiceInfo(id="Vivian", name="Vivian", language="en", gender="female"),
    VoiceInfo(id="Serena", name="Serena", language="en", gender="female"),
    VoiceInfo(id="default", name="Default"),
]

DEFAULT_MLX_AUDIO_MODELS = ProviderDefaultModels(
    tts_builtin="qwen3-tts-0.6b-base",
    tts_clone="qwen3-tts-0.6b-base-clone",
    asr="mlx-community/Qwen3-ASR-0.6B-8bit",
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
        default_models=DEFAULT_MIMO_MODELS.model_copy(deep=True),
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
        default_models=DEFAULT_FISH_AUDIO_MODELS.model_copy(deep=True),
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
        default_models=DEFAULT_OPENROUTER_MODELS.model_copy(deep=True),
        models=[model.model_copy() for model in OPENROUTER_MODELS],
        voices=[voice.model_copy() for voice in OPENROUTER_VOICES],
    )


def make_default_mlx_audio_provider_config(
    *,
    provider_id: str = "mlx-audio",
    name: str = "MLX Audio",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="mlx_audio",
        name=name,
        base_url=None,
        api_key_env=None,
        default_voice="Ryan",
        default_models=DEFAULT_MLX_AUDIO_MODELS.model_copy(deep=True),
        models=[model.model_copy() for model in MLX_AUDIO_MODELS],
        voices=[voice.model_copy() for voice in MLX_AUDIO_VOICES],
        options=[option.model_copy() for option in MLX_AUDIO_TTS_OPTIONS],
    )
