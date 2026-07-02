from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from voice_toolbox.models import ModelInfo, ProviderOptionSpec, VoiceInfo

ChunkingMode = Literal["off", "auto", "force"]


class APIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)


class ConsoleLoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    level: str = "INFO"
    format: Literal["human"] = "human"
    colorize: bool = True


class FileLoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    path: str = "logs/voice-toolbox.log"
    level: str = "DEBUG"
    rotation: str = "50 MB"
    retention: str = "14 days"
    compression: str | None = "gz"
    enqueue: bool = True


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)


class TTSChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ChunkingMode = "auto"
    max_chars: int = Field(default=1500, ge=200, le=8000)
    max_chunks: int = Field(default=40, ge=1, le=200)
    max_text_file_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)
    silence_ms: int = Field(default=120, ge=0, le=3000)
    repeat_leading_audio_tags: bool = True


class ASRChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ChunkingMode = "auto"
    target_seconds: int = Field(default=90, ge=10, le=600)
    overlap_ms: int = Field(default=1200, ge=0, le=10000)
    max_chunks: int = Field(default=80, ge=1, le=500)
    max_upload_mb: int = Field(default=250, ge=1, le=2048)
    browser_upload: bool = True
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    dedupe_min_chars: int = Field(default=8, ge=1, le=100)
    dedupe_max_chars: int = Field(default=200, ge=20, le=2000)

    @model_validator(mode="after")
    def validate_asr_chunking_bounds(self) -> ASRChunkingConfig:
        if self.dedupe_min_chars > self.dedupe_max_chars:
            raise ValueError("dedupe_min_chars must be <= dedupe_max_chars")
        if self.overlap_ms >= self.target_seconds * 1000 / 2:
            raise ValueError("overlap_ms must be less than half target_seconds")
        return self


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tts: TTSChunkingConfig = Field(default_factory=TTSChunkingConfig)
    asr: ASRChunkingConfig = Field(default_factory=ASRChunkingConfig)


class ProviderDefaultModels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tts_builtin: str | None = None
    tts_design: str | None = None
    tts_clone: str | None = None
    asr: str | None = None


class ConfiguredProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["mimo", "fish_audio", "openrouter", "mlx_audio"]
    name: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    default_voice: str | None = None
    default_models: ProviderDefaultModels | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    voices: list[VoiceInfo] = Field(default_factory=list)
    options: list[ProviderOptionSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_unused_local_provider_credentials(cls, data: object) -> object:
        if not isinstance(data, dict) or data.get("type") != "mlx_audio":
            return data
        if data.get("base_url") is not None:
            raise ValueError("base_url is not used by local provider type mlx_audio")
        if data.get("api_key_env") is not None:
            raise ValueError("api_key_env is not used by local provider type mlx_audio")
        return data

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("base_url must be an https URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not include credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not include query or fragment")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_key_env must not be empty")
        return stripped

    @model_validator(mode="after")
    def validate_provider_credentials(self) -> ConfiguredProvider:
        if self.type == "mlx_audio":
            return self
        if self.base_url is None:
            raise ValueError(f"base_url is required for provider type {self.type}")
        if self.api_key_env is None:
            raise ValueError(f"api_key_env is required for provider type {self.type}")
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_path: Path | None = None
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    providers: list[ConfiguredProvider]

    @model_validator(mode="after")
    def validate_providers(self) -> AppConfig:
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider ids must be unique")
        for provider in self.providers:
            validate_configured_provider(provider)
        return self


def validate_configured_provider(provider: ConfiguredProvider) -> None:
    model_by_id = {model.id: model for model in provider.models}
    if len(model_by_id) != len(provider.models):
        raise ValueError(f"provider {provider.id} has duplicate model ids")
    voice_ids = {voice.id for voice in provider.voices}
    if len(voice_ids) != len(provider.voices):
        raise ValueError(f"provider {provider.id} has duplicate voice ids")
    if provider.default_voice is not None and (
        provider.type == "mlx_audio" or provider.default_voice not in voice_ids
    ):
        default_tts_model = (
            provider.default_models.tts_builtin if provider.default_models is not None else None
        )
        if default_tts_model is None:
            default_tts_model = next(
                (model.id for model in provider.models if model.capability == "tts.builtin"),
                None,
            )
        default_model = model_by_id.get(default_tts_model)
        default_model_voice_ids = (
            {voice.id for voice in default_model.voices} if default_model is not None else set()
        )
        if provider.default_voice not in default_model_voice_ids and (
            provider.type == "mlx_audio" or provider.default_voice not in voice_ids
        ):
            raise ValueError(f"provider {provider.id} default_voice is not configured")
    provider_option_ids = [(option.capability, option.key) for option in provider.options]
    if len(provider_option_ids) != len(set(provider_option_ids)):
        raise ValueError(f"provider {provider.id} has duplicate provider option keys")
    for model in provider.models:
        model_voice_ids_for_model = {voice.id for voice in model.voices}
        if len(model_voice_ids_for_model) != len(model.voices):
            raise ValueError(f"provider {provider.id} model {model.id} has duplicate voice ids")
        for option in model.options:
            if model.capability is not None and option.capability != model.capability:
                raise ValueError(
                    f"provider {provider.id} model {model.id} option {option.key} has capability "
                    f"{option.capability}, expected {model.capability}"
                )
        option_ids = [(option.capability, option.key) for option in model.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(
                f"provider {provider.id} model {model.id} has duplicate provider option keys"
            )
    expected = {
        "tts_builtin": "tts.builtin",
        "tts_design": "tts.design",
        "tts_clone": "tts.clone",
        "asr": "asr.transcribe",
    }
    defaults = provider.default_models or ProviderDefaultModels()
    for field_name, capability in expected.items():
        model_id = getattr(defaults, field_name)
        if model_id is None:
            continue
        model = model_by_id.get(model_id)
        if model is None:
            raise ValueError(f"provider {provider.id} default model {model_id} is missing")
        if model.capability != capability:
            raise ValueError(
                f"provider {provider.id} default model {model_id} has capability "
                f"{model.capability}, expected {capability}"
            )
