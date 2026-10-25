"""Tests for the approved methodology: window, bonuses, horizons, overdue.

Every case targets a decision the methodology owner approved.  The fixtures are
synthetic by construction (the snapshot itself is synthetic), so these tests
prove internal consistency, not predictive accuracy.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.money import scaled_cents
from app.domain.revenue import (
    HORIZONS,
    PROLONG_WAIT_GRACE_DAYS,
    compute_customer_exposure,
    compute_horizons,
    compute_overdue,
)
from app.domain.risk import RiskSettings, compute_customer_risk, compute_service_risk

NOW = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)


class _Service:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.name = kw.get("name", "svc-1")
        self.status = kw.get("status", "active")
        self.price = kw.get("price", 1000)
        self.auto_prolong = kw.get("auto_prolong", True)
        self.payment_term = kw.get("payment_term", "month")
        self.created_at = kw.get("created_at", NOW - dt.timedelta(days=60))
        self.expires_at = kw.get("expires_at", NOW + dt.timedelta(days=10))


class _Account:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.email = kw.get("email", "a@example.test")
        self.balance = kw.get("balance", 10_000)
        self.withdraw_balance = kw.get("withdraw_balance", 0)
        self.bonus_balance = kw.get("bonus_balance", 0)
        self.bonus_state = kw.get("bonus_state", "locked")
        self.total_replenished = kw.get("total_replenished", 0)


class _Tx:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.type = kw.get("type", "prolong")
        self.status = kw.get("status", "performed")
        self.created_at = kw.get("created_at", NOW - dt.timedelta(days=1))
        self.performed_at = kw.get("performed_at", None)
        self.amount = kw.get("amount", 100)
        self.service_id = kw.get("service_id", 1)


def _risk(service=None, account=None, transactions=None, settings=None):
    return compute_service_risk(
        service=service or _Service(),
        account=account or _Account(),
        transactions=transactions or [],
        settings=settings or RiskSettings(),
        now=NOW,
    )


def test_window_excludes_old_failures():
    """At 90 days a 200-day-old failure must not count; at null it must."""
    service = _Service()
    old_fail = _Tx(id=1, status="not_performed", created_at=NOW - dt.timedelta(days=200))

    with_window = _risk(service=service, transactions=[old_fail], settings=RiskSettings())
    no_window = _risk(
        service=service,
        transactions=[old_fail],
        settings=RiskSettings(failed_renewal_window_days=None),
    )

    rate_w = next(f for f in with_window.factors if f.key == "renewal_failure_rate")
    rate_n = next(f for f in no_window.factors if f.key == "renewal_failure_rate")


    assert rate_w.value is None
    assert rate_w.available is False
    assert rate_n.value == pytest.approx(1.0)


def test_window_boundary_is_inclusive():
    """A transaction exactly at now - window is inside; one day older is not."""
    service = _Service()
    at_edge = _Tx(id=1, status="not_performed", created_at=NOW - dt.timedelta(days=90))
    just_out = _Tx(id=1, status="not_performed", created_at=NOW - dt.timedelta(days=91))

    edge = _risk(service=service, transactions=[at_edge], settings=RiskSettings())
    out = _risk(service=service, transactions=[just_out], settings=RiskSettings())

    assert next(f for f in edge.factors if f.key == "renewal_failure_rate").value == 1.0
    assert next(f for f in out.factors if f.key == "renewal_failure_rate").value is None


def test_no_attempts_is_unknown_not_zero_risk():
    """A service with no renewal history must not look safe."""
    risk = _risk(transactions=[])
    rate = next(f for f in risk.factors if f.key == "renewal_failure_rate")
    assert rate.value is None
    assert rate.available is False
    assert "Доля неуспешных продлений" in risk.missing_data


def test_future_transactions_do_not_leak_into_the_score():
    """A renewal recorded after ``now`` must be ignored entirely."""
    service = _Service()
    future_fail = _Tx(id=1, status="not_performed", created_at=NOW + dt.timedelta(days=5))
    risk = _risk(service=service, transactions=[future_fail])
    rate = next(f for f in risk.factors if f.key == "renewal_failure_rate")
    assert rate.value is None, "future event leaked into the score"


def test_diagnostic_count_reports_excluded_failures():
    """failed_renewals stays as diagnostics and shows what the window dropped."""
    service = _Service()
    txs = [
        _Tx(id=1, status="not_performed", created_at=NOW - dt.timedelta(days=10)),
        _Tx(id=2, status="not_performed", created_at=NOW - dt.timedelta(days=200)),
    ]
    risk = _risk(service=service, transactions=txs)
    diag = next(f for f in risk.factors if f.key == "failed_renewals")
    assert diag.value == pytest.approx(2.0)
    assert diag.weight == 0.0
    assert diag.available is False
    assert "Вне окна" in diag.reason


def test_unlocked_bonus_counts_toward_capacity():
    service = _Service(price=1000)
    locked = _risk(service=service, account=_Account(balance=600, bonus_balance=500,
                                                    bonus_state="locked"))
    unlocked = _risk(service=service, account=_Account(balance=600, bonus_balance=500,
                                                      bonus_state="unlocked"))
    locked_f = next(f for f in locked.factors if f.key == "insufficient_balance")
    unlocked_f = next(f for f in unlocked.factors if f.key == "insufficient_balance")

    assert locked_f.value == pytest.approx(0.4)
    assert unlocked_f.value == pytest.approx(0.0)
    assert unlocked_f.value < locked_f.value


def test_locked_and_unknown_bonus_are_not_spendable():
    service = _Service(price=1000)
    for state in ("locked", "unknown", None):
        risk = _risk(service=service, account=_Account(balance=600, bonus_balance=500,
                                                      bonus_state=state))
        f = next(f for f in risk.factors if f.key == "insufficient_balance")
        assert f.value == pytest.approx(0.4), f"bonus leaked in state {state!r}"


def test_withdraw_balance_is_not_renewal_funds():
    """Referral money meant for withdrawal must not cover a renewal."""
    service = _Service(price=1000)
    risk = _risk(service=service, account=_Account(balance=0, withdraw_balance=100_000))
    f = next(f for f in risk.factors if f.key == "insufficient_balance")
    assert f.value == pytest.approx(1.0)


def _high_risk_service(sid: int):
    """A service that actually lands in the high band (score >= 65)."""
    return _risk(
        service=_Service(id=sid, status="prolong_wait", auto_prolong=False,
                         price=1000, expires_at=NOW - dt.timedelta(days=1)),
        account=_Account(balance=0),
        transactions=[_Tx(id=sid, status="not_performed")],
    )


def test_high_risk_share_distinguishes_concentration():
    """max() stays the rating; share reports concentration separately."""
    healthy = _risk(service=_Service(id=99, expires_at=NOW + dt.timedelta(days=90)))
    one = [_high_risk_service(1), healthy, healthy]

    three = [_high_risk_service(i) for i in (1, 2, 3)]

    c_one = compute_customer_risk(customer_id=1, service_risks=one, settings=RiskSettings())
    c_three = compute_customer_risk(customer_id=2, service_risks=three, settings=RiskSettings())


    assert c_one.category == "high"

    assert c_one.score == pytest.approx(c_three.score)

    assert c_one.high_risk_share == pytest.approx(1 / 3)
    assert c_three.high_risk_share == pytest.approx(1.0)
    assert c_one.high_risk_share < c_three.high_risk_share


def test_portfolio_size_alone_does_not_raise_the_rating():
    """Ten healthy services must not outrank one, all else equal."""
    small = [_risk(service=_Service(id=1, expires_at=NOW + dt.timedelta(days=90)))]
    big = [_risk(service=_Service(id=i, expires_at=NOW + dt.timedelta(days=90)))
           for i in range(1, 11)]
    c_small = compute_customer_risk(customer_id=1, service_risks=small, settings=RiskSettings())
    c_big = compute_customer_risk(customer_id=2, service_risks=big, settings=RiskSettings())
    assert c_big.score == pytest.approx(c_small.score)


def test_empty_portfolio_has_no_division_error():
    customer = compute_customer_risk(customer_id=1, service_risks=[], settings=RiskSettings())
    assert customer.high_risk_share == 0.0
    assert customer.score is None
    assert customer.category == "insufficient_data"


def test_horizons_are_inclusive_and_nested():
    services = [
        _Service(id=1, expires_at=NOW),
        _Service(id=2, expires_at=NOW + dt.timedelta(days=7)),
        _Service(id=3, expires_at=NOW + dt.timedelta(days=30)),
        _Service(id=4, expires_at=NOW + dt.timedelta(days=90)),
        _Service(id=5, expires_at=NOW + dt.timedelta(days=91)),
    ]
    risks = {s.id: _risk(service=s) for s in services}
    h = compute_horizons(services=services, risks_by_service=risks, now=NOW)

    assert set(h) == set(HORIZONS)

    assert h[7].renewal_count == 2
    assert h[30].renewal_count == 3
    assert h[90].renewal_count == 4

    assert h[7].upcoming_renewals_cents <= h[30].upcoming_renewals_cents
    assert h[30].upcoming_renewals_cents <= h[90].upcoming_renewals_cents


def test_horizon_counts_each_service_once():
    services = [_Service(id=1, expires_at=NOW + dt.timedelta(days=5))]
    risks = {1: _risk(service=services[0])}
    h = compute_horizons(services=services, risks_by_service=risks, now=NOW)
    for days in HORIZONS:
        assert h[days].renewal_count == 1
        assert h[days].upcoming_renewals_cents == 1000


def test_expired_service_is_not_in_any_horizon():
    services = [_Service(id=1, expires_at=NOW - dt.timedelta(days=1))]
    risks = {1: _risk(service=services[0])}
    h = compute_horizons(services=services, risks_by_service=risks, now=NOW)
    for days in HORIZONS:
        assert h[days].renewal_count == 0
        assert h[days].upcoming_renewals_cents == 0


def test_deleted_service_is_not_counted_in_horizons():
    services = [_Service(id=1, status="deleted", expires_at=NOW + dt.timedelta(days=5))]
    risks = {1: _risk(service=services[0])}
    h = compute_horizons(services=services, risks_by_service=risks, now=NOW)
    for days in HORIZONS:
        assert h[days].upcoming_renewals_cents == 0


def test_overdue_is_reported_separately_from_future():
    services = [_Service(id=1, expires_at=NOW - dt.timedelta(days=3))]
    risks = {1: _risk(service=services[0])}
    overdue = compute_overdue(services=services, risks_by_service=risks, now=NOW)
    assert len(overdue) == 1
    assert overdue[0].amount_cents == 1000
    assert overdue[0].days_overdue == pytest.approx(3.0, abs=0.01)

    h = compute_horizons(services=services, risks_by_service=risks, now=NOW)
    assert all(h[d].renewal_count == 0 for d in HORIZONS)


def test_overdue_prolong_wait_beyond_grace_is_flagged():
    """Past the documented 5-day window the state contradicts the lifecycle."""
    inside = _Service(id=1, status="prolong_wait",
                      expires_at=NOW - dt.timedelta(days=PROLONG_WAIT_GRACE_DAYS))
    beyond = _Service(id=2, status="prolong_wait",
                      expires_at=NOW - dt.timedelta(days=PROLONG_WAIT_GRACE_DAYS + 1))
    risks = {s.id: _risk(service=s) for s in (inside, beyond)}
    overdue = {o.service_id: o for o in compute_overdue(
        services=[inside, beyond], risks_by_service=risks, now=NOW)}

    assert overdue[1].lifecycle_inconsistent is False
    assert overdue[2].lifecycle_inconsistent is True


def test_suspended_overdue_is_not_lifecycle_inconsistent():
    """Only prolong_wait has a documented deadline; suspended does not."""
    service = _Service(id=1, status="suspended", expires_at=NOW - dt.timedelta(days=100))
    risks = {1: _risk(service=service)}
    overdue = compute_overdue(services=[service], risks_by_service=risks, now=NOW)
    assert overdue[0].lifecycle_inconsistent is False


def test_customer_exposure_aggregates_overdue_once():
    services = [_Service(id=1, expires_at=NOW - dt.timedelta(days=2))]
    risks = {1: _risk(service=services[0])}
    exposure = compute_customer_exposure(
        customer_id=1, renewals=[], services=services, risks_by_service=risks, now=NOW
    )
    assert exposure.overdue_operational_cents == 1000
    assert exposure.upcoming_renewals_cents == 0


def test_revenue_uses_half_up():
    """A half-cent result must round up, consistently with money.py."""
    service = _Service(id=1, price=125, expires_at=NOW + dt.timedelta(days=5))
    risk = _risk(service=service)

    expected = scaled_cents(125, risk.score / 100.0)
    risks = {1: risk}
    h = compute_horizons(services=[service], risks_by_service=risks, now=NOW)
    assert h[30].revenue_at_risk_cents == expected


def test_scoring_is_deterministic():
    service = _Service()
    txs = [_Tx(id=1, status="not_performed"), _Tx(id=2, status="performed")]
    first = _risk(service=service, transactions=txs)
    second = _risk(service=service, transactions=txs)
    assert first.score == second.score
    assert [f.value for f in first.factors] == [f.value for f in second.factors]


def test_settings_validation_rejects_bad_window():
    from app.domain.risk import RiskConfigError

    with pytest.raises(RiskConfigError):
        RiskSettings(failed_renewal_window_days=0)
    with pytest.raises(RiskConfigError):
        RiskSettings(failed_renewal_window_days=99999)

    assert RiskSettings(failed_renewal_window_days=None).failed_renewal_window_days is None
