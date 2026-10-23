"""Serialisers that convert domain analyses into API payloads.

Money is exposed both as exact eurocents (integers, source units) and as
decimal euro strings, so a client never has to guess the unit and never has to
re-convert.

Every monetary accessor is null-aware.  A value that is *unknown* in the source
is published as the pair ``{"cents": null, "eur": null}`` rather than ``0``:
the API schema enforces that pairing, and silently reporting a missing balance
as zero would misstate the customer's position.
"""

from __future__ import annotations

from app.domain.analytics import (
    CATEGORY_LABELS,
    STATUS_LABELS,
    TERM_LABELS,
    CustomerAnalysis,
    ServiceAnalysis,
)
from app.domain.money import cents_to_eur


def money(cents: int | None) -> dict:
    """Render an amount as exact eurocents plus a decimal euro string."""

    if cents is None:
        return {"cents": None, "eur": None}
    return {"cents": cents, "eur": str(cents_to_eur(cents))}


def factor_payload(factor) -> dict:
    return {
        "key": factor.key,
        "label": factor.label,
        "value": factor.value,
        "weight": factor.weight,
        "contribution": round(factor.contribution, 4),
        "available": factor.available,
        "reason": factor.reason,
    }


def service_payload(sa: ServiceAnalysis) -> dict:
    service = sa.service
    risk = sa.risk
    return {
        "id": service.id,
        "name": service.name,
        "status": service.status,
        "statusLabel": STATUS_LABELS.get(service.status, service.status),
        "paymentTerm": service.payment_term,
        "paymentTermLabel": TERM_LABELS.get(service.payment_term, service.payment_term or ""),
        "autoProlong": service.auto_prolong,
        "createdAt": service.created_at.isoformat() if service.created_at else None,
        "expiresAt": service.expires_at.isoformat() if service.expires_at else None,
        "daysToExpiry": round(risk.days_to_expiry, 2) if risk.days_to_expiry is not None else None,
        "price": money(service.price),
        "riskScore": risk.score,
        "riskCategory": risk.category,
        "riskCategoryLabel": CATEGORY_LABELS.get(risk.category, risk.category),
        "eligibleForForecast": risk.eligible,
        "stateNote": risk.status_note,
        "reasons": risk.reasons,
        "missingData": risk.missing_data,
        "factors": [factor_payload(f) for f in risk.factors],
        "revenueAtRisk": money(sa.exposure.revenue_at_risk_cents) if sa.exposure else None,
        "upcomingRenewalAt": sa.exposure.renewal_at.isoformat() if sa.exposure else None,
        "recommendations": [
            {"code": r.code, "title": r.title, "detail": r.detail, "priority": r.priority}
            for r in sa.recommendations
        ],
    }


def customer_summary_payload(analysis: CustomerAnalysis) -> dict:
    account = analysis.account
    risk = analysis.risk
    return {
        "id": account.id,
        "email": account.email,
        "balance": money(account.balance),
        "withdrawBalance": money(account.withdraw_balance),
        "totalReplenished": money(account.total_replenished),
        "bonusBalance": money(account.bonus_balance),
        "bonusState": account.bonus_state,
        "riskScore": risk.score,
        "riskCategory": risk.category,
        "riskCategoryLabel": CATEGORY_LABELS.get(risk.category, risk.category),
        "serviceCount": risk.service_count,
        "eligibleServiceCount": risk.eligible_service_count,
        "highRiskServiceCount": risk.high_risk_service_count,
        "concludedStates": risk.concluded_states,
        "stateNote": risk.state_note,
        "revenueAtRisk": money(analysis.exposure.revenue_at_risk_cents),
        "upcomingRenewals": money(analysis.exposure.upcoming_renewals_cents),
        "topReasons": risk.reasons[:3],
        "missingData": risk.missing_data,
    }


def customer_detail_payload(analysis: CustomerAnalysis) -> dict:
    payload = customer_summary_payload(analysis)
    payload.update(
        {
            "reasons": analysis.risk.reasons,
            "services": [service_payload(sa) for sa in analysis.services],
            "recommendations": [
                {"code": r.code, "title": r.title, "detail": r.detail, "priority": r.priority}
                for r in analysis.recommendations
            ],
            "renewalDetails": [
                {
                    "serviceId": r.service_id,
                    "renewalAt": r.renewal_at.isoformat(),
                    "amount": money(r.amount_cents),
                    "riskScore": r.risk_score,
                    "revenueAtRisk": money(r.revenue_at_risk_cents),
                }
                for r in analysis.exposure.renewals
            ],
        }
    )
    return payload
