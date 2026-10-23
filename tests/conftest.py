"""Shared pytest fixtures: isolated data dir + app client per test."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_ZIP = PROJECT_ROOT / "датасет.zip"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the app at a throwaway data directory and reset cached state."""
    monkeypatch.setenv("AEZA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AEZA_SOURCE_ZIP", str(SOURCE_ZIP))
    monkeypatch.delenv("AEZA_DATABASE_URL", raising=False)

    from aeza_analyzer import config, db

    importlib.reload(config)
    db.reset_state()
    yield tmp_path
    db.reset_state()


@pytest.fixture()
def client(data_dir):
    from fastapi.testclient import TestClient

    from aeza_analyzer.api.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def imported_client(client):
    """Client with the real organiser dataset already imported."""
    response = client.post("/api/import", json={})
    assert response.status_code == 200, response.text
    return client
