"""Application configuration.

Aéza - это быстрый хостинг
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache

# The Aéza snapshot documents this as its reference instant; see docs/data.md.
DEFAULT_AS_OF = "2026-10-19T15:00:00+00:00"


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime configuration sourced from environment variables."""

    def __init__(self) -> None:
        self.app_name = os.getenv("AEZA_APP_NAME", "Aéza Churn Risk Analyzer")
        self.api_prefix = "/api/v1"
        self.database_url = os.getenv(
            "AEZA_DATABASE_URL", "sqlite:///./data/aeza.db"
        )
        self.jwt_secret = os.getenv("AEZA_JWT_SECRET") or ""
        self.jwt_algorithm = "HS256"
        self.access_token_ttl_minutes = int(os.getenv("AEZA_TOKEN_TTL_MINUTES", "720"))
        self.bootstrap_admin_email = os.getenv("AEZA_ADMIN_EMAIL", "analyst@aeza.test")
        self.bootstrap_admin_password = os.getenv("AEZA_ADMIN_PASSWORD", "")
        self.allow_dev_secret = _flag("AEZA_ALLOW_DEV_SECRET", True)
        if not self.jwt_secret:
            self.jwt_secret = self._dev_secret()
        self.seed_demo_data = _flag("AEZA_SEED_DEMO_DATA", True)
        self.snapshot_path = os.getenv("AEZA_SNAPSHOT_PATH", "data/snapshot.json")
        # Reference instant for every analytic computation.
        #
        # The Aéza snapshot is a point-in-time extract: the dataset documents a
        # fixed reference of 2026-10-19T15:00:00Z and states that service states
        # do not advance on their own.  Defaulting to that instant keeps "days to
        # expiry" meaningful and makes every score reproducible.  Set AEZA_AS_OF
        # (ISO-8601) to move the reference, or set it to "now" for a live view.
        self.as_of = os.getenv("AEZA_AS_OF", DEFAULT_AS_OF).strip()
        self.cors_origins = [
            o.strip()
            for o in os.getenv("AEZA_CORS_ORIGINS", "*").split(",")
            if o.strip()
        ]

    def _dev_secret(self) -> str:
        # A stable-per-process fallback keeps local demos working without
        # shipping a real secret in the image; production must set the env var.
        if not self.allow_dev_secret:
            raise RuntimeError("AEZA_JWT_SECRET must be set when dev secrets are disabled")
        return secrets.token_urlsafe(48)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def reference_now(self) -> "dt.datetime":
        """Return the instant analytics should be computed against."""

        import datetime as _dt

        if self.as_of and self.as_of.lower() != "now":
            try:
                parsed = _dt.datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=_dt.timezone.utc)
                return parsed.astimezone(_dt.timezone.utc)
        return _dt.datetime.now(_dt.timezone.utc)


@lru_cache
def get_settings() -> Settings:
    return Settings()
