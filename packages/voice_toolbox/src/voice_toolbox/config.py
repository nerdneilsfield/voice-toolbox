from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import ValidationError

from voice_toolbox.config_models import (
    APIConfig,
    ASRChunkingConfig,
    ChunkingConfig,
    AppConfig,
    ConfiguredProvider,
    ConsoleLoggingConfig,
    FileLoggingConfig,
    LoggingConfig,
    ProviderDefaultModels,
    TTSChunkingConfig,
)
from voice_toolbox.defaults import (
    DEFAULT_FISH_AUDIO_MODELS,
    DEFAULT_MIMO_BASE_URL,
    DEFAULT_MIMO_MODELS,
    MLX_AUDIO_DEFAULT_VOICE_ID,
    DEFAULT_MLX_AUDIO_MODELS,
    DEFAULT_OPENROUTER_MODELS,
    FISH_AUDIO_MODELS,
    FISH_AUDIO_VOICES,
    MIMO_MODELS,
    MIMO_VOICES,
    MLX_AUDIO_MODELS,
    MLX_AUDIO_TTS_OPTIONS,
    MLX_AUDIO_VOICES,
    OPENROUTER_MODELS,
    OPENROUTER_VOICES,
    DEFAULT_VOLCENGINE_MODELS,
    VOLCENGINE_MODELS,
    VOLCENGINE_VOICES,
)
from voice_toolbox.models import ModelInfo, ProviderOptionSpec

logger = logging.getLogger(__name__)

__all__ = [
    "APIConfig",
    "ASRChunkingConfig",
    "AppConfig",
    "ChunkingConfig",
    "ConfigError",
    "ConfiguredProvider",
    "ConsoleLoggingConfig",
    "FileLoggingConfig",
    "LoggingConfig",
    "ProviderDefaultModels",
    "TTSChunkingConfig",
    "load_app_config",
    "load_env_values",
    "mask_api_key_preview",
    "preview_config_path",
    "replay_config_warnings",
]

IGNORED_WHEN_TOML_ACTIVE = (
    "MIMO_BASE_URL",
    "VOICE_TOOLBOX_API_HOST",
    "VOICE_TOOLBOX_API_PORT",
    "API_HOST",
    "API_PORT",
)


class ConfigError(RuntimeError):
    pass


def load_app_config(
    path: Path | str | None = None,
    *,
    env_path: Path | str | None = None,
    env_values: dict[str, str] | None = None,
    emit_warnings: bool = True,
) -> AppConfig:
    env = env_values if env_values is not None else load_env_values(env_path)
    config_path = _discover_config_path(path, env, include_cwd=env_path is None)
    if config_path is None:
        return _fallback_config(env)
    payload = _read_toml(config_path)
    payload["config_path"] = config_path
    if emit_warnings:
        _warn_ignored_env(env)
    try:
        if not payload.get("providers"):
            if emit_warnings:
                logger.warning("providers is empty; using built-in default provider")
            payload["providers"] = [_default_provider_payload(env, use_env_base_url=False)]
        payload["providers"] = [
            _fill_provider_defaults(provider) for provider in payload["providers"]
        ]
        return AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(_safe_validation_message(exc)) from exc


def load_env_values(env_path: Path | str | None = None) -> dict[str, str]:
    values: dict[str, object] = {}
    path = Path(env_path) if env_path is not None else Path.cwd() / ".env"
    if env_path is not None and not path.exists():
        raise ConfigError(f"env file does not exist: {path}")
    if path.exists():
        values.update(dotenv_values(path))
    values.update(os.environ)
    return {key: str(value) for key, value in values.items() if value is not None}


def mask_api_key_preview(value: str | None, *, trusted_local: bool) -> str | None:
    if not value:
        return None
    if not trusted_local:
        return "configured"
    if len(value) <= 8:
        return "configured"
    if "-" in value:
        prefix = value.split("-", 1)[0] + "-"
        if len(value) <= len(prefix) + 8:
            return "configured"
        return f"{prefix}...{value[-4:]}"
    return f"...{value[-4:]}"


def preview_config_path(path: Path | None) -> str:
    if path is None:
        return "built-in default"
    parent = path.parent.name
    return f"{parent}/{path.name}" if parent else path.name


def _discover_config_path(
    path: Path | str | None,
    env: dict[str, str],
    *,
    include_cwd: bool = True,
) -> Path | None:
    if path is not None:
        candidate = Path(path)
        if not candidate.exists():
            raise ConfigError(f"config file does not exist: {candidate}")
        return candidate
    env_path = env.get("VOICE_TOOLBOX_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if not candidate.exists():
            raise ConfigError(f"VOICE_TOOLBOX_CONFIG points to missing file: {candidate}")
        return candidate
    if not include_cwd:
        return None
    cwd_candidate = Path.cwd() / "voice_toolbox.toml"
    return cwd_candidate if cwd_candidate.exists() else None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            payload = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return dict(payload)


def _fallback_config(env: dict[str, str]) -> AppConfig:
    try:
        payload = {
            "config_path": None,
            "api": {
                "host": env.get("VOICE_TOOLBOX_API_HOST") or env.get("API_HOST") or "127.0.0.1",
                "port": int(env.get("VOICE_TOOLBOX_API_PORT") or env.get("API_PORT") or "8000"),
            },
            "providers": [_default_provider_payload(env, use_env_base_url=True)],
        }
        return AppConfig.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise ConfigError(_safe_validation_message(exc)) from exc
        raise ConfigError(str(exc)) from exc


def _default_provider_payload(env: dict[str, str], *, use_env_base_url: bool) -> dict[str, Any]:
    base_url = env.get("MIMO_BASE_URL") if use_env_base_url else None
    return {
        "id": "mimo",
        "type": "mimo",
        "name": "MiMo",
        "base_url": base_url or DEFAULT_MIMO_BASE_URL,
        "api_key_env": "MIMO_API_KEY",
        "default_voice": "mimo_default",
        "default_models": DEFAULT_MIMO_MODELS.model_dump(),
        "models": [model.model_dump() for model in MIMO_MODELS],
        "voices": [voice.model_dump() for voice in MIMO_VOICES],
    }


def _warn_ignored_env(env: dict[str, str]) -> None:
    for key in IGNORED_WHEN_TOML_ACTIVE:
        if env.get(key):
            logger.warning("ignored env var %s because voice_toolbox.toml is active", key)


def replay_config_warnings(config: AppConfig, env: dict[str, str]) -> None:
    if config.config_path is None:
        return
    try:
        payload = _read_toml(config.config_path)
    except ConfigError:
        payload = {}
    if not payload.get("providers"):
        logger.warning("providers is empty; using built-in default provider")
    _warn_ignored_env(env)


def _fill_mimo_defaults(provider: dict[str, Any]) -> dict[str, Any]:
    return _fill_provider_defaults(provider)


def _fill_provider_defaults(provider: dict[str, Any]) -> dict[str, Any]:
    if provider.get("type") == "mimo":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_MIMO_MODELS,
            models=MIMO_MODELS,
            voices=MIMO_VOICES,
        )
    if provider.get("type") == "fish_audio":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_FISH_AUDIO_MODELS,
            models=FISH_AUDIO_MODELS,
            voices=FISH_AUDIO_VOICES,
        )
    if provider.get("type") == "openrouter":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_OPENROUTER_MODELS,
            models=OPENROUTER_MODELS,
            voices=OPENROUTER_VOICES,
        )
    if provider.get("type") == "mlx_audio":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_MLX_AUDIO_MODELS,
            models=MLX_AUDIO_MODELS,
            voices=MLX_AUDIO_VOICES,
            options=MLX_AUDIO_TTS_OPTIONS,
            default_voice=MLX_AUDIO_DEFAULT_VOICE_ID,
        )
    if provider.get("type") == "volcengine":
        return _fill_defaults_for_provider(
            provider,
            default_models=DEFAULT_VOLCENGINE_MODELS,
            models=VOLCENGINE_MODELS,
            voices=VOLCENGINE_VOICES,
        )
    return dict(provider)


def _fill_defaults_for_provider(
    provider: dict[str, Any],
    *,
    default_models: ProviderDefaultModels,
    models: list[ModelInfo],
    voices: list[Any],
    options: list[ProviderOptionSpec] | None = None,
    default_voice: str | None = None,
) -> dict[str, Any]:
    result = dict(provider)
    had_models = "models" in result
    had_voices = "voices" in result
    if "models" not in result:
        result["models"] = [model.model_dump() for model in models]
    if "voices" not in result:
        result["voices"] = [voice.model_dump() for voice in voices]
    if "options" not in result and options:
        result["options"] = [option.model_dump() for option in options]
    if "default_voice" not in result and not had_voices:
        if default_voice is not None:
            result["default_voice"] = default_voice
        elif voices:
            result["default_voice"] = voices[0].id
    models = [ModelInfo.model_validate(model) for model in result.get("models", [])]
    models_by_capability: dict[str, str] = {}
    for model in models:
        if model.capability and model.capability not in models_by_capability:
            models_by_capability[model.capability] = model.id
    current_defaults = ProviderDefaultModels.model_validate(result.get("default_models") or {})
    builtin_defaults = default_models if not had_models else ProviderDefaultModels()
    fallback = ProviderDefaultModels(
        tts_builtin=(
            current_defaults.tts_builtin
            or models_by_capability.get("tts.builtin")
            or builtin_defaults.tts_builtin
        ),
        tts_design=(
            current_defaults.tts_design
            or models_by_capability.get("tts.design")
            or builtin_defaults.tts_design
        ),
        tts_clone=(
            current_defaults.tts_clone
            or models_by_capability.get("tts.clone")
            or builtin_defaults.tts_clone
        ),
        asr=current_defaults.asr
        or models_by_capability.get("asr.transcribe")
        or builtin_defaults.asr,
    )
    result["default_models"] = fallback.model_dump()
    return result


def _safe_validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error.get("loc", ())) or "config"
        msg = str(error.get("msg", "invalid value"))
        error_type = str(error.get("type", "validation_error"))
        parts.append(f"{loc}: {msg} ({error_type})")
    return "; ".join(parts) or "invalid config"
