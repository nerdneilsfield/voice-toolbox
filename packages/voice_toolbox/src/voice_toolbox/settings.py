from __future__ import annotations

from pathlib import Path

from voice_toolbox.config import load_app_config, load_env_values
from voice_toolbox.config_models import ConfiguredProvider
from voice_toolbox.defaults import DEFAULT_MIMO_BASE_URL
from voice_toolbox.models import ProviderConfig


def _first_network_provider(providers: list[ConfiguredProvider]) -> tuple[ConfiguredProvider, str, str]:
    for provider in providers:
        base_url = provider.base_url
        api_key_env = provider.api_key_env
        if base_url is not None and api_key_env is not None:
            return provider, base_url, api_key_env
    raise ValueError("legacy settings require a network provider")


def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    """Legacy single-provider compatibility wrapper; prefer load_app_config()."""

    if env_path is not None:
        env = load_env_values(env_path)
        return ProviderConfig(
            provider_id="mimo",
            base_url=env.get("MIMO_BASE_URL") or DEFAULT_MIMO_BASE_URL,
            api_key_env="MIMO_API_KEY",
            api_host=env.get("VOICE_TOOLBOX_API_HOST") or env.get("API_HOST") or "127.0.0.1",
            api_port=int(env.get("VOICE_TOOLBOX_API_PORT") or env.get("API_PORT") or "8000"),
        )

    app_config = load_app_config(env_path=env_path)
    provider, base_url, api_key_env = _first_network_provider(app_config.providers)
    return ProviderConfig(
        provider_id=provider.id,
        base_url=base_url,
        api_key_env=api_key_env,
        api_host=app_config.api.host,
        api_port=app_config.api.port,
    )


def get_mimo_api_key(env_path: Path | str | None = None) -> str | None:
    """Legacy MiMo key helper; prefer provider-specific AppConfig lookup."""

    app_config = load_app_config(env_path=env_path)
    env = load_env_values(env_path)
    provider = next(
        (item for item in app_config.providers if item.id == "mimo" and item.api_key_env is not None),
        None,
    )
    if provider is None:
        provider = next((item for item in app_config.providers if item.api_key_env is not None), None)
    if provider is None or provider.api_key_env is None:
        return None
    value = env.get(provider.api_key_env)
    return value if value else None


def has_mimo_api_key(env_path: Path | str | None = None) -> bool:
    """Legacy MiMo key presence helper; prefer provider-specific AppConfig lookup."""

    return get_mimo_api_key(env_path) is not None
