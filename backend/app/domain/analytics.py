"""Analytics orchestration: turns a source snapshot into risk and revenue answers.

This module is the single place where risk, exposure and recommendations are
combined, so the HTTP layer stays thin and every endpoint reports consistent
numbers.  It performs no I/O of its own: it consumes a
:class:`~app.domain.source_view.SourceView` built from an already validated
snapshot, which keeps it testable and free of database coupling.

The risk, exposure and recommendation formulas themselves live in
:mod:`app.domain.risk` and :mod:`app.domain.revenue` and are never re-implemented
here — this module only aggregates them.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from app.domain.money import cents_to_eur
from app.domain.revenue import (
    CustomerExposure,
    RenewalExposure,
    build_recommendations,
    compute_customer_exposure,
    compute_service_exposure,
)
from app.domain.risk import (
    ELIGIBLE_STATUSES,
    CustomerRisk,
    RiskSettings,
    ServiceRisk,
    compute_customer_risk,
    compute_service_risk,
)
from app.domain.source_view import AccountView, ServiceView, SourceView

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

CATEGORY_ORDER = ("low", "medium", "high", "insufficient_data", "not_applicable")


@dataclass
class ServiceAnalysis:
    service: ServiceView
    risk: ServiceRisk
    exposure: RenewalExposure | None
    recommendations: list = field(default_factory=list)


@dataclass
class CustomerAnalysis:
    account: AccountView
    risk: CustomerRisk
    exposure: CustomerExposure
    services: list[ServiceAnalysis] = field(default_factory=list)
    recommendations: list = field(default_factory=list)


def _known_sum(values) -> int:
    """Sum only the values that are known.

    Unknown amounts are skipped rather than treated as zero; callers label the
    resulting figure as a partial aggregate.
    """

    return sum(value for value in values if value is not None)


class AnalyticsService:
    """Computes the full analytical model for a given settings object."""

    def __init__(self, view: SourceView, settings: RiskSettings, now: dt.datetime):
        self.view = view
        self.settings = settings
        self.now = now

    def analyze_customer(self, account: AccountView) -> CustomerAnalysis:
        service_analyses: list[ServiceAnalysis] = []
        exposures: list[RenewalExposure] = []
        for service in self.view.services_of(account.id):
            risk = compute_service_risk(
                service=service,
                account=account,
                transactions=self.view.transactions_of(service.id),
                settings=self.settings,
                now=self.now,
            )
            exposure = compute_service_exposure(
                service=service,
                risk=risk,
                horizon_days=self.settings.horizon_days,
                now=self.now,
            )
            if exposure is not None:
                exposures.append(exposure)
            service_analyses.append(
                ServiceAnalysis(
                    service=service,
                    risk=risk,
                    exposure=exposure,
                    recommendations=build_recommendations(risk, account, service),
                )
            )

        customer_risk = compute_customer_risk(
            customer_id=account.id,
            service_risks=[sa.risk for sa in service_analyses],
            settings=self.settings,
        )
        exposure = compute_customer_exposure(customer_id=account.id, renewals=exposures)

        recommendations = []
        seen: set[str] = set()
        for sa in sorted(
            service_analyses, key=lambda x: (x.risk.score is None, -(x.risk.score or 0.0))
        ):
            for rec in sa.recommendations:
                if rec.code in seen:
                    continue
                seen.add(rec.code)
                recommendations.append(rec)

        return CustomerAnalysis(
            account=account,
            risk=customer_risk,
            exposure=exposure,
            services=service_analyses,
            recommendations=recommendations,
        )

    def analyze_all(self) -> list[CustomerAnalysis]:
        return [self.analyze_customer(a) for a in self.view.accounts]

    def summary(self, analyses: list[CustomerAnalysis] | None = None) -> dict:
        analyses = self.analyze_all() if analyses is None else analyses
        by_category = {name: 0 for name in CATEGORY_ORDER}
        for analysis in analyses:
            by_category[analysis.risk.category] = by_category.get(analysis.risk.category, 0) + 1

        open_services = 0
        status_counts: dict[str, int] = {}
        concluded_counts: dict[str, int] = {}
        revenue_at_risk = 0
        upcoming = 0
        customers_with_exposure = 0
        services_at_risk = 0
        reason_counter: dict[str, int] = {}
        upcoming_renewals: list[dict] = []

        for analysis in analyses:
            if analysis.exposure.revenue_at_risk_cents > 0:
                customers_with_exposure += 1
            for sa in analysis.services:
                status_counts[sa.service.status] = status_counts.get(sa.service.status, 0) + 1
                if sa.service.status in ELIGIBLE_STATUSES:
                    open_services += 1
                else:
                    concluded_counts[sa.service.status] = (
                        concluded_counts.get(sa.service.status, 0) + 1
                    )
                if sa.risk.category == "high":
                    services_at_risk += 1
                for factor in sa.risk.factors:
                    if factor.available and factor.value and factor.value > 0:
                        reason_counter[factor.label] = reason_counter.get(factor.label, 0) + 1
                if sa.exposure is not None:
                    revenue_at_risk += sa.exposure.revenue_at_risk_cents
                    upcoming += sa.exposure.amount_cents
                    upcoming_renewals.append(
                        {
                            "customerId": analysis.account.id,
                            "serviceId": sa.service.id,
                            "serviceName": sa.service.name,
                            "renewalAt": sa.exposure.renewal_at.isoformat(),
                            "amountCents": sa.exposure.amount_cents,
                            "amountEur": str(cents_to_eur(sa.exposure.amount_cents)),
                            "riskScore": sa.risk.score,
                            "riskCategory": sa.risk.category,
                            "revenueAtRiskEur": str(cents_to_eur(sa.exposure.revenue_at_risk_cents)),
                        }
                    )

        upcoming_renewals.sort(key=lambda r: (r["renewalAt"], r["customerId"], r["serviceId"]))

        total_replenished = _known_sum(a.account.total_replenished for a in analyses)

        return {
            "generatedAt": self.now.isoformat(),
            "horizonDays": self.settings.horizon_days,
            "customers": {
                "total": len(analyses),
                "byCategory": by_category,
                "highRisk": by_category.get("high", 0),
                "mediumRisk": by_category.get("medium", 0),
                "insufficientData": by_category.get("insufficient_data", 0),
                "withRevenueAtRisk": customers_with_exposure,
            },
            "services": {
                "total": sum(a.risk.service_count for a in analyses),
                "open": open_services,
                "concluded": sum(concluded_counts.values()),
                "byStatus": status_counts,
                "highRisk": services_at_risk,
            },
            "revenue": {
                "revenueAtRiskCents": revenue_at_risk,
                "revenueAtRiskEur": str(cents_to_eur(revenue_at_risk)),
                "upcomingRenewalsCents": upcoming,
                "upcomingRenewalsEur": str(cents_to_eur(upcoming)),
                "historicalReplenishedCents": total_replenished,
                "historicalReplenishedEur": str(cents_to_eur(total_replenished)),
            },
            "topRiskReasons": [
                {"label": label, "count": count}
                for label, count in sorted(reason_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
            ],
            "upcomingRenewals": upcoming_renewals[:10],
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
