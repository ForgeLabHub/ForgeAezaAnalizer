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


    telegram_webhook_url: str = field(default_factory=lambda: os.getenv("AEZA_TELEGRAM_WEBHOOK_URL", ""))
    telegram_auth_max_age_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400")))
    telegram_session_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_SESSION_TTL_SECONDS", "3600")))
    telegram_otp_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_TTL_SECONDS", "600")))
    telegram_otp_resend_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_RESEND_SECONDS", "60")))
    telegram_otp_max_attempts: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_OTP_MAX_ATTEMPTS", "5")))
    telegram_worker_interval_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_TELEGRAM_WORKER_INTERVAL_SECONDS", "180")))


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


    email_provider: str = field(default_factory=lambda: os.getenv("AEZA_EMAIL_PROVIDER", "").strip().lower())

    postbox_username: str = field(default_factory=lambda: os.getenv("POSTBOX_SMTP_USERNAME", ""))
    postbox_password: str = field(default_factory=lambda: os.getenv("POSTBOX_SMTP_PASSWORD", ""))
    postbox_host: str = field(default_factory=lambda: os.getenv("POSTBOX_SMTP_HOST", "postbox.cloud.yandex.net"))
    postbox_port: int = field(default_factory=lambda: int(os.getenv("POSTBOX_SMTP_PORT", "465")))
    postbox_from_email: str = field(default_factory=lambda: os.getenv("POSTBOX_FROM_EMAIL", ""))
    postbox_from_name: str = field(default_factory=lambda: os.getenv("POSTBOX_FROM_NAME", ""))
    postbox_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("POSTBOX_TIMEOUT_SECONDS", "15")))

    smtp_bz_api_key: str = field(default_factory=lambda: os.getenv("SMTP_BZ_API_KEY", ""))
    smtp_bz_api_url: str = field(default_factory=lambda: os.getenv(
        "SMTP_BZ_API_URL", "https://api.smtp.bz/v1/smtp/send"))
    smtp_bz_from_email: str = field(default_factory=lambda: os.getenv("SMTP_BZ_FROM_EMAIL", ""))
    smtp_bz_from_name: str = field(default_factory=lambda: os.getenv("SMTP_BZ_FROM_NAME", ""))
    smtp_bz_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("SMTP_BZ_TIMEOUT_SECONDS", "15")))
    api_prefix: str = "/api/v1"
    app_name: str = "Aéza Analyzer"

    @property
    def postbox_configured(self) -> bool:
        """True when Postbox has an API key id/secret and a sender address."""

        return bool(self.postbox_username and self.postbox_password and self.postbox_from_email)

    @property
    def smtp_bz_configured(self) -> bool:
        """True when SMTP.BZ has an API key and a sender address."""

        return bool(self.smtp_bz_api_key and self.smtp_bz_from_email)

    @property
    def active_email_provider(self) -> str:
        """The transport that will be used, or ``""`` when mail is disabled.

        Deterministic by design: an explicit ``AEZA_EMAIL_PROVIDER`` wins (and
        disables mail if that provider lacks credentials), otherwise Postbox is
        preferred and SMTP.BZ is the fallback. There is no runtime failover, so
        a confirmation can only ever come from the provider named here.
        """

        choice = self.email_provider
        if choice == "postbox":
            return "postbox" if self.postbox_configured else ""
        if choice == "smtp.bz":
            return "smtp.bz" if self.smtp_bz_configured else ""
        if choice in ("", "auto"):
            if self.postbox_configured:
                return "postbox"
            if self.smtp_bz_configured:
                return "smtp.bz"
        return ""

    @property
    def email_configured(self) -> bool:
        """True when the active provider has everything needed for a send."""

        return bool(self.active_email_provider)

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


        if self.email_provider not in ("", "auto", "postbox", "smtp.bz"):
            raise ValueError("AEZA_EMAIL_PROVIDER must be one of: postbox, smtp.bz (or empty for auto)")
        if not 1 <= self.smtp_bz_timeout_seconds <= 120:
            raise ValueError("SMTP_BZ_TIMEOUT_SECONDS must be between 1 and 120")
        if not 1 <= self.postbox_timeout_seconds <= 120:
            raise ValueError("POSTBOX_TIMEOUT_SECONDS must be between 1 and 120")
        if self.postbox_port not in (465, 587):
            raise ValueError("POSTBOX_SMTP_PORT must be 465 (TLS) or 587 (STARTTLS)")
        if self.postbox_configured and "@" not in self.postbox_from_email:
            raise ValueError("POSTBOX_FROM_EMAIL must be a valid e-mail address")
        if self.smtp_bz_configured:
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
