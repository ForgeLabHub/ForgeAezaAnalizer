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
from datetime import datetime, timedelta

from .money import cents_to_eur


ELIGIBLE_STATUSES: frozenset[str] = frozenset({"active", "suspended", "prolong_wait"})


CONCLUDED_STATUSES: frozenset[str] = frozenset({"deleted", "blocked"})


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
    missing_data_behaviour: str = "фактор исключён, веса перенормированы"


    deprecated: bool = False


FACTORS: tuple[FactorDefinition, ...] = (
    FactorDefinition(
        key="expiry_proximity",
        label="Близость даты окончания",
        description="До окончания оплаченного периода осталось мало времени или срок уже вышел.",
        how_computed="days_left = (expiresAt - now) в сутках; линейный спад до нуля на границе горизонта",
        normalization="0 при days_left >= horizon; 1 при days_left <= 0; иначе 1 - days_left/horizon",
        default_weight=3.0,
    ),
    FactorDefinition(
        key="auto_prolong_disabled",
        label="Автопродление отключено",
        description="Клиенту нужно продлевать услугу вручную.",
        how_computed="autoProlong == false",
        normalization="1 если автопродление отключено, иначе 0",
        default_weight=2.0,
    ),
    FactorDefinition(
        key="insufficient_balance",
        label="Недостаточно средств для продления",
        description="На балансе не хватает средств для оплаты следующего продления.",
        how_computed="ratio = balance / price; при price = 0 фактор неприменим",
        normalization="clip(1 - ratio, 0, 1): 1 при нулевом балансе, 0 при balance >= price",
        default_weight=2.0,
    ),
    FactorDefinition(
        key="prolong_wait_status",
        label="Ожидание продления",
        description="Срок оплаты подошёл, услуга ожидает списания средств.",
        how_computed="status == 'prolong_wait'",
        normalization="1 если статус prolong_wait, иначе 0",
        default_weight=2.5,
    ),
    FactorDefinition(
        key="failed_renewals",
        label="Неуспешные продления",
        description="Количество неудачных попыток оплаты за всё время (справочно, не влияет на балл).",
        how_computed="количество not_performed продлений в пределах окна",
        normalization="не участвует в рейтинге (вес 0)",
        default_weight=0.0,
        deprecated=True,
        missing_data_behaviour="фактор исключён, веса перенормированы",
    ),
    FactorDefinition(
        key="suspended_status",
        label="Услуга приостановлена",
        description="Работа услуги временно приостановлена.",
        how_computed="status == 'suspended'",
        normalization="1 если статус suspended, иначе 0",
        default_weight=1.0,
    ),
    FactorDefinition(
        key="renewal_failure_rate",
        label="Доля неуспешных продлений",
        description="Как часто попытки продлить услугу завершались ошибкой оплаты.",
        how_computed="not_performed / все продления услуги в пределах окна",
        normalization="0..1; 0 если по услуге нет продлений",
        default_weight=2.5,
    ),
)

FACTOR_BY_KEY: dict[str, FactorDefinition] = {f.key: f for f in FACTORS}

DEFAULT_WEIGHTS: dict[str, float] = {f.key: f.default_weight for f in FACTORS}


DEPRECATED_KEYS: frozenset[str] = frozenset(f.key for f in FACTORS if f.deprecated)


def canonical_weights(weights: dict[str, float]) -> dict[str, float]:
    """Force deprecated factors to weight 0.

    A stored settings row can predate the deprecation (the bundled seed still
    carries ``failed_renewals: 2.0``).  Serving that value would advertise a
    weight the scoring core ignores and make the reported weight sum disagree
    with the score, so the value is normalised at the boundary instead.
    """

    return {key: (0.0 if key in DEPRECATED_KEYS else float(value)) for key, value in weights.items()}


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


        if FACTOR_BY_KEY[key].deprecated and weight != 0:
            raise RiskConfigError(
                f"weight for {key} must be 0: the factor is deprecated and its "
                f"signal is already counted by another factor"
            )


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


    raw["auto_prolong_disabled"] = 0.0 if service.auto_prolong else 1.0
    reasons["auto_prolong_disabled"] = (
        "Автопродление включено."
        if service.auto_prolong
        else "Автопродление отключено — продление зависит от ручного решения."
    )


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


    results: list[FactorResult] = []
    total_weight = 0.0
    weighted_sum = 0.0
    for definition in FACTORS:
        value = raw.get(definition.key)


        weight = 0.0 if definition.deprecated else settings.weight(definition.key)
        available = value is not None and weight > 0
        if available:
            feature = max(0.0, min(1.0, float(value)))
            total_weight += weight
            weighted_sum += weight * feature
            contribution = weight * feature
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


    high_risk_share: float = 0.0

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
