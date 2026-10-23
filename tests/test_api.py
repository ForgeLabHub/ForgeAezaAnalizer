"""End-to-end API tests against the real organiser dataset."""

from __future__ import annotations

import pytest


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_import_reports_real_counts(imported_client):
    body = imported_client.post("/api/import", json={}).json()
    assert body["accounts"] == 10
    assert body["services"] == 30
    assert body["transactions"] == 100
    assert body["rejected"] == []
    assert body["source_sha256"]


def test_dashboard_reflects_real_data(imported_client):
    data = imported_client.get("/api/dashboard").json()
    assert data["counts"] == {"accounts": 10, "services": 30, "transactions": 100}
    assert sum(data["service_status"].values()) == 30
    assert data["revenue_at_risk_eur"] is not None
    # Bands must be the case-specified low/medium/high thresholds.
    assert [b["level"] for b in data["risk_bands"]] == ["low", "medium", "high"]
    assert data["risk_bands"][1]["min"] == 35


def test_customers_endpoint_returns_real_rows(imported_client):
    data = imported_client.get("/api/customers").json()
    assert data["total"] == 10
    emails = {i["email"] for i in data["items"]}
    assert "user-0001@example.test" in emails
    for item in data["items"]:
        assert item["risk_level"] in {"low", "medium", "high", "churned", "unknown"}


def test_customer_search_and_filter(imported_client):
    found = imported_client.get("/api/customers", params={"search": "0003"}).json()
    assert found["total"] == 1
    assert found["items"][0]["account_id"] == 3

    high = imported_client.get("/api/customers", params={"level": "high"}).json()
    assert all(i["risk_level"] == "high" for i in high["items"])


def test_customer_sorting(imported_client):
    asc = imported_client.get(
        "/api/customers", params={"sort": "risk_score", "order": "asc"}
    ).json()["items"]
    scores = [i["risk_score"] for i in asc]
    assert scores == sorted(scores)


def test_customer_detail_has_services_and_reasons(imported_client):
    detail = imported_client.get("/api/customers/7").json()
    assert detail["account_id"] == 7
    assert len(detail["services"]) == 3
    assert detail["reasons"]
    for service in detail["services"]:
        assert "factors" in service
        for factor in service["factors"]:
            assert factor["value"] is None or 0 <= factor["value"] <= 1


def test_customer_detail_404(imported_client):
    assert imported_client.get("/api/customers/9999").status_code == 404


def test_services_endpoint(imported_client):
    data = imported_client.get("/api/services").json()
    assert data["total"] == 30
    statuses = {i["status"] for i in data["items"]}
    assert statuses <= {"active", "blocked", "suspended", "prolong_wait", "deleted"}


def test_weight_change_alters_scores(imported_client):
    before = imported_client.get("/api/customers/1").json()["risk_score"]
    imported_client.put("/api/weights", json={"weights": {
        "expiry_proximity": 1.0, "autoprolong_off": 0.0,
        "insufficient_balance": 0.0, "failed_renewals": 0.0, "status_risk": 0.0,
    }})
    after = imported_client.get("/api/customers/1").json()["risk_score"]
    assert before != after


def test_invalid_weights_rejected(imported_client):
    response = imported_client.put("/api/weights", json={"weights": {"nope": 1}})
    assert response.status_code == 400
    assert "unknown weight keys" in response.json()["detail"]


def test_reimport_does_not_duplicate(imported_client):
    for _ in range(3):
        imported_client.post("/api/import", json={})
    data = imported_client.get("/api/dashboard").json()
    assert data["counts"] == {"accounts": 10, "services": 30, "transactions": 100}


def test_bad_import_returns_400_and_keeps_data(imported_client):
    response = imported_client.post("/api/import", json={"source": "/tmp/nope.zip"})
    assert response.status_code == 400
    data = imported_client.get("/api/dashboard").json()
    assert data["counts"] == {"accounts": 10, "services": 30, "transactions": 100}


def test_audit_endpoint(imported_client):
    audit = imported_client.get("/api/audit").json()
    assert audit["row_counts"] == {"accounts": 10, "services": 30, "transactions": 100}
    assert audit["integrity"]["services_without_account"] == 0
    assert audit["integrity"]["transactions_without_service"] == 0


def test_meta_exposes_source_digest(imported_client):
    meta = imported_client.get("/api/meta").json()
    assert meta["source_sha256"]
    assert meta["last_import"]["accounts"] == 10


def test_horizon_changes_eligible_renewals(imported_client):
    narrow = imported_client.get("/api/dashboard", params={"horizon_days": 1}).json()
    wide = imported_client.get("/api/dashboard", params={"horizon_days": 365}).json()
    assert wide["eligible_renewal_cents"] >= narrow["eligible_renewal_cents"]


def test_index_page_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Aéza" in response.text
