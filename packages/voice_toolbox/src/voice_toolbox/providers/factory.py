from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from voice_toolbox.artifacts import ArtifactStore
from voice_toolbox.config import AppConfig, load_env_values
from voice_toolbox.config_models import ConfiguredProvider
from voice_toolbox.providers.base import ProviderError
from voice_toolbox.providers.fish_audio import FishAudioProvider
from voice_toolbox.providers.mlx_audio import MlxAudioProvider
from voice_toolbox.providers.mimo import MimoProvider
from voice_toolbox.providers.openrouter import OpenRouterProvider
from voice_toolbox.providers.registry import ProviderRegistry


def _api_key_for_network_provider(
    provider_config: ConfiguredProvider, env: Mapping[str, str]
) -> str | None:
    if provider_config.api_key_env is None:
        raise ProviderError(f"provider {provider_config.id} requires api_key_env")
    return env.get(provider_config.api_key_env)


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
                    api_key=_api_key_for_network_provider(provider_config, env),
                    artifact_store=ArtifactStore(root),
                )
            )
        elif provider_config.type == "fish_audio":
            providers.append(
                FishAudioProvider(
                    config=provider_config,
                    api_key=_api_key_for_network_provider(provider_config, env),
                    artifact_store=ArtifactStore(root),
                )
            )
        elif provider_config.type == "openrouter":
            providers.append(
                OpenRouterProvider(
                    config=provider_config,
                    api_key=_api_key_for_network_provider(provider_config, env),
                    artifact_store=ArtifactStore(root),
                )
            )
        elif provider_config.type == "mlx_audio":
            providers.append(
                MlxAudioProvider(
                    config=provider_config,
                    artifact_store=ArtifactStore(root),
                )
            )
    return ProviderRegistry(providers)
