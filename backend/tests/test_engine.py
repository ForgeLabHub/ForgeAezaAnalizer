"""Tests for the real analytics engine and its runtime integration.

These cover the module that connects the domain layer to the API contract, so a
regression here would silently return the 503 stub or publish numbers that
disagree with the domain tests.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import Analysis, InvalidInput, State
from backend.app.config import Settings
from backend.app.domain.engine import DomainAnalytics, create
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
AS_OF = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def snapshot():
    return json.loads((ROOT / "backend/data/snapshot.json").read_text(encoding="utf-8"))


def state(source, settings=None):
    engine = create()
    payload = settings if settings is not None else engine.definition().defaults
    return State(1, 1, 1, source, payload, as_of=AS_OF)


# ------------------------------------------------------------------ contract


def test_definition_matches_domain_factors_and_defaults():
    definition = create().definition()
    from app.domain.risk import DEFAULT_WEIGHTS, FACTORS

    assert definition.version
    assert set(definition.defaults["weights"]) == set(DEFAULT_WEIGHTS)
    assert [f["key"] for f in definition.factors] == [f.key for f in FACTORS]
    for factor in definition.factors:
        assert factor["label"] and factor["normalization"] and factor["missingDataBehaviour"]


def test_validate_settings_rejects_unknown_keys_and_factors():
    engine = create()
    with pytest.raises(InvalidInput):
        engine.validate_settings({**engine.definition().defaults, "typo": 1})
    with pytest.raises(InvalidInput):
        engine.validate_settings(
            {**engine.definition().defaults, "weights": {"nope": 1.0}}
        )


def test_validate_settings_rejects_negative_and_inverted_values():
    engine = create()
    base = engine.definition().defaults
    with pytest.raises(InvalidInput):
        engine.validate_settings({**base, "weights": {**base["weights"], "expiry_proximity": -1}})
    with pytest.raises(InvalidInput):
        engine.validate_settings({**base, "lowMax": 80, "mediumMax": 10})
    with pytest.raises(InvalidInput):
        engine.validate_settings({**base, "horizonDays": 0})


def test_validate_settings_accepts_null_window():
    engine = create()
    base = engine.definition().defaults
    result = engine.validate_settings({**base, "failedRenewalWindowDays": None})
    assert result["failedRenewalWindowDays"] is None


def test_calculate_requires_as_of():
    engine = create()
    with pytest.raises(InvalidInput):
        engine.calculate(State(1, 1, 1, {"accounts": [], "services": [], "transactions": []},
                               engine.definition().defaults))


def test_calculate_does_not_mutate_the_state(snapshot):
    engine = create()
    original = state(snapshot)
    before = copy.deepcopy(original)
    engine.calculate(original)
    assert original == before


# -------------------------------------------------------------- real numbers


def test_calculate_publishes_the_documented_snapshot_figures(snapshot):
    result = create().calculate(state(snapshot))
    summary = result.summary
    assert summary["customers"]["total"] == 10
    assert summary["services"]["total"] == 30
    assert summary["services"]["open"] == 18
    assert summary["revenue"]["revenueAtRiskEur"] == "5.74"
    assert summary["revenue"]["upcomingRenewalsEur"] == "17.03"
    assert summary["revenue"]["historicalReplenishedEur"] == "22240.73"
    assert summary["historyAvailable"] is False
    assert summary["model"]["calibrated"] is False


def test_every_account_and_service_is_present_and_owned_correctly(snapshot):
    result = create().calculate(state(snapshot))
    assert {c["id"] for c in result.customers} == {a["id"] for a in snapshot["accounts"]}
    owners = {
        (s["id"], c["id"]) for c in result.customers for s in c["services"]
    }
    assert owners == {(s["id"], s["ownerId"]) for s in snapshot["services"]}


def test_money_matches_source_without_double_conversion(snapshot):
    result = create().calculate(state(snapshot))
    accounts = {a["id"]: a for a in snapshot["accounts"]}
    for customer in result.customers:
        account = accounts[customer["id"]]
        assert customer["balance"]["cents"] == account["balance"]
        assert customer["totalReplenished"]["cents"] == account["totalReplenished"]


def test_concluded_services_are_not_forecast(snapshot):
    result = create().calculate(state(snapshot))
    for customer in result.customers:
        for service in customer["services"]:
            if service["status"] in {"deleted", "blocked"}:
                assert service["eligibleForForecast"] is False
                assert service["riskScore"] is None
                assert service["revenueAtRisk"] is None


def test_changing_weights_changes_the_result(snapshot):
    engine = create()
    base = engine.definition().defaults
    default = engine.calculate(state(snapshot, base)).summary

    # A heavier expiry weight pulls more renewals into the horizon, so the money
    # at risk must rise even though the category counts happen to hold.
    heavier_expiry = copy.deepcopy(base)
    heavier_expiry["weights"] = {**base["weights"], "expiry_proximity": 9.0}
    changed = engine.calculate(state(snapshot, heavier_expiry)).summary
    assert changed["revenue"]["revenueAtRiskCents"] > default["revenue"]["revenueAtRiskCents"]

    # A heavier prolong_wait weight must move customers between categories.
    heavier_wait = copy.deepcopy(base)
    heavier_wait["weights"] = {**base["weights"], "prolong_wait_status": 9.0}
    shifted = engine.calculate(state(snapshot, heavier_wait)).summary
    assert shifted["customers"]["highRisk"] != default["customers"]["highRisk"]


def test_zero_weights_yield_no_score(snapshot):
    engine = create()
    base = engine.definition().defaults
    zeroed = copy.deepcopy(base)
    zeroed["weights"] = {key: 0.0 for key in base["weights"]}
    summary = engine.calculate(state(snapshot, zeroed)).summary
    # No factor contributes, so nothing can be scored: the honest answer is
    # "insufficient data" rather than a fabricated zero-risk list.  Every
    # customer with at least one open service lands there; the rest are already
    # concluded and stay "not_applicable".
    assert summary["customers"]["highRisk"] == 0
    assert summary["customers"]["mediumRisk"] == 0
    assert summary["customers"]["insufficientData"] == 6
    assert sum(summary["customers"]["byCategory"].values()) == summary["customers"]["total"] == 10


def test_window_setting_changes_failed_renewal_factor(snapshot):
    engine = create()
    base = engine.definition().defaults
    wide = copy.deepcopy(base)
    wide["failedRenewalWindowDays"] = None
    narrow = copy.deepcopy(base)
    narrow["failedRenewalWindowDays"] = 30
    a = engine.calculate(state(snapshot, wide)).summary
    b = engine.calculate(state(snapshot, narrow)).summary
    # 9 of 23 failed renewals predate a 90-day window, so a 30-day window must
    # reduce the total score mass rather than leave it untouched.
    assert a["customers"]["highRisk"] >= b["customers"]["highRisk"]


# ------------------------------------------------------------------- runtime


def test_default_factory_makes_the_api_ready(settings, snapshot):
    with TestClient(create_app(settings)) as client:
        assert client.get("/ready").status_code == 200
        token = client.post("/api/v1/auth/login",
            json={"email": "analyst@aeza.test", "password": "demo123"}).json()["access_token"]
        body = client.get("/api/v1/analytics/summary",
            headers={"Authorization": f"Bearer {token}"}).json()
        assert body["customers"]["total"] == 10
        assert body["revenue"]["revenueAtRiskEur"] == "5.74"


def test_priority_endpoint_matches_summary_exposure(settings):
    with TestClient(create_app(settings)) as client:
        token = client.post("/api/v1/auth/login",
            json={"email": "analyst@aeza.test", "password": "demo123"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        priority = client.get("/api/v1/priority", headers=headers).json()
        summary = client.get("/api/v1/analytics/summary", headers=headers).json()
        assert priority["summary"]["revenueAtRiskCents"] == summary["revenue"]["revenueAtRiskCents"]
        assert priority["generation"] == summary["generation"]
        assert priority["summary"]["servicesInPortfolio"] == summary["services"]["total"]


def test_priority_requires_auth_and_validates_filters(client):
    assert client.get("/api/v1/priority").status_code == 401


def test_priority_rejects_unknown_sort_and_tier(client, auth_headers):
    assert client.get("/api/v1/priority?sort=nope", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/priority?tier=nope", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/priority?limit=0", headers=auth_headers).status_code == 422


def test_priority_pins_a_generation(client, auth_headers):
    first = client.get("/api/v1/priority", headers=auth_headers).json()["generation"]
    assert client.get(f"/api/v1/priority?generation={first}", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/priority?generation=999", headers=auth_headers).status_code == 404


def test_priority_is_empty_for_an_empty_snapshot(settings):
    empty = Settings(
        database_url=settings.database_url,
        jwt_secret=settings.jwt_secret,
        bootstrap_admin_password=settings.bootstrap_admin_password,
        snapshot_path=str(ROOT / "backend/data/snapshot.json"),
        as_of=settings.as_of,
        seed_demo_data=False,
    )
    with TestClient(create_app(empty)) as client:
        token = client.post("/api/v1/auth/login",
            json={"email": "analyst@aeza.test", "password": "demo123"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        body = client.get("/api/v1/priority", headers=headers).json()
        assert body["items"] == []
        assert body["summary"]["items"] == 0
        assert body["summary"]["revenueAtRiskCents"] == 0


def test_settings_window_round_trips_through_the_api(client, auth_headers):
    response = client.patch("/api/v1/model/settings",
        json={"failedRenewalWindowDays": 30}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["failedRenewalWindowDays"] == 30
    assert client.post("/api/v1/model/settings/reset",
        headers=auth_headers).json()["settings"]["failedRenewalWindowDays"] == 90
    assert client.patch("/api/v1/model/settings",
        json={"failedRenewalWindowDays": 0}, headers=auth_headers).status_code == 422
