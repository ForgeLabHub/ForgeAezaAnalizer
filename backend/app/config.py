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
    allow_dev_secret: bool = field(default_factory=lambda: flag("AEZA_ALLOW_DEV_SECRET", True))
    bootstrap_admin_email: str = field(default_factory=lambda: os.getenv("AEZA_ADMIN_EMAIL", "analyst@aeza.test"))
    bootstrap_admin_password: str = field(default_factory=lambda: os.getenv("AEZA_ADMIN_PASSWORD", ""))
    access_token_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("AEZA_TOKEN_TTL_MINUTES", "720")))
    seed_demo_data: bool = field(default_factory=lambda: flag("AEZA_SEED_DEMO_DATA", False))
    snapshot_path: str = field(default_factory=lambda: os.getenv("AEZA_SNAPSHOT_PATH", str(ROOT / "dataset/data.json")))
    as_of: str = field(default_factory=lambda: os.getenv("AEZA_AS_OF", DEFAULT_AS_OF))
    recalculate_seconds: int = field(default_factory=lambda: int(os.getenv("AEZA_RECALCULATE_SECONDS", "60")))
    metrics_token: str = field(default_factory=lambda: os.getenv("AEZA_METRICS_TOKEN", ""))
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
