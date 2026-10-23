"""Application configuration and filesystem layout.

Paths resolve from the environment on every access so tests (and deployments)
can point the app at a different data directory without reloading modules.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SOURCE_ZIP = PROJECT_ROOT / "датасет.zip"


class Settings:
    """Runtime paths and defaults, resolved lazily from environment variables.

    ``data_dir`` holds the SQLite store and extracted fixtures. It is ignored by
    git so the organiser archives stay the single source of truth.
    """

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        raw = os.environ.get("AEZA_DATA_DIR")
        return Path(raw).resolve() if raw else DEFAULT_DATA_DIR

    @property
    def source_archive(self) -> Path:
        raw = os.environ.get("AEZA_SOURCE_ZIP")
        return Path(raw).resolve() if raw else DEFAULT_SOURCE_ZIP

    @property
    def db_path(self) -> Path:
        return self.data_dir / "aeza.sqlite"

    @property
    def extract_dir(self) -> Path:
        return self.data_dir / "extracted"

    def database_url(self) -> str:
        override = os.environ.get("AEZA_DATABASE_URL")
        if override:
            return override
        return f"sqlite+pysqlite:///{self.db_path}"


settings = Settings()
