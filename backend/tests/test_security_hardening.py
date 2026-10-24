from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.auth.cache import LoginLimiter
from backend.config import Settings as AuthSettings
from backend.tests.conftest import ROOT, TEST_LOGIN, TEST_PASSWORD, make_test_auth_settings


def test_api_settings_do_not_require_bootstrap_credentials(monkeypatch):
    for name in ("AEZA_JWT_SECRET", "AEZA_ALLOW_DEV_SECRET", "AEZA_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    Settings()


def test_auth_settings_require_secure_cookies_for_https_issuer():
    with pytest.raises(ValueError):
        AuthSettings(issuer="https://auth.example.com")


def test_login_limiter_blocks_after_budget():
    limiter = LoginLimiter(capacity=10, attempts=3, window=60)
    assert all(limiter.check("127.0.0.1") for _ in range(3))
    assert not limiter.check("127.0.0.1")


@pytest.fixture
def throttled_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        seed_demo_data=True, snapshot_path=str(ROOT / "dataset/data.json"))
    auth_settings = make_test_auth_settings(tmp_path / "auth.db")
    with TestClient(create_app(settings, auth_settings=auth_settings), raise_server_exceptions=False) as client:
        yield client


def test_login_endpoint_rate_limits_and_reports_retry_after(throttled_client):
    payload = {"email": TEST_LOGIN, "password": "wrong"}
    for _ in range(10):
        assert throttled_client.post("/api/v1/auth/login", json=payload).status_code == 401
    blocked = throttled_client.post("/api/v1/auth/login", json=payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert throttled_client.post(
        "/api/v1/auth/login",
        json={"email": TEST_LOGIN, "password": TEST_PASSWORD}).status_code == 429


def test_successful_login_is_not_rate_limited(throttled_client):
    for _ in range(5):
        response = throttled_client.post(
            "/api/v1/auth/login",
            json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        assert response.status_code == 200
