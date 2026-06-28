from __future__ import annotations

from pathlib import Path

from voice_toolbox.config import load_app_config, load_env_values
from voice_toolbox.models import ProviderConfig


def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    """Legacy single-provider compatibility wrapper; prefer load_app_config()."""

    app_config = load_app_config(env_path=env_path)
    provider = app_config.providers[0]
    return ProviderConfig(
        provider_id=provider.id,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        api_host=app_config.api.host,
        api_port=app_config.api.port,
    )


def get_mimo_api_key(env_path: Path | str | None = None) -> str | None:
    """Legacy MiMo key helper; prefer provider-specific AppConfig lookup."""

    app_config = load_app_config(env_path=env_path)
    env = load_env_values(env_path)
    provider = next(
        (item for item in app_config.providers if item.id == "mimo"), app_config.providers[0]
    )
    value = env.get(provider.api_key_env)
    return value if value else None


def has_mimo_api_key(env_path: Path | str | None = None) -> bool:
    """Legacy MiMo key presence helper; prefer provider-specific AppConfig lookup."""

    return get_mimo_api_key(env_path) is not None
