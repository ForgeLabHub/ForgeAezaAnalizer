"""Adapter that connects the explainable analytics core to the platform runtime.

The platform (``backend/app/modules.py``) deliberately knows nothing about risk
formulas: it owns storage, versions, auth and HTTP, and calls an
``AnalyticsModule`` for the numbers.  This module is that plug-in.

Everything mathematical lives in :mod:`app.domain.risk`, :mod:`app.domain.revenue`
and :mod:`app.domain.money`.  This file only translates between the platform's
``State`` (plain dicts) and those functions, and shapes the result into the
``Summary`` / ``CustomerDetail`` contracts the API validates.

Wire it up with::

    AEZA_ANALYTICS_FACTORY=backend.app.domain.module:create

Design notes
------------
* The source arrives as a dict of ``accounts`` / ``services`` / ``transactions``
  in the dataset's camelCase form.  It is parsed with the domain ``Snapshot``
  model, which is the same validation the core already relies on.
* Money never leaves this module as a float.  Amounts cross the boundary as
  ``{cents, eur}`` with ``eur`` an exact two-decimal string.
* The score is an **explicit heuristic index**, not a churn probability.  There
  are no historical churn labels in the dataset, so no calibration, accuracy or
  predictive metric is claimed anywhere in this module or its output.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from core import Analysis, InvalidInput, State

from .money import cents_to_eur
from .revenue import build_recommendations, compute_customer_exposure, compute_service_exposure
from .risk import (
    DEFAULT_WEIGHTS,
    FACTORS,
    FAILED_RENEWAL_WINDOW_DAYS,
    RiskConfigError,
    RiskSettings,
    compute_customer_risk,
    compute_service_risk,
)
from .schema import Snapshot

#: Bumped whenever the scoring algorithm changes, so the platform recalculates
#: stored results instead of serving numbers produced by older code.
MODEL_VERSION = "aeza-heuristic-1.3.0"

STATUS_LABELS = {
    "active": "Активна",
    "suspended": "Приостановлена",
    "prolong_wait": "Ожидает продления",
    "blocked": "Заблокирована",
    "deleted": "Удалена",
}

CATEGORY_LABELS = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "insufficient_data": "Недостаточно данных",
    "not_applicable": "Не применимо",
}

TERM_LABELS = {
    "hour": "Час",
    "week": "Неделя",
    "month": "Месяц",
    "quarter_year": "Квартал",
    "half_year": "Полугодие",
    "year": "Год",
}


def money(cents: int | None) -> dict:
    """Render eurocents as the platform's ``{cents, eur}`` pair.

    ``None`` stays unknown: the platform rejects a pair where ``cents`` is null
    but ``eur`` is not, and a missing amount must never be presented as zero.
    """

    if cents is None:
        return {"cents": None, "eur": None}
    value = cents_to_eur(cents)
    sign = "-" if cents < 0 else ""
    absolute = abs(int(cents))
    return {"cents": int(cents), "eur": f"{sign}{absolute // 100}.{absolute % 100:02d}"}


def _settings_from_payload(payload: dict) -> RiskSettings:
    """Map the platform's settings dict onto the domain ``RiskSettings``."""

    weights = payload.get("weights") or {}
    merged = dict(DEFAULT_WEIGHTS)
    for key, value in weights.items():
        if key in merged:
            merged[key] = float(value)
    try:
        return RiskSettings(
            horizon_days=int(payload.get("horizonDays", 30)),
            weights=merged,
            low_max=int(payload.get("lowMax", 34)),
            medium_max=int(payload.get("mediumMax", 64)),
            failed_renewal_window_days=payload.get("failedRenewalWindowDays", 90),
        )
    except (RiskConfigError, TypeError, ValueError) as exc:
        raise InvalidInput(str(exc)) from exc


def _factor_info() -> list[dict]:
    return [
        {
            "key": factor.key,
            "label": factor.label,
            "description": factor.description,
            "howComputed": factor.how_computed,
            "normalization": factor.normalization,
            "defaultWeight": float(factor.default_weight),
            "missingDataBehaviour": factor.missing_data_behaviour,
            # Additive: the platform schema allows extra fields, and this lets a
            # client tell a live rating factor from a diagnostic one.
            "deprecated": factor.deprecated,
        }
        for factor in FACTORS
    ]


def _factor_payload(factor) -> dict:
    return {
        "key": factor.key,
        "label": factor.label,
        "value": factor.value,
        "weight": float(factor.weight),
        "contribution": float(factor.contribution),
        "available": factor.available,
        "reason": factor.reason,
        "deprecated": factor.deprecated,
    }


def _recommendation_payload(rec) -> dict:
    return {"code": rec.code, "title": rec.title, "detail": rec.detail, "priority": rec.priority}


class AézaAnalyticsModule:
    """The platform's ``AnalyticsModule``, backed by the domain core."""

    def definition(self):
        from backend.app.modules import ModelDefinition

        return ModelDefinition(
            defaults={
                "horizonDays": 30,
                "weights": {k: float(v) for k, v in DEFAULT_WEIGHTS.items()},
                "lowMax": 34,
                "mediumMax": 64,
                # Without this the platform's SettingsPayload would fill the
                # field with its own default and the approved 90-day window
                # would silently become "whole snapshot" on a fresh database.
                "failedRenewalWindowDays": FAILED_RENEWAL_WINDOW_DAYS,
            },
            factors=tuple(_factor_info()),
            version=MODEL_VERSION,
        )

    def validate_settings(self, settings: dict) -> dict:
        """Reject anything the scoring core cannot evaluate.

        The platform has already shape-checked the payload, so this layer only
        enforces model rules: known factor keys, non-negative finite weights,
        ordered thresholds and a usable horizon/window.
        """

        risk_settings = _settings_from_payload(settings)
        # Re-read through the same constructor the scoring uses, so a bad
        # combination fails here (HTTP 422) rather than mid-calculation.
        validated = RiskSettings(
            horizon_days=risk_settings.horizon_days,
            weights=risk_settings.weights,
            low_max=risk_settings.low_max,
            medium_max=risk_settings.medium_max,
            failed_renewal_window_days=risk_settings.failed_renewal_window_days,
        )
        result = {
            "horizonDays": validated.horizon_days,
            "weights": {k: float(v) for k, v in validated.weights.items()},
            "lowMax": validated.low_max,
            "mediumMax": validated.medium_max,
        }
        if "failedRenewalWindowDays" in settings:
            result["failedRenewalWindowDays"] = validated.failed_renewal_window_days
        return result

    def calculate(self, state: State) -> Analysis:
        try:
            snapshot = Snapshot.model_validate(state.source)
        except Exception as exc:  # noqa: BLE001 - surfaced as InvalidInput to the platform
            raise InvalidInput(f"снимок не прошёл разбор: {exc}") from exc

        settings = _settings_from_payload(state.settings)
        now = state.as_of or state.calculated_at or dt.datetime.now(dt.timezone.utc)

        accounts = {account.id: account for account in snapshot.accounts}
        services_by_owner: dict[int, list] = {}
        for service in snapshot.services:
            services_by_owner.setdefault(service.owner_id, []).append(service)
        transactions_by_service: dict[int, list] = {}
        for transaction in snapshot.transactions:
            transactions_by_service.setdefault(transaction.service_id, []).append(transaction)

        customers: list[dict] = []
        revenue_at_risk_total = 0
        upcoming_total = 0
        historical_total = 0
        by_category = {name: 0 for name in CATEGORY_LABELS}
        status_counts: dict[str, int] = {}
        concluded_counts: dict[str, int] = {}
        reason_counter: dict[str, int] = {}
        upcoming_rows: list[dict] = []
        services_at_risk = 0
        open_services = 0
        concluded_services = 0
        customers_with_exposure = 0

        for account in snapshot.accounts:
            services = services_by_owner.get(account.id, [])
            service_analyses = []
            exposures = []
            risks_by_service = {}
            for service in services:
                risk = compute_service_risk(
                    service=service,
                    account=account,
                    transactions=transactions_by_service.get(service.id, []),
                    settings=settings,
                    now=now,
                )
                exposure = compute_service_exposure(
                    service=service, risk=risk, horizon_days=settings.horizon_days, now=now
                )
                if exposure is not None:
                    exposures.append(exposure)
                risks_by_service[service.id] = risk
                service_analyses.append((service, risk, exposure))

            customer_risk = compute_customer_risk(
                customer_id=account.id,
                service_risks=[risk for _, risk, _ in service_analyses],
                settings=settings,
            )
            customer_exposure = compute_customer_exposure(
                customer_id=account.id,
                renewals=exposures,
                services=services,
                risks_by_service=risks_by_service,
                now=now,
            )

            by_category[customer_risk.category] = by_category.get(customer_risk.category, 0) + 1
            revenue_at_risk_total += customer_exposure.revenue_at_risk_cents
            upcoming_total += customer_exposure.upcoming_renewals_cents
            historical_total += account.total_replenished or 0
            if customer_exposure.revenue_at_risk_cents > 0:
                customers_with_exposure += 1

            recommendations = []
            seen: set[str] = set()
            for service, risk, _ in sorted(
                service_analyses, key=lambda item: (item[1].score is None, -(item[1].score or 0.0))
            ):
                for rec in build_recommendations(risk, account, service):
                    if rec.code in seen:
                        continue
                    seen.add(rec.code)
                    recommendations.append(_recommendation_payload(rec))

            service_items = []
            for service, risk, exposure in service_analyses:
                status_counts[service.status] = status_counts.get(service.status, 0) + 1
                if risk.eligible:
                    open_services += 1
                else:
                    concluded_services += 1
                    concluded_counts[service.status] = concluded_counts.get(service.status, 0) + 1
                if risk.category == "high":
                    services_at_risk += 1
                for factor in risk.factors:
                    if factor.available and factor.value and factor.value > 0:
                        reason_counter[factor.label] = reason_counter.get(factor.label, 0) + 1
                if exposure is not None:
                    upcoming_rows.append(
                        {
                            "customerId": account.id,
                            "serviceId": service.id,
                            "serviceName": service.name,
                            "renewalAt": service.expires_at.isoformat(),
                            "amountCents": exposure.amount_cents,
                            "amountEur": str(cents_to_eur(exposure.amount_cents)),
                            "riskScore": risk.score,
                            "riskCategory": risk.category,
                            "revenueAtRiskEur": str(cents_to_eur(exposure.revenue_at_risk_cents)),
                        }
                    )
                service_items.append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "status": service.status,
                        "statusLabel": STATUS_LABELS.get(service.status, service.status),
                        "paymentTerm": service.payment_term,
                        "paymentTermLabel": TERM_LABELS.get(service.payment_term, service.payment_term or "—"),
                        "autoProlong": service.auto_prolong,
                        "createdAt": service.created_at.isoformat() if service.created_at else None,
                        "expiresAt": service.expires_at.isoformat() if service.expires_at else None,
                        "daysToExpiry": risk.days_to_expiry,
                        "price": money(service.price),
                        "riskScore": risk.score,
                        "riskCategory": risk.category,
                        "riskCategoryLabel": CATEGORY_LABELS.get(risk.category, risk.category),
                        "eligibleForForecast": risk.eligible,
                        "stateNote": risk.status_note,
                        "reasons": risk.reasons,
                        "missingData": risk.missing_data,
                        "factors": [_factor_payload(f) for f in risk.factors],
                        "revenueAtRisk": money(exposure.revenue_at_risk_cents) if exposure else None,
                        "upcomingRenewalAt": service.expires_at.isoformat() if exposure else None,
                        "recommendations": [_recommendation_payload(r) for r in build_recommendations(risk, account, service)],
                    }
                )

            customers.append(
                {
                    "id": account.id,
                    "email": account.email,
                    "balance": money(account.balance),
                    "withdrawBalance": money(account.withdraw_balance),
                    "totalReplenished": money(account.total_replenished),
                    "bonusBalance": money(account.bonus_balance),
                    "bonusState": account.bonus_state,
                    "riskScore": customer_risk.score,
                    "riskCategory": customer_risk.category,
                    "riskCategoryLabel": CATEGORY_LABELS.get(customer_risk.category, customer_risk.category),
                    "serviceCount": customer_risk.service_count,
                    "eligibleServiceCount": customer_risk.eligible_service_count,
                    "highRiskServiceCount": customer_risk.high_risk_service_count,
                    "concludedStates": customer_risk.concluded_states,
                    "stateNote": customer_risk.state_note,
                    "revenueAtRisk": money(customer_exposure.revenue_at_risk_cents),
                    "upcomingRenewals": money(customer_exposure.upcoming_renewals_cents),
                    "topReasons": customer_risk.reasons[:3],
                    "missingData": customer_risk.missing_data,
                    "reasons": customer_risk.reasons,
                    "services": service_items,
                    "recommendations": recommendations,
                    "renewalDetails": [
                        {
                            "serviceId": renewal.service_id,
                            "renewalAt": renewal.renewal_at.isoformat(),
                            "amount": money(renewal.amount_cents),
                            "riskScore": renewal.risk_score,
                            "revenueAtRisk": money(renewal.revenue_at_risk_cents),
                        }
                        for renewal in customer_exposure.renewals
                    ],
                    # Additive fields the platform preserves: concentration and
                    # the operational backlog, kept apart from the score itself.
                    "highRiskShare": round(customer_risk.high_risk_share, 4),
                    "overdueServiceCount": customer_risk.overdue_service_count,
                    "overdueOperational": money(customer_exposure.overdue_operational_cents),
                    "lifecycleInconsistentCount": customer_exposure.lifecycle_inconsistent_count,
                    "exposureByHorizon": [
                        {
                            "horizonDays": horizon.horizon_days,
                            "renewalCount": horizon.renewal_count,
                            "upcomingRenewals": money(horizon.upcoming_renewals_cents),
                            "revenueAtRisk": money(horizon.revenue_at_risk_cents),
                        }
                        for _, horizon in sorted(customer_exposure.horizons.items())
                    ],
                }
            )

        upcoming_rows.sort(key=lambda row: row["renewalAt"])

        summary = {
            "generatedAt": now.isoformat(),
            "horizonDays": settings.horizon_days,
            "customers": {
                "total": len(snapshot.accounts),
                "byCategory": by_category,
                "highRisk": by_category.get("high", 0),
                "mediumRisk": by_category.get("medium", 0),
                "insufficientData": by_category.get("insufficient_data", 0),
                "withRevenueAtRisk": customers_with_exposure,
            },
            "services": {
                "total": len(snapshot.services),
                "open": open_services,
                "concluded": concluded_services,
                "byStatus": status_counts,
                "highRisk": services_at_risk,
            },
            "revenue": {
                "revenueAtRiskCents": revenue_at_risk_total,
                "revenueAtRiskEur": str(cents_to_eur(revenue_at_risk_total)),
                "upcomingRenewalsCents": upcoming_total,
                "upcomingRenewalsEur": str(cents_to_eur(upcoming_total)),
                "historicalReplenishedCents": historical_total,
                "historicalReplenishedEur": str(cents_to_eur(historical_total)),
            },
            "topRiskReasons": [
                {"label": label, "count": count}
                for label, count in sorted(reason_counter.items(), key=lambda kv: -kv[1])[:8]
            ],
            "upcomingRenewals": upcoming_rows[:10],
            "historyAvailable": False,
            "historyNote": (
                "В снимке нет истории оттока: события отмен и потери клиентов не передаются, "
                "поэтому динамика и точность модели не рассчитываются."
            ),
            "model": {
                "type": "rule_based_weighted",
                "calibrated": False,
                "note": (
                    "Прозрачная взвешенная rule-based модель. Балл риска не является "
                    "откалиброванной вероятностью, так как в данных нет исторических исходов."
                ),
            },
        }
        return Analysis(summary, customers)


def create() -> AézaAnalyticsModule:
    """Factory referenced by ``AEZA_ANALYTICS_FACTORY``."""

    return AézaAnalyticsModule()
