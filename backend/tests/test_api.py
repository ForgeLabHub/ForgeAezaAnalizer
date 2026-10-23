"""API tests: auth, customers, analytics, settings, import, metrics, OpenAPI."""

from __future__ import annotations

import copy

import pytest


# --------------------------------------------------------------------------- auth


def test_login_success_returns_token(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_login_wrong_password_is_401(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "nope"}
    )
    assert response.status_code == 401


def test_login_unknown_user_is_401_without_enumeration(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "ghost@aeza.test", "password": "nope"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный email или пароль"


def test_protected_routes_require_auth(client):
    for path in (
        "/api/v1/customers",
        "/api/v1/customers/1",
        "/api/v1/analytics/summary",
        "/api/v1/model/settings",
        "/api/v1/source/snapshot",
    ):
        assert client.get(path).status_code == 401, path


def test_me_returns_current_user(client, auth_headers):
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "analyst@aeza.test"


def test_invalid_token_is_401(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


def test_logout_is_authenticated_and_204(client, auth_headers):
    assert client.post("/api/v1/auth/logout", headers=auth_headers).status_code == 204
    assert client.post("/api/v1/auth/logout").status_code == 401


# --------------------------------------------------------------------------- customers


def test_customer_list_paginates(client, auth_headers):
    response = client.get("/api/v1/customers?page=1&pageSize=3", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 10
    assert len(body["items"]) == 3
    assert body["pages"] == 4


def test_customer_list_search_by_email(client, auth_headers):
    response = client.get("/api/v1/customers?search=user-0004", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == 4


def test_customer_list_search_by_id(client, auth_headers):
    response = client.get("/api/v1/customers?search=7", headers=auth_headers)
    assert any(item["id"] == 7 for item in response.json()["items"])


@pytest.mark.parametrize("field", ["id", "email", "riskScore", "balance", "totalReplenished"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_customer_sorting_changes_order(client, auth_headers, field, direction):
    response = client.get(
        f"/api/v1/customers?sortBy={field}&sortDir={direction}&pageSize=200", headers=auth_headers
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 10

    if field == "riskScore":
        values = [(i["riskScore"] is None, -(i["riskScore"] or 0)) for i in items]
    elif field == "email":
        values = [i["email"].lower() for i in items]
    elif field == "balance":
        values = [i["balance"]["cents"] for i in items]
    elif field == "totalReplenished":
        values = [i["totalReplenished"]["cents"] for i in items]
    else:
        values = [i["id"] for i in items]

    expected = sorted(values, reverse=(direction == "desc"))
    if field == "riskScore":
        expected = sorted(values, reverse=(direction == "asc"))
    assert values == expected, f"{field} {direction}"


def test_numeric_sorting_is_not_lexicographic(client, auth_headers):
    # Balance 91506 cents vs 3478 cents: string sort would put "91506" first for
    # descending but would mis-order values of different digit lengths ascending.
    asc = client.get(
        "/api/v1/customers?sortBy=balance&sortDir=asc&pageSize=200", headers=auth_headers
    ).json()["items"]
    cents = [i["balance"]["cents"] for i in asc]
    assert cents == sorted(cents)
    assert cents[0] < 10_000 < cents[-1]


def test_risk_category_filter(client, auth_headers):
    response = client.get("/api/v1/customers?riskCategory=high&pageSize=200", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(i["riskCategory"] == "high" for i in items)


def test_service_status_filter(client, auth_headers):
    response = client.get(
        "/api/v1/customers?serviceStatus=prolong_wait&pageSize=200", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["items"]


def test_invalid_sort_field_is_400(client, auth_headers):
    assert client.get("/api/v1/customers?sortBy=secret", headers=auth_headers).status_code == 400


def test_invalid_risk_category_is_400(client, auth_headers):
    assert (
        client.get("/api/v1/customers?riskCategory=bogus", headers=auth_headers).status_code == 400
    )


def test_customer_detail_shape(client, auth_headers):
    response = client.get("/api/v1/customers/1", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert len(body["services"]) == 3
    for service in body["services"]:
        assert "riskScore" in service
        assert "reasons" in service
        assert "factors" in service
        assert service["price"]["cents"] >= 0
        assert service["price"]["eur"]


def test_customer_detail_unknown_id_is_404(client, auth_headers):
    assert client.get("/api/v1/customers/9999", headers=auth_headers).status_code == 404


def test_customer_detail_separates_current_state_from_forecast(client, auth_headers):
    body = client.get("/api/v1/customers/3", headers=auth_headers).json()
    # Customer 3 owns a deleted service; it must be reported as concluded, not forecast.
    deleted = [s for s in body["services"] if s["status"] == "deleted"]
    assert deleted
    assert all(s["eligibleForForecast"] is False for s in deleted)
    assert all(s["riskScore"] is None for s in deleted)
    assert deleted[0]["stateNote"]


# --------------------------------------------------------------------------- analytics


def test_summary_reports_honest_metadata(client, auth_headers):
    body = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert body["customers"]["total"] == 10
    assert body["services"]["total"] == 30
    assert body["services"]["open"] == 18
    assert body["services"]["concluded"] == 12
    assert body["historyAvailable"] is False
    assert body["model"]["calibrated"] is False
    assert "не является" in body["model"]["note"] or "не откалиброван" in body["model"]["note"]


def test_summary_revenue_is_separate_from_balances(client, auth_headers):
    body = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert body["revenue"]["revenueAtRiskCents"] <= body["revenue"]["upcomingRenewalsCents"]
    assert body["revenue"]["historicalReplenishedCents"] > 0
    # Historical top-ups must never be folded into revenue at risk.
    assert body["revenue"]["revenueAtRiskCents"] != body["revenue"]["historicalReplenishedCents"]


def test_summary_risk_distribution_sums_to_customer_total(client, auth_headers):
    body = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert sum(body["customers"]["byCategory"].values()) == body["customers"]["total"]


def test_summary_reasons_are_labelled(client, auth_headers):
    body = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert body["topRiskReasons"]
    assert all(r["label"] and r["count"] > 0 for r in body["topRiskReasons"])


# --------------------------------------------------------------------------- settings


def test_settings_default_and_reset(client, auth_headers):
    body = client.get("/api/v1/model/settings", headers=auth_headers).json()
    assert body["isDefault"] is True
    assert body["settings"]["horizonDays"] == 30
    assert len(body["factors"]) >= 5
    assert all(f["normalization"] for f in body["factors"])


def test_patch_settings_persists(client, auth_headers):
    response = client.patch(
        "/api/v1/model/settings",
        json={"horizonDays": 60, "weights": {"expiry_proximity": 9.0}},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["isDefault"] is False

    reread = client.get("/api/v1/model/settings", headers=auth_headers).json()
    assert reread["settings"]["horizonDays"] == 60
    assert reread["settings"]["weights"]["expiry_proximity"] == 9.0


def test_patch_settings_rejects_negative_weight(client, auth_headers):
    response = client.patch(
        "/api/v1/model/settings", json={"weights": {"expiry_proximity": -1}}, headers=auth_headers
    )
    assert response.status_code == 422


def test_patch_settings_rejects_unknown_factor(client, auth_headers):
    response = client.patch(
        "/api/v1/model/settings", json={"weights": {"not_a_factor": 1}}, headers=auth_headers
    )
    assert response.status_code == 422


def test_patch_settings_rejects_inverted_thresholds(client, auth_headers):
    response = client.patch(
        "/api/v1/model/settings", json={"lowMax": 80, "mediumMax": 50}, headers=auth_headers
    )
    assert response.status_code == 422


def test_weight_change_really_changes_results(client, auth_headers):
    before = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    factors = client.get("/api/v1/model/settings", headers=auth_headers).json()["factors"]

    # Concentrate all weight on autoprolong, which many services have disabled.
    zeroed = {f["key"]: 0.0 for f in factors}
    zeroed["auto_prolong_disabled"] = 10.0
    assert client.patch(
        "/api/v1/model/settings", json={"weights": zeroed}, headers=auth_headers
    ).status_code == 200

    after = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert after["customers"]["byCategory"] != before["customers"]["byCategory"]

    client.post("/api/v1/model/settings/reset", headers=auth_headers)


def test_horizon_change_changes_revenue(client, auth_headers):
    client.post("/api/v1/model/settings/reset", headers=auth_headers)
    short = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    client.patch("/api/v1/model/settings", json={"horizonDays": 365}, headers=auth_headers)
    long = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert long["revenue"]["upcomingRenewalsCents"] >= short["revenue"]["upcomingRenewalsCents"]
    assert long["revenue"]["upcomingRenewalsCents"] > short["revenue"]["upcomingRenewalsCents"]
    client.post("/api/v1/model/settings/reset", headers=auth_headers)


# --------------------------------------------------------------------------- source / import


def test_snapshot_status(client, auth_headers):
    body = client.get("/api/v1/source/snapshot", headers=auth_headers).json()
    assert body["counts"] == {"accounts": 10, "services": 30, "transactions": 100}
    assert body["lastImport"] is not None


def test_import_valid_snapshot_is_idempotent(client, auth_headers, snapshot_payload):
    for _ in range(2):
        response = client.put(
            "/api/v1/source/snapshot", json=snapshot_payload, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        report = response.json()["report"]
        assert report["accepted"] == {"accounts": 10, "services": 30, "transactions": 100}
        assert report["rejected"] == 0

    counts = client.get("/api/v1/source/snapshot", headers=auth_headers).json()["counts"]
    assert counts == {"accounts": 10, "services": 30, "transactions": 100}


def test_import_rejects_negative_money_and_keeps_previous_data(
    client, auth_headers, snapshot_payload
):
    broken = copy.deepcopy(snapshot_payload)
    broken["accounts"][0]["balance"] = -1
    response = client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers)
    assert response.status_code == 422

    # Atomicity: the previous dataset must still be intact.
    counts = client.get("/api/v1/source/snapshot", headers=auth_headers).json()["counts"]
    assert counts == {"accounts": 10, "services": 30, "transactions": 100}


def test_import_rejects_dangling_foreign_key(client, auth_headers, snapshot_payload):
    broken = copy.deepcopy(snapshot_payload)
    broken["services"][0]["ownerId"] = 999
    response = client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers)
    assert response.status_code == 422
    counts = client.get("/api/v1/source/snapshot", headers=auth_headers).json()["counts"]
    assert counts["accounts"] == 10


def test_import_rejects_duplicate_ids(client, auth_headers, snapshot_payload):
    broken = copy.deepcopy(snapshot_payload)
    broken["accounts"][1]["id"] = broken["accounts"][0]["id"]
    response = client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers)
    assert response.status_code == 422


def test_import_rejects_wrong_type(client, auth_headers):
    response = client.put("/api/v1/source/snapshot", json=[], headers=auth_headers)
    assert response.status_code == 422


def test_import_then_analytics_reflects_new_data(client, auth_headers, snapshot_payload):
    reduced = copy.deepcopy(snapshot_payload)
    keep = {1, 2, 3}
    reduced["services"] = [s for s in reduced["services"] if s["id"] in keep]
    reduced["transactions"] = [t for t in reduced["transactions"] if t["serviceId"] in keep]
    reduced["accounts"] = [a for a in reduced["accounts"] if a["id"] in {1, 2, 3}]

    assert (
        client.put("/api/v1/source/snapshot", json=reduced, headers=auth_headers).status_code == 200
    )
    summary = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert summary["customers"]["total"] == 3
    assert summary["services"]["total"] == 3

    # Restore the full dataset for subsequent tests.
    client.put("/api/v1/source/snapshot", json=snapshot_payload, headers=auth_headers)
    assert (
        client.get("/api/v1/analytics/summary", headers=auth_headers).json()["customers"]["total"]
        == 10
    )


# --------------------------------------------------------------------------- metrics / openapi


def test_metrics_endpoint_exposes_expected_series(client, auth_headers):
    client.get("/api/v1/analytics/summary", headers=auth_headers)
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "aeza_customers_total" in text
    assert "aeza_services_total" in text
    assert "aeza_customers_by_risk_category" in text
    assert "aeza_revenue_at_risk_eur" in text


def test_metrics_contain_no_personal_data(client, auth_headers):
    client.get("/api/v1/customers", headers=auth_headers)
    text = client.get("/metrics").text
    assert "example.test" not in text
    assert "user-000" not in text


def test_openapi_matches_implemented_routes(client):
    spec = client.get("/api/v1/openapi.json").json()
    paths = set(spec["paths"])
    expected = {
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/customers",
        "/api/v1/customers/{customer_id}",
        "/api/v1/analytics/summary",
        "/api/v1/model/settings",
        "/api/v1/source/snapshot",
        "/metrics",
        "/api/v1/docs",
    }
    # /api/v1/docs is the Swagger UI itself; the spec covers the data routes.
    missing = expected - paths - {"/api/v1/docs"}
    assert not missing, f"missing from OpenAPI: {missing}"


def test_openapi_documents_bearer_auth(client):
    spec = client.get("/api/v1/openapi.json").json()
    assert "securitySchemes" in spec["components"]
