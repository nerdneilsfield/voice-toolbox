from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config import AppConfig, load_env_values
from voice_toolbox.providers.fish_audio import FishAudioProvider
from voice_toolbox.providers.mimo import MimoProvider
from voice_toolbox.providers.openrouter import OpenRouterProvider
from voice_toolbox.providers.registry import ProviderRegistry


def build_provider_registry(
    config: AppConfig,
    *,
    artifact_root: Path | str,
    env_values: Mapping[str, str] | None = None,
) -> ProviderRegistry:
    env = dict(load_env_values() if env_values is None else env_values)
    root = Path(artifact_root)
    providers = []
    for provider_config in config.providers:
        if provider_config.type == "mimo":
            providers.append(
                MimoProvider(
                    config=provider_config,
                    api_key=env.get(provider_config.api_key_env),
                    artifact_store=ArtifactStore(root),
                )
            )
        elif provider_config.type == "fish_audio":
            providers.append(
                FishAudioProvider(
                    config=provider_config,
                    api_key=env.get(provider_config.api_key_env),
                    artifact_store=ArtifactStore(root),
                )
            )
        elif provider_config.type == "openrouter":
            providers.append(
                OpenRouterProvider(
                    config=provider_config,
                    api_key=env.get(provider_config.api_key_env),
                    artifact_store=ArtifactStore(root),
                )
            )
    return ProviderRegistry(providers)
