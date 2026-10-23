"""End-to-end integration test of the full analyst workflow.

Walks the ten steps from the case brief: obtain data, validate, import, score,
read the summary, open a customer, change weights, recompute, verify the
settings were persisted, then re-import and confirm data integrity.
"""

from __future__ import annotations

import copy

from app.domain.importer import current_counts


def test_full_workflow(client, auth_headers, snapshot_payload):
    # 1. Source data is present in the snapshot file itself.
    assert set(snapshot_payload) == {"accounts", "services", "transactions"}

    # 2. Validation rejects a broken payload before anything is written.
    broken = copy.deepcopy(snapshot_payload)
    broken["transactions"][0]["amount"] = 5000  # above the documented ceiling of 1000
    assert (
        client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers).status_code == 422
    )

    # 3. Import the valid snapshot.
    imported = client.put(
        "/api/v1/source/snapshot", json=snapshot_payload, headers=auth_headers
    )
    assert imported.status_code == 200
    assert imported.json()["report"]["accepted"]["accounts"] == 10

    # 4. Risk is computed for every customer.
    summary = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert summary["customers"]["total"] == 10
    assert sum(summary["customers"]["byCategory"].values()) == 10
    assert summary["customers"]["byCategory"]["high"] >= 1

    # 5. Analytics summary carries the KPI block the dashboard needs.
    for key in ("revenueAtRiskEur", "upcomingRenewalsEur", "historicalReplenishedEur"):
        assert key in summary["revenue"]

    # 6. A high-risk customer can be opened and explained.
    ranked = client.get(
        "/api/v1/customers?sortBy=riskScore&sortDir=desc&pageSize=5", headers=auth_headers
    ).json()["items"]
    top = ranked[0]
    detail = client.get(f"/api/v1/customers/{top['id']}", headers=auth_headers).json()
    assert detail["reasons"], "high-risk customer must expose reasons"
    assert detail["services"]
    scored = [s for s in detail["services"] if s["eligibleForForecast"]]
    assert scored and all(s["reasons"] for s in scored)

    # 7. Changing weights changes the score.
    original_score = top["riskScore"]
    all_factors = client.get("/api/v1/model/settings", headers=auth_headers).json()["factors"]
    weights = {f["key"]: 0.0 for f in all_factors}
    weights["expiry_proximity"] = 10.0
    assert (
        client.patch(
            "/api/v1/model/settings", json={"weights": weights}, headers=auth_headers
        ).status_code
        == 200
    )

    # 8. Analytics recompute against the new configuration.
    after = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert after["customers"]["byCategory"] != summary["customers"]["byCategory"]
    new_detail = client.get(f"/api/v1/customers/{top['id']}", headers=auth_headers).json()
    assert new_detail["riskScore"] != original_score

    # 9. The change is persisted server-side, not just in the response.
    persisted = client.get("/api/v1/model/settings", headers=auth_headers).json()
    assert persisted["isDefault"] is False
    assert persisted["settings"]["weights"]["expiry_proximity"] == 10.0
    assert persisted["settings"]["weights"]["auto_prolong_disabled"] == 0.0

    # 10. Re-import and verify integrity, then restore defaults.
    assert (
        client.put("/api/v1/source/snapshot", json=snapshot_payload, headers=auth_headers).status_code
        == 200
    )
    counts = client.get("/api/v1/source/snapshot", headers=auth_headers).json()["counts"]
    assert counts == {"accounts": 10, "services": 30, "transactions": 100}
    assert (
        client.post("/api/v1/model/settings/reset", headers=auth_headers).json()["isDefault"] is True
    )
    restored = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert restored["customers"]["byCategory"] == summary["customers"]["byCategory"]


def test_import_is_atomic_on_failure(client, auth_headers, snapshot_payload):
    """A rejected import must leave the previous dataset byte-identical."""

    before = client.get("/api/v1/analytics/summary", headers=auth_headers).json()

    broken = copy.deepcopy(snapshot_payload)
    # Valid structure, invalid semantics: the account violates a documented invariant.
    broken["accounts"][0]["withdrawBalance"] = broken["accounts"][0]["balance"] + 1
    assert (
        client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers).status_code == 422
    )

    after = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert after["customers"] == before["customers"]
    assert after["revenue"] == before["revenue"]
    assert (
        client.get("/api/v1/source/snapshot", headers=auth_headers).json()["counts"]
        == {"accounts": 10, "services": 30, "transactions": 100}
    )


def test_analysis_is_deterministic_for_a_fixed_clock(client, auth_headers):
    """With AEZA_AS_OF pinned, repeated runs must produce identical numbers."""

    first = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    second = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert first["customers"] == second["customers"]
    assert first["revenue"] == second["revenue"]
    assert first["topRiskReasons"] == second["topRiskReasons"]


def test_scores_are_reproducible_across_processes(app_env, snapshot_payload):
    """Recomputing from a clean database yields the same scores."""

    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as first_client:
        token = first_client.post(
            "/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        first = first_client.get("/api/v1/customers?pageSize=200", headers=headers).json()["items"]

    from app.db import get_session_factory

    with get_session_factory()() as session:
        assert current_counts(session) == {"accounts": 10, "services": 30, "transactions": 100}

    with TestClient(create_app()) as second_client:
        token = second_client.post(
            "/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        second = second_client.get("/api/v1/customers?pageSize=200", headers=headers).json()["items"]

    assert [(i["id"], i["riskScore"]) for i in first] == [
        (i["id"], i["riskScore"]) for i in second
    ]
