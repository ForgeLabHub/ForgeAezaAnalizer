"""Unit tests for revenue-at-risk and retention recommendations."""

from __future__ import annotations

import datetime as dt


from app.domain.revenue import (
    build_recommendations,
    compute_customer_exposure,
    compute_service_exposure,
)
from app.domain.risk import RiskSettings, compute_service_risk
from app.domain.schema import Account, Service

NOW = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)


def _account(balance=10_000, **overrides):
    base = {
        "id": 1,
        "email": "a@b.c",
        "balance": balance,
        "withdrawBalance": min(1_000, balance),
        "totalReplenished": max(50_000, balance),
        "bonusBalance": 500,
        "bonusState": "locked",
    }
    base.update(overrides)
    return Account.model_validate(base)


def _service(**overrides) -> Service:
    base = {
        "id": 1,
        "name": "svc-1",
        "ownerId": 1,
        "paymentTerm": "month",
        "autoProlong": False,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "expiresAt": "2026-10-25T15:00:00.000Z",
        "status": "active",
        "price": 1000,
    }
    base.update(overrides)
    return Service.model_validate(base)


def _risk(service, account, transactions=(), settings=None):
    return compute_service_risk(
        service=service,
        account=account,
        transactions=list(transactions),
        settings=settings or RiskSettings(),
        now=NOW,
    )


def test_exposure_is_price_times_score_over_100():
    service = _service()
    account = _account(balance=0)
    risk = _risk(service, account)
    exposure = compute_service_exposure(
        service=service, risk=risk, horizon_days=30, now=NOW
    )
    assert exposure is not None
    assert exposure.amount_cents == 1000
    assert exposure.revenue_at_risk_cents == round(1000 * risk.score / 100)


def test_renewal_outside_horizon_is_excluded():
    service = _service(expiresAt="2027-06-01T00:00:00.000Z")
    risk = _risk(service, _account())
    assert compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW) is None


def test_already_expired_open_service_is_excluded():


    service = _service(expiresAt="2026-10-01T00:00:00.000Z")
    risk = _risk(service, _account())
    assert compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW) is None


def test_zero_price_service_is_excluded():
    service = _service(price=0)
    risk = _risk(service, _account())
    assert compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW) is None


def test_concluded_service_is_excluded():
    service = _service(status="deleted")
    risk = _risk(service, _account())
    assert compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW) is None


def test_horizon_edge_is_inclusive():

    service = _service(expiresAt="2026-11-18T15:00:00.000Z")
    risk = _risk(service, _account())
    exposure = compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW)
    assert exposure is not None


def test_horizon_is_configurable():
    service = _service(expiresAt="2026-11-18T15:00:00.000Z")
    risk = _risk(service, _account())
    assert compute_service_exposure(service=service, risk=risk, horizon_days=29, now=NOW) is None
    assert compute_service_exposure(service=service, risk=risk, horizon_days=31, now=NOW) is not None


def test_customer_exposure_sums_without_double_counting():
    services = [_service(id=1, price=1000), _service(id=2, price=2000)]
    account = _account(balance=0)
    renewals = []
    for service in services:
        risk = _risk(service, account)
        exposure = compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW)
        assert exposure is not None
        renewals.append(exposure)
    total = compute_customer_exposure(customer_id=1, renewals=renewals)
    assert total.upcoming_renewals_cents == 3000
    assert total.revenue_at_risk_cents == sum(r.revenue_at_risk_cents for r in renewals)
    assert len({r.service_id for r in total.renewals}) == 2


def test_revenue_at_risk_is_not_the_balance():
    service = _service(price=1000)
    account = _account(balance=999_999)
    risk = _risk(service, account)
    exposure = compute_service_exposure(service=service, risk=risk, horizon_days=30, now=NOW)
    assert exposure is not None

    assert exposure.revenue_at_risk_cents <= service.price


def test_recommendations_trace_to_real_signals():
    service = _service(autoProlong=False, status="prolong_wait")
    account = _account(balance=0)
    risk = _risk(service, account)
    recs = build_recommendations(risk, account, service)
    codes = {r.code for r in recs}
    assert "check_balance" in codes
    assert "check_prolong_wait" in codes
    assert "notify_expiring" in codes
    assert all(r.detail for r in recs)


def test_overdue_service_gets_overdue_recommendation_not_notify():

    service = _service(expiresAt="2026-09-01T00:00:00.000Z", autoProlong=False)
    account = _account(balance=0)
    risk = _risk(service, account)
    recs = build_recommendations(risk, account, service)
    codes = {r.code for r in recs}
    assert "overdue_renewal" in codes
    assert "notify_expiring" not in codes
    overdue = next(r for r in recs if r.code == "overdue_renewal")
    assert "истекла" in overdue.detail
    assert "осталось" not in overdue.detail


def test_recommendations_are_deduplicated_and_priority_ordered():
    service = _service(autoProlong=False, status="prolong_wait")
    account = _account(balance=0)
    risk = _risk(service, account)
    recs = build_recommendations(risk, account, service)
    codes = [r.code for r in recs]
    assert len(codes) == len(set(codes))
    assert [r.priority for r in recs] == sorted(r.priority for r in recs)


def test_no_recommendation_promises_prevention():
    service = _service()
    account = _account(balance=0)
    risk = _risk(service, account)
    for rec in build_recommendations(risk, account, service):
        lowered = rec.detail.lower()
        assert "гарантир" not in lowered
        assert "точно предотврат" not in lowered
