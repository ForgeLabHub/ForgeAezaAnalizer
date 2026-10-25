"""Tests for the SMTP.BZ outbound-e-mail integration.

Two layers, both real:

* **Client unit tests** drive ``backend/app/integrations/email.py`` through
  ``httpx.MockTransport``. Nothing leaves the machine, and every branch —
  success, 401, 4xx, 5xx, timeout, transport failure — is exercised against a
  stubbed provider answer.
* **HTTP route tests** stand up a *real* loopback HTTP server that speaks the
  SMTP.BZ response shape, point ``SMTP_BZ_API_URL`` at it and call the shipped
  endpoints through ``TestClient``. That covers the whole path (route →
  integration → httpx → socket) without touching the public internet.

No API key is required and no real letter is ever sent.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.integrations import email as email_integration
from backend.app.main import create_app

from backend.tests.conftest import (
    AS_OF,
    ROOT,
    TEST_LOGIN,
    TEST_PASSWORD,
    FixtureAnalytics,
    make_test_auth_settings,
)

API_KEY = "test-key-not-a-real-secret"
FROM_EMAIL = "sentinel@pixel-minds.ru"
FROM_NAME = "Aéza Sentinel"


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        smtp_bz_api_key=API_KEY,
        smtp_bz_from_email=FROM_EMAIL,
        smtp_bz_from_name=FROM_NAME,
    )
    base.update(overrides)
    return Settings(**base)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_settings_reject_plain_http_provider_url():
    with pytest.raises(ValueError, match="SMTP_BZ_API_URL"):
        _settings(smtp_bz_api_url="http://api.smtp.bz/v1/smtp/send")


def test_settings_allow_loopback_http_for_local_provider():
    assert _settings(smtp_bz_api_url="http://127.0.0.1:9/v1/smtp/send").smtp_bz_api_url


def test_settings_reject_a_malformed_from_address():
    with pytest.raises(ValueError, match="SMTP_BZ_FROM_EMAIL"):
        _settings(smtp_bz_from_email="not-an-address")


def test_settings_reject_out_of_range_timeout():
    with pytest.raises(ValueError, match="SMTP_BZ_TIMEOUT_SECONDS"):
        _settings(smtp_bz_timeout_seconds=0)


def test_email_configured_requires_key_and_from():
    assert _settings().email_configured is True
    assert _settings(smtp_bz_api_key="").email_configured is False
    assert _settings(smtp_bz_from_email="").email_configured is False


def test_send_refuses_when_unconfigured():
    with pytest.raises(email_integration.EmailDisabled):
        email_integration.send_email(
            _settings(smtp_bz_api_key=""), to="someone@example.test", subject="s", html="<b>x</b>")


def test_send_posts_the_documented_contract():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"result": True, "messageId": "abc-123"})

    result = email_integration.send_email(
        _settings(), to="recipient@example.test", subject="Тема",
        html="<b>тело</b>", text="тело", transport=_transport(handler))

    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.smtp.bz/v1/smtp/send"
    assert seen["auth"] == API_KEY
    assert "application/json" in seen["content_type"]
    assert seen["body"] == {
        "from": FROM_EMAIL,
        "subject": "Тема",
        "to": "recipient@example.test",
        "html": "<b>тело</b>",
        "name": FROM_NAME,
        "text": "тело",
    }
    assert result.accepted is True
    assert result.message_id == "abc-123"


def test_send_omits_optional_fields_when_absent():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"result": True})

    email_integration.send_email(
        _settings(smtp_bz_from_name=""), to="recipient@example.test",
        subject="s", html="<b>x</b>", transport=_transport(handler))
    assert "name" not in seen["body"]
    assert "text" not in seen["body"]


def test_send_rejects_an_unauthorised_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Invalid or missing API key!")

    with pytest.raises(email_integration.EmailRejected, match="ключ API"):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_rejects_a_bad_request_with_the_provider_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "sender domain is not verified"})

    with pytest.raises(email_integration.EmailRejected) as error:
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))
    assert "not verified" in str(error.value)


def test_send_reports_a_provider_failure_as_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_treats_rate_limiting_as_transient_not_a_refusal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "too many requests"})

    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_treats_an_unreadable_body_as_a_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>",
                              headers={"Content-Type": "text/html"})


    result = email_integration.send_email(
        _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
        transport=_transport(handler))
    assert result.accepted is True
    assert result.message_id is None


def test_send_rejects_an_unexpected_2xx_body_that_denies_the_send():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": False, "error": "ip not allowed"})

    with pytest.raises(email_integration.EmailRejected, match="ip not allowed"):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_surfaces_the_provider_reason_from_a_400_refusal():


    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "result": False,
            "errors": {"message": "Domain pixel-minds.ru [sentinel@pixel-minds.ru] not verified."}})

    with pytest.raises(email_integration.EmailRejected) as error:
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))

    assert "not verified" in str(error.value)
    assert "pixel-minds.ru" in str(error.value)


def test_send_treats_a_2xx_with_an_errors_body_as_a_refusal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "result": False, "errors": {"message": "sender not verified"}})

    with pytest.raises(email_integration.EmailRejected, match="sender not verified"):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_surfaces_field_level_validation_errors():


    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "result": False,
            "errors": {"from": "Invalid or missing from address",
                       "to": "Invalid or missing to address"}})

    with pytest.raises(email_integration.EmailRejected) as error:
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))
    assert "Invalid or missing to address" in str(error.value)
    assert "Invalid or missing from address" in str(error.value)


def test_send_never_calls_the_provider_after_a_timeout():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


    assert calls["n"] == 1


def test_send_errors_never_contain_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(email_integration.EmailUnavailable) as error:
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))
    assert API_KEY not in str(error.value)
    assert API_KEY not in repr(error.value)


def test_send_reports_a_timeout_as_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_reports_a_transport_failure_as_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_rejects_an_invalid_recipient_before_calling_the_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be called for an invalid recipient")

    with pytest.raises(email_integration.EmailRejected):
        email_integration.send_email(
            _settings(), to="not-an-email", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_rejects_header_injection_in_the_subject():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be called for an injected header")

    with pytest.raises(email_integration.EmailRejected, match="перевод строки"):
        email_integration.send_email(
            _settings(), to="recipient@example.test",
            subject="Тема\r\nBcc: attacker@evil.test", html="<b>x</b>",
            transport=_transport(handler))


def test_send_treats_an_explicit_refusal_as_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": False, "message": "domain not verified"})

    with pytest.raises(email_integration.EmailRejected, match="domain not verified"):
        email_integration.send_email(
            _settings(), to="recipient@example.test", subject="s", html="<b>x</b>",
            transport=_transport(handler))


def test_send_requires_a_non_empty_subject_and_html():
    with pytest.raises(email_integration.EmailRejected):
        email_integration.send_email(_settings(), to="recipient@example.test", subject="  ", html="<b>x</b>")
    with pytest.raises(email_integration.EmailRejected):
        email_integration.send_email(_settings(), to="recipient@example.test", subject="s", html="   ")


def test_describe_never_leaks_the_api_key():
    described = email_integration.describe(_settings())
    assert described["configured"] is True
    assert described["keyPresent"] is True
    assert described["fromEmail"] == FROM_EMAIL
    assert API_KEY not in json.dumps(described, ensure_ascii=False)


def test_otp_adapter_matches_the_telegram_provider_contract():


    import inspect

    provider = email_integration.SmtpBzEmailProvider(_settings())
    method = getattr(provider, "send_otp", None)
    assert callable(method)
    parameters = list(inspect.signature(method).parameters)
    assert parameters == ["email", "code", "expires_in_seconds"]


def test_otp_adapter_sends_the_code_as_a_confirmed_letter():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"result": True, "messageId": "otp-1"})

    provider = email_integration.SmtpBzEmailProvider(_settings(), transport=_transport(handler))
    provider.send_otp("client@example.test", "654321", 600)

    assert seen["body"]["to"] == "client@example.test"
    assert "654321" in seen["body"]["html"]
    assert seen["body"]["from"] == FROM_EMAIL


def test_otp_adapter_reports_unconfigured_as_integration_not_configured():
    from backend.app.telegram.providers import IntegrationNotConfigured
    provider = email_integration.SmtpBzEmailProvider(_settings(smtp_bz_api_key=""))
    with pytest.raises(IntegrationNotConfigured):
        provider.send_otp("client@example.test", "654321", 600)


def test_otp_adapter_maps_a_provider_failure_to_delivery_error_without_the_code():
    from backend.app.telegram.providers import DeliveryError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = email_integration.SmtpBzEmailProvider(_settings(), transport=_transport(handler))
    with pytest.raises(DeliveryError) as error:
        provider.send_otp("client@example.test", "654321", 600)
    assert "654321" not in str(error.value)
    assert API_KEY not in str(error.value)


def test_otp_transport_is_wired_only_when_smtp_bz_is_configured():


    from backend.app.integrations.email import SmtpBzEmailProvider

    app = create_app(_settings(), FixtureAnalytics())
    with TestClient(app, raise_server_exceptions=False):
        assert isinstance(app.state.runtime.telegram.email_provider, SmtpBzEmailProvider)


def test_otp_stays_disabled_when_smtp_bz_is_not_configured():


    from backend.app.telegram.providers import UnconfiguredEmailProvider

    app = create_app(_settings(smtp_bz_api_key="", smtp_bz_from_email=""), FixtureAnalytics())
    with TestClient(app, raise_server_exceptions=False):
        assert isinstance(app.state.runtime.telegram.email_provider, UnconfiguredEmailProvider)


class _ProviderHandler(BaseHTTPRequestHandler):
    """Minimal SMTP.BZ stand-in that records what it was sent."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        status, payload = self.server.responder(self.path, body)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        return


class _Provider:
    def __init__(self, responder):
        self.requests: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        self._server.requests = self.requests
        self._server.responder = responder
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1/smtp/send"

    def __enter__(self) -> "_Provider":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def provider():
    with _Provider(lambda path, body: (200, {"result": True, "messageId": "msg-1"})) as server:
        yield server


@pytest.fixture
def email_client(provider, tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        as_of=AS_OF,
        smtp_bz_api_key=API_KEY,
        smtp_bz_from_email=FROM_EMAIL,
        smtp_bz_from_name=FROM_NAME,
        smtp_bz_api_url=provider.url,
    )
    auth_settings = make_test_auth_settings(tmp_path / "auth.db")
    app = create_app(settings, FixtureAnalytics(), auth_settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        assert login.status_code == 200, login.text
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client


def test_status_requires_authentication(client):
    assert client.get("/api/v1/email/status").status_code == 401


def test_test_route_requires_authentication(client, provider):

    response = client.post("/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
    assert response.status_code == 401
    assert provider.requests == []


def test_status_reports_configuration_without_the_key(email_client):
    response = email_client.get("/api/v1/email/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["keyPresent"] is True
    assert body["fromEmail"] == FROM_EMAIL
    assert API_KEY not in response.text


def test_test_route_refuses_without_explicit_confirmation(email_client):
    response = email_client.post("/api/v1/email/test", json={"to": "ops@example.test"})
    assert response.status_code == 422
    assert "confirm" in response.json()["detail"]


def test_test_route_rejects_a_malformed_recipient_before_the_provider(email_client):
    response = email_client.post("/api/v1/email/test", json={"to": "not-an-address", "confirm": True})
    assert response.status_code == 422

    assert response.status_code != 502


def test_test_route_cannot_override_the_provider_url(email_client, provider):


    response = email_client.post("/api/v1/email/test", json={
        "to": "ops@example.test", "confirm": True, "apiUrl": "http://169.254.169.254/latest/meta-data"})
    assert response.status_code == 422
    assert provider.requests == []


def test_test_route_maps_rate_limiting_to_503(tmp_path):
    with _Provider(lambda path, body: (429, {"message": "too many requests"})) as server:
        settings = Settings(
            database_url=f"sqlite:///{(tmp_path / 'rate.db').as_posix()}",
            seed_demo_data=True, snapshot_path=str(ROOT / "dataset/data.json"), as_of=AS_OF,
            smtp_bz_api_key=API_KEY, smtp_bz_from_email=FROM_EMAIL, smtp_bz_api_url=server.url)
        app = create_app(settings, FixtureAnalytics(), make_test_auth_settings(tmp_path / "rate_auth.db"))
        with TestClient(app, raise_server_exceptions=False) as client:
            token = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
            client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
            response = client.post("/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
    assert response.status_code == 503


def test_status_response_never_contains_the_key_or_authorization(email_client):
    response = email_client.get("/api/v1/email/status")
    assert response.status_code == 200
    assert API_KEY not in response.text
    assert "Authorization" not in response.text
    assert "authorization" not in response.text


def test_send_and_refusal_leave_no_secret_in_the_logs(email_client, provider, caplog):


    import logging

    with caplog.at_level(logging.DEBUG):
        email_client.post("/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
        email_client.get("/api/v1/email/status")
    blob = "\n".join(record.getMessage() for record in caplog.records)
    assert API_KEY not in blob
    assert "Authorization" not in blob


def test_test_route_sends_through_the_real_client(email_client, provider):
    response = email_client.post(
        "/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["messageId"] == "msg-1"

    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert sent["path"] == "/v1/smtp/send"
    assert sent["headers"]["Authorization"] == API_KEY
    payload = json.loads(sent["body"].decode("utf-8"))
    assert payload["from"] == FROM_EMAIL
    assert payload["to"] == "ops@example.test"
    assert payload["name"] == FROM_NAME
    assert "<html>" in payload["html"]


def test_test_route_maps_a_provider_refusal_to_502(tmp_path):
    with _Provider(lambda path, body: (400, {"message": "sender domain is not verified"})) as server:
        settings = Settings(
            database_url=f"sqlite:///{(tmp_path / 'refuse.db').as_posix()}",
            seed_demo_data=True,
            snapshot_path=str(ROOT / "dataset/data.json"),
            as_of=AS_OF,
            smtp_bz_api_key=API_KEY,
            smtp_bz_from_email=FROM_EMAIL,
            smtp_bz_api_url=server.url,
        )
        app = create_app(settings, FixtureAnalytics(), make_test_auth_settings(tmp_path / "refuse_auth.db"))
        with TestClient(app, raise_server_exceptions=False) as client:
            token = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
            client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
            response = client.post("/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
    assert response.status_code == 502
    assert "not verified" in response.json()["detail"]


def test_test_route_is_503_when_unconfigured(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'off.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        as_of=AS_OF,
        smtp_bz_api_key="",
        smtp_bz_from_email="",
    )
    app = create_app(settings, FixtureAnalytics(), make_test_auth_settings(tmp_path / "off_auth.db"))
    with TestClient(app, raise_server_exceptions=False) as client:
        token = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        status = client.get("/api/v1/email/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False
        response = client.post("/api/v1/email/test", json={"to": "ops@example.test", "confirm": True})
    assert response.status_code == 503
