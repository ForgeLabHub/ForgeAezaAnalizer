"""Provider interface and shared error types.

A provider is the only component that talks to a model runtime.  Business logic
depends on this interface, never on Ollama directly, so the runtime can be
replaced (or faked in tests) without touching the service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Raised when the model runtime is unreachable or returns an unusable reply."""


class ProviderUnavailable(ProviderError):
    """The runtime is not reachable at all (not merely a bad answer)."""


@dataclass(frozen=True)
class Generation:
    """Raw provider output plus the measurements we report."""

    text: str
    model: str
    provider: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider(Protocol):
    name: str

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict | None = None,
        num_ctx: int,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> Generation: ...

    def health(self, *, timeout: float) -> bool: ...
