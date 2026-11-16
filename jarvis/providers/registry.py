"""Chooses the AI provider from configuration.

Providers are looked up by name in a registry so new ones (MLX, other local
runtimes, approved external services) can be plugged in without touching the
orchestrator. External providers are refused unless explicitly allowed.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from ..config import LOOPBACK_HOSTS, Config
from .base import AIProvider, NullProvider
from .ollama import OllamaProvider

Factory = Callable[[Config], AIProvider]
_FACTORIES: dict[str, Factory] = {}


def register_provider(name: str, factory: Factory) -> None:
    _FACTORIES[name.strip().lower()] = factory


def available_providers() -> list[str]:
    return sorted(_FACTORIES)


def _is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOOPBACK_HOSTS


def _ollama(config: Config) -> AIProvider:
    if not _is_loopback(config.ollama_url) and not config.allow_external_ai:
        return NullProvider(
            f"JARVIS_OLLAMA_URL ({config.ollama_url}) is not on this machine, which would send your "
            "data elsewhere. Use a local address or set JARVIS_ALLOW_EXTERNAL_AI=true."
        )
    local = OllamaProvider(config.ollama_url, config.ai_model, config.ai_timeout_seconds)
    from .boost import Boosted, OpenAICompatible, boost_settings
    boost = boost_settings() if config.allow_external_ai else None
    if boost:                     # more power from an open-model platform; the Mac's model is the fallback
        return Boosted(local, OpenAICompatible(*boost))
    return local


def _mlx(config: Config) -> AIProvider:
    return NullProvider("Apple MLX support is planned but not implemented yet. No model is connected.")


register_provider("none", lambda config: NullProvider())
register_provider("ollama", _ollama)
register_provider("mlx", _mlx)


def build_provider(config: Config) -> AIProvider:
    """Return the configured provider, or a NullProvider explaining why not."""
    factory = _FACTORIES.get(config.ai_provider)
    if factory is None:
        return NullProvider(
            f"Unknown AI provider '{config.ai_provider}'. "
            f"Supported values: {', '.join(available_providers())}."
        )
    provider = factory(config)
    if not provider.is_local and not config.allow_external_ai:
        return NullProvider(
            f"'{config.ai_provider}' is an external provider and JARVIS_ALLOW_EXTERNAL_AI is false."
        )
    return provider
