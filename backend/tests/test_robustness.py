"""Robustness guarantees for the risk ranking.

Two properties a jury can attack directly:

1. **The ranking is not an artefact of the chosen weights.** Perturbing any
   single weight by ±25% or ±50% must not change which customers are in the
   top three.
2. **No two factors measure the same signal.** A pair with |correlation| > 0.9
   would mean the score double-counts one observation.

Both are recomputed here from factor values returned by the engine, so they
fail if the weights, the normalisation or the factor set drift.
"""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.conftest import TEST_LOGIN, TEST_PASSWORD, make_test_auth_settings

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "dataset" / "data.json"
AS_OF = "2026-10-19T15:00:00+00:00"


def _weighted_score(factors: list[dict], weights: dict[str, float]) -> float | None:
    """Re-derive a service score from factor values and weights."""
    numerator = denominator = 0.0
    for factor in factors:
        if not factor["available"]:
            continue
        weight = weights.get(factor["key"], 0.0)
        if weight == 0:
            continue
        numerator += weight * factor["value"]
        denominator += weight
    return None if denominator == 0 else round(100.0 * numerator / denominator, 1)


def _customer_risk(services, weights):
    per_customer: dict[int, float] = {}
    for customer_id, detail in services:
        for service in detail["services"]:
            if not service["eligibleForForecast"]:
                continue
            score = _weighted_score(service["factors"], weights)
            if score is None:
                continue
            per_customer[customer_id] = max(per_customer.get(customer_id, 0.0), score)
    return per_customer


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("robustness")
    previous = os.environ.get("AEZA_ANALYTICS_FACTORY")
    os.environ["AEZA_ANALYTICS_FACTORY"] = "backend.app.domain.module:create"
    # Authentication lives in the standalone module, so the app is built with
    # its own auth settings and the shared test credential.
    settings = Settings(
        database_url=f"sqlite:///{(tmp / 'rob.db').as_posix()}",
        seed_demo_data=True, snapshot_path=str(SNAPSHOT), as_of=AS_OF,
    )
    auth_settings = make_test_auth_settings(tmp / "rob_auth.db")
    try:
        with TestClient(create_app(settings, auth_settings=auth_settings), raise_server_exceptions=False) as client:
            token = client.post("/api/v1/auth/login",
                                json={"email": TEST_LOGIN, "password": TEST_PASSWORD}
                                ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            weights = client.get("/api/v1/model/settings", headers=headers).json()["settings"]["weights"]
            details = []
            for item in client.get("/api/v1/customers", headers=headers).json()["items"]:
                detail = client.get(f"/api/v1/customers/{item['id']}", headers=headers).json()
                details.append((item["id"], detail))
            yield weights, details
    finally:
        if previous is None:
            os.environ.pop("AEZA_ANALYTICS_FACTORY", None)
        else:
            os.environ["AEZA_ANALYTICS_FACTORY"] = previous


def test_engine_scores_are_reproducible_from_factors(engine):
    """Our independent weighted sum must equal the engine's published score."""
    _, details = engine
    for _, detail in details:
        for service in detail["services"]:
            if not service["eligibleForForecast"]:
                continue
            weights = {f["key"]: f["weight"] for f in service["factors"]}
            assert _weighted_score(service["factors"], weights) == service["riskScore"]


def test_top_three_survives_every_single_weight_perturbation(engine):
    weights, details = engine
    baseline = _customer_risk(details, weights)
    top_three = set(sorted(baseline, key=lambda k: -baseline[k])[:3])
    assert len(top_three) == 3

    for key, original in weights.items():
        if original == 0:
            continue
        for multiplier in (0.5, 0.75, 1.25, 1.5):
            perturbed = dict(weights)
            perturbed[key] = original * multiplier
            ranking = _customer_risk(details, perturbed)
            top = set(sorted(ranking, key=lambda k: -ranking[k])[:3])
            assert top == top_three, f"{key} x{multiplier} changed the top three: {top}"


def test_no_factor_pair_is_redundant(engine):
    """|r| > 0.9 would mean two factors carry the same signal."""
    weights, details = engine
    keys = [key for key, weight in weights.items() if weight > 0]
    vectors: dict[str, list[float]] = {key: [] for key in keys}
    for _, detail in details:
        for service in detail["services"]:
            if not service["eligibleForForecast"]:
                continue
            by_key = {f["key"]: f for f in service["factors"]}
            for key in keys:
                factor = by_key.get(key)
                vectors[key].append(
                    float(factor["value"]) if factor and factor["available"] else 0.0
                )

    def correlation(a: list[float], b: list[float]) -> float:
        n = len(a)
        mean_a, mean_b = sum(a) / n, sum(b) / n
        numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        dev_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
        dev_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
        return 0.0 if dev_a == 0 or dev_b == 0 else numerator / (dev_a * dev_b)

    for a, b in itertools.combinations(keys, 2):
        r = correlation(vectors[a], vectors[b])
        assert abs(r) <= 0.9, f"{a} and {b} are redundant (r={r:.2f})"
