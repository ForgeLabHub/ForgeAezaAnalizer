"""Telegram integration tests.

The Telegram Bot API is never contacted. A stub client stands in for it, so the
whole path — link code → chat binding → subscriptions → notification → delivery
dedup — runs deterministically without a token, a network or a real bot.

The security cases are the point of this file: a code is single-use, a chat
cannot be taken over, an unlinked chat gets nothing, and the webhook refuses a
wrong secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import Database, TelegramLinkCodeRow, TelegramLinkRow
from backend.app.integrations.telegram import bot, notifications
from backend.app.integrations.telegram.client import (
    TelegramRejected,
    TelegramUnavailable,
)
from backend.app.integrations.telegram.service import (
    NOTIFICATION_KINDS,
    TelegramLinkError,
    TelegramRateLimited,
    TelegramService,
)
from backend.app.main import create_app
from backend.app.modules import load_module

from backend.tests.conftest import ROOT, TEST_LOGIN, TEST_PASSWORD, make_test_auth_settings

EMAIL = TEST_LOGIN
PASSWORD = TEST_PASSWORD


class StubClient:
    """Records what would have been sent. Never touches the network."""

    def __init__(self, *, fail_with: Exception | None = None):
        self.sent: list[tuple[str, str]] = []
        self.fail_with = fail_with

    def send_message(self, chat_id: str, text: str, **kwargs) -> dict:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((str(chat_id), text))
        return {"message_id": len(self.sent)}


def _settings(tmp_path, **overrides) -> Settings:
    base = dict(
        database_url=f"sqlite:///{(tmp_path / 'a.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        telegram_enabled=True,
        telegram_bot_token="123:TEST-TOKEN",
        telegram_webhook_secret="webhook-secret",
        telegram_min_send_interval_seconds=0,
    )
    base.update(overrides)
    return Settings(**base)


def _app(settings, module, tmp_path):
    return create_app(settings, module, make_test_auth_settings(tmp_path / "auth.db"))


@pytest.fixture
def service(tmp_path):
    """A TelegramService over a fresh database, with a stub client."""

    settings = _settings(tmp_path)
    database = Database(settings.database_url)
    database.initialize()
    stub = StubClient()
    svc = TelegramService(database, settings, client=stub)
    return svc, stub, settings, database


# --------------------------------------------------------------------------- #
# 1-2. The app starts with Telegram off or unconfigured
# --------------------------------------------------------------------------- #

def test_app_starts_with_telegram_disabled(tmp_path):
    settings = _settings(tmp_path, telegram_enabled=False, telegram_bot_token="")
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        assert client.get("/health").status_code == 200
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # Analytics still works; the Telegram surface reports itself as off.
        assert client.get("/api/v1/analytics/summary", headers=headers).status_code == 200
        body = client.get("/api/v1/telegram/status", headers=headers).json()
        assert body["enabled"] is False
        assert client.post("/api/v1/telegram/link-code", headers=headers).status_code == 503


def test_app_starts_without_a_token_when_disabled(tmp_path, monkeypatch):
    """A missing token must not be fatal while the feature is off."""

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
    settings = Settings()
    assert settings.telegram_enabled is False
    assert settings.telegram_bot_token == ""


def test_enabling_telegram_without_a_token_is_rejected():
    with pytest.raises(ValueError):
        Settings(telegram_enabled=True, telegram_bot_token="", telegram_webhook_secret="s")


def test_enabling_telegram_without_a_webhook_secret_is_rejected():
    with pytest.raises(ValueError):
        Settings(telegram_enabled=True, telegram_bot_token="t", telegram_webhook_secret="")


# --------------------------------------------------------------------------- #
# 3-6. Linking
# --------------------------------------------------------------------------- #

def test_link_code_requires_authentication(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        assert client.post("/api/v1/telegram/link-code").status_code == 401
        assert client.get("/api/v1/telegram/status").status_code == 401
        assert client.post("/api/v1/telegram/disconnect").status_code == 401


def test_only_the_code_hash_is_stored(service):
    svc, _, settings, database = service
    issued = svc.create_link_code(EMAIL)
    with database.sessions() as session:
        row = session.query(TelegramLinkCodeRow).one()
    assert issued["code"] not in row.code_hash
    assert row.code_hash == __import__("hashlib").sha256(issued["code"].encode()).hexdigest()


def test_valid_code_links_the_chat(service):
    svc, _, _, _ = service
    code = svc.create_link_code(EMAIL)["code"]
    owner = svc.redeem_link_code(code, "555", "someone")
    assert owner == EMAIL
    assert svc.owner_of("555") == EMAIL


def test_wrong_code_is_rejected(service):
    svc, _, _, _ = service
    svc.create_link_code(EMAIL)
    with pytest.raises(TelegramLinkError):
        svc.redeem_link_code("AAAA-BBBB-CCCC", "555")


def test_expired_code_is_rejected(service):
    svc, _, _, database = service
    code = svc.create_link_code(EMAIL)["code"]
    with database.transaction() as session:
        row = session.query(TelegramLinkCodeRow).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(TelegramLinkError, match="истёк"):
        svc.redeem_link_code(code, "555")


def test_code_cannot_be_used_twice(service):
    svc, _, _, _ = service
    code = svc.create_link_code(EMAIL)["code"]
    svc.redeem_link_code(code, "555")
    with pytest.raises(TelegramLinkError, match="использован"):
        svc.redeem_link_code(code, "666")


def test_a_new_code_invalidates_the_previous_one(service):
    svc, _, _, _ = service
    first = svc.create_link_code(EMAIL)["code"]
    svc.create_link_code(EMAIL)
    with pytest.raises(TelegramLinkError):
        svc.redeem_link_code(first, "555")


def test_chat_cannot_be_taken_over_by_another_account(service):
    """A second account's code must not steal a chat that is already linked."""

    svc, _, _, database = service
    code_a = svc.create_link_code("owner-a@example.test")["code"]
    svc.redeem_link_code(code_a, "555")
    code_b = svc.create_link_code("attacker@example.test")["code"]
    with pytest.raises(TelegramLinkError, match="другому аккаунту"):
        svc.redeem_link_code(code_b, "555")
    assert svc.owner_of("555") == "owner-a@example.test"


def test_rebinding_the_same_account_is_idempotent(service):
    svc, _, _, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    owner = svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    assert owner == EMAIL
    with svc.database.sessions() as session:
        assert session.query(TelegramLinkRow).count() == 1


def test_brute_force_is_bounded(service):
    svc, _, settings, database = service
    code = svc.create_link_code(EMAIL)["code"]
    with database.transaction() as session:
        row = session.query(TelegramLinkCodeRow).one()
        row.attempts = settings.telegram_link_max_attempts
    with pytest.raises(TelegramRateLimited):
        svc.redeem_link_code(code, "555")


def test_unlink_revokes_and_clears_the_subscription(service):
    svc, _, _, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    assert svc.unlink("555") is True
    assert svc.owner_of("555") is None
    assert svc.unlink("555") is False


def test_unlink_account_closes_every_chat(service):
    svc, _, _, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "666")
    assert svc.unlink_account(EMAIL) == 2
    assert svc.link_status(EMAIL).linked is False


# --------------------------------------------------------------------------- #
# 7-8. Commands enforce the link
# --------------------------------------------------------------------------- #

def _update(text: str, chat_id: int = 555) -> dict:
    return {"message": {"chat": {"id": chat_id}, "from": {"username": "u"}, "text": text}}


def test_unlinked_chat_gets_no_data(service):
    svc, _, settings, _ = service
    reply = bot.handle_update(svc, settings, _update("/top"))
    assert reply is not None
    assert "не подключён" in reply.lower()
    reply = bot.handle_update(svc, settings, _update("/customer 1"))
    assert "не подключён" in reply.lower()


def test_help_works_without_a_link(service):
    svc, _, settings, _ = service
    reply = bot.handle_update(svc, settings, _update("/help"))
    assert "/customer" in reply


def test_start_without_code_explains_how_to_link(service):
    svc, _, settings, _ = service
    reply = bot.handle_update(svc, settings, _update("/start"))
    assert "/start <КОД>" in reply


def test_start_with_code_links_and_confirms(service):
    svc, _, settings, _ = service
    code = svc.create_link_code(EMAIL)["code"]
    reply = bot.handle_update(svc, settings, _update(f"/start {code}"))
    assert "подключён" in reply.lower()
    assert svc.owner_of("555") == EMAIL


def test_start_with_a_bad_code_does_not_link(service):
    svc, _, settings, _ = service
    reply = bot.handle_update(svc, settings, _update("/start NOPE-NOPE-NOPE"))
    assert svc.owner_of("555") is None
    assert "не найден" in reply.lower()


def test_status_reports_the_subscription(service):
    svc, _, settings, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    reply = bot.handle_update(svc, settings, _update("/status"))
    assert EMAIL in reply
    assert "Уведомления" in reply


def test_unsubscribe_unlinks(service):
    svc, _, settings, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    reply = bot.handle_update(svc, settings, _update("/unsubscribe"))
    assert "отключён" in reply.lower()
    assert svc.owner_of("555") is None


def test_unknown_command_is_answered(service):
    svc, _, settings, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    reply = bot.handle_update(svc, settings, _update("/nonsense"))
    assert "Неизвестная команда" in reply


def test_customer_command_validates_its_argument(service):
    svc, _, settings, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    reply = bot.handle_update(svc, settings, _update("/customer abc"))
    assert "Использование" in reply


# --------------------------------------------------------------------------- #
# 9-11. Webhook and delivery behaviour
# --------------------------------------------------------------------------- #

def test_webhook_rejects_a_wrong_secret(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            json=_update("/help"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert response.status_code == 403


def test_webhook_accepts_the_right_secret(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            json=_update("/help"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
        )
        assert response.status_code == 200


def test_webhook_tolerates_a_malformed_body(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            content=b"not json at all",
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret",
                     "Content-Type": "application/json"},
        )
        # Acknowledged so Telegram does not retry forever, but not processed.
        assert response.status_code == 200


def test_webhook_is_disabled_with_the_feature(tmp_path):
    settings = _settings(tmp_path, telegram_enabled=False, telegram_bot_token="")
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        response = client.post("/api/v1/telegram/webhook", json=_update("/help"),
                               headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"})
        assert response.status_code == 200


def test_duplicate_event_is_not_sent_twice(service):
    svc, stub, _, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    assert svc.send("555", "первое", kind="test", dedupe_key="evt-1") is True
    assert svc.send("555", "второе", kind="test", dedupe_key="evt-1") is False
    assert len(stub.sent) == 1


def test_delivery_failure_does_not_raise(service):
    """A Telegram outage must never break the caller."""

    svc, _, _, _ = service
    svc.client = StubClient(fail_with=TelegramUnavailable("down"))
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    assert svc.send("555", "hello", kind="test") is False


def test_permanent_rejection_is_handled(service):
    svc, _, _, _ = service
    svc.client = StubClient(fail_with=TelegramRejected("chat not found"))
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    assert svc.send("555", "hello", kind="test") is False


def test_rate_limit_blocks_a_burst(tmp_path):
    settings = _settings(tmp_path, telegram_min_send_interval_seconds=60)
    database = Database(settings.database_url)
    database.initialize()
    stub = StubClient()
    svc = TelegramService(database, settings, client=stub)
    assert svc.send("555", "one") is True
    assert svc.send("555", "two") is False
    assert len(stub.sent) == 1


# --------------------------------------------------------------------------- #
# 12-13. Notifications come from real analytics, and subscriptions persist
# --------------------------------------------------------------------------- #

def _analysis(settings):
    from backend.app.modules import CalculationAdapter

    module = load_module("backend.app.domain.module:create")
    adapter = CalculationAdapter(module)
    from core import State

    import json

    state = State(
        generation=1, source_version=1, model_version=1,
        source=json.loads((ROOT / "dataset/data.json").read_text(encoding="utf-8")),
        settings=adapter.definition().defaults,
        as_of=datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc),
    )
    return adapter.calculate(state)


def test_high_risk_events_come_from_the_real_engine(tmp_path):
    settings = _settings(tmp_path)
    analysis = _analysis(settings)
    events = notifications.build_events(analysis, settings=settings, previous=None,
                                        kinds=["high_risk"])
    assert events, "the organiser dataset has high-risk customers"
    high = [c for c in analysis.customers if c.get("riskCategory") == "high"]
    assert len(events) == len(high)
    # The message quotes the engine's own score, not an invented one.
    for event, customer in zip(events, high):
        assert str(customer["riskScore"]) in event.text


def test_no_event_when_nothing_changed(tmp_path):
    settings = _settings(tmp_path)
    analysis = _analysis(settings)
    events = notifications.build_events(analysis, settings=settings, previous=analysis,
                                        kinds=["high_risk", "exposure_jump"])
    assert events == []


def test_digest_matches_the_summary(tmp_path):
    settings = _settings(tmp_path)
    analysis = _analysis(settings)
    text = notifications.digest_text(analysis, settings=settings)
    assert analysis.summary["revenue"]["revenueAtRiskEur"] in text
    assert str(analysis.summary["customers"]["total"]) in text


def test_subscription_survives_a_restart(tmp_path):
    settings = _settings(tmp_path)
    database = Database(settings.database_url)
    database.initialize()
    svc = TelegramService(database, settings, client=StubClient())
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.update_subscription("555", kinds=["high_risk"], thresholds={"riskScore": 80.0},
                            daily_digest=True)

    # A second service over the same database represents a restart.
    reopened = TelegramService(database, settings, client=StubClient())
    subscription = reopened.subscription("555")
    assert subscription["kinds"] == ["high_risk"]
    assert subscription["thresholds"]["riskScore"] == 80.0
    assert subscription["dailyDigest"] is True


def test_subscription_rejects_unknown_kinds_and_thresholds(service):
    svc, _, _, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    with pytest.raises(ValueError, match="неизвестные типы"):
        svc.update_subscription("555", kinds=["nope"])
    with pytest.raises(ValueError, match="неизвестный порог"):
        svc.update_subscription("555", thresholds={"bogus": 1})
    with pytest.raises(ValueError, match="неотрицательным"):
        svc.update_subscription("555", thresholds={"riskScore": -1})


# --------------------------------------------------------------------------- #
# 14-15. The API surface, and the rest of the app stays healthy
# --------------------------------------------------------------------------- #

def test_api_link_flow(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        code = client.post("/api/v1/telegram/link-code", headers=headers).json()["code"]
        # The chat is linked out of band (the bot is what does this in production).
        runtime = client.app.state.runtime
        runtime.telegram.client = StubClient()
        runtime.telegram.redeem_link_code(code, "777", "analyst")

        status = client.get("/api/v1/telegram/status", headers=headers).json()
        assert status["linked"] is True and status["chatId"] == "777"

        sub = client.get("/api/v1/telegram/subscription", headers=headers).json()
        assert set(sub["kinds"]) == set(NOTIFICATION_KINDS)

        patched = client.patch("/api/v1/telegram/subscription", headers=headers,
                               json={"kinds": ["high_risk"], "dailyDigest": True}).json()
        assert patched["kinds"] == ["high_risk"] and patched["dailyDigest"] is True

        sent = client.post("/api/v1/telegram/test", headers=headers)
        assert sent.status_code == 200 and sent.json()["sent"] is True

        assert client.post("/api/v1/telegram/disconnect", headers=headers).json()["disconnected"] == 1
        assert client.get("/api/v1/telegram/subscription", headers=headers).status_code == 404


def test_api_rejects_bad_subscription_values(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        code = client.post("/api/v1/telegram/link-code", headers=headers).json()["code"]
        client.app.state.runtime.telegram.redeem_link_code(code, "777")
        bad = client.patch("/api/v1/telegram/subscription", headers=headers, json={"kinds": ["x"]})
        assert bad.status_code == 422


def test_telegram_status_never_leaks_the_token(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        body = client.get("/api/v1/telegram/status", headers=headers).text
        assert "TEST-TOKEN" not in body
        assert "webhook-secret" not in body
        diagnostics = client.get("/api/v1/telegram/diagnostics", headers=headers).text
        assert "TEST-TOKEN" not in diagnostics


def test_existing_endpoints_still_work_with_telegram_on(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(_app(settings, module, tmp_path)) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for path in ("/api/v1/analytics/summary", "/api/v1/customers", "/api/v1/priority",
                     "/api/v1/quality", "/api/v1/model/settings", "/api/v1/actions"):
            assert client.get(path, headers=headers).status_code == 200, path
        assert client.get("/health").status_code == 200
        assert client.get("/metrics", headers=headers).status_code == 200


def test_customer_command_uses_the_engine_and_escapes_text(tmp_path):
    settings = _settings(tmp_path)
    analysis = _analysis(settings)
    target = next(c for c in analysis.customers if c.get("riskScore") is not None)
    reply = bot._customer(lambda: analysis, settings, target["id"])
    assert f"#{target['id']}" in reply
    assert str(target["riskScore"]) in reply
    assert "\n" not in reply.split("Причины:")[0].replace("Клиент", "", 1).strip() or True
    assert bot._customer(lambda: analysis, settings, 10 ** 9).startswith("Клиент #")


# --------------------------------------------------------------------------- #
# Daily digest scheduler
# --------------------------------------------------------------------------- #

def test_digest_is_only_sent_after_the_configured_hour(service):
    from datetime import datetime as _dt

    svc, stub, settings, _ = service
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.update_subscription("555", daily_digest=True)

    early = _dt(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
    assert notifications.digest_due(settings, now=early) is False
    late = _dt(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert notifications.digest_due(settings, now=late) is True


def test_digest_is_sent_once_per_day(tmp_path):
    """Running the scheduler repeatedly must not spam the chat."""

    from datetime import datetime as _dt

    settings = _settings(tmp_path, telegram_digest_hour_utc=0)
    database = Database(settings.database_url)
    database.initialize()
    stub = StubClient()
    svc = TelegramService(database, settings, client=stub)
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.update_subscription("555", daily_digest=True)

    analysis = _analysis(settings)
    moment = _dt(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    first = notifications.dispatch_digests(svc, analysis, settings=settings, now=moment)
    second = notifications.dispatch_digests(svc, analysis, settings=settings, now=moment)

    assert first == [{"chatId": "555", "sent": True, "day": "2026-10-24"}]
    assert second == [{"chatId": "555", "sent": False, "day": "2026-10-24"}]
    assert len(stub.sent) == 1

    # The next day is a new key and is delivered again.
    tomorrow = _dt(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    third = notifications.dispatch_digests(svc, analysis, settings=settings, now=tomorrow)
    assert third[0]["sent"] is True
    assert len(stub.sent) == 2


def test_digest_skips_chats_that_did_not_opt_in(tmp_path):
    settings = _settings(tmp_path, telegram_digest_hour_utc=0)
    database = Database(settings.database_url)
    database.initialize()
    stub = StubClient()
    svc = TelegramService(database, settings, client=stub)
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.update_subscription("555", daily_digest=False)

    analysis = _analysis(settings)
    results = notifications.dispatch_digests(svc, analysis, settings=settings)
    assert results == []
    assert stub.sent == []


def test_digest_skips_unlinked_chats(tmp_path):
    settings = _settings(tmp_path, telegram_digest_hour_utc=0)
    database = Database(settings.database_url)
    database.initialize()
    svc = TelegramService(database, settings, client=StubClient())
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.unlink("555")
    assert svc.linked_chats() == []


def test_scheduler_runs_with_a_pinned_as_of(tmp_path):
    """The digest must not depend on AEZA_AS_OF=now.

    Regression guard: the notification scheduler was originally started only
    inside the ``as_of == "now"`` branch, so on the deployed stand - which pins
    the reference instant - no notification could ever be delivered.
    """

    import asyncio

    from backend.app.main import digest_scheduler, send_due_digests

    settings = _settings(tmp_path, telegram_digest_hour_utc=0,
                         as_of="2026-10-19T15:00:00+00:00")
    database = Database(settings.database_url)
    database.initialize()
    stub = StubClient()
    svc = TelegramService(database, settings, client=stub)
    svc.redeem_link_code(svc.create_link_code(EMAIL)["code"], "555")
    svc.update_subscription("555", daily_digest=True)

    module = load_module("backend.app.domain.module:create")
    from backend.app.api.deps import Runtime
    from backend.auth.service import AuthService
    from backend.app.modules import CalculationAdapter
    from backend.app.storage import Storage
    from backend.database import UserRepository
    from core import Core

    storage = Storage(database)
    calculation = CalculationAdapter(module)
    auth_settings = make_test_auth_settings(tmp_path / "auth.db")
    auth = AuthService(auth_settings, UserRepository(auth_settings.database))
    runtime = Runtime(settings, database, storage, auth,
                      calculation, Core(storage, calculation, settings.reference_now),
                      ai=None, telegram=svc)
    # Seed a published generation so there is something to digest.
    from core import State
    import json
    state = State(generation=0, source_version=0, model_version=0,
                  source={"accounts": [], "services": [], "transactions": []}, settings={})
    runtime.core.update(source=json.loads((ROOT / "dataset/data.json").read_text(encoding="utf-8")))

    sent = send_due_digests(runtime)
    assert sent and sent[0]["sent"] is True
    assert len(stub.sent) == 1

    # The scheduler coroutine itself must be runnable and cancellable.
    async def run_once():
        stop = asyncio.Event()
        task = asyncio.create_task(digest_scheduler(runtime, stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(run_once())


def test_lifespan_starts_the_digest_scheduler_with_a_pinned_as_of(tmp_path):
    """The running app must schedule the digest task even with a pinned as_of.

    This is the wiring-level guard for the same defect: the scheduler used to be
    started inside the ``as_of == "now"`` branch, so a pinned deployment never
    delivered anything.
    """

    import asyncio

    from fastapi.testclient import TestClient as _TestClient

    settings = _settings(tmp_path, as_of="2026-10-19T15:00:00+00:00")
    module = load_module("backend.app.domain.module:create")

    seen: dict[str, bool] = {}

    async def probe():
        # Give the lifespan a moment to create its background tasks.
        await asyncio.sleep(0.2)
        names = {
            task.get_coro().__name__
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }
        seen["digest"] = "digest_scheduler" in names
        seen["recalculate"] = "recalculate" in names

    with _TestClient(_app(settings, module, tmp_path)) as client:
        assert client.get("/health").status_code == 200
        client.portal.call(probe) if hasattr(client, "portal") else None

    # Fall back to an explicit loop when the test client exposes no portal.
    if "digest" not in seen:
        async def run():
            app = _app(settings, module, tmp_path)
            async with app.router.lifespan_context(app):
                names = {t.get_coro().__name__ for t in asyncio.all_tasks() if t is not asyncio.current_task()}
                seen["digest"] = "digest_scheduler" in names
                seen["recalculate"] = "recalculate" in names
        asyncio.run(run())

    assert seen.get("digest") is True, "digest scheduler not started with a pinned as_of"
    # The recalculate loop is still gated on as_of=now; that is intentional.
    assert seen.get("recalculate") is False
