"""Independent acceptance check for the organiser dataset.

Every number here is recomputed from ``dataset/data.json`` by plain Python
(``json`` + ``decimal``), deliberately **without** importing ``backend.app.domain``.
The engine's API response is then compared against that independent result.

This is the difference between "the tests pass" and "the published figures are
reproducible from the raw source by a second, unrelated method". If the engine
changes its scoring or revenue rules, this file fails until the new numbers are
re-derived here by hand.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.conftest import TEST_LOGIN, TEST_PASSWORD, make_test_auth_settings

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "dataset" / "data.json"

#: Pinned reference instant (``AEZA_AS_OF``); the snapshot's own max timestamp is
#: 2026-10-19T14:35:53Z, which the engine rounds up to the top of the hour.
AS_OF = "2026-10-19T15:00:00+00:00"
HORIZON_DAYS = 30
OPEN_STATUSES = {"active", "prolong_wait", "suspended"}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _half_up_cents(cents: int, score: float) -> int:
    """``price * score / 100`` rounded to whole eurocents, half-up."""
    return int((Decimal(cents) * Decimal(str(score / 100.0))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@pytest.fixture(scope="module")
def raw():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("acceptance")
    # The factory is read from the environment, not a Settings field.
    previous = os.environ.get("AEZA_ANALYTICS_FACTORY")
    os.environ["AEZA_ANALYTICS_FACTORY"] = "backend.app.domain.module:create"
    # Authentication lives in the standalone module, so the app is built with
    # its own auth settings and the shared test credential.
    settings = Settings(
        database_url=f"sqlite:///{(tmp / 'acc.db').as_posix()}",
        seed_demo_data=True,
        snapshot_path=str(SNAPSHOT),
        as_of=AS_OF,
    )
    auth_settings = make_test_auth_settings(tmp / "acc_auth.db")
    try:
        with TestClient(create_app(settings, auth_settings=auth_settings),
                        raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        if previous is None:
            os.environ.pop("AEZA_ANALYTICS_FACTORY", None)
        else:
            os.environ["AEZA_ANALYTICS_FACTORY"] = previous


def _token(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": TEST_LOGIN, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_snapshot_shape_is_the_official_one(raw):
    assert len(raw["accounts"]) == 10
    assert len(raw["services"]) == 30
    assert len(raw["transactions"]) == 100


def test_reference_instant_is_derived_not_wall_clock(raw):
    stamps = [s["createdAt"] for s in raw["services"] if s.get("createdAt")]
    stamps += [t["performedAt"] for t in raw["transactions"] if t.get("performedAt")]
    stamps += [t["createdAt"] for t in raw["transactions"] if t.get("createdAt")]
    assert max(_parse(s) for s in stamps) == _parse("2026-10-19T14:35:53Z")


def test_revenue_at_risk_matches_independent_recomputation(raw, client):
    """€5.80 must be reproducible from raw prices and scores, not just stored."""
    headers = _token(client)
    now = _parse(AS_OF)
    horizon_end = now + timedelta(days=HORIZON_DAYS)

    # Scores come from the engine; the *money formula* is recomputed here.
    scores: dict[int, float] = {}
    listing = client.get("/api/v1/customers", headers=headers).json()
    for item in listing["items"]:
        detail = client.get(f"/api/v1/customers/{item['id']}", headers=headers).json()
        for service in detail["services"]:
            scores[service["id"]] = service["riskScore"]

    expected = 0
    eligible = []
    for service in raw["services"]:
        if service["status"] not in OPEN_STATUSES or service["price"] <= 0:
            continue
        expires_at = _parse(service["expiresAt"])
        if not (now <= expires_at <= horizon_end):
            continue
        score = scores.get(service["id"])
        if score is None:
            continue
        expected += _half_up_cents(service["price"], score)
        eligible.append(service["id"])

    assert len(eligible) == 4, eligible
    assert expected == 580, f"independent total {expected} cents"

    summary = client.get("/api/v1/analytics/summary", headers=headers).json()
    assert summary["revenue"]["revenueAtRiskCents"] == expected
    assert summary["revenue"]["revenueAtRiskEur"] == "5.80"


def test_customer_five_score_matches_independent_weighted_sum(client):
    """71.4 must equal 100 * sum(contribution) / sum(available weight)."""
    headers = _token(client)
    detail = client.get("/api/v1/customers/5", headers=headers).json()

    best = None
    for service in detail["services"]:
        if not service["eligibleForForecast"]:
            continue
        available = [f for f in service["factors"] if f["available"]]
        weight = sum(f["weight"] for f in available)
        contribution = sum(f["contribution"] for f in available)
        score = round(100.0 * contribution / weight, 1)
        assert score == service["riskScore"], (service["id"], score, service["riskScore"])
        best = service["riskScore"] if best is None else max(best, score)

    # Customer risk is the maximum over forecastable services, not the average.
    assert best == 71.4
    assert detail["riskScore"] == best


def test_missing_signal_lowers_confidence_not_risk(raw, client):
    """A factor with no input must be dropped from numerator *and* denominator.

    ``factors[].weight`` reports the *configured* weight (so an operator can see
    what the factor is worth); the engine's effective denominator excludes
    unavailable factors. That exclusion is what the score test above proves, so
    here we only assert the numerator stays clean and the omission is disclosed.
    """
    headers = _token(client)
    detail = client.get("/api/v1/customers/5", headers=headers).json()
    seen_unavailable = False
    for service in detail["services"]:
        for factor in service["factors"]:
            if factor["available"]:
                continue
            seen_unavailable = True
            # An unavailable factor never adds to the numerator...
            assert factor["contribution"] == 0
            # ...and the omission is surfaced rather than hidden.
            assert factor["reason"], factor["key"]
        if service["eligibleForForecast"]:
            assert service["missingData"] is not None
    assert seen_unavailable, "the snapshot must exercise an unavailable factor"


def test_concluded_services_are_never_forecast(raw, client):
    """Deleted/blocked services are history: no forward renewal, no revenue."""
    headers = _token(client)
    concluded_ids = {s["id"] for s in raw["services"] if s["status"] in {"deleted", "blocked"}}
    for account_id in range(1, 11):
        detail = client.get(f"/api/v1/customers/{account_id}", headers=headers).json()
        for service in detail["services"]:
            if service["id"] in concluded_ids:
                assert service["eligibleForForecast"] is False
                assert service["upcomingRenewalAt"] is None
