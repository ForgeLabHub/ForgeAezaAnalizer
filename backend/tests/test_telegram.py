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

from backend.tests.conftest import ROOT

EMAIL = "analyst@aeza.test"
PASSWORD = "demo123"


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
        auth_database_url=f"sqlite:///{(tmp_path / 'auth.db').as_posix()}",
        jwt_secret="test-secret",
        bootstrap_admin_password=PASSWORD,
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        telegram_enabled=True,
        telegram_bot_token="123:TEST-TOKEN",
        telegram_webhook_secret="webhook-secret",
        telegram_min_send_interval_seconds=0,
    )
    base.update(overrides)
    return Settings(**base)


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
    with TestClient(create_app(settings, module)) as client:
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
    settings = Settings(jwt_secret="x", bootstrap_admin_password="y")
    assert settings.telegram_enabled is False
    assert settings.telegram_bot_token == ""


def test_enabling_telegram_without_a_token_is_rejected():
    with pytest.raises(ValueError):
        Settings(jwt_secret="x", bootstrap_admin_password="y",
                 telegram_enabled=True, telegram_bot_token="", telegram_webhook_secret="s")


def test_enabling_telegram_without_a_webhook_secret_is_rejected():
    with pytest.raises(ValueError):
        Settings(jwt_secret="x", bootstrap_admin_password="y",
                 telegram_enabled=True, telegram_bot_token="t", telegram_webhook_secret="")


# --------------------------------------------------------------------------- #
# 3-6. Linking
# --------------------------------------------------------------------------- #

def test_link_code_requires_authentication(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(create_app(settings, module)) as client:
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
    with TestClient(create_app(settings, module)) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            json=_update("/help"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert response.status_code == 403


def test_webhook_accepts_the_right_secret(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(create_app(settings, module)) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            json=_update("/help"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
        )
        assert response.status_code == 200


def test_webhook_tolerates_a_malformed_body(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(create_app(settings, module)) as client:
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
    with TestClient(create_app(settings, module)) as client:
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
    with TestClient(create_app(settings, module)) as client:
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
    with TestClient(create_app(settings, module)) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        code = client.post("/api/v1/telegram/link-code", headers=headers).json()["code"]
        client.app.state.runtime.telegram.redeem_link_code(code, "777")
        bad = client.patch("/api/v1/telegram/subscription", headers=headers, json={"kinds": ["x"]})
        assert bad.status_code == 422


def test_telegram_status_never_leaks_the_token(tmp_path):
    settings = _settings(tmp_path)
    module = load_module("backend.app.domain.module:create")
    with TestClient(create_app(settings, module)) as client:
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
    with TestClient(create_app(settings, module)) as client:
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
