"""Projected revenue-at-risk and retention recommendations.

Revenue exposure is deliberately kept out of the risk score.  A cheap service
can be high risk and an expensive service low risk; only the monetary impact
combines the two.

Method
------
``revenue_at_risk = eligible_renewal_amount * risk_score / 100``

where ``eligible_renewal_amount`` is the price of the *next* renewal of a
service that is both open (``active`` / ``suspended`` / ``prolong_wait``) and
due inside the configured horizon.  Each renewal is counted once: a service
contributes at most one upcoming renewal per horizon, and services whose
``expiresAt`` lies beyond the horizon contribute nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.money import cents_to_eur, scaled_cents
from app.domain.risk import ServiceRisk


@dataclass
class RenewalExposure:
    service_id: int
    renewal_at: datetime
    amount_cents: int
    risk_score: float
    revenue_at_risk_cents: int
    in_horizon: bool


#: Horizons reported side by side, in days.
HORIZONS: tuple[int, ...] = (7, 30, 90)

#: A ``prolong_wait`` service that has been awaiting payment longer than this
#: should already have moved to ``deleted`` per the case brief.  Kept as a
#: named constant so the diagnostic and its tests share one definition.
PROLONG_WAIT_GRACE_DAYS = 5


@dataclass
class OverdueExposure:
    """An open service whose ``expiresAt`` is already in the past.

    Reported separately from the forward horizons: a service that has already
    expired has no *future* renewal to count, but leaving it out entirely would
    hide a real operational problem.  The nominal price is shown as the amount
    needing review, never as predicted revenue.
    """

    service_id: int
    status: str
    expired_at: datetime
    days_overdue: float
    amount_cents: int
    #: True when a ``prolong_wait`` service is past the documented grace period,
    #: i.e. the snapshot state contradicts the stated lifecycle.
    lifecycle_inconsistent: bool


@dataclass
class HorizonExposure:
    """Nominal and risk-weighted amounts for one forward horizon."""

    horizon_days: int
    renewal_count: int
    upcoming_renewals_cents: int
    revenue_at_risk_cents: int


@dataclass
class CustomerExposure:
    customer_id: int
    upcoming_renewals_cents: int
    revenue_at_risk_cents: int
    renewals: list[RenewalExposure] = field(default_factory=list)
    #: Per-horizon breakdown keyed by day count (7 / 30 / 90).
    horizons: dict[int, HorizonExposure] = field(default_factory=dict)
    overdue: list[OverdueExposure] = field(default_factory=list)
    overdue_operational_cents: int = 0
    #: Number of services whose state contradicts the documented lifecycle.
    lifecycle_inconsistent_count: int = 0


def compute_service_exposure(
    *,
    service,
    risk: ServiceRisk,
    horizon_days: int,
    now: datetime,
) -> RenewalExposure | None:
    """Return the renewal exposure for one service, or ``None`` if not eligible.

    A service is eligible when it is open, has a positive price and its
    ``expiresAt`` falls inside ``[now, now + horizon]``.  Already-expired open
    services are *not* included: the snapshot has no evidence that they will be
    renewed, and counting them would present an unverifiable guess as lost
    revenue.
    """

    if not risk.eligible or risk.score is None:
        return None
    if service.price <= 0:
        return None

    horizon_end = now + timedelta(days=horizon_days)
    if not (now <= service.expires_at <= horizon_end):
        return None

    revenue_at_risk = scaled_cents(service.price, risk.score / 100.0)
    return RenewalExposure(
        service_id=service.id,
        renewal_at=service.expires_at,
        amount_cents=service.price,
        risk_score=risk.score,
        revenue_at_risk_cents=revenue_at_risk,
        in_horizon=True,
    )


def compute_overdue(
    *, services: list, risks_by_service: dict, now: datetime
) -> list[OverdueExposure]:
    """Collect open services whose ``expiresAt`` already passed.

    These carry no *future* renewal, so they stay out of the forward horizons,
    but they are exactly the cases an operator must look at.  A ``prolong_wait``
    service overdue beyond the documented grace period is additionally flagged
    as lifecycle-inconsistent: the brief says it should have become ``deleted``.

    The flag is a data-consistency signal.  It is never a claim that the service
    will be renewed, nor that the customer has churned.
    """

    out: list[OverdueExposure] = []
    for service in services:
        risk = risks_by_service.get(service.id)
        if risk is None or not risk.eligible:
            continue
        if service.expires_at >= now:
            continue
        days_overdue = (now - service.expires_at).total_seconds() / 86400.0
        inconsistent = (
            service.status == "prolong_wait" and days_overdue > PROLONG_WAIT_GRACE_DAYS
        )
        out.append(
            OverdueExposure(
                service_id=service.id,
                status=service.status,
                expired_at=service.expires_at,
                days_overdue=days_overdue,
                amount_cents=service.price,
                lifecycle_inconsistent=inconsistent,
            )
        )
    return out


def compute_horizons(
    *, services: list, risks_by_service: dict, now: datetime
) -> dict[int, HorizonExposure]:
    """Nominal and risk-weighted amounts for each configured horizon.

    A service contributes to a horizon when ``now <= expiresAt <= now + H``
    (inclusive on both ends).  It appears in every horizon that contains its
    expiry but only **once** per horizon, so no amount is double counted.
    """

    result: dict[int, HorizonExposure] = {}
    for days in HORIZONS:
        end = now + timedelta(days=days)
        count = 0
        nominal = 0
        at_risk = 0
        for service in services:
            risk = risks_by_service.get(service.id)
            if risk is None or not risk.eligible or risk.score is None:
                continue
            if service.price <= 0:
                continue
            if not (now <= service.expires_at <= end):
                continue
            count += 1
            nominal += service.price
            at_risk += scaled_cents(service.price, risk.score / 100.0)
        result[days] = HorizonExposure(
            horizon_days=days,
            renewal_count=count,
            upcoming_renewals_cents=nominal,
            revenue_at_risk_cents=at_risk,
        )
    return result


def compute_customer_exposure(
    *,
    customer_id: int,
    renewals: list[RenewalExposure],
    services: list | None = None,
    risks_by_service: dict | None = None,
    now: datetime | None = None,
) -> CustomerExposure:
    """Sum a customer's upcoming renewals and the portion at risk.

    Summing is safe because :func:`compute_service_exposure` guarantees one
    entry per service, so no renewal can be double counted.

    When ``services`` and ``now`` are supplied the per-horizon breakdown and the
    overdue list are filled in as well; otherwise those fields stay empty and
    the function keeps its original two-argument behaviour.
    """

    horizons: dict[int, HorizonExposure] = {}
    overdue: list[OverdueExposure] = []
    if services is not None and risks_by_service is not None and now is not None:
        horizons = compute_horizons(
            services=services, risks_by_service=risks_by_service, now=now
        )
        overdue = compute_overdue(services=services, risks_by_service=risks_by_service, now=now)

    return CustomerExposure(
        customer_id=customer_id,
        upcoming_renewals_cents=sum(r.amount_cents for r in renewals),
        revenue_at_risk_cents=sum(r.revenue_at_risk_cents for r in renewals),
        renewals=renewals,
        horizons=horizons,
        overdue=overdue,
        overdue_operational_cents=sum(o.amount_cents for o in overdue),
        lifecycle_inconsistent_count=sum(1 for o in overdue if o.lifecycle_inconsistent),
    )


def format_eur(cents: int) -> str:
    return f"{cents_to_eur(cents):.2f} EUR"


@dataclass(frozen=True)
class Recommendation:
    code: str
    title: str
    detail: str
    priority: int


def build_recommendations(risk: ServiceRisk, account, service) -> list[Recommendation]:
    """Derive retention actions that are grounded in observed signals.

    Every recommendation traces back to a concrete factor or status in the
    snapshot.  Nothing here claims that an action *will* prevent churn.
    """

    out: list[Recommendation] = []

    if risk.category in ("high", "medium") and risk.days_to_expiry is not None:
        if risk.days_to_expiry < 0:
            overdue = abs(risk.days_to_expiry)
            out.append(
                Recommendation(
                    code="overdue_renewal",
                    title="Просроченное продление",
                    detail=(
                        f"Услуга «{service.name}» истекла {overdue:.1f} дн. назад "
                        f"({service.expires_at:%d.%m.%Y %H:%M} UTC) и не продлена. "
                        "Выясните, планирует ли клиент продление."
                    ),
                    priority=1,
                )
            )
        elif risk.days_to_expiry <= 7:
            out.append(
                Recommendation(
                    code="notify_expiring",
                    title="Уведомить о скором окончании",
                    detail=(
                        f"Услуга «{service.name}» истекает {service.expires_at:%d.%m.%Y %H:%M} UTC "
                        f"(осталось {risk.days_to_expiry:.1f} дн.). Свяжитесь с клиентом заранее."
                    ),
                    priority=1,
                )
            )

    for factor in risk.factors:
        if not factor.available or not factor.value or factor.value <= 0:
            continue
        if factor.key == "insufficient_balance":
            out.append(
                Recommendation(
                    code="check_balance",
                    title="Проверить достаточность баланса",
                    detail=(
                        f"Баланс {format_eur(account.balance)} не покрывает продление "
                        f"({format_eur(service.price)}). Предложите пополнение или смену тарифа."
                    ),
                    priority=2,
                )
            )
        elif factor.key == "failed_renewals":
            out.append(
                Recommendation(
                    code="investigate_failed_renewal",
                    title="Разобраться с неуспешным продлением",
                    detail="По услуге есть транзакции продления со статусом not_performed — проверьте причину отказа.",
                    priority=2,
                )
            )
        elif factor.key == "prolong_wait_status":
            out.append(
                Recommendation(
                    code="check_prolong_wait",
                    title="Проверить причину ожидания продления",
                    detail="Услуга находится в статусе prolong_wait дольше ожидаемого — уточните, что блокирует продление.",
                    priority=1,
                )
            )
        elif factor.key == "auto_prolong_disabled":
            out.append(
                Recommendation(
                    code="review_autoprolong",
                    title="Обсудить включение автопродления",
                    detail="Автопродление отключено — предложите клиенту включить его, чтобы избежать разрыва услуги.",
                    priority=3,
                )
            )
        elif factor.key == "suspended_status":
            out.append(
                Recommendation(
                    code="restore_suspended",
                    title="Выяснить причину приостановки",
                    detail="Услуга приостановлена (suspended) — уточните причину и условия восстановления.",
                    priority=1,
                )
            )

    if not out and risk.category == "high":
        out.append(
            Recommendation(
                code="verify_renewal",
                title="Проверить возможность продления",
                detail=f"Проверьте, что услуга «{service.name}» может быть продлена в текущих условиях.",
                priority=2,
            )
        )

    seen: set[str] = set()
    unique: list[Recommendation] = []
    for rec in sorted(out, key=lambda r: r.priority):
        if rec.code in seen:
            continue
        seen.add(rec.code)
        unique.append(rec)
    return unique
