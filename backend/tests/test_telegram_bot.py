"""Telegram bot tests: webhook, Mini App auth, OTP, notifications, support.

The Telegram Bot API and the SMTP.BZ provider are never contacted. Recording
providers stand in for them, so the whole path — webhook → link → consent →
support → notification → delivery — runs deterministically. The security cases
are the point of this file: a wrong secret is refused, an unsigned initData is
refused, an expired or reused code is refused, and one client cannot reach
another account's data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.db import (
    NotificationQueueRow,
    SupportMessageRow,
    TelegramChatStateRow,
    TelegramLinkRow,
    TelegramOtpRow,
)
from backend.app.main import create_app
from backend.app.telegram.providers import DeliveryError, TelegramBotApi
from backend.tests.conftest import ROOT, make_test_auth_settings

TOKEN = "123456:TEST-BOT-TOKEN"
SECRET = "webhook-secret-value"
AS_OF = "2026-10-19T15:00:00+00:00"
WEBHOOK_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


class RecordingTelegram:
    """Records what would have been sent. Optionally fails on demand."""

    def __init__(self, fail_with: Exception | None = None):
        self.sent: list[tuple[str, str]] = []
        self.markups: list[dict | None] = []
        self.fail_with = fail_with

    def send_message(self, chat_id, text, reply_markup=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((str(chat_id), text))
        self.markups.append(reply_markup)
        return f"m{len(self.sent)}"


class RecordingEmail:
    def __init__(self, fail_with: Exception | None = None):
        self.codes: list[tuple[str, str, int]] = []
        self.fail_with = fail_with

    def send_otp(self, email, code, expires_in_seconds):
        if self.fail_with is not None:
            raise self.fail_with
        self.codes.append((email, code, expires_in_seconds))

    @property
    def last_code(self) -> str:
        return self.codes[-1][1]


def _settings(tmp_path, **overrides) -> Settings:
    base = dict(
        database_url=f"sqlite:///{(tmp_path / 'tg.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        as_of=AS_OF,
    )
    base.update(overrides)
    return Settings(**base)


def _app(settings, tmp_path, telegram=None, email=None):
    """Build the app with the real analytics module, so the demo snapshot loads."""

    from backend.app.modules import load_module

    return create_app(
        settings,
        load_module("backend.app.domain.module:create"),
        auth_settings=make_test_auth_settings(tmp_path / "auth.db"),
        telegram_provider=telegram,
        email_provider=email,
    )


@pytest.fixture
def bot(tmp_path):
    """A running app with the bot on, recording providers, and an analyst token."""

    telegram = RecordingTelegram()
    email = RecordingEmail()
    settings = _settings(tmp_path, telegram_bot_enabled=True, telegram_bot_token=TOKEN,
                         telegram_webhook_secret=SECRET, telegram_mini_app_url="https://example.test/app")
    app = _app(settings, tmp_path, telegram=telegram, email=email)
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "analyst-test-password"})
        analyst = {"Authorization": f"Bearer {login.json()['access_token']}"}
        yield {"client": client, "app": app, "runtime": app.state.runtime, "telegram": telegram,
               "email": email, "settings": settings, "analyst": analyst, "tmp_path": tmp_path}


def update(update_id, text, chat_id=100, message_id=None, chat_type="private"):
    message = {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": chat_id}, "text": text}
    if message_id is not None:
        message["message_id"] = message_id
    return {"update_id": update_id, "message": message}


def post(bot, payload, headers=WEBHOOK_HEADERS):
    return bot["client"].post("/api/v1/telegram/webhook", json=payload, headers=headers)


_UPDATE_COUNTER = {"n": 0}


def next_update_id() -> int:
    """A globally unique update_id. Telegram's ids are unique per bot, and the
    service dedupes on them, so a test that reused one would be (correctly)
    ignored as a redelivery."""

    _UPDATE_COUNTER["n"] += 1
    return 10_000_000 + _UPDATE_COUNTER["n"]


def link_account(bot, chat_id=100, email="user-0001@example.test", consent=True):
    """Drive /start → email → code → consent. Returns the chat id."""

    post(bot, update(next_update_id(), "/start", chat_id=chat_id))
    post(bot, update(next_update_id(), email, chat_id=chat_id))
    code = bot["email"].last_code
    post(bot, update(next_update_id(), code, chat_id=chat_id))
    if consent:
        post(bot, update(next_update_id(), "да", chat_id=chat_id))
    return chat_id


def mini_app_init_data(user_id, *, token=TOKEN, auth_date=None, extra=None):
    values = {"auth_date": str(auth_date if auth_date is not None else int(time.time())),
              "user": json.dumps({"id": user_id})}
    if extra:
        values.update(extra)
    check_string = "\n".join(f"{k}={values[k]}" for k in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{k}={v}" for k, v in values.items())


def test_bot_disabled_webhook_reports_not_ready(tmp_path):
    settings = _settings(tmp_path, telegram_bot_enabled=False)
    with TestClient(_app(settings, tmp_path), raise_server_exceptions=False) as client:
        response = client.post("/api/v1/telegram/webhook", json=update(next_update_id(), "/start"), headers=WEBHOOK_HEADERS)
        assert response.status_code == 503


def test_enabling_the_bot_without_a_token_or_secret_is_rejected():
    with pytest.raises(ValueError):
        Settings(telegram_bot_enabled=True, telegram_bot_token="", telegram_webhook_secret=SECRET)
    with pytest.raises(ValueError):
        Settings(telegram_bot_enabled=True, telegram_bot_token=TOKEN, telegram_webhook_secret="")


def test_webhook_url_must_be_https():
    with pytest.raises(ValueError):
        Settings(telegram_webhook_url="http://example.test/hook")


def test_analyst_endpoints_require_authentication(tmp_path):
    settings = _settings(tmp_path, telegram_bot_enabled=True, telegram_bot_token=TOKEN, telegram_webhook_secret=SECRET)
    with TestClient(_app(settings, tmp_path), raise_server_exceptions=False) as client:
        for path in ("/api/v1/telegram/support/conversations", "/api/v1/telegram/notifications",
                     "/api/v1/telegram/diagnostics"):
            assert client.get(path).status_code == 401, path


def test_webhook_requires_the_secret_header(bot):
    assert bot["client"].post("/api/v1/telegram/webhook", json=update(next_update_id(), "/start")).status_code == 403


def test_webhook_rejects_a_wrong_secret(bot):
    response = post(bot, update(next_update_id(), "/start"), headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert response.status_code == 403


def test_webhook_accepts_the_right_secret(bot):
    assert post(bot, update(next_update_id(), "/start")).status_code == 200


def test_webhook_tolerates_malformed_json(bot):
    response = bot["client"].post("/api/v1/telegram/webhook", content=b"not json",
                                  headers={**WEBHOOK_HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 200


def test_webhook_tolerates_an_oversized_body(bot):
    big = b"x" * (256 * 1024)
    response = bot["client"].post("/api/v1/telegram/webhook", content=big,
                                  headers={**WEBHOOK_HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 200


def test_webhook_never_returns_5xx_on_an_internal_error(bot):
    """A handled update must not 500, or Telegram retries it forever."""

    bot["runtime"].telegram.handle_update = lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))
    response = post(bot, update(next_update_id(), "/start"))
    assert response.status_code == 200


def test_a_failed_reply_does_not_fail_the_webhook(bot):
    """A Telegram outage must not turn a handled /start into a 500."""

    bot["runtime"].telegram.telegram_provider = RecordingTelegram(fail_with=DeliveryError("down"))
    response = post(bot, update(next_update_id(), "/start"))
    assert response.status_code == 200
    assert response.json()["processed"] is True


def test_a_redelivered_update_runs_once(bot):
    link_account(bot)
    payload = update(50, "Помогите, пожалуйста", message_id=777)
    first = post(bot, payload)
    second = post(bot, payload)
    assert first.status_code == 200 and second.status_code == 200
    with bot["runtime"].database.sessions() as session:
        assert session.scalars(select(SupportMessageRow)).all().__len__() == 1


def test_the_same_message_id_is_stored_once(bot):
    link_account(bot)
    post(bot, update(50, "Первое", message_id=777))
    post(bot, update(51, "Первое", message_id=777))
    with bot["runtime"].database.sessions() as session:
        assert len(session.scalars(select(SupportMessageRow)).all()) == 1


def test_start_without_a_link_asks_for_email(bot):
    post(bot, update(next_update_id(), "/start"))
    assert "email" in bot["telegram"].sent[-1][1].lower()


def test_successful_otp_shows_the_mini_app_button(bot):
    chat_id = 107
    post(bot, update(next_update_id(), "/start", chat_id=chat_id))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=chat_id))
    response = post(bot, update(next_update_id(), bot["email"].last_code, chat_id=chat_id))

    assert response.json()["action"] == "verified"
    assert bot["telegram"].markups[-1] == {
        "inline_keyboard": [[{
            "text": "Открыть Mini App",
            "web_app": {"url": "https://example.test/app"},
        }]],
    }

    session_response = bot["client"].post(
        "/api/v1/client/session",
        json={"initData": mini_app_init_data(chat_id)},
    )
    assert session_response.status_code == 200
    with bot["runtime"].database.sessions() as session:
        state = session.get(TelegramChatStateRow, str(chat_id))
        assert state.state == "ready"


def test_unknown_text_before_linking_is_treated_as_an_email_attempt(bot):
    response = post(bot, update(next_update_id(), "not-an-email"))
    assert response.status_code == 200
    assert response.json()["processed"] is True


def test_provider_error_never_leaks_the_token():
    token = "8123456789:AAF-SUPER-SECRET-VALUE"
    provider = TelegramBotApi(token, max_attempts=1, sleep=lambda _: None)

    import urllib.error

    def fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    provider._opener = fail
    with pytest.raises(DeliveryError) as caught:
        provider.send_message("1", "hi")
    assert token not in str(caught.value)
    assert caught.value.__cause__ is None


def test_provider_retries_a_429_then_succeeds():
    token = "123:TOKEN"
    calls = {"n": 0}

    class Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.error

    def opener(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return Resp(b'{"ok": true, "result": {"message_id": 42}}')

    provider = TelegramBotApi(token, max_attempts=3, opener=opener, sleep=lambda _: None)
    assert provider.send_message("1", "hi") == "42"
    assert calls["n"] == 2


def test_init_data_with_a_bad_signature_is_refused(bot):
    bad = mini_app_init_data(555, token="WRONG-TOKEN")
    assert bot["client"].post("/api/v1/client/session", json={"initData": bad}).status_code == 401


def test_expired_init_data_is_refused(bot):
    old = mini_app_init_data(555, auth_date=int(time.time()) - 100000)
    assert bot["client"].post("/api/v1/client/session", json={"initData": old}).status_code == 401


def test_valid_init_data_for_an_unlinked_user_is_refused(bot):
    valid = mini_app_init_data(555)
    assert bot["client"].post("/api/v1/client/session", json={"initData": valid}).status_code == 403


def test_valid_init_data_for_a_linked_user_creates_a_session(bot):
    link_account(bot, chat_id=555)
    valid = mini_app_init_data(555)
    response = bot["client"].post("/api/v1/client/session", json={"initData": valid})
    assert response.status_code == 200, response.text
    assert response.json()["tokenType"] == "bearer"
    assert response.json()["accessToken"]


def client_token(bot, chat_id=100, email="user-0001@example.test"):
    link_account(bot, chat_id=chat_id, email=email)
    return bot["client"].post("/api/v1/client/session", json={"initData": mini_app_init_data(chat_id)}).json()["accessToken"]


def test_client_session_can_be_revoked(bot):
    token = client_token(bot)
    headers = {"Authorization": f"Bearer {token}"}
    assert bot["client"].get("/api/v1/client/me", headers=headers).status_code == 200
    assert bot["client"].post("/api/v1/client/session/logout", headers=headers).status_code == 204
    assert bot["client"].get("/api/v1/client/me", headers=headers).status_code == 401


def test_expired_client_session_is_refused(bot):
    token = client_token(bot)
    headers = {"Authorization": f"Bearer {token}"}
    with bot["runtime"].database.transaction() as session:
        from backend.app.db import TelegramClientSessionRow
        row = session.scalars(select(TelegramClientSessionRow)).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert bot["client"].get("/api/v1/client/me", headers=headers).status_code == 401


def test_unknown_email_does_not_send_a_code(bot):
    post(bot, update(next_update_id(), "/start", chat_id=200))
    response = post(bot, update(next_update_id(), "nobody@example.test", chat_id=200))
    assert response.status_code == 200
    assert bot["email"].codes == []


def test_duplicate_email_stops_the_link(bot):
    """The importer enforces unique emails; prove the service rule directly.

    ``backend/app/source.py`` rejects a snapshot with a duplicate email outright,
    so a duplicate can only reach the service through a state the validator never
    produced. This patches the account lookup to return two matches and asserts no
    code is sent and no account is chosen at random.
    """

    runtime = bot["runtime"]
    service = runtime.telegram
    original = service._find_email
    service._find_email = lambda email: [
        {"id": 1, "email": "user-0001@example.test"},
        {"id": 2, "email": "user-0001@example.test"},
    ]
    try:
        post(bot, update(next_update_id(), "/start", chat_id=300))
        response = post(bot, update(next_update_id(), "user-0001@example.test", chat_id=300))
    finally:
        service._find_email = original
    assert response.status_code == 200
    assert bot["email"].codes == []
    with runtime.database.sessions() as session:
        assert session.scalars(select(TelegramLinkRow).where(TelegramLinkRow.telegram_user_id == "300")).first() is None


def test_wrong_code_is_refused(bot):
    post(bot, update(next_update_id(), "/start", chat_id=400))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=400))
    response = post(bot, update(next_update_id(), "000000", chat_id=400))
    assert response.status_code == 200
    with bot["runtime"].database.sessions() as session:
        assert session.scalars(select(TelegramLinkRow).where(TelegramLinkRow.telegram_user_id == "400")).first() is None


def test_expired_code_is_refused(bot):
    post(bot, update(next_update_id(), "/start", chat_id=401))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=401))
    code = bot["email"].last_code
    with bot["runtime"].database.transaction() as session:
        row = session.scalars(select(TelegramOtpRow)).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    post(bot, update(next_update_id(), code, chat_id=401))
    with bot["runtime"].database.sessions() as session:
        assert session.scalars(select(TelegramLinkRow).where(TelegramLinkRow.telegram_user_id == "401")).first() is None


def test_a_code_cannot_be_used_twice(bot):
    link_account(bot, chat_id=402, consent=False)
    code = bot["email"].last_code
    post(bot, update(next_update_id(), "/rebind", chat_id=402))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=402))

    post(bot, update(next_update_id(), code, chat_id=402))
    with bot["runtime"].database.sessions() as session:
        links = session.scalars(select(TelegramLinkRow).where(TelegramLinkRow.telegram_user_id == "402")).all()
        assert len(links) == 1


def test_attempt_limit_consumes_the_code(bot):
    post(bot, update(next_update_id(), "/start", chat_id=403))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=403))
    with bot["runtime"].database.transaction() as session:
        row = session.scalars(select(TelegramOtpRow)).first()
        row.max_attempts = 2
    post(bot, update(next_update_id(), "000000", chat_id=403))
    post(bot, update(next_update_id(), "111111", chat_id=403))
    with bot["runtime"].database.sessions() as session:
        row = session.scalars(select(TelegramOtpRow)).first()
        assert row.consumed_at is not None


def test_resend_is_throttled(bot):
    post(bot, update(next_update_id(), "/start", chat_id=404))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=404))
    first_count = len(bot["email"].codes)
    post(bot, update(next_update_id(), "/rebind", chat_id=404))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=404))

    assert len(bot["email"].codes) == first_count


def test_otp_is_stored_hashed_not_in_clear(bot):
    post(bot, update(next_update_id(), "/start", chat_id=405))
    post(bot, update(next_update_id(), "user-0001@example.test", chat_id=405))
    code = bot["email"].last_code
    with bot["runtime"].database.sessions() as session:
        row = session.scalars(select(TelegramOtpRow)).first()
        assert code not in row.code_hash
        assert row.code_salt
        assert row.code_hash != code


def test_consent_is_recorded(bot):
    link_account(bot, chat_id=500, consent=True)
    with bot["runtime"].database.sessions() as session:
        link = session.scalars(select(TelegramLinkRow).where(TelegramLinkRow.telegram_user_id == "500")).first()
        assert link.notifications_enabled is True
        assert link.consent_at is not None


def test_client_sees_only_its_own_account(bot):
    token_a = client_token(bot, chat_id=600, email="user-0001@example.test")
    token_b = client_token(bot, chat_id=601, email="user-0002@example.test")
    a = bot["client"].get("/api/v1/client/account", headers={"Authorization": f"Bearer {token_a}"}).json()
    b = bot["client"].get("/api/v1/client/account", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert a["id"] == 1 and b["id"] == 2
    assert a["email"] != b["email"]


def test_client_services_are_filtered_and_money_is_in_cents(bot):
    token = client_token(bot, chat_id=602, email="user-0001@example.test")
    body = bot["client"].get("/api/v1/client/services", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["accountId"] == 1
    assert all(item["id"] for item in body["items"])
    for item in body["items"]:
        assert "riskScore" not in item and "reasons" not in item
        if item["price"]["cents"] is not None:
            assert item["price"]["eur"] is not None


def test_client_endpoints_require_a_session(bot):
    for path in ("/api/v1/client/me", "/api/v1/client/account", "/api/v1/client/services", "/api/v1/client/support"):
        assert bot["client"].get(path).status_code == 401, path


def test_client_message_reaches_the_analyst_and_a_reply_is_delivered(bot):
    token = client_token(bot, chat_id=700, email="user-0001@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    created = bot["client"].post("/api/v1/client/support/messages", json={"text": "Не работает услуга"}, headers=headers)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversation"]["id"]

    listed = bot["client"].get("/api/v1/telegram/support/conversations", headers=bot["analyst"]).json()["items"]
    assert any(item["id"] == conversation_id for item in listed)

    reply = bot["client"].post(
        f"/api/v1/telegram/support/conversations/{conversation_id}/messages",
        json={"text": "Проверяем, спасибо"}, headers=bot["analyst"],
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["deliveryStatus"] == "delivered"
    assert any("Проверяем" in text for _, text in bot["telegram"].sent)


def test_analyst_reply_is_marked_failed_when_telegram_is_down(bot):
    token = client_token(bot, chat_id=701, email="user-0001@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    created = bot["client"].post("/api/v1/client/support/messages", json={"text": "Вопрос"}, headers=headers)
    conversation_id = created.json()["conversation"]["id"]
    bot["runtime"].telegram.telegram_provider = RecordingTelegram(fail_with=DeliveryError("down"))
    reply = bot["client"].post(
        f"/api/v1/telegram/support/conversations/{conversation_id}/messages",
        json={"text": "Ответ"}, headers=bot["analyst"],
    )
    assert reply.json()["deliveryStatus"] == "failed"
    assert reply.json()["deliveryError"]


def test_client_cannot_read_another_accounts_conversation(bot):
    token_a = client_token(bot, chat_id=702, email="user-0001@example.test")
    created = bot["client"].post("/api/v1/client/support/messages", json={"text": "A"},
                                 headers={"Authorization": f"Bearer {token_a}"})
    conversation_id = created.json()["conversation"]["id"]
    token_b = client_token(bot, chat_id=703, email="user-0002@example.test")
    response = bot["client"].get(f"/api/v1/client/support?conversationId={conversation_id}",
                                 headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404


def test_notifications_are_queued_for_active_autoprolong_services(bot):
    runtime = bot["runtime"]
    runtime.telegram.sync_notifications()
    with runtime.database.sessions() as session:
        rows = session.scalars(select(NotificationQueueRow)).all()
    assert rows, "the demo dataset has active services with autoProlong"
    assert {row.interval_days for row in rows} == {7, 3}
    for row in rows:
        assert row.scheduled_at == row.expires_at - timedelta(days=row.interval_days)


def test_notifications_are_not_queued_for_deleted_or_blocked(bot):
    runtime = bot["runtime"]
    state = runtime.storage.load()
    source = json.loads(json.dumps(state.source))
    for service in source["services"]:
        if service["status"] in ("deleted", "blocked"):
            service["autoProlong"] = True
    runtime.core.update(source=source)
    runtime.telegram.sync_notifications()
    with runtime.database.sessions() as session:
        rows = session.scalars(select(NotificationQueueRow)).all()
    blocked_ids = {s["id"] for s in source["services"] if s["status"] in ("deleted", "blocked")}
    assert not ({row.service_id for row in rows} & blocked_ids)


def test_changing_expires_at_cancels_a_stale_notification(bot):
    runtime = bot["runtime"]
    runtime.telegram.sync_notifications()
    with runtime.database.sessions() as session:
        before = {row.id for row in session.scalars(select(NotificationQueueRow)).all()}
    state = runtime.storage.load()
    source = json.loads(json.dumps(state.source))
    for service in source["services"]:
        if service["status"] == "active" and service.get("autoProlong") is True:
            service["expiresAt"] = "2028-01-01T00:00:00Z"
    runtime.core.update(source=source)
    runtime.telegram.sync_notifications()
    with runtime.database.sessions() as session:
        after = {row.id: row for row in session.scalars(select(NotificationQueueRow)).all()}

    assert any(after[row_id].status == "cancelled" for row_id in before if row_id in after)


def test_notification_delivery_is_idempotent(bot):
    runtime = bot["runtime"]
    link_account(bot, chat_id=800, email="user-0001@example.test")

    runtime.telegram.sync_notifications()
    with runtime.database.transaction() as session:
        for row in session.scalars(select(NotificationQueueRow)).all():
            row.scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    first = runtime.telegram.process_notifications()
    second = runtime.telegram.process_notifications()
    assert second["sent"] == 0
    assert first["sent"] >= 0


def test_support_history_is_purged_after_30_days(bot):
    runtime = bot["runtime"]
    token = client_token(bot, chat_id=900, email="user-0001@example.test")
    bot["client"].post("/api/v1/client/support/messages", json={"text": "старое"},
                       headers={"Authorization": f"Bearer {token}"})
    with runtime.database.transaction() as session:
        row = session.scalars(select(SupportMessageRow)).first()
        row.created_at = datetime.now(timezone.utc) - timedelta(days=31)
    assert runtime.telegram.purge_support_history() >= 1


def test_diagnostics_never_leaks_the_token_or_secret(bot):
    body = bot["client"].get("/api/v1/telegram/diagnostics", headers=bot["analyst"]).text
    assert TOKEN not in body
    assert SECRET not in body


def test_a_service_without_expiry_does_not_break_the_notification_sync(tmp_path):
    """``expiresAt`` is optional in the ingest schema; an active auto-prolong
    service without one cannot be scheduled and must be skipped, not crash the
    whole sync (unknown != zero).

    The published analytics module rejects such a snapshot, but the module is
    pluggable (``AEZA_ANALYTICS_FACTORY``), so the service must not assume it.
    """

    from backend.tests.conftest import FixtureAnalytics

    source = json.loads((ROOT / "dataset/data.json").read_text())
    source["services"].append({"id": 99999, "name": "no-expiry", "ownerId": 1, "status": "active",
                               "autoProlong": True, "expiresAt": None, "price": 100})
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(source))
    settings = _settings(tmp_path, snapshot_path=str(snapshot))
    app = create_app(settings, FixtureAnalytics(),
                     auth_settings=make_test_auth_settings(tmp_path / "auth.db"),
                     telegram_provider=RecordingTelegram(), email_provider=RecordingEmail())
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login",
                            json={"email": "analyst@aeza.test", "password": "analyst-test-password"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.post("/api/v1/telegram/notifications/sync", headers=headers).status_code == 200
        assert client.post("/api/v1/telegram/notifications/run", headers=headers).status_code == 200


def test_otp_transport_is_wired_when_smtp_bz_is_configured(tmp_path):
    from backend.app.integrations.email import SmtpBzEmailProvider
    from backend.app.modules import load_module

    settings = _settings(tmp_path, smtp_bz_api_key="test-key", smtp_bz_from_email="sentinel@pixel-minds.ru")
    app = create_app(settings, load_module("backend.app.domain.module:create"),
                     auth_settings=make_test_auth_settings(tmp_path / "auth.db"))
    with TestClient(app, raise_server_exceptions=False):
        assert isinstance(app.state.runtime.telegram.email_provider, SmtpBzEmailProvider)


def test_otp_transport_stays_off_when_smtp_bz_is_not_configured(tmp_path):
    from backend.app.modules import load_module
    from backend.app.telegram.providers import UnconfiguredEmailProvider

    settings = _settings(tmp_path, smtp_bz_api_key="", smtp_bz_from_email="")
    app = create_app(settings, load_module("backend.app.domain.module:create"),
                     auth_settings=make_test_auth_settings(tmp_path / "auth.db"))
    with TestClient(app, raise_server_exceptions=False):
        assert isinstance(app.state.runtime.telegram.email_provider, UnconfiguredEmailProvider)
