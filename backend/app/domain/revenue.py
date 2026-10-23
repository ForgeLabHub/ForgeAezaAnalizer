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

from app.domain.money import cents_to_eur
from app.domain.risk import ServiceRisk


@dataclass
class RenewalExposure:
    service_id: int
    renewal_at: datetime
    amount_cents: int
    risk_score: float
    revenue_at_risk_cents: int
    in_horizon: bool


@dataclass
class CustomerExposure:
    customer_id: int
    upcoming_renewals_cents: int
    revenue_at_risk_cents: int
    renewals: list[RenewalExposure] = field(default_factory=list)


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
    # An unknown price or expiry cannot be turned into a monetary exposure: a
    # missing value is not zero, and the snapshot offers no basis to guess.
    if service.price is None or service.price <= 0:
        return None
    if service.expires_at is None:
        return None

    horizon_end = now + timedelta(days=horizon_days)
    if not (now <= service.expires_at <= horizon_end):
        return None

    revenue_at_risk = int(round(service.price * risk.score / 100.0))
    return RenewalExposure(
        service_id=service.id,
        renewal_at=service.expires_at,
        amount_cents=service.price,
        risk_score=risk.score,
        revenue_at_risk_cents=revenue_at_risk,
        in_horizon=True,
    )


def compute_customer_exposure(
    *, customer_id: int, renewals: list[RenewalExposure]
) -> CustomerExposure:
    """Sum a customer's upcoming renewals and the portion at risk.

    Summing is safe because :func:`compute_service_exposure` guarantees one
    entry per service, so no renewal can be double counted.
    """

    return CustomerExposure(
        customer_id=customer_id,
        upcoming_renewals_cents=sum(r.amount_cents for r in renewals),
        revenue_at_risk_cents=sum(r.revenue_at_risk_cents for r in renewals),
        renewals=renewals,
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
            balance_text = (
                format_eur(account.balance) if account.balance is not None else "неизвестен"
            )
            price_text = (
                format_eur(service.price) if service.price is not None else "неизвестна"
            )
            out.append(
                Recommendation(
                    code="check_balance",
                    title="Проверить достаточность баланса",
                    detail=(
                        f"Баланс {balance_text} не покрывает продление "
                        f"({price_text}). Предложите пополнение или смену тарифа."
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
