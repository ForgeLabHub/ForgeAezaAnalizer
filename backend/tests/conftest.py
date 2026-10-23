"""Shared pytest fixtures: isolated database, test client and deterministic clock."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Fixed reference instant matching the snapshot's own "now" (2026-10-19T15:00Z).
AS_OF = "2026-10-19T15:00:00.000Z"

SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "snapshot.json")


@pytest.fixture(scope="session")
def snapshot_payload() -> dict:
    with open(SNAPSHOT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def app_env(tmp_path, monkeypatch, snapshot_payload):
    """Point the app at a fresh SQLite file and a fixed clock."""

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEZA_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AEZA_JWT_SECRET", "test-secret-key")
    monkeypatch.setenv("AEZA_ADMIN_EMAIL", "analyst@aeza.test")
    monkeypatch.setenv("AEZA_ADMIN_PASSWORD", "demo123")
    monkeypatch.setenv("AEZA_AS_OF", AS_OF)
    monkeypatch.setenv("AEZA_SEED_DEMO_DATA", "1")
    monkeypatch.setenv("AEZA_SNAPSHOT_PATH", SNAPSHOT_PATH)

    import app.config as config_module
    import app.db as db_module

    config_module.get_settings.cache_clear()
    db_module.reset_engine_for_tests()
    yield
    db_module.reset_engine_for_tests()
    config_module.get_settings.cache_clear()


@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def reference_now() -> dt.datetime:
    return dt.datetime.fromisoformat(AS_OF.replace("Z", "+00:00"))
