from __future__ import annotations

from voice_toolbox.config_models import ConfiguredProvider, ProviderDefaultModels
from voice_toolbox.models import (
    ModelInfo,
    ProviderOptionChoice,
    ProviderOptionOverride,
    ProviderOptionSpec,
    TranscriptCapabilities,
    VoiceInfo,
)

DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_FISH_AUDIO_BASE_URL = "https://api.fish.audio"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_VOLCENGINE_BASE_URL = "https://openspeech.bytedance.com/api/v3/plan"

VOLCENGINE_MODELS: list[ModelInfo] = [
    ModelInfo(id="seed-tts-2.0", name="Doubao Seed TTS 2.0", capability="tts.builtin"),
    ModelInfo(
        id="volc.seedasr.sauc.duration",
        name="Doubao Seed ASR 2.0",
        capability="asr.transcribe",
        transcript_capabilities=TranscriptCapabilities(timestamps=True, segments=True),
    ),
]

_VOLCENGINE_URANUS_VOICES = [
    ("Vivi 2.0", "zh_female_vv_uranus_bigtts", "zh,ja,id,es-MX"),
    ("小何 2.0", "zh_female_xiaohe_uranus_bigtts", "zh"),
    ("云舟 2.0", "zh_male_m191_uranus_bigtts", "zh"),
    ("小天 2.0", "zh_male_taocheng_uranus_bigtts", "zh"),
    ("刘飞 2.0", "zh_male_liufei_uranus_bigtts", "zh"),
    ("魅力苏菲 2.0", "zh_female_sophie_uranus_bigtts", "zh"),
    ("清新女声 2.0", "zh_female_qingxinnvsheng_uranus_bigtts", "zh"),
    ("知性灿灿 2.0", "zh_female_cancan_uranus_bigtts", "zh"),
    ("撒娇学妹 2.0", "zh_female_sajiaoxuemei_uranus_bigtts", "zh"),
    ("甜美小源 2.0", "zh_female_tianmeixiaoyuan_uranus_bigtts", "zh"),
    ("甜美桃子 2.0", "zh_female_tianmeitaozi_uranus_bigtts", "zh"),
    ("爽快思思 2.0", "zh_female_shuangkuaisisi_uranus_bigtts", "zh"),
    ("佩奇猪 2.0", "zh_female_peiqi_uranus_bigtts", "zh"),
    ("邻家女孩 2.0", "zh_female_linjianvhai_uranus_bigtts", "zh"),
    ("少年梓辛 2.0", "zh_male_shaonianzixin_uranus_bigtts", "zh"),
    ("猴哥 2.0", "zh_male_sunwukong_uranus_bigtts", "zh"),
    ("Tina老师 2.0", "zh_female_yingyujiaoxue_uranus_bigtts", "zh,en-GB"),
    ("暖阳女声 2.0", "zh_female_kefunvsheng_uranus_bigtts", "zh"),
    ("儿童绘本 2.0", "zh_female_xiaoxue_uranus_bigtts", "zh"),
    ("大壹 2.0", "zh_male_dayi_uranus_bigtts", "zh"),
    ("黑猫侦探社咪仔 2.0", "zh_female_mizai_uranus_bigtts", "zh"),
    ("鸡汤女 2.0", "zh_female_jitangnv_uranus_bigtts", "zh"),
    ("魅力女友 2.0", "zh_female_meilinvyou_uranus_bigtts", "zh"),
    ("流畅女声 2.0", "zh_female_liuchangnv_uranus_bigtts", "zh"),
    ("儒雅逸辰 2.0", "zh_male_ruyayichen_uranus_bigtts", "zh"),
    ("Tim", "en_male_tim_uranus_bigtts", "en-US"),
    ("Dacey", "en_female_dacey_uranus_bigtts", "en-US"),
    ("Stokie", "en_female_stokie_uranus_bigtts", "en-US"),
    ("温柔妈妈 2.0", "zh_female_wenroumama_uranus_bigtts", "zh"),
    ("解说小明 2.0", "zh_male_jieshuoxiaoming_uranus_bigtts", "zh"),
    ("TVB女声 2.0", "zh_female_tvbnv_uranus_bigtts", "zh"),
    ("译制片男 2.0", "zh_male_yizhipiannan_uranus_bigtts", "zh"),
    ("俏皮女声 2.0", "zh_female_qiaopinv_uranus_bigtts", "zh"),
    ("直率英子 2.0", "zh_female_zhishuaiyingzi_uranus_bigtts", "zh"),
    ("邻家男孩 2.0", "zh_male_linjiananhai_uranus_bigtts", "zh"),
    ("四郎 2.0", "zh_male_silang_uranus_bigtts", "zh"),
    ("儒雅青年 2.0", "zh_male_ruyaqingnian_uranus_bigtts", "zh"),
    ("擎苍 2.0", "zh_male_qingcang_uranus_bigtts", "zh"),
    ("熊二 2.0", "zh_male_xionger_uranus_bigtts", "zh"),
    ("樱桃丸子 2.0", "zh_female_yingtaowanzi_uranus_bigtts", "zh"),
    ("温暖阿虎 2.0", "zh_male_wennuanahu_uranus_bigtts", "zh"),
    ("奶气萌娃 2.0", "zh_male_naiqimengwa_uranus_bigtts", "zh"),
    ("婆婆 2.0", "zh_female_popo_uranus_bigtts", "zh"),
    ("高冷御姐 2.0", "zh_female_gaolengyujie_uranus_bigtts", "zh"),
    ("傲娇霸总 2.0", "zh_male_aojiaobazong_uranus_bigtts", "zh"),
    ("懒音绵宝 2.0", "zh_male_lanyinmianbao_uranus_bigtts", "zh"),
    ("反卷青年 2.0", "zh_male_fanjuanqingnian_uranus_bigtts", "zh"),
    ("温柔淑女 2.0", "zh_female_wenroushunv_uranus_bigtts", "zh"),
    ("古风少御 2.0", "zh_female_gufengshaoyu_uranus_bigtts", "zh"),
    ("活力小哥 2.0", "zh_male_huolixiaoge_uranus_bigtts", "zh"),
    ("霸气青叔 2.0", "zh_male_baqiqingshu_uranus_bigtts", "zh"),
    ("悬疑解说 2.0", "zh_male_xuanyijieshuo_uranus_bigtts", "zh"),
    ("萌丫头 2.0", "zh_female_mengyatou_uranus_bigtts", "zh"),
    ("贴心女声 2.0", "zh_female_tiexinnvsheng_uranus_bigtts", "zh"),
    ("鸡汤妹妹 2.0", "zh_female_jitangmei_uranus_bigtts", "zh"),
    ("磁性解说男声 2.0", "zh_male_cixingjieshuonan_uranus_bigtts", "zh"),
    ("亮嗓萌仔 2.0", "zh_male_liangsangmengzai_uranus_bigtts", "zh"),
    ("开朗姐姐 2.0", "zh_female_kailangjiejie_uranus_bigtts", "zh"),
    ("高冷沉稳 2.0", "zh_male_gaolengchenwen_uranus_bigtts", "zh"),
    ("深夜播客 2.0", "zh_male_shenyeboke_uranus_bigtts", "zh"),
    ("鲁班七号 2.0", "zh_male_lubanqihao_uranus_bigtts", "zh"),
    ("娇喘女声 2.0", "zh_female_jiaochuannv_uranus_bigtts", "zh"),
    ("林潇 2.0", "zh_female_linxiao_uranus_bigtts", "zh"),
    ("玲玲姐姐 2.0", "zh_female_lingling_uranus_bigtts", "zh"),
    ("春日部姐姐 2.0", "zh_female_chunribu_uranus_bigtts", "zh"),
    ("唐僧 2.0", "zh_male_tangseng_uranus_bigtts", "zh"),
    ("庄周 2.0", "zh_male_zhuangzhou_uranus_bigtts", "zh"),
    ("开朗弟弟 2.0", "zh_male_kailangdidi_uranus_bigtts", "zh"),
    ("猪八戒 2.0", "zh_male_zhubajie_uranus_bigtts", "zh"),
    ("感冒电音姐姐 2.0", "zh_female_ganmaodianyin_uranus_bigtts", "zh"),
    ("谄媚女声 2.0", "zh_female_chanmeinv_uranus_bigtts", "zh"),
    ("女雷神 2.0", "zh_female_nvleishen_uranus_bigtts", "zh"),
    ("亲切女声 2.0", "zh_female_qinqienv_uranus_bigtts", "zh"),
    ("快乐小东 2.0", "zh_male_kuailexiaodong_uranus_bigtts", "zh"),
    ("开朗学长 2.0", "zh_male_kailangxuezhang_uranus_bigtts", "zh"),
    ("悠悠君子 2.0", "zh_male_youyoujunzi_uranus_bigtts", "zh"),
    ("文静毛毛 2.0", "zh_female_wenjingmaomao_uranus_bigtts", "zh"),
    ("知性女声 2.0", "zh_female_zhixingnv_uranus_bigtts", "zh"),
    ("清爽男大 2.0", "zh_male_qingshuangnanda_uranus_bigtts", "zh"),
    ("渊博小叔 2.0", "zh_male_yuanboxiaoshu_uranus_bigtts", "zh"),
    ("阳光青年 2.0", "zh_male_yangguangqingnian_uranus_bigtts", "zh"),
    ("清澈梓梓 2.0", "zh_female_qingchezizi_uranus_bigtts", "zh"),
    ("甜美悦悦 2.0", "zh_female_tianmeiyueyue_uranus_bigtts", "zh"),
    ("心灵鸡汤 2.0", "zh_female_xinlingjitang_uranus_bigtts", "zh"),
    ("温柔小哥 2.0", "zh_male_wenrouxiaoge_uranus_bigtts", "zh"),
    ("柔美女友 2.0", "zh_female_roumeinvyou_uranus_bigtts", "zh"),
    ("东方浩然 2.0", "zh_male_dongfanghaoran_uranus_bigtts", "zh"),
    ("温柔小雅 2.0", "zh_female_wenrouxiaoya_uranus_bigtts", "zh"),
    ("天才童声 2.0", "zh_male_tiancaitongsheng_uranus_bigtts", "zh"),
    ("武则天 2.0", "zh_female_wuzetian_uranus_bigtts", "zh"),
    ("顾姐 2.0", "zh_female_gujie_uranus_bigtts", "zh"),
    ("广告解说 2.0", "zh_male_guanggaojieshuo_uranus_bigtts", "zh"),
    ("少儿故事 2.0", "zh_female_shaoergushi_uranus_bigtts", "zh"),
]

VOLCENGINE_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id=voice_id,
        name=name,
        language=language,
        gender="female" if "_female_" in voice_id else "male",
        note="Doubao Seed TTS 2.0 built-in voice; supports instruction following",
    )
    for name, voice_id, language in _VOLCENGINE_URANUS_VOICES
]

DEFAULT_VOLCENGINE_MODELS = ProviderDefaultModels(
    tts_builtin="seed-tts-2.0",
    asr="volc.seedasr.sauc.duration",
)

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
    ModelInfo(id="mimo-v2.5-asr", name="MiMo V2.5 ASR", capability="asr.transcribe"),
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
    ModelInfo(
        id="fish-audio-asr",
        name="Fish Audio ASR",
        capability="asr.transcribe",
        transcript_capabilities=TranscriptCapabilities(timestamps=True, segments=True),
    ),
]

FISH_AUDIO_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id="e58b0d7efca34eb38d5c4985e378abcb",
        name="Fish Audio default reference",
        note="public reference_id from Fish Audio docs; replace with your own model/reference id",
    ),
    VoiceInfo(
        id="bf6c479f5a384b8d857310030035824b", name="活泼女声", language="zh", gender="female"
    ),
    VoiceInfo(
        id="7f92f8afb8ec43bf81429cc1c9199cb1", name="AD 学姐", language="zh", gender="female"
    ),
    VoiceInfo(id="54a5170264694bfc8e9ad98df7bd89c3", name="丁真", language="zh", gender="male"),
    VoiceInfo(id="aebaa2305aa2452fbdc8f41eec852a79", name="雷军", language="zh", gender="male"),
    VoiceInfo(id="59cb5986671546eaa6ca8ae6f29f6d22", name="央视配音", language="zh", gender="male"),
    VoiceInfo(id="e80ea225770f42f79d50aa98be3cedfc", name="孙笑川", language="zh", gender="male"),
    VoiceInfo(id="f6f293aabfe24e46aff0fc309c233d31", name="曹操", language="zh", gender="male"),
    VoiceInfo(
        id="5c353fdb312f4888836a9a5680099ef0", name="女大学生", language="zh", gender="female"
    ),
    VoiceInfo(id="57eab548c7ed4ddc974c4c153cb015b2", name="女主播", language="zh", gender="female"),
    VoiceInfo(
        id="af495c47b4484b2b92244872bbabd9af", name="张琦震惊", language="zh", gender="female"
    ),
    VoiceInfo(
        id="0d6c092805a04e53aef4848f77d5c366", name="白发女教授", language="zh", gender="female"
    ),
    VoiceInfo(
        id="dd43b30d04d9446a94ebe41f301229b5", name="纪录片男声", language="zh", gender="male"
    ),
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
    "qwen3-tts-1.7b-base": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "qwen3-tts-1.7b-base-clone": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "qwen3-tts-1.7b-base-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "qwen3-tts-1.7b-base-8bit-clone": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "longcat-audiodit-1b": "mlx-community/LongCat-AudioDiT-1B-bf16",
    "longcat-audiodit-1b-clone": "mlx-community/LongCat-AudioDiT-1B-bf16",
    "ming-omni-tts-16.8b-a3b": "mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    "ming-omni-tts-16.8b-a3b-clone": "mlx-community/Ming-omni-tts-16.8B-A3B-bf16",
    "higgs-audio-v3-tts-4b": "bosonai/higgs-audio-v3-tts-4b",
    "higgs-audio-v3-tts-4b-clone": "bosonai/higgs-audio-v3-tts-4b",
}

MLX_AUDIO_DEFAULT_VOICE_ID = "Ryan"

MLX_AUDIO_QWEN3_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="Vivian", name="Vivian", language="zh", gender="female"),
    VoiceInfo(id="Serena", name="Serena", language="zh", gender="female"),
    VoiceInfo(id="Uncle_Fu", name="Uncle Fu", language="zh", gender="male"),
    VoiceInfo(id="Dylan", name="Dylan", language="zh", gender="male", note="Beijing dialect"),
    VoiceInfo(id="Eric", name="Eric", language="zh", gender="male", note="Sichuan dialect"),
    VoiceInfo(id="Ryan", name="Ryan", language="en", gender="male"),
    VoiceInfo(id="Aiden", name="Aiden", language="en", gender="male"),
]

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
        ("temperature", "Temperature", None, 0.0, 2.0),
        ("speed", "Speed", 1.0, 0.25, 4.0),
    )
]


def _mlx_longcat_options(
    capability: str,
    *,
    guidance_method_default: str = "cfg",
) -> list[ProviderOptionSpec | ProviderOptionOverride]:
    return [
        ProviderOptionSpec(
            key="guidance_method",
            label="Guidance method",
            type="select",
            capability=capability,
            default=guidance_method_default,
            choices=[
                ProviderOptionChoice(value="cfg", label="CFG"),
                ProviderOptionChoice(value="apg", label="APG"),
            ],
            advanced=True,
            safe_metadata=True,
        ),
        ProviderOptionSpec(
            key="cfg_strength",
            label="CFG strength",
            type="number",
            capability=capability,
            default=4.0,
            min_value=0.0,
            max_value=20.0,
            step=0.1,
            advanced=True,
            safe_metadata=True,
        ),
        ProviderOptionSpec(
            key="steps",
            label="Steps",
            type="integer",
            capability=capability,
            default=16,
            min_value=1,
            max_value=100,
            step=1,
            advanced=True,
            safe_metadata=True,
        ),
    ]


def _mlx_ming_omni_options(capability: str) -> list[ProviderOptionSpec | ProviderOptionOverride]:
    return [
        ProviderOptionSpec(
            key="prompt",
            label="Prompt",
            type="text",
            capability=capability,
            advanced=True,
            safe_metadata=False,
        ),
        ProviderOptionSpec(
            key="instruct",
            label="Instruction",
            type="text",
            capability=capability,
            advanced=True,
            safe_metadata=False,
        ),
        ProviderOptionSpec(
            key="cfg_scale",
            label="CFG scale",
            type="number",
            capability=capability,
            default=2.0,
            min_value=0.0,
            max_value=20.0,
            step=0.1,
            advanced=True,
            safe_metadata=True,
        ),
        ProviderOptionSpec(
            key="sigma",
            label="Sigma",
            type="number",
            capability=capability,
            default=0.25,
            min_value=0.0,
            max_value=5.0,
            step=0.05,
            advanced=True,
            safe_metadata=True,
        ),
        ProviderOptionSpec(
            key="max_tokens",
            label="Max tokens",
            type="integer",
            capability=capability,
            default=200,
            min_value=1,
            max_value=4000,
            step=1,
            advanced=True,
            safe_metadata=True,
        ),
        ProviderOptionSpec(
            key="use_zero_spk_emb",
            label="Zero speaker embedding",
            type="boolean",
            capability=capability,
            advanced=True,
            safe_metadata=True,
        ),
    ]


def _mlx_higgs_options(capability: str) -> list[ProviderOptionSpec | ProviderOptionOverride]:
    return [
        ProviderOptionSpec(
            key="max_new_tokens",
            label="Max new tokens",
            type="integer",
            capability=capability,
            default=2048,
            min_value=1,
            max_value=8192,
            step=1,
            advanced=True,
            safe_metadata=True,
        )
    ]


MLX_AUDIO_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="qwen3-tts-0.6b-base",
        name="Qwen3 TTS 0.6B Base",
        capability="tts.builtin",
        voices=[voice.model_copy() for voice in MLX_AUDIO_QWEN3_VOICES],
    ),
    ModelInfo(
        id="qwen3-tts-0.6b-base-clone",
        name="Qwen3 TTS 0.6B Clone",
        capability="tts.clone",
        note="uses upstream Qwen3 TTS base model with clone_reference_text",
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base",
        name="Qwen3 TTS 1.7B Base",
        capability="tts.builtin",
        voices=[voice.model_copy() for voice in MLX_AUDIO_QWEN3_VOICES],
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base-clone",
        name="Qwen3 TTS 1.7B Clone",
        capability="tts.clone",
        note="uses upstream Qwen3 TTS 1.7B base model with clone_reference_text",
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base-8bit",
        name="Qwen3 TTS 1.7B 8-bit",
        capability="tts.builtin",
        voices=[voice.model_copy() for voice in MLX_AUDIO_QWEN3_VOICES],
    ),
    ModelInfo(
        id="qwen3-tts-1.7b-base-8bit-clone",
        name="Qwen3 TTS 1.7B 8-bit Clone",
        capability="tts.clone",
        note="uses upstream Qwen3 TTS 1.7B 8-bit base model with clone_reference_text",
    ),
    ModelInfo(
        id="longcat-audiodit-1b",
        name="LongCat AudioDiT 1B",
        capability="tts.builtin",
        note="supports zero-shot voice cloning with ref_audio and ref_text",
        options=_mlx_longcat_options("tts.builtin"),
    ),
    ModelInfo(
        id="longcat-audiodit-1b-clone",
        name="LongCat AudioDiT 1B Clone",
        capability="tts.clone",
        note="supports ref_audio/ref_text; upstream recommends guidance_method=apg for clone",
        options=_mlx_longcat_options("tts.clone", guidance_method_default="apg"),
    ),
    ModelInfo(
        id="ming-omni-tts-16.8b-a3b",
        name="Ming Omni TTS 16.8B A3B",
        capability="tts.builtin",
        note="requires onnx and safetensors conversion artifacts",
        options=_mlx_ming_omni_options("tts.builtin"),
    ),
    ModelInfo(
        id="ming-omni-tts-16.8b-a3b-clone",
        name="Ming Omni TTS 16.8B A3B Clone",
        capability="tts.clone",
        note="uses ref_audio/ref_text; requires onnx and safetensors conversion artifacts",
        options=_mlx_ming_omni_options("tts.clone"),
    ),
    ModelInfo(
        id="higgs-audio-v3-tts-4b",
        name="Higgs Audio v3 TTS 4B",
        capability="tts.builtin",
        note="large model; supports inline controls and zero-shot voice cloning",
        options=_mlx_higgs_options("tts.builtin"),
    ),
    ModelInfo(
        id="higgs-audio-v3-tts-4b-clone",
        name="Higgs Audio v3 TTS 4B Clone",
        capability="tts.clone",
        note="uses ref_audio/ref_text; large model with higher memory and startup cost",
        options=_mlx_higgs_options("tts.clone"),
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-0.6B-8bit",
        name="Qwen3 ASR 0.6B 8-bit",
        capability="asr.transcribe",
        transcript_capabilities=TranscriptCapabilities(timestamps=True, segments=True),
    ),
    ModelInfo(
        id="mlx-community/Qwen3-ASR-1.7B-8bit",
        name="Qwen3 ASR 1.7B 8-bit",
        capability="asr.transcribe",
        transcript_capabilities=TranscriptCapabilities(timestamps=True, segments=True),
    ),
]

MLX_AUDIO_VOICES: list[VoiceInfo] = []

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
        default_voice=MLX_AUDIO_DEFAULT_VOICE_ID,
        default_models=DEFAULT_MLX_AUDIO_MODELS.model_copy(deep=True),
        models=[model.model_copy() for model in MLX_AUDIO_MODELS],
        voices=[voice.model_copy() for voice in MLX_AUDIO_VOICES],
        options=[option.model_copy() for option in MLX_AUDIO_TTS_OPTIONS],
    )


def make_default_volcengine_provider_config(
    *,
    provider_id: str = "volcengine",
    name: str = "Volcengine Speech",
    base_url: str = DEFAULT_VOLCENGINE_BASE_URL,
    api_key_env: str = "VOLCENGINE_SPEECH_API_KEY",
) -> ConfiguredProvider:
    return ConfiguredProvider(
        id=provider_id,
        type="volcengine",
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice=VOLCENGINE_VOICES[0].id,
        default_models=DEFAULT_VOLCENGINE_MODELS.model_copy(deep=True),
        models=[model.model_copy() for model in VOLCENGINE_MODELS],
        voices=[voice.model_copy() for voice in VOLCENGINE_VOICES],
    )
