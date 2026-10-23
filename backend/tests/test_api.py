from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_stub_starts_auth_and_reports_missing_module(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 503
        assert client.get("/api/v1/docs").status_code == 200
        login = client.post("/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/analytics/summary", headers=headers).status_code == 503
        assert client.patch("/api/v1/model/settings", json={"horizonDays": 7}, headers=headers).status_code == 503
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/v1/customers", None), ("GET", "/api/v1/customers/1", None),
    ("GET", "/api/v1/analytics/summary", None), ("GET", "/api/v1/analytics/events", None),
    ("GET", "/api/v1/model/settings", None), ("GET", "/api/v1/source/snapshot", None),
    ("GET", "/api/v1/source/observations", None), ("POST", "/api/v1/auth/logout", None),
    ("PATCH", "/api/v1/model/settings", {"horizonDays": 7}),
    ("POST", "/api/v1/model/settings/reset", None), ("GET", "/metrics", None),
    ("PUT", "/api/v1/source/snapshot", {"accounts": [], "services": [], "transactions": []}),
])
def test_private_endpoints_require_auth(client, method, path, payload):
    assert client.request(method, path, json=payload).status_code == 401


def test_login_errors_do_not_enumerate_users(client):
    bodies = [client.post("/api/v1/auth/login", json={"email": email, "password": "bad"}).json()
        for email in ("analyst@aeza.test", "unknown@example.test")]
    assert bodies[0] == bodies[1]


def test_secret_not_echoed_on_validation_failure(client):
    response = client.post("/api/v1/auth/login", json={"email": "a", "password": "private-password", "extra": "private-password"})
    assert response.status_code == 422
    assert "private-password" not in response.text


def test_logout_revokes_only_current_session(client, auth_headers):
    other = client.post("/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"}).json()
    assert client.post("/api/v1/auth/logout", headers=auth_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 200


def test_reads_share_published_generation_without_calculation(client, auth_headers, analytics):
    calls = analytics.calls
    for path in ("/api/v1/customers?pageSize=3", "/api/v1/customers/1", "/api/v1/analytics/summary",
                 "/api/v1/model/settings", "/api/v1/source/snapshot"):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["generation"] == 1
        assert response.headers["X-Analysis-Generation"] == "1"
    assert analytics.calls == calls


@pytest.mark.parametrize("field", ["id", "email", "balance", "totalReplenished", "riskScore"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sql_sorting_with_stable_ties_and_nulls_last(client, auth_headers, field, direction):
    body = client.get(f"/api/v1/customers?sortBy={field}&sortDir={direction}&pageSize=200", headers=auth_headers).json()
    items = body["items"]
    def value(item):
        raw = item[field]
        if field in {"balance", "totalReplenished"}:
            raw = raw["cents"]
        return raw.lower() if isinstance(raw, str) else raw
    values = [value(item) for item in items if value(item) is not None]
    assert values == sorted(values, reverse=direction == "desc")
    for left, right in zip(items, items[1:]):
        if value(left) == value(right):
            assert left["id"] < right["id"]
    nulls = [value(item) is None for item in items]
    assert nulls == sorted(nulls)


def test_sql_search_filters_and_pagination(client, auth_headers):
    page = client.get("/api/v1/customers?pageSize=3", headers=auth_headers).json()
    assert page["total"] == 10 and page["pages"] == 4 and len(page["items"]) == 3
    found = client.get("/api/v1/customers?search=user-0004", headers=auth_headers).json()["items"]
    assert [item["id"] for item in found] == [4]
    assert client.get("/api/v1/customers?search=%", headers=auth_headers).json()["items"] == []
    items = client.get("/api/v1/customers?riskCategory=high", headers=auth_headers).json()["items"]
    assert items and all(item["riskCategory"] == "high" for item in items)
    assert client.get("/api/v1/customers?serviceStatus=prolong_wait", headers=auth_headers).json()["items"]


@pytest.mark.parametrize("query", ["sortBy=unknown", "riskCategory=unknown", "serviceStatus=unknown", "page=0", "pageSize=10000"])
def test_invalid_queries_are_422(client, auth_headers, query):
    assert client.get(f"/api/v1/customers?{query}", headers=auth_headers).status_code == 422


def test_missing_resources_are_404(client, auth_headers):
    assert client.get("/api/v1/customers/99999", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/analytics/summary?generation=999", headers=auth_headers).status_code == 404


@pytest.mark.parametrize("patch", [{"weights": {"unknown": 1}}, {"weights": {"fixture": -1}},
    {"weights": {"fixture": True}}, {"horizonDays": None}, {"lowMax": 80, "mediumMax": 10}])
def test_invalid_model_settings_never_publish(client, auth_headers, analytics, patch):
    calls = analytics.calls
    assert client.patch("/api/v1/model/settings", json=patch, headers=auth_headers).status_code == 422
    assert analytics.calls == calls
    assert client.get("/api/v1/analytics/summary", headers=auth_headers).json()["generation"] == 1


def test_non_finite_weight_is_rejected_without_serialization_error(client, auth_headers):
    response = client.patch("/api/v1/model/settings", content='{"weights":{"fixture":NaN}}',
        headers={**auth_headers, "Content-Type": "application/json"})
    assert response.status_code == 422


def test_model_update_reset_and_generation_pinning(client, auth_headers):
    response = client.patch("/api/v1/model/settings", json={"horizonDays": 7, "expectedGeneration": 1}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["generation"] == 2
    assert response.json()["settings"]["horizonDays"] == 7
    old = client.get("/api/v1/model/settings?generation=1", headers=auth_headers).json()
    assert old["settings"]["horizonDays"] == 30
    assert client.get("/api/v1/customers?generation=1", headers=auth_headers).json()["generation"] == 1
    assert client.patch("/api/v1/model/settings", json={"horizonDays": 8, "expectedGeneration": 1}, headers=auth_headers).status_code == 409
    assert client.post("/api/v1/model/settings/reset", headers=auth_headers).json()["settings"]["horizonDays"] == 30


def test_metrics_read_published_result_without_summary_request(client, auth_headers):
    body = client.get("/metrics", headers=auth_headers).text
    assert "aeza_analysis_generation 1.0" in body
    assert "aeza_customers_total 10.0" in body
    assert "@example.test" not in body
    client.patch("/api/v1/model/settings", json={"horizonDays": 7}, headers=auth_headers)
    assert "aeza_analysis_generation 2.0" in client.get("/metrics", headers=auth_headers).text


def test_unmatched_route_metrics_do_not_store_requested_paths(client, auth_headers):
    client.get("/random-private-id")
    body = client.get("/metrics", headers=auth_headers).text
    assert 'route="unmatched"' in body
    assert "random-private-id" not in body


def test_openapi_describes_responses_and_all_frontend_paths(client):
    document = client.get("/api/v1/openapi.json").json()
    for path in ("/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout",
        "/api/v1/customers", "/api/v1/customers/{customer_id}", "/api/v1/analytics/summary",
        "/api/v1/model/settings", "/api/v1/model/settings/reset", "/api/v1/source/snapshot",
        "/api/v1/analytics/events", "/metrics"):
        assert path in document["paths"]
    schema = document["paths"]["/api/v1/customers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/CustomerPage")


# Every path the shipped frontend calls must be present in the published schema,
# otherwise the UI breaks at runtime while the OpenAPI document still looks fine.
FRONTEND_CALLS = (
    ("get", "/api/v1/analytics/summary"),
    ("get", "/api/v1/analytics/events"),
    ("get", "/api/v1/customers"),
    ("get", "/api/v1/customers/{customer_id}"),
    ("get", "/api/v1/priority"),
    ("get", "/api/v1/quality"),
    ("post", "/api/v1/scenarios/compare"),
    ("get", "/api/v1/model/settings"),
    ("patch", "/api/v1/model/settings"),
    ("post", "/api/v1/model/settings/reset"),
    ("get", "/api/v1/source/snapshot"),
    ("get", "/api/v1/source/observations"),
    ("get", "/api/v1/export/customers.csv"),
)


def test_openapi_covers_every_frontend_call(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    missing = [f"{m.upper()} {p}" for m, p in FRONTEND_CALLS if p not in paths or m not in paths[p]]
    assert missing == []


def test_openapi_documents_priority_query_parameters(client):
    parameters = client.get("/api/v1/openapi.json").json()["paths"]["/api/v1/priority"]["get"]["parameters"]
    names = {p["name"] for p in parameters}
    assert {"horizonDays", "category", "sortBy", "sortDir"} <= names
    sort_by = next(p for p in parameters if p["name"] == "sortBy")
    assert set(sort_by["schema"]["enum"]) == {"urgency", "riskScore", "exposure", "id"}


def test_removed_whatif_endpoint_is_not_published(client):
    # The scenario preview moved to POST /api/v1/scenarios/compare; the old
    # route must not linger in the schema, or clients keep calling a 404.
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/whatif" not in paths
