"""Regression tests for the security hardening applied to the reference app.

Each test pins a defect that was previously open: the unsafe development
signing-secret default and the absence of any login rate limit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.auth.security import LoginThrottle, RateLimited
from backend.app.config import Settings
from backend.app.main import create_app

from backend.tests.conftest import ROOT


def test_settings_refuse_to_invent_a_secret_by_default(monkeypatch):
    """A shared environment must fail closed, not mint a throwaway secret."""
    for name in ("AEZA_JWT_SECRET", "AEZA_ALLOW_DEV_SECRET", "AEZA_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError):
        Settings()


def test_settings_allow_an_explicit_development_secret(monkeypatch):
    """Local development keeps working, but only when it opts in explicitly."""
    monkeypatch.delenv("AEZA_JWT_SECRET", raising=False)
    monkeypatch.setenv("AEZA_ALLOW_DEV_SECRET", "1")
    settings = Settings()
    assert settings.jwt_secret


def test_login_throttle_blocks_after_the_budget_is_spent():
    throttle = LoginThrottle(max_attempts=3, window_seconds=60)
    for _ in range(3):
        throttle.check("a@x|1.2.3.4")
        throttle.record_failure("a@x|1.2.3.4")
    with pytest.raises(RateLimited) as excinfo:
        throttle.check("a@x|1.2.3.4")
    assert excinfo.value.retry_after >= 1


def test_login_throttle_is_scoped_to_the_caller():
    """One noisy client must not lock out another account on a different key."""
    throttle = LoginThrottle(max_attempts=2, window_seconds=60)
    for _ in range(2):
        throttle.record_failure("a@x|1.1.1.1")
    throttle.check("b@x|2.2.2.2")  # unrelated key stays available


def test_successful_login_clears_the_failure_budget():
    throttle = LoginThrottle(max_attempts=2, window_seconds=60)
    throttle.record_failure("a@x|1.1.1.1")
    throttle.reset("a@x|1.1.1.1")
    throttle.check("a@x|1.1.1.1")
    throttle.check("a@x|1.1.1.1")


@pytest.fixture
def throttled_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        auth_database_url=f"sqlite:///{(tmp_path / 'auth.db').as_posix()}",
        jwt_secret="test-secret-key", bootstrap_admin_password="demo123",
        seed_demo_data=True, snapshot_path=str(ROOT / "dataset/data.json"),
        login_max_attempts=3, login_window_seconds=300)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def test_login_endpoint_rate_limits_and_reports_retry_after(throttled_client):
    payload = {"email": "analyst@aeza.test", "password": "wrong"}
    for _ in range(3):
        assert throttled_client.post("/api/v1/auth/login", json=payload).status_code == 401
    blocked = throttled_client.post("/api/v1/auth/login", json=payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    # The correct password must not bypass an active lockout.
    assert throttled_client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@aeza.test", "password": "demo123"}).status_code == 429


def test_successful_login_is_not_rate_limited(throttled_client):
    for _ in range(5):
        response = throttled_client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@aeza.test", "password": "demo123"})
        assert response.status_code == 200
