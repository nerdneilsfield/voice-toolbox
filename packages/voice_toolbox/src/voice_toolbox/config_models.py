from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from voice_toolbox.models import ModelInfo, VoiceInfo


class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class ConsoleLoggingConfig(BaseModel):
    enabled: bool = True
    level: str = "INFO"
    format: Literal["human"] = "human"
    colorize: bool = True


class FileLoggingConfig(BaseModel):
    enabled: bool = False
    path: str = "logs/voice-toolbox.log"
    level: str = "DEBUG"
    rotation: str = "50 MB"
    retention: str = "14 days"
    compression: str | None = "gz"
    enqueue: bool = True


class LoggingConfig(BaseModel):
    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)


class ProviderDefaultModels(BaseModel):
    tts_builtin: str | None = None
    tts_design: str | None = None
    tts_clone: str | None = None
    asr: str | None = None


class ConfiguredProvider(BaseModel):
    id: str
    type: Literal["mimo"]
    name: str
    base_url: str
    api_key_env: str
    default_voice: str | None = None
    default_models: ProviderDefaultModels | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    voices: list[VoiceInfo] = Field(default_factory=list)


class AppConfig(BaseModel):
    config_path: Path | None = None
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
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
    if provider.default_voice is not None and provider.default_voice not in voice_ids:
        raise ValueError(f"provider {provider.id} default_voice is not configured")
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
