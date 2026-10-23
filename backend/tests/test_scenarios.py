"""Tests for what-if simulation: comparison logic and the non-publishing guarantee."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.domain.scenarios import build_simulation, compare_customers
from backend.app.config import Settings
from backend.app.main import create_app


def _customer(customer_id, category="low", score=10.0, email=None):
    return {"id": customer_id, "email": email or f"c{customer_id}@x.test",
            "riskCategory": category, "riskScore": score}


def _summary(high=0, medium=0, low=0, insufficient=0, not_applicable=0,
             revenue_cents=0, renewals_cents=0, services_high=0, total_services=0):
    return {
        "horizonDays": 30,
        "customers": {
            "total": high + medium + low + insufficient + not_applicable,
            "byCategory": {"high": high, "medium": medium, "low": low,
                           "insufficient_data": insufficient, "not_applicable": not_applicable},
            "highRisk": high, "mediumRisk": medium, "insufficientData": insufficient,
            "withRevenueAtRisk": 0,
        },
        "services": {"total": total_services, "open": 0, "concluded": 0, "byStatus": {},
                     "highRisk": services_high},
        "revenue": {"revenueAtRiskCents": revenue_cents, "revenueAtRiskEur": f"{revenue_cents / 100:.2f}",
                    "upcomingRenewalsCents": renewals_cents, "upcomingRenewalsEur": f"{renewals_cents / 100:.2f}",
                    "historicalReplenishedCents": 0, "historicalReplenishedEur": "0.00"},
    }


def _simulate(before_customers, after_customers, before_summary, after_summary, **kwargs):
    defaults = dict(settings_patch={"weights": {"x": 1}}, settings_applied={"horizonDays": 30})
    defaults.update(kwargs)
    return build_simulation(before_summary, after_summary, before_customers, after_customers, **defaults)


# ----------------------------------------------------------------- comparison


def test_unchanged_customers_are_not_reported():
    customers = [_customer(1), _customer(2)]
    assert compare_customers(customers, copy.deepcopy(customers)) == []


def test_category_change_is_reported_with_direction():
    movements = compare_customers([_customer(1, "medium", 40.0)], [_customer(1, "high", 70.0)])
    assert len(movements) == 1
    assert movements[0].direction == "up"
    assert movements[0].delta == 30.0
    assert movements[0].category_changed


def test_downgrade_is_direction_down():
    movements = compare_customers([_customer(1, "high", 70.0)], [_customer(1, "medium", 50.0)])
    assert movements[0].direction == "down"


def test_score_only_change_is_flat_but_still_reported():
    movements = compare_customers([_customer(1, "medium", 40.0)], [_customer(1, "medium", 55.0)])
    assert len(movements) == 1
    assert movements[0].direction == "flat"
    assert movements[0].delta == 15.0
    assert not movements[0].category_changed


def test_customers_missing_from_the_baseline_are_skipped():
    assert compare_customers([], [_customer(1)]) == []


def test_category_changes_sort_before_score_only_changes():
    before = [_customer(1, "medium", 40.0), _customer(2, "low", 10.0)]
    after = [_customer(1, "medium", 80.0), _customer(2, "high", 90.0)]
    movements = compare_customers(before, after)
    assert [m.customer_id for m in movements] == [2, 1]


def test_movement_with_unknown_score_has_no_delta():
    before = [_customer(1, "low", None)]
    after = [_customer(1, "high", None)]
    movements = compare_customers(before, after)
    assert movements[0].delta is None
    assert movements[0].direction == "up"


# --------------------------------------------------------------------- deltas


def test_delta_reports_category_and_revenue_changes():
    payload = _simulate(
        [_customer(1, "low", 10.0)], [_customer(1, "high", 70.0)],
        _summary(low=1, revenue_cents=100, renewals_cents=500, services_high=0),
        _summary(high=1, revenue_cents=250, renewals_cents=500, services_high=2),
    )
    assert payload["delta"]["highRisk"] == 1
    assert payload["delta"]["lowRisk"] == -1
    assert payload["delta"]["revenueAtRiskCents"] == 150
    assert payload["delta"]["revenueAtRiskEur"] == "1.50"
    assert payload["delta"]["servicesHighRisk"] == 2
    assert payload["delta"]["byCategory"]["high"] == 1
    assert payload["delta"]["byCategory"]["low"] == -1


def test_negative_revenue_delta_keeps_sign_and_format():
    payload = _simulate(
        [_customer(1)], [_customer(1)],
        _summary(revenue_cents=1000), _summary(revenue_cents=250),
    )
    assert payload["delta"]["revenueAtRiskCents"] == -750
    assert payload["delta"]["revenueAtRiskEur"] == "-7.50"


def test_delta_of_identical_models_is_zero():
    customers = [_customer(1, "high", 70.0)]
    summary = _summary(high=1, revenue_cents=500)
    payload = _simulate(customers, copy.deepcopy(customers), summary, copy.deepcopy(summary))
    assert payload["movedCustomers"] == 0
    assert payload["categoryChanges"] == 0
    assert payload["delta"]["revenueAtRiskCents"] == 0
    assert payload["delta"]["revenueAtRiskEur"] == "0.00"


def test_payload_carries_settings_and_the_non_publishing_note():
    payload = _simulate(
        [_customer(1)], [_customer(1)], _summary(), _summary(),
        settings_patch={"horizonDays": 7}, settings_applied={"horizonDays": 7, "weights": {}},
    )
    assert payload["settingsPatch"] == {"horizonDays": 7}
    assert payload["settingsApplied"]["horizonDays"] == 7
    assert "не публикуется" in payload["note"]
    assert payload["baseline"]["horizonDays"] == 30
    assert payload["scenario"]["horizonDays"] == 30


# ------------------------------------------------------------------- endpoint
#
# The shared ``client`` fixture runs a single-factor stub module, so these tests
# build the app with the bundled engine instead: the point is to exercise the
# real weights the UI exposes.


@pytest.fixture
def real_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'whatif.db').as_posix()}",
        jwt_secret="test-secret-key",
        bootstrap_admin_password="demo123",
        as_of="2026-10-19T15:00:00+00:00",
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def real_headers(real_client):
    response = real_client.post("/api/v1/auth/login",
        json={"email": "analyst@aeza.test", "password": "demo123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_whatif_does_not_publish_a_generation(real_client, real_headers):
    before = real_client.get("/api/v1/analytics/summary", headers=real_headers).json()
    response = real_client.post("/api/v1/whatif", json={"weights": {"insufficient_balance": 9.0}},
                                headers=real_headers)
    assert response.status_code == 200, response.text
    after = real_client.get("/api/v1/analytics/summary", headers=real_headers).json()
    assert before["generation"] == after["generation"]
    assert before["customers"] == after["customers"]


def test_whatif_reports_a_real_scenario_change(real_client, real_headers):
    body = real_client.post("/api/v1/whatif", json={"weights": {"insufficient_balance": 9.0}},
                            headers=real_headers).json()
    assert body["delta"]["highRisk"] < 0
    assert body["categoryChanges"] > 0
    assert body["movements"][0]["direction"] == "down"


def test_whatif_matches_a_committed_patch(real_client, real_headers):
    scenario = real_client.post("/api/v1/whatif", json={"horizonDays": 7},
                                headers=real_headers).json()
    committed = real_client.patch("/api/v1/model/settings", json={"horizonDays": 7},
                                  headers=real_headers).json()
    summary = real_client.get("/api/v1/analytics/summary", headers=real_headers).json()
    # A committed change must reproduce exactly what the simulation predicted.
    assert summary["revenue"]["revenueAtRiskCents"] == scenario["scenario"]["revenue"]["revenueAtRiskCents"]
    assert summary["customers"]["highRisk"] == scenario["scenario"]["customers"]["highRisk"]
    assert committed["settings"]["horizonDays"] == 7


def test_whatif_requires_auth(real_client):
    assert real_client.post("/api/v1/whatif", json={"horizonDays": 7}).status_code == 401


def test_whatif_rejects_empty_and_invalid_patches(real_client, real_headers):
    assert real_client.post("/api/v1/whatif", json={}, headers=real_headers).status_code == 422
    assert real_client.post("/api/v1/whatif", json={"weights": {"nope": 1}},
                            headers=real_headers).status_code == 422
    assert real_client.post("/api/v1/whatif", json={"horizonDays": 0},
                            headers=real_headers).status_code == 422
    assert real_client.post("/api/v1/whatif", json={"lowMax": 80, "mediumMax": 10},
                            headers=real_headers).status_code == 422


def test_whatif_rejects_invalid_patch_without_publishing(real_client, real_headers):
    before = real_client.get("/api/v1/analytics/summary", headers=real_headers).json()["generation"]
    real_client.post("/api/v1/whatif", json={"weights": {"expiry_proximity": -5}}, headers=real_headers)
    after = real_client.get("/api/v1/analytics/summary", headers=real_headers).json()["generation"]
    assert before == after
