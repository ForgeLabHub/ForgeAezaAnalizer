"""Explainable, rule-based churn risk scoring.

Model
-----
``risk_score = 100 * sum(weight_i * feature_i) / sum(weight_i)``

This is an **explicit, weighted feature model**, not a trained ML model. The
organiser dataset has 10 accounts / 30 services — far too little labelled churn
data to fit or validate a statistical model, so none is claimed.

Feature handling rules
----------------------
* Every feature is normalised to ``[0, 1]`` where higher means more churn risk.
* A feature whose input data is missing is **unknown** (``None``), not ``0``.
  Unknown features are removed from both the numerator and the denominator, and
  the surviving weight coverage is reported as ``confidence``. An unknown signal
  therefore never silently reduces risk.
* Features describing events that have *already* ended (``deleted`` services)
  are excluded from future-churn scoring entirely — they are history, not
  forecast. They are surfaced separately as ``already_churned``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

RISK_LEVEL_BANDS = ((0, 34, "low"), (35, 64, "medium"), (65, 100, "high"))

DEFAULT_WEIGHTS: dict[str, float] = {
    "expiry_proximity": 1.0,
    "autoprolong_off": 0.8,
    "insufficient_balance": 1.0,
    "failed_renewals": 0.6,
    "status_risk": 0.9,
}

FACTOR_TITLES = {
    "expiry_proximity": "Service is close to expiry",
    "autoprolong_off": "Auto-prolongation is disabled",
    "insufficient_balance": "Withdrawable balance below service price",
    "failed_renewals": "Previous prolongations failed",
    "status_risk": "Service status indicates elevated risk",
}

# Statuses that represent an ongoing or future obligation.
LIVE_STATUSES = ("active", "blocked", "suspended", "prolong_wait")
# Status already resolved into churn; excluded from forward-looking risk.
TERMINAL_STATUSES = ("deleted",)

# Status -> base risk contribution (0..1). ``active`` is healthy.
STATUS_RISK = {
    "active": 0.0,
    "prolong_wait": 0.6,
    "suspended": 0.9,
    "blocked": 1.0,
}

DEFAULT_HORIZON_DAYS = 30
FAILED_RENEWAL_SATURATION = 2  # 2+ failed prolongations = full signal


@dataclass
class Factor:
    key: str
    title: str
    value: float | None  # None = unknown
    weight: float
    detail: str

    @property
    def unknown(self) -> bool:
        return self.value is None

    @property
    def contribution(self) -> float | None:
        return None if self.value is None else self.weight * self.value

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "value": None if self.value is None else round(self.value, 4),
            "weight": self.weight,
            "weighted": None if self.contribution is None else round(self.contribution, 4),
            "unknown": self.value is None,
            "detail": self.detail,
        }


@dataclass
class ServiceRisk:
    service_id: int
    service_name: str
    status: str
    price_cents: int
    expires_at: datetime
    factors: list[Factor]
    score: float
    level: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    is_live: bool = True

    def as_dict(self) -> dict:
        return {
            "service_id": self.service_id,
            "service_name": self.service_name,
            "status": self.status,
            "price_cents": self.price_cents,
            "expires_at": self.expires_at.isoformat(),
            "score": round(self.score, 2),
            "level": self.level,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "factors": [f.as_dict() for f in self.factors],
        }


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate user-supplied weights; reject unknown keys and bad numbers."""
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object")
    unknown = set(weights) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise ValueError(f"unknown weight keys: {sorted(unknown)}")
    cleaned: dict[str, float] = dict(DEFAULT_WEIGHTS)
    for key, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"weight '{key}' must be a number")
        if value < 0:
            raise ValueError(f"weight '{key}' must be >= 0")
        cleaned[key] = float(value)
    if sum(cleaned.values()) <= 0:
        raise ValueError("at least one weight must be > 0")
    return cleaned


def level_for(score: float) -> str:
    """Band a 0..100 score into a risk level.

    Boundaries follow the case definition: low 0-34, medium 35-64, high 65-100.
    Fractional scores in the gaps (e.g. 34.9) fall into the lower band, so a
    score is only promoted once it reaches the next band's lower bound.
    """
    score = max(0.0, min(100.0, score))
    level = RISK_LEVEL_BANDS[0][2]
    for low, _high, name in RISK_LEVEL_BANDS:
        if score >= low:
            level = name
    return level


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _expiry_feature(expires_at: datetime, reference: datetime, horizon: timedelta) -> Factor:
    remaining = (expires_at - reference).total_seconds()
    if remaining <= 0:
        value, detail = 1.0, "service already expired at snapshot time"
    else:
        value = _clamp(1.0 - remaining / horizon.total_seconds())
        days = remaining / 86400
        detail = f"expires in {days:.1f} day(s)"
    return Factor("expiry_proximity", FACTOR_TITLES["expiry_proximity"], value,
                  DEFAULT_WEIGHTS["expiry_proximity"], detail)


def _autoprolong_feature(auto_prolong: bool) -> Factor:
    value = 0.0 if auto_prolong else 1.0
    detail = "auto-prolongation enabled" if auto_prolong else "auto-prolongation disabled"
    return Factor("autoprolong_off", FACTOR_TITLES["autoprolong_off"], value,
                  DEFAULT_WEIGHTS["autoprolong_off"], detail)


def _balance_feature(price_cents: int, withdraw_balance: int | None) -> Factor:
    title = FACTOR_TITLES["insufficient_balance"]
    weight = DEFAULT_WEIGHTS["insufficient_balance"]
    if withdraw_balance is None:
        return Factor("insufficient_balance", title, None, weight,
                      "withdrawable balance unknown")
    if price_cents <= 0:
        return Factor("insufficient_balance", title, 0.0, weight,
                      "service is free; no balance needed")
    if withdraw_balance >= price_cents:
        return Factor("insufficient_balance", title, 0.0, weight,
                      f"withdrawable {withdraw_balance} covers price {price_cents}")
    value = _clamp(1.0 - withdraw_balance / price_cents)
    return Factor("insufficient_balance", title, value, weight,
                  f"withdrawable {withdraw_balance} of {price_cents} required")


def _failed_renewals_feature(failed_count: int) -> Factor:
    value = _clamp(failed_count / FAILED_RENEWAL_SATURATION)
    return Factor("failed_renewals", FACTOR_TITLES["failed_renewals"], value,
                  DEFAULT_WEIGHTS["failed_renewals"],
                  f"{failed_count} failed prolongation(s)")


def _status_feature(status: str) -> Factor:
    value = STATUS_RISK.get(status, 0.0)
    return Factor("status_risk", FACTOR_TITLES["status_risk"], value,
                  DEFAULT_WEIGHTS["status_risk"], f"status = {status}")


def score_service(
    *,
    service_id: int,
    service_name: str,
    status: str,
    price_cents: int,
    expires_at: datetime,
    auto_prolong: bool,
    withdraw_balance: int | None,
    failed_renewals: int,
    reference: datetime,
    horizon_days: int,
    weights: dict[str, float],
) -> ServiceRisk:
    """Compute a single service's risk with per-factor explanations."""
    horizon = timedelta(days=horizon_days)
    raw = [
        _expiry_feature(expires_at, reference, horizon),
        _autoprolong_feature(auto_prolong),
        _balance_feature(price_cents, withdraw_balance),
        _failed_renewals_feature(failed_renewals),
        _status_feature(status),
    ]
    factors = [Factor(f.key, f.title, f.value, weights[f.key], f.detail) for f in raw]

    total_weight = sum(f.weight for f in factors)
    known_weight = sum(f.weight for f in factors if f.value is not None)
    weighted = sum(f.contribution for f in factors if f.contribution is not None)

    if known_weight <= 0 or total_weight <= 0:
        # Nothing scoreable: report as unknown rather than a confident zero.
        return ServiceRisk(
            service_id=service_id, service_name=service_name, status=status,
            price_cents=price_cents, expires_at=expires_at, factors=factors,
            score=0.0, level="unknown", confidence=0.0,
            reasons=["insufficient data to score this service"], is_live=False,
        )

    score = _clamp(100.0 * weighted / known_weight, 0.0, 100.0)
    confidence = known_weight / total_weight
    reasons = [
        f"{f.title} ({f.detail})"
        for f in factors
        if f.value is not None and f.value >= 0.5
    ]
    if not reasons:
        reasons = ["no elevated risk signals detected"]
    if confidence < 1.0:
        unknown = [f.key for f in factors if f.value is None]
        reasons.append(f"confidence {confidence:.0%}; unknown signals: {', '.join(unknown)}")

    return ServiceRisk(
        service_id=service_id, service_name=service_name, status=status,
        price_cents=price_cents, expires_at=expires_at, factors=factors,
        score=score, level=level_for(score), confidence=confidence,
        reasons=reasons, is_live=status in LIVE_STATUSES,
    )


def eligible_for_renewal(expires_at: datetime, reference: datetime, horizon_days: int) -> bool:
    """True when a service renewal falls inside the forward horizon.

    A renewal already past (``expires_at < reference``) is *not* a future
    renewal and is excluded, matching the "no double counting, no historical
    renewals" rule.
    """
    horizon = timedelta(days=horizon_days)
    return reference <= expires_at <= reference + horizon
