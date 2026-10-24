from __future__ import annotations

import os
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
    # --- Telegram integration -------------------------------------------------
    # Off by default and never fatal: a missing bot token must not stop the
    # analytics app from starting. The token is read from the environment only —
    # never from the database, the repo or the frontend.
    telegram_enabled: bool = field(default_factory=lambda: flag("TELEGRAM_ENABLED", False))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    #: Shared secret Telegram echoes back in X-Telegram-Bot-Api-Secret-Token.
    telegram_webhook_secret: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_SECRET", ""))
    telegram_webhook_url: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_URL", ""))
    telegram_api_base: str = field(default_factory=lambda: os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org"))
    telegram_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "10")))
    telegram_link_code_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_LINK_CODE_TTL_SECONDS", "600")))
    telegram_link_max_attempts: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_LINK_MAX_ATTEMPTS", "5")))
    #: Minimum seconds between two messages to the same chat, to bound spam.
    telegram_min_send_interval_seconds: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_MIN_SEND_INTERVAL_SECONDS", "3")))
    telegram_max_retries: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_MAX_RETRIES", "2")))
    #: Public base URL used to build deep links back into the Sentinel UI.
    telegram_app_base_url: str = field(default_factory=lambda: os.getenv("TELEGRAM_APP_BASE_URL", "http://localhost:8080"))
    #: How often the digest scheduler checks whether a digest is due. Small
    #: enough to be punctual, large enough not to spin. The digest itself is
    #: deduplicated per UTC day, so a check that is too frequent is harmless.
    telegram_digest_check_seconds: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_DIGEST_CHECK_SECONDS", "300")))
    #: UTC hour at which the daily digest is sent.
    telegram_digest_hour_utc: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_DIGEST_HOUR_UTC", "9")))
    api_prefix: str = "/api/v1"
    app_name: str = "Aéza Analyzer"

    def __post_init__(self):
        if not 1 <= self.recalculate_seconds <= 3600:
            raise ValueError("AEZA_RECALCULATE_SECONDS must be between 1 and 3600")
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
        # Telegram is validated only when it is switched on. An incomplete or
        # absent configuration must leave the rest of the app fully usable, so
        # nothing here raises unless the operator asked for the feature.
        if self.telegram_enabled:
            if not self.telegram_bot_token.strip():
                raise ValueError("TELEGRAM_BOT_TOKEN is required when TELEGRAM_ENABLED=1")
            if not self.telegram_webhook_secret.strip():
                raise ValueError("TELEGRAM_WEBHOOK_SECRET is required when TELEGRAM_ENABLED=1")
            if not self.telegram_api_base.startswith(("http://", "https://")):
                raise ValueError("TELEGRAM_API_BASE must be an http(s) URL")
            if not 1 <= self.telegram_timeout_seconds <= 120:
                raise ValueError("TELEGRAM_TIMEOUT_SECONDS must be between 1 and 120")
            if not 30 <= self.telegram_link_code_ttl_seconds <= 3600:
                raise ValueError("TELEGRAM_LINK_CODE_TTL_SECONDS must be between 30 and 3600")
            if not 1 <= self.telegram_link_max_attempts <= 20:
                raise ValueError("TELEGRAM_LINK_MAX_ATTEMPTS must be between 1 and 20")
            if not 0 <= self.telegram_max_retries <= 5:
                raise ValueError("TELEGRAM_MAX_RETRIES must be between 0 and 5")
            if not 30 <= self.telegram_digest_check_seconds <= 86400:
                raise ValueError("TELEGRAM_DIGEST_CHECK_SECONDS must be between 30 and 86400")
            if not 0 <= self.telegram_digest_hour_utc <= 23:
                raise ValueError("TELEGRAM_DIGEST_HOUR_UTC must be between 0 and 23")
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
