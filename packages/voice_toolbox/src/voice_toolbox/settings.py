from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from voice_toolbox.models import ProviderConfig


def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    values = dict(os.environ)
    if env_path is not None:
        values = {**dotenv_values(env_path), **values}

    base_url = values.get("MIMO_BASE_URL") or ProviderConfig().base_url
    return ProviderConfig(base_url=base_url)


def get_mimo_api_key(env_path: Path | str | None = None) -> str | None:
    settings = load_settings(env_path)
    values = dict(os.environ)
    if env_path is not None:
        values = {**dotenv_values(env_path), **values}
    value = values.get(settings.api_key_env)
    return value if value else None


def has_mimo_api_key(env_path: Path | str | None = None) -> bool:
    return get_mimo_api_key(env_path) is not None
