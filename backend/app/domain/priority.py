"""Retention priority: a ranked worklist over risk *and* money at stake.

Risk and exposure answer different questions and are deliberately kept apart in
:mod:`app.domain.risk` and :mod:`app.domain.revenue`.  An analyst, however, needs
a single ordered answer to "whom do we work first, and why".  This module builds
that order without corrupting either input:

* the **risk score** is never inflated by price — it stays the pure likelihood
  signal produced by :mod:`app.domain.risk`;
* the **expected exposure** is the risk-weighted money inside the horizon,
  already computed by :mod:`app.domain.revenue`;
* the **priority score** is a 0–100 *relative triage index* derived from the
  expected exposure, so the most exposed service in the current portfolio scores
  100 and the rest are scaled against it.

The priority score is explicitly **not** a probability and **not** a currency
amount.  It only orders a worklist, and it is documented as relative to the
portfolio because that is what it is.

Ranking is defined over the *serialised customer payloads* that the API already
publishes, so the worklist is computed from the same stored generation as the
dashboard and the customer card and can never drift from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.money import cents_to_eur

#: Tiers, most urgent first.  The tier is *absolute* (it depends only on the
#: risk category and whether money is inside the horizon), so it does not shift
#: when unrelated customers are added or removed.
TIER_CRITICAL = "p1"
TIER_HIGH = "p2"
TIER_WATCH = "p3"

TIER_LABELS = {
    TIER_CRITICAL: "P1 · Критический",
    TIER_HIGH: "P2 · Высокий",
    TIER_WATCH: "P3 · Наблюдение",
}

TIER_DESCRIPTIONS = {
    TIER_CRITICAL: "Высокий риск и продление внутри горизонта: деньги теряются сейчас.",
    TIER_HIGH: "Высокий риск без продления в горизонте либо средний риск с деньгами в горизонте.",
    TIER_WATCH: "Есть рассчитанный риск, но деньги в горизонте не подтверждены.",
}

#: Categories that can appear on the worklist at all.
SCORED_CATEGORIES = frozenset({"low", "medium", "high"})


@dataclass
class PriorityItem:
    """One retention action, ready to be displayed as a worklist row."""

    rank: int
    customer_id: int
    email: str
    service_id: int
    service_name: str
    service_status: str
    risk_score: float | None
    risk_category: str
    days_to_expiry: float | None
    renewal_at: str | None
    renewal_amount_cents: int | None
    revenue_at_risk_cents: int
    priority_score: float
    tier: str
    tier_label: str = ""
    tier_reason: str = ""
    reasons: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


def tier_for(risk_category: str, revenue_at_risk_cents: int) -> str:
    """Classify one service into an absolute urgency tier."""

    has_money = revenue_at_risk_cents > 0
    if risk_category == "high" and has_money:
        return TIER_CRITICAL
    if risk_category == "high":
        return TIER_HIGH
    if risk_category == "medium" and has_money:
        return TIER_HIGH
    return TIER_WATCH


def _amount_cents(money: dict | None) -> int | None:
    """Read eurocents from a serialised ``{cents, eur}`` pair."""

    if not isinstance(money, dict):
        return None
    cents = money.get("cents")
    return cents if isinstance(cents, int) and not isinstance(cents, bool) else None


def collect_candidates(customers: list[dict]) -> list[PriorityItem]:
    """Build the unranked candidate set from serialised customer payloads."""

    candidates: list[PriorityItem] = []
    for customer in customers:
        for service in customer.get("services") or []:
            if not service.get("eligibleForForecast"):
                continue
            category = service.get("riskCategory")
            score = service.get("riskScore")
            if category not in SCORED_CATEGORIES or score is None:
                continue
            exposure_cents = _amount_cents(service.get("revenueAtRisk")) or 0
            renewal_amount = _amount_cents(service.get("renewalAmount")) if "renewalAmount" in service else None
            candidates.append(
                PriorityItem(
                    rank=0,
                    customer_id=customer["id"],
                    email=customer.get("email") or "",
                    service_id=service["id"],
                    service_name=service.get("name") or "",
                    service_status=service.get("status") or "",
                    risk_score=score,
                    risk_category=category,
                    days_to_expiry=service.get("daysToExpiry"),
                    renewal_at=service.get("upcomingRenewalAt"),
                    renewal_amount_cents=renewal_amount,
                    revenue_at_risk_cents=exposure_cents,
                    priority_score=0.0,
                    tier=tier_for(category, exposure_cents),
                    reasons=list(service.get("reasons") or [])[:3],
                    actions=[rec.get("title", "") for rec in (service.get("recommendations") or [])],
                )
            )
    return candidates


def rank_candidates(candidates: list[PriorityItem], *, limit: int | None = None,
                    tier: str | None = None, sort: str = "priority") -> list[PriorityItem]:
    """Order candidates and assign ranks.

    ``sort="priority"`` orders by expected exposure (risk-weighted money inside
    the horizon) and is the default because it answers "where do we save the most
    revenue".  ``sort="risk"`` orders by the risk score instead, for teams that
    work by likelihood rather than by money.  Neither mode changes any score; only
    the presentation order changes.
    """

    if not candidates:
        return []

    # Normalise against the largest expected exposure in this portfolio.  When no
    # exposure is inside the horizon the index falls back to the risk score so the
    # list still orders meaningfully.
    peak = max((c.revenue_at_risk_cents for c in candidates), default=0)
    for item in candidates:
        if peak > 0:
            item.priority_score = round(100.0 * item.revenue_at_risk_cents / peak, 1)
        else:
            item.priority_score = round(float(item.risk_score or 0.0), 1)

    if sort == "risk":
        key = lambda c: (
            -(c.risk_score or 0.0),
            -c.revenue_at_risk_cents,
            c.days_to_expiry if c.days_to_expiry is not None else float("inf"),
            c.customer_id,
            c.service_id,
        )
    else:
        key = lambda c: (
            -c.revenue_at_risk_cents,
            -(c.risk_score or 0.0),
            c.days_to_expiry if c.days_to_expiry is not None else float("inf"),
            c.customer_id,
            c.service_id,
        )
    candidates.sort(key=key)

    selected = [c for c in candidates if tier is None or c.tier == tier]
    if limit is not None:
        selected = selected[:limit]
    for position, item in enumerate(selected, start=1):
        item.rank = position
        item.tier_label = TIER_LABELS[item.tier]
        item.tier_reason = TIER_DESCRIPTIONS[item.tier]
    return selected


def build_priority(customers: list[dict], *, limit: int | None = None,
                   tier: str | None = None, sort: str = "priority") -> list[PriorityItem]:
    """Rank serialised customer payloads into a worklist."""

    return rank_candidates(
        collect_candidates(customers), limit=limit, tier=tier, sort=sort
    )


def priority_summary(items: list[PriorityItem], total_services: int) -> dict:
    """Aggregate a priority worklist for the Action Center header."""

    by_tier = {tier: 0 for tier in (TIER_CRITICAL, TIER_HIGH, TIER_WATCH)}
    for item in items:
        by_tier[item.tier] = by_tier.get(item.tier, 0) + 1
    exposure = sum(item.revenue_at_risk_cents for item in items)
    return {
        "items": len(items),
        # Total services in the snapshot, so the analyst can see how much of the
        # portfolio the worklist actually covers.
        "servicesInPortfolio": total_services,
        "servicesScored": len(items),
        "byTier": by_tier,
        "tierLabels": TIER_LABELS,
        "tierDescriptions": TIER_DESCRIPTIONS,
        "revenueAtRiskCents": exposure,
        "revenueAtRiskEur": str(cents_to_eur(exposure)),
        "customers": len({item.customer_id for item in items}),
        "note": (
            "Приоритет — относительный индекс 0–100 по ожидаемой экспозиции внутри горизонта. "
            "Это порядок работ, а не вероятность и не сумма денег."
        ),
    }


def serialize_priority(item: PriorityItem) -> dict:
    return {
        "rank": item.rank,
        "customerId": item.customer_id,
        "email": item.email,
        "serviceId": item.service_id,
        "serviceName": item.service_name,
        "serviceStatus": item.service_status,
        "riskScore": item.risk_score,
        "riskCategory": item.risk_category,
        "daysToExpiry": round(item.days_to_expiry, 2) if item.days_to_expiry is not None else None,
        "renewalAt": item.renewal_at,
        "renewalAmount": (
            {"cents": item.renewal_amount_cents, "eur": str(cents_to_eur(item.renewal_amount_cents))}
            if item.renewal_amount_cents is not None
            else None
        ),
        "revenueAtRisk": {
            "cents": item.revenue_at_risk_cents,
            "eur": str(cents_to_eur(item.revenue_at_risk_cents)),
        },
        "priorityScore": item.priority_score,
        "tier": item.tier,
        "tierLabel": item.tier_label,
        "tierReason": item.tier_reason,
        "reasons": item.reasons,
        "actions": item.actions,
    }
