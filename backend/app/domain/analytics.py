"""Analytics orchestration: turns stored rows into risk and revenue answers.

This module is the single place where risk, exposure and recommendations are
computed, so the API layer stays thin and every endpoint reports consistent
numbers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import AccountRow, ServiceRow
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


@dataclass
class ServiceAnalysis:
    service: ServiceRow
    risk: ServiceRisk
    exposure: RenewalExposure | None
    recommendations: list


@dataclass
class CustomerAnalysis:
    account: AccountRow
    risk: CustomerRisk
    exposure: CustomerExposure
    services: list[ServiceAnalysis] = field(default_factory=list)
    recommendations: list = field(default_factory=list)


class AnalyticsService:
    """Computes the full analytical model for a given settings object."""

    def __init__(self, session: Session, settings: RiskSettings, now: dt.datetime | None = None):
        self.session = session
        self.settings = settings
        self.now = now or get_settings().reference_now()

    def _load_accounts(self) -> list[AccountRow]:
        return list(
            self.session.scalars(
                select(AccountRow).options(
                    selectinload(AccountRow.services).selectinload(ServiceRow.transactions)
                )
            )
        )

    def analyze_customer(self, account: AccountRow) -> CustomerAnalysis:
        service_analyses: list[ServiceAnalysis] = []
        exposures: list[RenewalExposure] = []
        for service in account.services:
            risk = compute_service_risk(
                service=service,
                account=account,
                transactions=list(service.transactions),
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
        return [self.analyze_customer(a) for a in self._load_accounts()]

    def summary(self) -> dict:
        analyses = self.analyze_all()
        by_category = {"low": 0, "medium": 0, "high": 0, "insufficient_data": 0, "not_applicable": 0}
        for analysis in analyses:
            by_category[analysis.risk.category] = by_category.get(analysis.risk.category, 0) + 1

        active_services = 0
        status_counts: dict[str, int] = {}
        concluded_counts: dict[str, int] = {}
        revenue_at_risk = 0
        upcoming = 0
        customers_at_risk: set[int] = set()
        services_at_risk = 0
        reason_counter: dict[str, int] = {}
        upcoming_renewals: list[dict] = []

        for analysis in analyses:
            for sa in analysis.services:
                status_counts[sa.service.status] = status_counts.get(sa.service.status, 0) + 1
                if sa.service.status in ELIGIBLE_STATUSES:
                    active_services += 1
                else:
                    concluded_counts[sa.service.status] = (
                        concluded_counts.get(sa.service.status, 0) + 1
                    )
                if sa.risk.category == "high":
                    services_at_risk += 1
                    customers_at_risk.add(analysis.account.id)
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
                            "renewalAt": sa.service.expires_at.isoformat(),
                            "amountCents": sa.exposure.amount_cents,
                            "amountEur": str(cents_to_eur(sa.exposure.amount_cents)),
                            "riskScore": sa.risk.score,
                            "riskCategory": sa.risk.category,
                            "revenueAtRiskEur": str(cents_to_eur(sa.exposure.revenue_at_risk_cents)),
                        }
                    )

        upcoming_renewals.sort(key=lambda r: r["renewalAt"])

        total_replenished = sum(a.account.total_replenished for a in analyses)

        return {
            "generatedAt": self.now.isoformat(),
            "horizonDays": self.settings.horizon_days,
            "customers": {
                "total": len(analyses),
                "byCategory": by_category,
                "highRisk": by_category.get("high", 0),
                "mediumRisk": by_category.get("medium", 0),
                "insufficientData": by_category.get("insufficient_data", 0),
                "withRevenueAtRisk": len(customers_at_risk),
            },
            "services": {
                "total": sum(a.risk.service_count for a in analyses),
                "open": active_services,
                "concluded": sum(concluded_counts.values()),
                "byStatus": status_counts,
                "highRisk": services_at_risk,
            },
            "revenue": {
                "revenueAtRiskEur": str(cents_to_eur(revenue_at_risk)),
                "revenueAtRiskCents": revenue_at_risk,
                "upcomingRenewalsEur": str(cents_to_eur(upcoming)),
                "upcomingRenewalsCents": upcoming,
                "historicalReplenishedEur": str(cents_to_eur(total_replenished)),
                "historicalReplenishedCents": total_replenished,
            },
            "topRiskReasons": [
                {"label": label, "count": count}
                for label, count in sorted(reason_counter.items(), key=lambda kv: -kv[1])[:8]
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
