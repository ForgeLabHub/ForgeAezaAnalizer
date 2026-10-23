"""Unit tests for the retention priority worklist."""

from __future__ import annotations

from app.domain.priority import (
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_WATCH,
    build_priority,
    collect_candidates,
    priority_summary,
    rank_candidates,
    serialize_priority,
    tier_for,
)


def _service(**overrides):
    base = {
        "id": 1,
        "name": "svc-1",
        "status": "active",
        "eligibleForForecast": True,
        "riskScore": 50.0,
        "riskCategory": "high",
        "daysToExpiry": 5.0,
        "revenueAtRisk": {"cents": 1000, "eur": "10.00"},
        "upcomingRenewalAt": "2026-10-25T00:00:00+00:00",
        "reasons": ["r1", "r2", "r3", "r4"],
        "recommendations": [{"code": "c", "title": "T", "detail": "D", "priority": 1}],
    }
    base.update(overrides)
    return base


def _customer(customer_id=1, **service_overrides):
    return {"id": customer_id, "email": f"c{customer_id}@x.test", "services": [_service(**service_overrides)]}


# --------------------------------------------------------------------- tiering


def test_tier_critical_requires_high_risk_and_money_in_horizon():
    assert tier_for("high", 1) == TIER_CRITICAL


def test_tier_high_when_high_risk_without_money():
    assert tier_for("high", 0) == TIER_HIGH


def test_tier_high_when_medium_risk_with_money():
    assert tier_for("medium", 5) == TIER_HIGH


def test_tier_watch_is_the_fallback():
    assert tier_for("low", 0) == TIER_WATCH
    assert tier_for("medium", 0) == TIER_WATCH
    assert tier_for("low", 100) == TIER_WATCH


# ---------------------------------------------------------------- eligibility


def test_ineligible_services_are_excluded():
    payload = [_customer(eligibleForForecast=False)]
    assert collect_candidates(payload) == []


def test_unscored_categories_are_excluded():
    for category in ("insufficient_data", "not_applicable"):
        assert collect_candidates([_customer(riskCategory=category)]) == []


def test_service_without_score_is_excluded():
    assert collect_candidates([_customer(riskScore=None)]) == []


def test_customer_without_services_yields_nothing():
    assert collect_candidates([{"id": 1, "email": "a@b.c", "services": []}]) == []


# ----------------------------------------------------------------- normalising


def test_priority_score_is_relative_to_the_portfolio_peak():
    customers = [
        _customer(1, id=1, revenueAtRisk={"cents": 500, "eur": "5.00"}),
        _customer(2, id=2, revenueAtRisk={"cents": 250, "eur": "2.50"}),
        _customer(3, id=3, revenueAtRisk={"cents": 1000, "eur": "10.00"}),
    ]
    items = build_priority(customers)
    by_service = {i.customer_id: i.priority_score for i in items}
    assert by_service[3] == 100.0
    assert by_service[1] == 50.0
    assert by_service[2] == 25.0


def test_priority_falls_back_to_risk_when_no_money_in_horizon():
    customers = [
        _customer(1, id=1, riskScore=80.0, revenueAtRisk={"cents": 0, "eur": "0.00"}),
        _customer(2, id=2, riskScore=20.0, revenueAtRisk={"cents": 0, "eur": "0.00"}),
    ]
    items = build_priority(customers)
    assert [i.priority_score for i in items] == [80.0, 20.0]


def test_empty_portfolio_returns_empty_worklist():
    assert build_priority([]) == []


# -------------------------------------------------------------------- ordering


def test_default_order_is_by_exposure_then_risk():
    customers = [
        _customer(1, id=1, revenueAtRisk={"cents": 100, "eur": "1.00"}),
        _customer(2, id=2, revenueAtRisk={"cents": 900, "eur": "9.00"}),
    ]
    items = build_priority(customers)
    assert [i.customer_id for i in items] == [2, 1]
    assert [i.rank for i in items] == [1, 2]


def test_risk_sort_orders_by_score_not_money():
    customers = [
        _customer(1, id=1, riskScore=10.0, revenueAtRisk={"cents": 900, "eur": "9.00"}),
        _customer(2, id=2, riskScore=90.0, revenueAtRisk={"cents": 100, "eur": "1.00"}),
    ]
    items = build_priority(customers, sort="risk")
    assert [i.customer_id for i in items] == [2, 1]


def test_ranking_is_deterministic_for_identical_rows():
    # Same money, same risk, same expiry: the only remaining tie-breakers are
    # customer id and service id, so the order must be stable and input-order
    # independent.
    customers = [_customer(n, id=n) for n in (3, 1, 2)]
    first = [(i.customer_id, i.service_id) for i in build_priority(customers)]
    second = [(i.customer_id, i.service_id) for i in build_priority(list(reversed(customers)))]
    assert first == second == [(1, 1), (2, 2), (3, 3)]


def test_limit_and_tier_filters_apply_after_ranking():
    customers = [
        _customer(1, id=1, riskCategory="high", revenueAtRisk={"cents": 900, "eur": "9.00"}),
        _customer(2, id=2, riskCategory="low", revenueAtRisk={"cents": 500, "eur": "5.00"}),
        _customer(3, id=3, riskCategory="high", revenueAtRisk={"cents": 100, "eur": "1.00"}),
    ]
    assert [i.customer_id for i in build_priority(customers, limit=2)] == [1, 2]
    critical = build_priority(customers, tier=TIER_CRITICAL)
    assert [i.customer_id for i in critical] == [1, 3]
    # Ranks are assigned after filtering, so the first selected row is rank 1.
    assert [i.rank for i in critical] == [1, 2]


def test_limit_is_applied_after_tier_filter():
    customers = [
        _customer(1, id=1, riskCategory="high", revenueAtRisk={"cents": 900, "eur": "9.00"}),
        _customer(2, id=2, riskCategory="high", revenueAtRisk={"cents": 500, "eur": "5.00"}),
    ]
    items = build_priority(customers, tier=TIER_CRITICAL, limit=1)
    assert [i.customer_id for i in items] == [1]


# ------------------------------------------------------------------- summary


def test_summary_counts_tiers_customers_and_exposure():
    customers = [
        _customer(1, id=1, riskCategory="high", revenueAtRisk={"cents": 900, "eur": "9.00"}),
        _customer(2, id=2, riskCategory="low", revenueAtRisk={"cents": 100, "eur": "1.00"}),
    ]
    items = build_priority(customers)
    summary = priority_summary(items, total_services=7)
    assert summary["items"] == 2
    assert summary["customers"] == 2
    assert summary["byTier"][TIER_CRITICAL] == 1
    assert summary["byTier"][TIER_WATCH] == 1
    assert summary["revenueAtRiskCents"] == 1000
    assert summary["revenueAtRiskEur"] == "10.00"
    assert summary["servicesInPortfolio"] == 7
    assert "не вероятность" in summary["note"]


def test_summary_of_empty_worklist_is_zeroed():
    summary = priority_summary([], total_services=0)
    assert summary["items"] == 0 and summary["revenueAtRiskCents"] == 0
    assert summary["revenueAtRiskEur"] == "0.00"
    assert set(summary["byTier"]) == {TIER_CRITICAL, TIER_HIGH, TIER_WATCH}


# -------------------------------------------------------------- serialisation


def test_serialization_exposes_units_and_truncates_reasons():
    item = build_priority([_customer(1, reasons=["a", "b", "c", "d"])])[0]
    payload = serialize_priority(item)
    assert payload["revenueAtRisk"] == {"cents": 1000, "eur": "10.00"}
    assert len(payload["reasons"]) == 3
    assert payload["tierLabel"] and payload["tierReason"]
    assert payload["actions"] == ["T"]


def test_serialization_handles_missing_renewal_amount():
    payload = serialize_priority(build_priority([_customer(1, upcomingRenewalAt=None)])[0])
    assert payload["renewalAmount"] is None
    assert payload["renewalAt"] is None


def test_rank_candidates_ignores_empty_input():
    assert rank_candidates([]) == []
