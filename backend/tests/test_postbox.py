"""Tests for the Yandex Cloud Postbox SMTP transport.

The transport is exercised against a *real* loopback SMTP server (``aiosmtpd``)
that speaks the SMTP protocol over TLS with a self-signed certificate generated
at test time. Nothing leaves the machine and no real letter is sent.

Covered: the happy path (server accepts the message), an authentication refusal,
a sender refusal (the unverified-domain case), a dropped connection, and the
provider-selection logic that decides whether Postbox or SMTP.BZ is active.
"""

from __future__ import annotations

import datetime
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP as SmtpProtocol

from backend.app.config import Settings
from backend.app.integrations import email as email_integration

FROM_EMAIL = "sentinel@pixel-minds.ru"
FROM_NAME = "Aéza Sentinel"
KEY_ID = "test-key-id"
KEY_SECRET = "test-key-secret-not-real"


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
        postbox_username=KEY_ID,
        postbox_password=KEY_SECRET,
        postbox_from_email=FROM_EMAIL,
        postbox_from_name=FROM_NAME,
    )
    base.update(overrides)
    return Settings(**base)


def _self_signed_context() -> tuple[ssl.SSLContext, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    import tempfile
    from pathlib import Path
    directory = Path(tempfile.mkdtemp())
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    return context, str(cert_path)


class _Recorder:
    """A minimal SMTP handler that records what the server accepted."""

    def __init__(self, *, refuse_sender: bool = False):
        self.messages: list[dict] = []
        self.refuse_sender = refuse_sender

    async def handle_DATA(self, server, session, envelope):
        self.messages.append({
            "mail_from": envelope.mail_from,
            "rcpt_tos": envelope.rcpt_tos,
            "content": envelope.content,
        })
        return "250 Message accepted for delivery"

    async def handle_MAIL(self, server, session, envelope, address, options):
        if self.refuse_sender:
            return "550 sender domain not verified"
        envelope.mail_from = address
        return "250 OK"

    async def handle_RCPT(self, server, session, envelope, address, options):
        envelope.rcpt_tos.append(address)
        return "250 OK"


class _Server:
    """A loopback SMTP server in one of three modes.

    ``mode`` selects the TLS behaviour aiosmtpd must offer: ``"tls"`` is implicit
    TLS (what Postbox uses on 465), ``"starttls"`` offers STARTTLS (port 587) and
    ``"plain"`` offers neither.
    """

    def __init__(self, handler: _Recorder, *, mode: str, require_auth: bool):
        self.handler = handler


        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self._port = probe.getsockname()[1]
        probe.close()
        tls_context, _ = _self_signed_context()
        kwargs: dict = {}
        if mode == "tls":
            kwargs["ssl_context"] = tls_context
        elif mode == "starttls":
            kwargs["tls_context"] = tls_context
        if require_auth:
            def authenticator(server, session, envelope, mechanism, auth_data):
                if auth_data.login == KEY_ID.encode() and auth_data.password == KEY_SECRET.encode():
                    return True
                return False
            kwargs["authenticator"] = authenticator
            kwargs["auth_require_tls"] = False
        self._controller = Controller(handler, hostname="127.0.0.1", port=self._port, **kwargs)

    def __enter__(self) -> "_Server":
        self._controller.start()
        return self

    def __exit__(self, *exc) -> None:
        self._controller.stop()

    @property
    def port(self) -> int:
        return self._port


def _factory_for(server: _Server, *, use_tls: bool):
    """Return an ``SMTP_SSL``/``SMTP`` factory that connects to the loopback port."""

    if use_tls:
        def factory(host, port, timeout=None, context=None):
            import smtplib
            return smtplib.SMTP_SSL("127.0.0.1", server.port, timeout=timeout, context=context)
    else:
        def factory(host, port, timeout=None, context=None):
            import smtplib
            return smtplib.SMTP("127.0.0.1", server.port, timeout=timeout)
    return factory


def _client_context():
    """A context that trusts the test server's self-signed certificate."""

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def test_postbox_is_preferred_when_both_are_configured():
    settings = _settings(smtp_bz_api_key="k", smtp_bz_from_email="a@b.co")
    assert settings.active_email_provider == "postbox"


def test_smtp_bz_is_the_fallback_when_only_it_is_configured():
    settings = Settings(database_url="sqlite://", smtp_bz_api_key="k", smtp_bz_from_email="a@b.co")
    assert settings.active_email_provider == "smtp.bz"


def test_an_explicit_choice_disables_mail_when_that_provider_lacks_credentials():


    settings = _settings(email_provider="smtp.bz")
    assert settings.active_email_provider == ""
    assert settings.email_configured is False


def test_an_unknown_provider_name_is_rejected_at_startup():
    with pytest.raises(ValueError, match="AEZA_EMAIL_PROVIDER"):
        _settings(email_provider="mailgun")


def test_postbox_requires_a_valid_sender_address():
    with pytest.raises(ValueError, match="POSTBOX_FROM_EMAIL"):
        _settings(postbox_from_email="not-an-address")


def test_postbox_port_must_be_465_or_587():
    with pytest.raises(ValueError, match="POSTBOX_SMTP_PORT"):
        _settings(postbox_port=25)


def test_send_via_postbox_delivers_the_message():
    handler = _Recorder()
    with _Server(handler, mode="tls", require_auth=True) as server:
        settings = _settings(postbox_host="localhost", postbox_port=465)
        result = email_integration.send_email(
            settings, to="ops@example.test", subject="s", html="<b>x</b>", text="x",
            smtp_factory=_factory_for(server, use_tls=True), ssl_context=_client_context())

    assert result.accepted is True
    assert result.provider == "postbox"
    assert result.message_id
    assert len(handler.messages) == 1
    assert handler.messages[0]["mail_from"] == FROM_EMAIL
    assert handler.messages[0]["rcpt_tos"] == ["ops@example.test"]
    assert b"<b>x</b>" in handler.messages[0]["content"]


def test_send_via_postbox_never_leaks_the_key_in_the_result():
    handler = _Recorder()
    with _Server(handler, mode="tls", require_auth=True) as server:
        settings = _settings(postbox_host="localhost", postbox_port=465)
        result = email_integration.send_email(
            settings, to="ops@example.test", subject="s", html="<b>x</b>",
            smtp_factory=_factory_for(server, use_tls=True), ssl_context=_client_context())
    assert KEY_SECRET not in str(result.as_dict())


def test_send_via_postbox_reports_a_rejected_sender_domain():

    handler = _Recorder(refuse_sender=True)
    with _Server(handler, mode="tls", require_auth=True) as server:
        settings = _settings(postbox_host="localhost", postbox_port=465)
        with pytest.raises(email_integration.EmailRejected) as error:
            email_integration.send_email(
                settings, to="ops@example.test", subject="s", html="<b>x</b>",
                smtp_factory=_factory_for(server, use_tls=True), ssl_context=_client_context())
    assert "отправител" in str(error.value).lower()
    assert KEY_SECRET not in str(error.value)
    assert handler.messages == []


def test_send_via_postbox_reports_a_refused_authentication():
    handler = _Recorder()
    with _Server(handler, mode="tls", require_auth=True) as server:
        settings = _settings(postbox_host="localhost", postbox_port=465, postbox_password="wrong")
        with pytest.raises(email_integration.EmailRejected) as error:
            email_integration.send_email(
                settings, to="ops@example.test", subject="s", html="<b>x</b>",
                smtp_factory=_factory_for(server, use_tls=True), ssl_context=_client_context())
    assert "ключ" in str(error.value).lower()
    assert KEY_SECRET not in str(error.value)
    assert "wrong" not in str(error.value)


def test_send_via_postbox_reports_an_unreachable_server_as_unavailable():


    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    settings = _settings(postbox_host="127.0.0.1", postbox_port=465)
    with pytest.raises(email_integration.EmailUnavailable):
        email_integration.send_email(
            settings, to="ops@example.test", subject="s", html="<b>x</b>",
            ssl_context=_client_context())


def test_send_via_postbox_uses_starttls_on_port_587():
    handler = _Recorder()
    with _Server(handler, mode="starttls", require_auth=True) as server:
        settings = _settings(postbox_host="localhost", postbox_port=587)
        result = email_integration.send_email(
            settings, to="ops@example.test", subject="s", html="<b>x</b>",
            smtp_factory=_factory_for(server, use_tls=False), ssl_context=_client_context())
    assert result.accepted is True
    assert len(handler.messages) == 1


def test_send_via_postbox_fails_honestly_when_starttls_is_refused():


    handler = _Recorder()
    with _Server(handler, mode="plain", require_auth=False) as server:
        settings = _settings(postbox_host="localhost", postbox_port=587)
        with pytest.raises(email_integration.EmailUnavailable):
            email_integration.send_email(
                settings, to="ops@example.test", subject="s", html="<b>x</b>",
                smtp_factory=_factory_for(server, use_tls=False), ssl_context=_client_context())
    assert handler.messages == []


def test_describe_reports_postbox_without_the_key():
    settings = _settings()
    described = email_integration.describe(settings)
    assert described["provider"] == "postbox"
    assert described["configured"] is True
    assert described["keyPresent"] is True
    assert described["smtpHost"] == "postbox.cloud.yandex.net"
    assert described["fromEmail"] == FROM_EMAIL
    assert KEY_SECRET not in str(described)
    assert KEY_ID not in str(described)


def _postbox_app(tmp_path):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from backend.tests.conftest import FixtureAnalytics, make_test_auth_settings

    root = Path(__file__).resolve().parents[2]
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'postbox.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(root / "dataset/data.json"),
        postbox_username=KEY_ID,
        postbox_password=KEY_SECRET,
        postbox_from_email=FROM_EMAIL,
        postbox_from_name=FROM_NAME,
    )
    app = create_app(settings, FixtureAnalytics(), make_test_auth_settings(tmp_path / "postbox_auth.db"))
    return app, TestClient(app, raise_server_exceptions=False)


def _login(client):
    from backend.tests.conftest import TEST_LOGIN, TEST_PASSWORD

    login = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return client


def test_status_route_reports_postbox_and_never_the_key(tmp_path):
    app, client = _postbox_app(tmp_path)
    with client:
        response = _login(client).get("/api/v1/email/status")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "postbox"
    assert body["configured"] is True
    assert KEY_SECRET not in response.text
    assert KEY_ID not in response.text


def test_test_route_still_requires_explicit_confirmation_under_postbox(tmp_path):
    app, client = _postbox_app(tmp_path)
    with client:
        response = _login(client).post("/api/v1/email/test", json={"to": "ops@example.test"})
    assert response.status_code == 422
    assert "confirm" in response.json()["detail"]
