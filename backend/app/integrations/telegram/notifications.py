"""Turn the analytics output into Telegram notifications.

Every message here is derived from data the product already publishes: the same
``Analysis`` the HTTP API serves. Nothing is invented, and nothing is
recomputed — if the Risk Engine's number changes, the notification changes with
it.

Deduplication is by content, not by wall-clock time: a ``dedupe_key`` built from
the analysis generation and the subject means re-running the evaluation on the
same generation cannot send the same alert twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.config import Settings
from backend.app.integrations.telegram.client import escape_text
from backend.app.integrations.telegram.service import (
    DEFAULT_THRESHOLDS,
    TelegramService,
)

logger = logging.getLogger("aeza.telegram")


@dataclass(frozen=True)
class Event:
    """One notifiable fact, already rendered as text."""

    kind: str
    dedupe_key: str
    text: str


def _money(eur: str | None) -> str:
    return f"{eur} €" if eur else "—"


def _generation_of(analysis) -> int | None:
    """The published generation of an analysis, from either shape.

    The engine nests it under ``version``; an ``analysis`` built directly in a
    test may carry it at the top level. Both are accepted so a caller never
    silently loses the version and falls back to a dedupe key that never changes.
    """

    summary = getattr(analysis, "summary", None) or {}
    if summary.get("generation") is not None:
        return summary["generation"]
    return (summary.get("version") or {}).get("generation")


def _generation_label(analysis) -> str:
    generation = _generation_of(analysis)
    return str(generation) if generation is not None else "—"


def build_events(
    analysis,
    *,
    settings: Settings,
    previous=None,
    thresholds: dict | None = None,
    kinds: list[str] | None = None,
) -> list[Event]:
    """Derive the notifications this analysis justifies.

    ``analysis`` is the object the analytics module returns (``summary`` plus
    ``customers``). ``previous`` is the previous published analysis, used to
    detect a *change* (a category move, a jump in exposure) rather than a
    steady state — so a customer who has been high-risk for a week does not
    produce a message every run.
    """

    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    enabled = set(kinds if kinds is not None else ("high_risk", "exposure_jump"))
    summary = analysis.summary
    # ``generation`` lives inside the ``version`` block the engine attaches to the
    # summary, not at the top level. Reading it from the wrong place yielded
    # ``None``, which made every dedupe key identical across generations and
    # suppressed every alert after the first.
    generation = _generation_of(analysis)
    events: list[Event] = []

    previous_customers = {
        customer["id"]: customer for customer in (getattr(previous, "customers", None) or [])
    }

    # --- high risk: only a transition into high, not a standing state ------ #
    if "high_risk" in enabled:
        for customer in analysis.customers:
            if customer.get("riskCategory") != "high":
                continue
            before = previous_customers.get(customer["id"])
            was_high = bool(before) and before.get("riskCategory") == "high"
            score = customer.get("riskScore")
            if was_high:
                continue
            if score is not None and score < limits["riskScore"] and before is not None:
                # A fresh high-risk customer whose score is below the configured
                # threshold is not worth waking someone for.
                continue
            reason = (customer.get("topReasons") or ["причины не указаны"])[0]
            events.append(Event(
                kind="high_risk",
                dedupe_key=f"high_risk:{generation}:{customer['id']}",
                text=(
                    f"⚠️ Клиент #{customer['id']} перешёл в высокий риск\n"
                    f"Балл: {score if score is not None else '—'} · "
                    f"выручка под риском: {_money((customer.get('revenueAtRisk') or {}).get('eur'))}\n"
                    f"Причина: {escape_text(reason)}"
                ),
            ))

    # --- exposure jump: revenue at risk grew past the threshold ------------ #
    if "exposure_jump" in enabled:
        current = (summary.get("revenue") or {}).get("revenueAtRiskCents") or 0
        previous_cents = None
        if previous is not None:
            previous_cents = (getattr(previous, "summary", {}) or {}).get("revenue", {}).get("revenueAtRiskCents")
        if previous_cents is not None:
            growth = (current - previous_cents) / 100
            if growth >= limits["exposureEur"]:
                events.append(Event(
                    kind="exposure_jump",
                    dedupe_key=f"exposure_jump:{generation}",
                    text=(
                        f"📈 Выручка под риском выросла на {growth:.2f} €\n"
                        f"Сейчас: {_money((summary.get('revenue') or {}).get('revenueAtRiskEur'))}\n"
                        f"Поколение расчёта: #{generation}"
                    ),
                ))

    # --- new retention recommendation ------------------------------------- #
    if "new_action" in enabled:
        seen_before = set()
        for customer in (getattr(previous, "customers", None) or []):
            for item in customer.get("recommendations") or []:
                seen_before.add((customer["id"], item.get("code")))
        for customer in analysis.customers:
            for item in customer.get("recommendations") or []:
                key = (customer["id"], item.get("code"))
                if key in seen_before:
                    continue
                events.append(Event(
                    kind="new_action",
                    dedupe_key=f"new_action:{generation}:{customer['id']}:{item.get('code')}",
                    text=(
                        f"📋 Новая рекомендация для клиента #{customer['id']}\n"
                        f"{escape_text(item.get('title'))}\n"
                        f"{escape_text(item.get('detail'))}"
                    ),
                ))

    return events


def digest_text(analysis, *, settings: Settings) -> str:
    """A one-message summary of the current picture, for the daily digest."""

    summary = analysis.summary
    customers = summary.get("customers") or {}
    revenue = summary.get("revenue") or {}
    by_category = customers.get("byCategory") or {}
    return (
        "📊 Сводка Aéza Sentinel\n"
        f"Клиентов: {customers.get('total', '—')} "
        f"(высокий {by_category.get('high', 0)}, средний {by_category.get('medium', 0)})\n"
        f"Выручка под риском: {_money(revenue.get('revenueAtRiskEur'))}\n"
        f"Предстоящие продления: {_money(revenue.get('upcomingRenewalsEur'))}\n"
        f"Поколение расчёта: #{_generation_label(analysis)}"
    )


def dispatch(
    service: TelegramService,
    analysis,
    *,
    settings: Settings,
    previous=None,
    chat_id: str,
) -> list[dict]:
    """Send every event justified by this analysis to one chat.

    Returns a per-event result so the caller (and the tests) can see what was
    sent, skipped or refused without parsing logs.
    """

    subscription = service.subscription(chat_id)
    events = build_events(
        analysis,
        settings=settings,
        previous=previous,
        thresholds=subscription["thresholds"],
        kinds=subscription["kinds"],
    )
    results = []
    for event in events:
        sent = service.send(chat_id, event.text, kind=event.kind, dedupe_key=event.dedupe_key)
        results.append({"kind": event.kind, "dedupeKey": event.dedupe_key, "sent": sent})
    return results


def dispatch_digests(service: TelegramService, analysis, *, settings: Settings, now=None) -> list[dict]:
    """Send the daily digest to every chat that asked for it, at most once a day.

    The dedupe key is the UTC date, so the scheduler can run as often as it likes
    without sending twice. Chats that have not enabled the digest are skipped
    even if they are subscribed to other kinds.
    """

    moment = now or datetime.now(timezone.utc)
    day = moment.date().isoformat()
    results = []
    for chat_id in service.linked_chats():
        subscription = service.subscription(chat_id)
        if not subscription["dailyDigest"]:
            continue
        sent = service.send(
            chat_id,
            digest_text(analysis, settings=settings),
            kind="daily_digest",
            dedupe_key=f"daily_digest:{day}",
        )
        results.append({"chatId": chat_id, "sent": sent, "day": day})
    return results


def digest_due(settings: Settings, now=None) -> bool:
    """Whether the configured digest hour has passed for the current UTC day."""

    moment = now or datetime.now(timezone.utc)
    return moment.hour >= settings.telegram_digest_hour_utc
