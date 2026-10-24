"""Environment-driven configuration for the local AI Analyst.

Read lazily on each access, mirroring ``backend.app.config`` so tests can repoint
the environment without reloading modules.  Nothing here reaches the network; the
provider is selected by name and the default is the offline ``mock`` provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered not in {"0", "1", "true", "false"}:
        raise ValueError(f"{name}: expected 0/1/true/false")
    return lowered in {"1", "true"}


def _int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _float(name: str, default: float, *, low: float, high: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class AISettings:
    """AI Analyst configuration.

    ``enabled`` is the master feature flag and defaults to **off**: a stock
    checkout must never block on, or silently call, a model that may not exist.
    """

    enabled: bool = field(default_factory=lambda: _flag("AEZA_AI_ENABLED", False))
    provider: str = field(default_factory=lambda: os.getenv("AEZA_AI_PROVIDER", "mock").strip().lower())
    base_url: str = field(default_factory=lambda: os.getenv("AEZA_AI_BASE_URL", "http://127.0.0.1:11434").rstrip("/"))
    model: str = field(default_factory=lambda: os.getenv("AEZA_AI_MODEL", "qwen2.5:3b-instruct").strip())
    request_timeout_seconds: float = field(default_factory=lambda: _float("AEZA_AI_TIMEOUT_SECONDS", 180.0, low=1.0, high=900.0))
    max_concurrency: int = field(default_factory=lambda: _int("AEZA_AI_MAX_CONCURRENCY", 1, low=1, high=16))
    max_question_chars: int = field(default_factory=lambda: _int("AEZA_AI_MAX_QUESTION_CHARS", 2000, low=16, high=20000))
    num_ctx: int = field(default_factory=lambda: _int("AEZA_AI_NUM_CTX", 4096, low=512, high=32768))
    max_tokens: int = field(default_factory=lambda: _int("AEZA_AI_MAX_TOKENS", 1200, low=64, high=4096))
    temperature: float = field(default_factory=lambda: _float("AEZA_AI_TEMPERATURE", 0.1, low=0.0, high=1.0))
    #: Total character budget for the retrieved documentation block.  Small by
    #: default because CPU prompt evaluation dominates latency.
    max_context_chars: int = field(default_factory=lambda: _int("AEZA_AI_MAX_CONTEXT_CHARS", 1600, low=200, high=40000))
    #: Number of local documentation chunks injected per question.
    rag_top_k: int = field(default_factory=lambda: _int("AEZA_AI_RAG_TOP_K", 2, low=0, high=20))
    #: Extra generation attempts when the first answer fails grounding validation.
    max_retries: int = field(default_factory=lambda: _int("AEZA_AI_MAX_RETRIES", 1, low=0, high=3))
    rag_index_path: str = field(default_factory=lambda: os.getenv(
        "AEZA_AI_RAG_INDEX_PATH", str(ROOT / "backend" / "data" / "rag_index.json")))
    docs_path: str = field(default_factory=lambda: os.getenv("AEZA_AI_DOCS_PATH", str(ROOT / "docs")))

    def __post_init__(self) -> None:
        if self.provider not in {"mock", "ollama"}:
            raise ValueError("AEZA_AI_PROVIDER must be 'mock' or 'ollama'")
        if not self.model:
            raise ValueError("AEZA_AI_MODEL must not be empty")


def ai_settings() -> AISettings:
    """Build a fresh settings object so tests can change the environment."""

    return AISettings()
