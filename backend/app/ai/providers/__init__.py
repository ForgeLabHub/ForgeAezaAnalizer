"""Provider factory.

Selects the runtime from configuration.  ``mock`` is the default so a checkout
without a model still answers deterministically; ``ollama`` is the local runtime
the product uses for real explanations.
"""

from __future__ import annotations

import os

from ..config import AISettings
from .base import Generation, Provider, ProviderError, ProviderUnavailable
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = [
    "Generation",
    "MockProvider",
    "OllamaProvider",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "build_provider",
]


def build_provider(settings: AISettings) -> Provider:
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider == "ollama":
        allow_remote = os.getenv("AEZA_AI_ALLOW_REMOTE", "0").strip().lower() in {"1", "true"}
        return OllamaProvider(base_url=settings.base_url, model=settings.model, allow_remote=allow_remote)
    raise ValueError(f"unknown AI provider: {settings.provider}")
