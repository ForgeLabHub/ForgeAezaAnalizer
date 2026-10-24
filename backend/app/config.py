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
    telegram_bot_enabled: bool = field(default_factory=lambda: flag("AEZA_TELEGRAM_BOT_ENABLED", False))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("AEZA_TELEGRAM_BOT_TOKEN", ""))
    telegram_webhook_secret: str = field(default_factory=lambda: os.getenv("AEZA_TELEGRAM_WEBHOOK_SECRET", ""))
    telegram_mini_app_url: str = field(default_factory=lambda: os.getenv("AEZA_TELEGRAM_MINI_APP_URL", ""))
    #: Public HTTPS URL of this API plus /telegram/webhook. Registration is an
    #: explicit operator action (POST /telegram/webhook/register), never automatic
    #: on startup, so a restart cannot race another instance or drop updates.
    telegram_webhook_url: str = field(default_factory=lambda: os.getenv("AEZA_TELEGRAM_WEBHOOK_URL", ""))
    telegram_auth_max_age_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400")))
    telegram_session_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_SESSION_TTL_SECONDS", "3600")))
    telegram_otp_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_TTL_SECONDS", "600")))
    telegram_otp_resend_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_RESEND_SECONDS", "60")))
    telegram_otp_max_attempts: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_MAX_ATTEMPTS", "5")))
    telegram_worker_interval_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_WORKER_INTERVAL_SECONDS", "180")))
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
    # --- Outbound e-mail (SMTP.BZ HTTP API) -----------------------------------
    # The key is read from the environment only; it is never written to a file,
    # an image or a log line. An empty key means "not configured", which the
    # e-mail surface reports honestly instead of pretending to have sent.
    smtp_bz_api_key: str = field(default_factory=lambda: os.getenv("SMTP_BZ_API_KEY", ""))
    smtp_bz_api_url: str = field(default_factory=lambda: os.getenv(
        "SMTP_BZ_API_URL", "https://api.smtp.bz/v1/smtp/send"))
    smtp_bz_from_email: str = field(default_factory=lambda: os.getenv("SMTP_BZ_FROM_EMAIL", ""))
    smtp_bz_from_name: str = field(default_factory=lambda: os.getenv("SMTP_BZ_FROM_NAME", ""))
    smtp_bz_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("SMTP_BZ_TIMEOUT_SECONDS", "15")))
    api_prefix: str = "/api/v1"
    app_name: str = "Aéza Analyzer"

    @property
    def email_configured(self) -> bool:
        """True when every field needed for a send is present."""

        return bool(self.smtp_bz_api_key and self.smtp_bz_from_email)

    def __post_init__(self):
        if not 1 <= self.recalculate_seconds <= 3600:
            raise ValueError("AEZA_RECALCULATE_SECONDS must be between 1 and 3600")
        for name, value, maximum in (
            ("AEZA_TELEGRAM_AUTH_MAX_AGE_SECONDS", self.telegram_auth_max_age_seconds, 86400),
            ("AEZA_TELEGRAM_SESSION_TTL_SECONDS", self.telegram_session_ttl_seconds, 86400),
            ("AEZA_TELEGRAM_OTP_TTL_SECONDS", self.telegram_otp_ttl_seconds, 3600),
            ("AEZA_TELEGRAM_OTP_RESEND_SECONDS", self.telegram_otp_resend_seconds, 3600),
            ("AEZA_TELEGRAM_OTP_MAX_ATTEMPTS", self.telegram_otp_max_attempts, 10),
            ("AEZA_TELEGRAM_WORKER_INTERVAL_SECONDS", self.telegram_worker_interval_seconds, 3600),
        ):
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        if self.telegram_bot_enabled and (not self.telegram_bot_token or not self.telegram_webhook_secret):
            raise ValueError("Telegram bot requires AEZA_TELEGRAM_BOT_TOKEN and AEZA_TELEGRAM_WEBHOOK_SECRET")
        # --- Outbound e-mail (SMTP.BZ) ---------------------------------------
        # Restored after the Telegram merge dropped it: an out-of-range timeout,
        # a plain-HTTP provider URL or a malformed sender must fail fast at
        # startup rather than at the first send.
        if not 1 <= self.smtp_bz_timeout_seconds <= 120:
            raise ValueError("SMTP_BZ_TIMEOUT_SECONDS must be between 1 and 120")
        if self.email_configured:
            loopback = ("http://localhost", "http://127.0.0.1", "http://[::1]")
            if not self.smtp_bz_api_url.startswith("https://") and not self.smtp_bz_api_url.startswith(loopback):
                raise ValueError("SMTP_BZ_API_URL must use HTTPS; HTTP is allowed only on loopback")
            if "@" not in self.smtp_bz_from_email:
                raise ValueError("SMTP_BZ_FROM_EMAIL must be a valid e-mail address")
        if self.telegram_webhook_url and not self.telegram_webhook_url.startswith("https://"):
            raise ValueError("AEZA_TELEGRAM_WEBHOOK_URL must be an https:// URL (Telegram requires HTTPS)")
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
