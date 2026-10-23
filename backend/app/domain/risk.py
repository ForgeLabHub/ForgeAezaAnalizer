"""Explainable churn-risk scoring for Aéza services and customers.

Design notes
------------
The snapshot contains **no historical churn outcomes** (no cancellation events,
no lost-customer labels), so a trained and validated classifier is not
defensible.  This module therefore implements a transparent, weighted
rule-based score and the product states that honestly instead of implying
predictive accuracy it cannot demonstrate.

Three concepts are kept strictly apart:

``current_state``
    What is true about the service right now (``active``, ``suspended``,
    ``prolong_wait``) or already concluded (``deleted``, ``blocked``).
``churn_risk``
    A forward-looking score for a *future* adverse event inside the configured
    horizon.  Only services whose state is still open are eligible.
``revenue_at_risk``
    A monetary exposure, computed separately (see :mod:`app.domain.revenue`).
    A high price never by itself raises the risk score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .money import cents_to_eur

#: Service states that are still open, i.e. a future churn event is possible.
ELIGIBLE_STATUSES: frozenset[str] = frozenset({"active", "suspended", "prolong_wait"})

#: Service states that describe an already-concluded outcome.
CONCLUDED_STATUSES: frozenset[str] = frozenset({"deleted", "blocked"})

#: Trailing window (days) used when counting failed renewals.  ``None`` means
#: "every event present in the snapshot".
FAILED_RENEWAL_WINDOW_DAYS: int | None = 90


@dataclass(frozen=True)
class FactorDefinition:
    """Static description of one risk factor."""

    key: str
    label: str
    description: str
    how_computed: str
    normalization: str
    default_weight: float
    missing_data_behaviour: str = "factor excluded and weights renormalised"
    #: ``True`` for factors kept in the API for compatibility but excluded from
    #: the weighted sum (weight is 0).  The signal they describe is already
    #: carried by another factor, so counting them again would double-weight it.
    deprecated: bool = False


FACTORS: tuple[FactorDefinition, ...] = (
    FactorDefinition(
        key="expiry_proximity",
        label="Близость даты окончания",
        description="Услуга истекает в пределах горизонта прогноза или уже истекла.",
        how_computed="days_left = (expiresAt - now) в сутках; линейный спад до нуля на границе горизонта",
        normalization="0 при days_left >= horizon; 1 при days_left <= 0; иначе 1 - days_left/horizon",
        default_weight=3.0,
    ),
    FactorDefinition(
        key="auto_prolong_disabled",
        label="Автопродление отключено",
        description="Услуга не продлится автоматически, поэтому решение о продлении не принято заранее.",
        how_computed="autoProlong == false",
        normalization="1 если автопродление отключено, иначе 0",
        default_weight=2.0,
    ),
    FactorDefinition(
        key="insufficient_balance",
        label="Недостаточно средств для продления",
        description="Доступного баланса аккаунта не хватает для оплаты ближайшего продления.",
        how_computed="ratio = balance / price; при price = 0 фактор неприменим",
        normalization="clip(1 - ratio, 0, 1): 1 при нулевом балансе, 0 при balance >= price",
        default_weight=2.0,
    ),
    FactorDefinition(
        key="prolong_wait_status",
        label="Ожидание продления",
        description="Услуга находится в статусе prolong_wait, то есть продление не завершено.",
        how_computed="status == 'prolong_wait'",
        normalization="1 если статус prolong_wait, иначе 0",
        default_weight=2.5,
    ),
    FactorDefinition(
        key="failed_renewals",
        label="Неуспешные продления",
        description=(
            "Число транзакций продления со статусом not_performed. Диагностический "
            "показатель: сигнал уже учтён в renewal_failure_rate и в рейтинг не входит."
        ),
        how_computed="количество not_performed продлений в пределах окна",
        normalization="не участвует в рейтинге (вес 0)",
        default_weight=0.0,
        deprecated=True,
        missing_data_behaviour="factor excluded and weights renormalised",
    ),
    FactorDefinition(
        key="suspended_status",
        label="Услуга приостановлена",
        description=(
            "Статус suspended означает отключение по требованию клиента, при этом "
            "начисления продолжаются, поэтому это сигнал внимания, а не оттока."
        ),
        how_computed="status == 'suspended'",
        normalization="1 если статус suspended, иначе 0",
        default_weight=1.0,
    ),
    FactorDefinition(
        key="renewal_failure_rate",
        label="Доля неуспешных продлений",
        description="Доля неуспешных продлений от всех попыток продления по услуге.",
        how_computed="not_performed / все продления услуги в пределах окна",
        normalization="0..1; 0 если по услуге нет продлений",
        default_weight=2.5,
    ),
)

FACTOR_BY_KEY: dict[str, FactorDefinition] = {f.key: f for f in FACTORS}

DEFAULT_WEIGHTS: dict[str, float] = {f.key: f.default_weight for f in FACTORS}

#: Risk bands, inclusive upper bounds.  Centralised so both the API and the UI
#: agree on the same classification.
DEFAULT_LOW_MAX = 34
DEFAULT_MEDIUM_MAX = 64


class RiskConfigError(ValueError):
    """Raised when model settings are structurally invalid."""


@dataclass(frozen=True)
class RiskSettings:
    """User-tunable model configuration."""

    horizon_days: int = 30
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    low_max: int = DEFAULT_LOW_MAX
    medium_max: int = DEFAULT_MEDIUM_MAX
    #: Trailing window for failed renewals.  ``None`` = whole snapshot.
    failed_renewal_window_days: int | None = FAILED_RENEWAL_WINDOW_DAYS

    def __post_init__(self) -> None:
        validate_settings(self)

    def weight(self, key: str) -> float:
        return self.weights.get(key, 0.0)


def validate_settings(settings: RiskSettings) -> None:
    """Validate weights, horizon and thresholds.

    Rejects unknown factors, negative weights, non-finite weights and an
    inverted band configuration.  All-zero weights are *allowed* at this level
    (the scoring function degrades to ``insufficient_data``) so an operator can
    temporarily silence every factor without the settings endpoint failing.
    """

    if not 1 <= settings.horizon_days <= 365:
        raise RiskConfigError("horizon_days must be between 1 and 365")
    window = settings.failed_renewal_window_days
    if window is not None and not 1 <= window <= 3650:
        raise RiskConfigError(
            "failed_renewal_window_days must be null (whole snapshot) or between 1 and 3650"
        )
    if not 0 <= settings.low_max < settings.medium_max <= 100:
        raise RiskConfigError("thresholds must satisfy 0 <= low_max < medium_max <= 100")
    unknown = set(settings.weights) - set(FACTOR_BY_KEY)
    if unknown:
        raise RiskConfigError(f"unknown factor keys: {sorted(unknown)}")
    for key, weight in settings.weights.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise RiskConfigError(f"weight for {key} must be a number")
        if weight != weight or weight in (float("inf"), float("-inf")):
            raise RiskConfigError(f"weight for {key} must be finite")
        if weight < 0:
            raise RiskConfigError(f"weight for {key} cannot be negative")


def classify(score: float | None, settings: RiskSettings) -> str:
    """Map a numeric score to a risk band."""

    if score is None:
        return "insufficient_data"
    if score <= settings.low_max:
        return "low"
    if score <= settings.medium_max:
        return "medium"
    return "high"


@dataclass
class FactorResult:
    key: str
    label: str
    value: float | None
    weight: float
    contribution: float
    reason: str
    available: bool
    #: Mirrors :class:`FactorDefinition.deprecated`.  Reported to the client so
    #: a consumer can tell a live rating factor from a diagnostic one.
    deprecated: bool = False


@dataclass
class ServiceRisk:
    service_id: int
    score: float | None
    category: str
    eligible: bool
    current_state: str
    status_note: str
    factors: list[FactorResult]
    reasons: list[str]
    missing_data: list[str]
    days_to_expiry: float | None


def _days_to_expiry(expires_at: datetime, now: datetime) -> float:
    return (expires_at - now).total_seconds() / 86400.0


def _format_eur(cents: int) -> str:
    return f"{cents_to_eur(cents):.2f} EUR"


def compute_service_risk(
    *,
    service,
    account,
    transactions: list,
    settings: RiskSettings,
    now: datetime,
) -> ServiceRisk:
    """Compute the explainable risk for a single service.

    ``transactions`` must already be filtered to the service in question.
    """

    status = service.status
    eligible = status in ELIGIBLE_STATUSES
    days_left = _days_to_expiry(service.expires_at, now)

    if not eligible:
        note = (
            "Услуга удалена: событие оттока уже состоялось, прогноз не строится."
            if status == "deleted"
            else "Аккаунт/услуга заблокированы: это текущее известное состояние, а не прогноз."
        )
        return ServiceRisk(
            service_id=service.id,
            score=None,
            category="not_applicable",
            eligible=False,
            current_state=status,
            status_note=note,
            factors=[],
            reasons=[],
            missing_data=[],
            days_to_expiry=days_left,
        )

    raw: dict[str, float | None] = {}
    reasons: dict[str, str] = {}
    missing: list[str] = []

    horizon = float(settings.horizon_days)

    # --- expiry proximity -------------------------------------------------
    if days_left <= 0:
        raw["expiry_proximity"] = 1.0
        reasons["expiry_proximity"] = (
            f"Услуга истекла {-days_left:.1f} дн. назад и не продлена."
        )
    elif days_left >= horizon:
        raw["expiry_proximity"] = 0.0
        reasons["expiry_proximity"] = (
            f"До окончания {days_left:.1f} дн., это за пределами горизонта {int(horizon)} дн."
        )
    else:
        raw["expiry_proximity"] = max(0.0, min(1.0, 1.0 - days_left / horizon))
        reasons["expiry_proximity"] = (
            f"До окончания {days_left:.1f} дн. — внутри горизонта {int(horizon)} дн."
        )

    # --- auto prolong -----------------------------------------------------
    raw["auto_prolong_disabled"] = 0.0 if service.auto_prolong else 1.0
    reasons["auto_prolong_disabled"] = (
        "Автопродление включено."
        if service.auto_prolong
        else "Автопродление отключено — продление зависит от ручного решения."
    )

    # --- balance vs price -------------------------------------------------
    # Only funds that can actually pay for the renewal count.  The bonus
    # balance is spendable only when the snapshot marks it unlocked; an
    # unknown bonusState is treated as *not* available, so missing data can
    # never inflate the customer's capacity.  withdrawBalance is referral money
    # meant for withdrawal and is deliberately excluded.
    #
    # A missing balance is unknown, not zero: scoring it as "no funds" would
    # invent a risk signal out of absent data.
    balance = getattr(account, "balance", None)
    bonus_available = (
        getattr(account, "bonus_balance", None) or 0
        if getattr(account, "bonus_state", None) == "unlocked"
        else 0
    )

    if balance is None:
        raw["insufficient_balance"] = None
        missing.append("insufficient_balance")
        reasons["insufficient_balance"] = (
            "Баланс аккаунта в снимке отсутствует — достаточность средств не определена."
        )
    elif service.price <= 0:
        raw["insufficient_balance"] = None
        missing.append("insufficient_balance")
        reasons["insufficient_balance"] = "Цена услуги равна нулю, фактор неприменим."
    else:
        spendable = balance + bonus_available
        ratio = spendable / service.price
        feature = max(0.0, min(1.0, 1.0 - ratio))
        raw["insufficient_balance"] = feature
        bonus_note = (
            f" + бонус {_format_eur(bonus_available)} (unlocked)"
            if bonus_available
            else ""
        )
        if feature <= 0:
            reasons["insufficient_balance"] = (
                f"Доступно {_format_eur(spendable)}{bonus_note} против цены "
                f"{_format_eur(service.price)} — продление обеспечено."
            )
        else:
            reasons["insufficient_balance"] = (
                f"Доступно {_format_eur(spendable)}{bonus_note} против цены продления "
                f"{_format_eur(service.price)} — покрытие {ratio * 100:.0f}%."
            )

    # --- status factors ---------------------------------------------------
    raw["prolong_wait_status"] = 1.0 if status == "prolong_wait" else 0.0
    reasons["prolong_wait_status"] = (
        "Услуга ожидает продления (prolong_wait)."
        if status == "prolong_wait"
        else "Услуга не находится в ожидании продления."
    )

    raw["suspended_status"] = 1.0 if status == "suspended" else 0.0
    reasons["suspended_status"] = (
        "Услуга приостановлена (suspended)."
        if status == "suspended"
        else "Услуга не приостановлена."
    )

    # --- transaction history ---------------------------------------------
    # Only events at or before the evaluation instant may be used: a renewal
    # recorded after ``now`` would leak the future into the score.
    window = settings.failed_renewal_window_days
    if window is None:
        window_start = None
    else:
        window_start = now - timedelta(days=window)

    prolongs_all = [
        t
        for t in transactions
        if t.type == "prolong" and (t.created_at is None or t.created_at <= now)
    ]
    in_window = [
        t
        for t in prolongs_all
        if window_start is None or (t.created_at is not None and t.created_at >= window_start)
    ]
    failed_all = [t for t in prolongs_all if t.status == "not_performed"]
    failed = [t for t in in_window if t.status == "not_performed"]

    window_note = (
        "за всё время снимка"
        if window is None
        else f"за последние {window} дн."
    )

    if not in_window:
        # No observable attempts inside the window: the rate is unknown, not 0.
        raw["renewal_failure_rate"] = None
        missing.append("renewal_failure_rate")
        reasons["renewal_failure_rate"] = (
            f"Попыток продления {window_note} нет — доля неуспешных не определена."
        )
    else:
        raw["renewal_failure_rate"] = len(failed) / len(in_window)
        reasons["renewal_failure_rate"] = (
            f"Неуспешных продлений {len(failed)} из {len(in_window)} {window_note} "
            f"({len(failed) / len(in_window) * 100:.0f}%)."
        )

    # Diagnostics only: never enters the weighted sum (its weight is 0).
    # Kept so the analyst can still see how many failures exist historically
    # and how many the window excluded.
    raw["failed_renewals"] = float(len(failed_all)) if prolongs_all else None
    if not prolongs_all:
        reasons["failed_renewals"] = "История продлений отсутствует в снимке."
    else:
        excluded = len(failed_all) - len(failed)
        tail = (
            f" Вне окна {window_note}: {excluded}."
            if excluded and window is not None
            else ""
        )
        reasons["failed_renewals"] = (
            f"Диагностика: неуспешных продлений {len(failed_all)} из "
            f"{len(prolongs_all)} всего.{tail} В рейтинг не входит."
        )

    # --- weighted aggregation --------------------------------------------
    results: list[FactorResult] = []
    total_weight = 0.0
    weighted_sum = 0.0
    for definition in FACTORS:
        value = raw.get(definition.key)
        weight = settings.weight(definition.key)
        available = value is not None and weight > 0
        if available:
            total_weight += weight
            weighted_sum += weight * float(value)
            contribution = weight * float(value)
        else:
            contribution = 0.0
        results.append(
            FactorResult(
                key=definition.key,
                label=definition.label,
                value=value,
                weight=weight,
                contribution=contribution,
                reason=reasons.get(definition.key, ""),
                available=available,
                deprecated=definition.deprecated,
            )
        )

    if total_weight <= 0:
        score = None
        category = "insufficient_data"
    else:
        # risk_score = 100 * sum(w_i * f_i) / sum(w_i)
        score = round(100.0 * weighted_sum / total_weight, 1)
        category = classify(score, settings)

    ordered_reasons = [
        f"{r.label}: {r.reason}"
        for r in sorted(results, key=lambda x: x.contribution, reverse=True)
        if r.available and r.value and r.value > 0
    ]

    return ServiceRisk(
        service_id=service.id,
        score=score,
        category=category,
        eligible=True,
        current_state=status,
        status_note="Услуга открыта, прогноз оттока применим.",
        factors=results,
        reasons=ordered_reasons,
        missing_data=[FACTOR_BY_KEY[k].label for k in missing],
        days_to_expiry=days_left,
    )


@dataclass
class CustomerRisk:
    customer_id: int
    score: float | None
    category: str
    service_count: int
    eligible_service_count: int
    high_risk_service_count: int
    service_risks: list[ServiceRisk]
    reasons: list[str]
    missing_data: list[str]
    concluded_states: dict[str, int]
    state_note: str = ""
    #: Share of *scored* services that sit in the high band (0..1).
    #: Reported alongside ``score`` rather than folded into it: ``score`` stays
    #: the maximum service risk, so a wider portfolio never raises the rating
    #: by itself.  Concentration is a separate decision input.
    high_risk_share: float = 0.0
    #: Services in an open state whose ``expiresAt`` is already in the past.
    overdue_service_count: int = 0


def compute_customer_risk(
    *, customer_id: int, service_risks: list[ServiceRisk], settings: RiskSettings
) -> CustomerRisk:
    """Aggregate service risks into a customer-level risk.

    The maximum score among *eligible* services is used as the customer risk:
    a customer is at risk as soon as one of their services is at risk, and
    averaging would dilute a single severe exposure.

    Three "no score" situations are kept distinct, because collapsing them
    would misrepresent the customer:

    * every service is in a concluded state (``deleted`` / ``blocked``) →
      ``not_applicable``; the event already happened and is not a forecast;
    * at least one service is open but no factor could be evaluated →
      ``insufficient_data``;
    * the customer has no services at all → ``insufficient_data``.
    """

    eligible = [r for r in service_risks if r.eligible]
    scored = [r for r in eligible if r.score is not None]

    concluded: dict[str, int] = {}
    for risk in service_risks:
        if not risk.eligible:
            concluded[risk.current_state] = concluded.get(risk.current_state, 0) + 1

    if scored:
        top = max(scored, key=lambda r: r.score or 0.0)
        score = top.score
        category = top.category
        # Reasons are drawn from every service at or near the top score so the
        # analyst sees the full picture, not just one service's wording.
        threshold = (score or 0.0) - 10.0
        reasons: list[str] = []
        for risk in sorted(scored, key=lambda r: r.score or 0.0, reverse=True):
            if (risk.score or 0.0) < threshold:
                continue
            for reason in risk.reasons:
                if reason not in reasons:
                    reasons.append(reason)
        missing = sorted({m for r in eligible for m in r.missing_data})
        state_note = ""
    else:
        score = None
        reasons = []
        missing = sorted({m for r in eligible for m in r.missing_data})
        if eligible:
            category = "insufficient_data"
            state_note = (
                "Прогноз невозможен: ни один фактор риска не удалось рассчитать "
                "по имеющимся данным."
            )
        elif service_risks:
            category = "not_applicable"
            state_note = (
                "Прогноз не строится: все услуги клиента находятся в завершённом "
                "состоянии (удалены или заблокированы). Это текущее известное состояние, "
                "а не прогноз оттока."
            )
        else:
            category = "insufficient_data"
            state_note = "У клиента нет услуг в снимке."

    high_risk_count = sum(1 for r in scored if r.category == "high")
    # Denominator is the *scored* services: services with no computable score
    # carry no information, so including them would understate concentration.
    # An empty denominator yields 0.0 rather than a division error.
    high_risk_share = (high_risk_count / len(scored)) if scored else 0.0
    overdue_count = sum(
        1 for r in eligible if r.days_to_expiry is not None and r.days_to_expiry < 0
    )

    return CustomerRisk(
        customer_id=customer_id,
        score=score,
        category=category,
        service_count=len(service_risks),
        eligible_service_count=len(eligible),
        high_risk_service_count=high_risk_count,
        service_risks=service_risks,
        reasons=reasons[:8],
        missing_data=missing,
        concluded_states=concluded,
        state_note=state_note,
        high_risk_share=high_risk_share,
        overdue_service_count=overdue_count,
    )
