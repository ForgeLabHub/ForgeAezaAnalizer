from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AS_OF = "2026-10-19T15:00:00+00:00"


def flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() not in {"0", "1", "true", "false"}:
        raise ValueError(f"{name}: expected 0/1/true/false")
    return value.lower() in {"1", "true"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "AEZA_DATABASE_URL", "postgresql+psycopg://aeza:aeza@localhost:5432/aeza"))
    auth_database_url: str = field(default_factory=lambda: os.getenv(
        "AEZA_AUTH_DATABASE_URL", f"sqlite:///{(ROOT / 'db' / 'auth.sqlite3').as_posix()}"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("AEZA_JWT_SECRET", ""))
    # Secure by default: refuse to invent a signing secret unless a local
    # development environment explicitly opts in with AEZA_ALLOW_DEV_SECRET=1.
    allow_dev_secret: bool = field(default_factory=lambda: flag("AEZA_ALLOW_DEV_SECRET", False))
    bootstrap_admin_email: str = field(default_factory=lambda: os.getenv("AEZA_ADMIN_EMAIL", "analyst@aeza.test"))
    bootstrap_admin_password: str = field(default_factory=lambda: os.getenv("AEZA_ADMIN_PASSWORD", ""))
    access_token_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("AEZA_TOKEN_TTL_MINUTES", "720")))
    login_max_attempts: int = field(default_factory=lambda: int(os.getenv("AEZA_LOGIN_MAX_ATTEMPTS", "10")))
    login_window_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_LOGIN_WINDOW_SECONDS", "300")))
    seed_demo_data: bool = field(default_factory=lambda: flag("AEZA_SEED_DEMO_DATA", False))
    snapshot_path: str = field(default_factory=lambda: os.getenv("AEZA_SNAPSHOT_PATH", str(ROOT / "dataset/data.json")))
    as_of: str = field(default_factory=lambda: os.getenv("AEZA_AS_OF", DEFAULT_AS_OF))
    recalculate_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_RECALCULATE_SECONDS", "60")))
    metrics_token: str = field(default_factory=lambda: os.getenv("AEZA_METRICS_TOKEN", ""))
    # --- Local LLM (Ollama) ---------------------------------------------------
    # Disabled by default: an unavailable model must never be presented as if it
    # had answered. The provider URL is configuration, never a hardcoded host.
    #
    # Two env-var spellings are accepted for the same provider so the AI layer
    # has a single source of truth: AEZA_OLLAMA_* wins, AEZA_LLM_* is the older
    # alias and still works. The default host is the address Ollama is reachable
    # at from inside the Compose network (the Docker bridge gateway).
    llm_enabled: bool = field(default_factory=lambda: flag("AEZA_LLM_ENABLED", False))
    llm_base_url: str = field(default_factory=lambda: os.getenv("AEZA_OLLAMA_URL")
                              or os.getenv("AEZA_LLM_BASE_URL", "http://172.18.0.1:11434"))
    llm_model: str = field(default_factory=lambda: os.getenv("AEZA_OLLAMA_MODEL")
                           or os.getenv("AEZA_LLM_MODEL", "qwen2.5:7b"))
    llm_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_OLLAMA_TIMEOUT_SECONDS")
                                                                 or os.getenv("AEZA_LLM_TIMEOUT_SECONDS", "90")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("AEZA_OLLAMA_MAX_TOKENS")
                                                            or os.getenv("AEZA_LLM_MAX_TOKENS", "700")))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("AEZA_OLLAMA_TEMPERATURE")
                                                                 or os.getenv("AEZA_LLM_TEMPERATURE", "0.2")))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        origin.strip() for origin in os.getenv("AEZA_CORS_ORIGINS", "http://localhost:8080,http://localhost:5173").split(",") if origin.strip()))
    api_prefix: str = "/api/v1"
    app_name: str = "Aéza Analyzer"

    def __post_init__(self):
        if not self.jwt_secret:
            if not self.allow_dev_secret:
                raise ValueError("AEZA_JWT_SECRET is required")
            object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(48))
        if not self.allow_dev_secret and not self.bootstrap_admin_password:
            raise ValueError("AEZA_ADMIN_PASSWORD is required")
        if not 1 <= self.access_token_ttl_minutes <= 1440:
            raise ValueError("AEZA_TOKEN_TTL_MINUTES must be between 1 and 1440")
        if not 1 <= self.recalculate_seconds <= 3600:
            raise ValueError("AEZA_RECALCULATE_SECONDS must be between 1 and 3600")
        if self.login_max_attempts < 1:
            raise ValueError("AEZA_LOGIN_MAX_ATTEMPTS must be at least 1")
        if self.login_window_seconds < 1:
            raise ValueError("AEZA_LOGIN_WINDOW_SECONDS must be at least 1")
        if self.llm_enabled:
            if not self.llm_base_url.startswith(("http://", "https://")):
                raise ValueError("AEZA_LLM_BASE_URL must be an http(s) URL")
            if not self.llm_model.strip():
                raise ValueError("AEZA_LLM_MODEL must not be empty when AEZA_LLM_ENABLED=1")
            if not 1 <= self.llm_timeout_seconds <= 600:
                raise ValueError("AEZA_LLM_TIMEOUT_SECONDS must be between 1 and 600")
            if not 16 <= self.llm_max_tokens <= 8192:
                raise ValueError("AEZA_LLM_MAX_TOKENS must be between 16 and 8192")
            if not 0.0 <= self.llm_temperature <= 2.0:
                raise ValueError("AEZA_LLM_TEMPERATURE must be between 0 and 2")
        self.reference_now()

    def reference_now(self) -> datetime:
        if self.as_of.lower() == "now":
            return datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("AEZA_AS_OF must include a timezone")
        return parsed.astimezone(timezone.utc)


@lru_cache
def get_settings() -> Settings:
    return Settings()
