from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from voice_toolbox.models import ProviderConfig


def load_settings(env_path: Path | str | None = None) -> ProviderConfig:
    load_dotenv(dotenv_path=env_path, override=False)
    return ProviderConfig()


def get_mimo_api_key(env_path: Path | str | None = None) -> str | None:
    settings = load_settings(env_path)
    value = os.getenv(settings.api_key_env)
    return value if value else None


def has_mimo_api_key(env_path: Path | str | None = None) -> bool:
    return get_mimo_api_key(env_path) is not None
