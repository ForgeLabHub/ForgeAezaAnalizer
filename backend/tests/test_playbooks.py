"""Tests for retention playbooks: workflow status storage and its API.

The status is a workflow fact, not an analytical signal, so these tests check
both halves of that claim: the status behaves like durable per-recommendation
state, and it never leaks into the model or into another customer's data.
"""

from __future__ import annotations

import pytest


def _playbooks(client, headers, customer_id: int) -> dict:
    response = client.get(f"/api/v1/customers/{customer_id}/recommendations", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _first_code(payload: dict) -> str:
    assert payload["items"], "fixture must produce at least one recommendation"
    return payload["items"][0]["code"]


def test_recommendations_default_to_new(client, auth_headers):
    payload = _playbooks(client, auth_headers, 5)
    assert payload["statuses"] == ["new", "in_progress", "done"]
    for item in payload["items"]:
        assert item["status"] == "new"
        assert item["statusUpdatedAt"] is None
    # Codes are unique within a customer: the identity the status keys on.
    codes = [item["code"] for item in payload["items"]]
    assert len(codes) == len(set(codes))


def test_status_change_persists_across_reads(client, auth_headers):
    code = _first_code(_playbooks(client, auth_headers, 5))
    updated = client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "in_progress"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["updatedBy"] == "analyst@aeza.test"

    # A fresh read must reflect the stored value, not a default.
    again = _playbooks(client, auth_headers, 5)
    stored = next(i for i in again["items"] if i["code"] == code)
    assert stored["status"] == "in_progress"
    assert stored["statusUpdatedAt"] is not None


def test_only_the_addressed_recommendation_changes(client, auth_headers):
    payload = _playbooks(client, auth_headers, 5)
    codes = [item["code"] for item in payload["items"]]
    assert len(codes) >= 2, "need at least two playbooks to prove isolation"

    client.patch(
        f"/api/v1/customers/5/recommendations/{codes[0]}",
        json={"status": "done"},
        headers=auth_headers,
    )
    after = {i["code"]: i["status"] for i in _playbooks(client, auth_headers, 5)["items"]}
    assert after[codes[0]] == "done"
    for code in codes[1:]:
        assert after[code] == "new", f"{code} must not have been touched"


def test_status_does_not_leak_to_another_customer(client, auth_headers):
    code = _first_code(_playbooks(client, auth_headers, 5))
    client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "done"},
        headers=auth_headers,
    )
    other = _playbooks(client, auth_headers, 10)
    same_code = [i for i in other["items"] if i["code"] == code]
    for item in same_code:
        assert item["status"] == "new", "another customer's playbook must stay new"


def test_reopening_a_completed_playbook_is_allowed(client, auth_headers):
    code = _first_code(_playbooks(client, auth_headers, 5))
    url = f"/api/v1/customers/5/recommendations/{code}"
    for status in ("done", "in_progress", "done"):
        response = client.patch(url, json={"status": status}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == status


def test_repeated_identical_update_is_idempotent(client, auth_headers):
    code = _first_code(_playbooks(client, auth_headers, 5))
    url = f"/api/v1/customers/5/recommendations/{code}"
    first = client.patch(url, json={"status": "in_progress"}, headers=auth_headers).json()
    second = client.patch(url, json={"status": "in_progress"}, headers=auth_headers).json()
    assert first["status"] == second["status"] == "in_progress"
    # Still exactly one row for that playbook.
    stored = [i for i in _playbooks(client, auth_headers, 5)["items"] if i["code"] == code]
    assert len(stored) == 1


def test_unknown_recommendation_is_rejected(client, auth_headers):
    response = client.patch(
        "/api/v1/customers/5/recommendations/does_not_exist",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_unknown_status_is_rejected(client, auth_headers):
    code = _first_code(_playbooks(client, auth_headers, 5))
    response = client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "shipped"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_extra_fields_are_rejected(client, auth_headers):
    """A status change must not be able to smuggle analytical fields."""
    code = _first_code(_playbooks(client, auth_headers, 5))
    response = client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "done", "riskScore": 0},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_unknown_customer_is_not_found(client, auth_headers):
    response = client.get("/api/v1/customers/99999/recommendations", headers=auth_headers)
    assert response.status_code == 404


def test_endpoints_require_authentication(client):
    assert client.get("/api/v1/customers/5/recommendations").status_code == 401
    assert client.patch(
        "/api/v1/customers/5/recommendations/overdue_renewal", json={"status": "done"}
    ).status_code == 401


def test_status_does_not_change_the_analysis(client, auth_headers):
    """A workflow status must never move a score, an exposure or the settings."""
    before_customer = client.get("/api/v1/customers/5", headers=auth_headers).json()
    before_summary = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    before_settings = client.get("/api/v1/model/settings", headers=auth_headers).json()

    code = _first_code(_playbooks(client, auth_headers, 5))
    client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "done"},
        headers=auth_headers,
    )

    after_customer = client.get("/api/v1/customers/5", headers=auth_headers).json()
    after_summary = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    after_settings = client.get("/api/v1/model/settings", headers=auth_headers).json()

    assert after_customer["riskScore"] == before_customer["riskScore"]
    assert after_customer["riskCategory"] == before_customer["riskCategory"]
    assert after_customer["revenueAtRisk"] == before_customer["revenueAtRisk"]
    assert after_summary["customers"] == before_summary["customers"]
    assert after_summary["revenue"] == before_summary["revenue"]
    assert after_settings["settings"] == before_settings["settings"]
    # The generation is untouched too: a status is not a recalculation.
    assert after_summary["generation"] == before_summary["generation"]


def test_status_survives_a_recalculation(client, auth_headers):
    """The reason the table is not keyed by generation.

    A recalculation republishes a generation; if the status were tied to it the
    operator's work would silently vanish.
    """
    code = _first_code(_playbooks(client, auth_headers, 5))
    client.patch(
        f"/api/v1/customers/5/recommendations/{code}",
        json={"status": "in_progress"},
        headers=auth_headers,
    )
    before = client.get("/api/v1/analytics/summary", headers=auth_headers).json()

    # Change a model setting, which publishes a new generation.
    client.patch("/api/v1/model/settings", json={"horizonDays": 45}, headers=auth_headers)
    after = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert after["generation"] != before["generation"], "recalculation must bump the generation"

    stored = next(i for i in _playbooks(client, auth_headers, 5)["items"] if i["code"] == code)
    assert stored["status"] == "in_progress", "status must survive a recalculation"


def test_recommendation_list_matches_the_customer_payload(client, auth_headers):
    """The playbook list must not invent or drop recommendations."""
    detail = client.get("/api/v1/customers/5", headers=auth_headers).json()
    payload = _playbooks(client, auth_headers, 5)
    assert [i["code"] for i in payload["items"]] == [r["code"] for r in detail["recommendations"]]
    for item in payload["items"]:
        original = next(r for r in detail["recommendations"] if r["code"] == item["code"])
        assert item["title"] == original["title"]
        assert item["detail"] == original["detail"]
