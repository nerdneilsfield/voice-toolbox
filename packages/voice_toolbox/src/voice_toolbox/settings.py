from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from voice_toolbox.models import ProviderConfig


def _default_env_path() -> Path | None:
    path = Path.cwd() / ".env"
    return path if path.exists() else None


def _env_cache_key(env_path: Path | str | None) -> str:
    if env_path is not None:
        return str(Path(env_path))
    default_path = _default_env_path()
    return str(default_path) if default_path is not None else ""


@lru_cache(maxsize=16)
def _load_env_values(env_path: str) -> dict[str, str]:
    values = dict(os.environ)
    path = Path(env_path) if env_path else None
    if path is not None:
        values = {**dotenv_values(path), **values}
    return {key: str(value) for key, value in values.items() if value is not None}


def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    values = _load_env_values(_env_cache_key(env_path))

    base_url = values.get("MIMO_BASE_URL") or ProviderConfig().base_url
    api_host = values.get("VOICE_TOOLBOX_API_HOST") or values.get("API_HOST") or "127.0.0.1"
    api_port = int(values.get("VOICE_TOOLBOX_API_PORT") or values.get("API_PORT") or "8000")
    return ProviderConfig(base_url=base_url, api_host=api_host, api_port=api_port)


def get_mimo_api_key(env_path: Path | str | None = None) -> str | None:
    settings = load_settings(env_path)
    values = _load_env_values(_env_cache_key(env_path))
    value = values.get(settings.api_key_env)
    return value if value else None


def has_mimo_api_key(env_path: Path | str | None = None) -> bool:
    return get_mimo_api_key(env_path) is not None
