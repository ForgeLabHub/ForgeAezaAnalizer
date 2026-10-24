"""Tests for the scenario, quality, priority and export views.

These features are additive views over the published calculation.  The tests
pin the properties the task requires: scenarios are isolated, nothing is
invented, unknown stays unknown, and the export matches the API.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from pathlib import Path

import pytest

from backend.app.api.routes_export import _safe, row_for
from backend.app.domain import insights

SNAPSHOT = Path(__file__).resolve().parents[2] / "dataset" / "data.json"
NOW = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)


def _source() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ scenarios


def test_scenario_rejects_parameters_it_must_not_touch():
    """A scenario may only move model parameters, never data."""
    for forbidden in ("balance", "price", "status", "services", "source"):
        with pytest.raises(insights.ScenarioError):
            insights.ScenarioDefinition("x", {forbidden: 1}).cleaned()


def test_scenario_accepts_only_the_allowed_parameters():
    definition = insights.ScenarioDefinition(
        "x", {"weights": {"expiry_proximity": 1.0}, "failedRenewalWindowDays": None}
    )
    assert definition.cleaned()["failedRenewalWindowDays"] is None


def test_weights_merge_instead_of_replacing():
    base = {"weights": {"a": 1.0, "b": 2.0}, "horizonDays": 30}
    result = insights.apply_overrides(base, {"weights": {"a": 5.0}})
    assert result["weights"] == {"a": 5.0, "b": 2.0}
    assert result["horizonDays"] == 30


def test_apply_overrides_does_not_mutate_the_base():
    base = {"weights": {"a": 1.0}}
    insights.apply_overrides(base, {"weights": {"a": 9.0}, "horizonDays": 7})
    assert base == {"weights": {"a": 1.0}}


def test_null_window_is_preserved_not_dropped():
    """Null means "whole snapshot"; it must not be read as "unchanged"."""
    base = {"weights": {}, "failedRenewalWindowDays": 90}
    result = insights.apply_overrides(base, {"failedRenewalWindowDays": None})
    assert "failedRenewalWindowDays" in result and result["failedRenewalWindowDays"] is None


def test_compare_does_not_divide_by_zero():
    comparison = insights.compare(
        {"customers": {"highRisk": 0}, "revenue": {"revenueAtRiskCents": 0}},
        {"customers": {"highRisk": 2}, "revenue": {"revenueAtRiskCents": 500}},
    )
    assert comparison["highRiskCustomers"]["absolute"] == 2
    assert comparison["highRiskCustomers"]["relative"] is None
    assert comparison["revenueAtRiskCents"]["relative"] is None


def test_customer_changes_reports_movement():
    baseline = [{"id": 1, "email": "a@x", "riskScore": 71.4, "riskCategory": "high"}]
    scenario = [{"id": 1, "email": "a@x", "riskScore": 61.5, "riskCategory": "medium"}]
    changes = insights.customer_changes(baseline, scenario)
    assert len(changes) == 1
    assert changes[0]["categoryChanged"] is True
    assert changes[0]["scoreBefore"] == 71.4 and changes[0]["scoreAfter"] == 61.5


def test_customer_changes_omits_unmoved_customers():
    same = [{"id": 1, "riskScore": 50.0, "riskCategory": "medium"}]
    assert insights.customer_changes(same, same) == []


def test_factor_availability_detects_a_lost_factor():
    """The window can turn a measured factor into an unknown one."""
    baseline = [{"id": 1, "services": [{"factors": [
        {"key": "renewal_failure_rate", "available": True}]}]}]
    scenario = [{"id": 1, "services": [{"factors": [
        {"key": "renewal_failure_rate", "available": False}]}]}]
    result = insights.factor_availability(baseline, scenario)
    assert result["renewal_failure_rate"]["becameUnknown"] == 1


# -------------------------------------------------------------------- quality


def test_quality_audit_is_read_only():
    source = _source()
    before = json.dumps(source, sort_keys=True)
    insights.inspect_source(source, as_of=NOW)
    assert json.dumps(source, sort_keys=True) == before


def test_quality_flags_a_dangling_owner():
    source = _source()
    source["services"][0]["ownerId"] = 999_999
    report = insights.inspect_source(source, as_of=NOW)
    assert any(issue["code"] == "unknown_owner" for issue in report["issues"])
    assert report["counts"]["critical"] >= 1


def test_quality_flags_a_negative_balance():
    source = _source()
    source["accounts"][0]["balance"] = -1
    report = insights.inspect_source(source, as_of=NOW)
    assert any(issue["code"] == "negative_amount" for issue in report["issues"])


def test_quality_flags_a_missing_amount_without_calling_it_zero():
    source = _source()
    source["accounts"][0]["bonusBalance"] = None
    report = insights.inspect_source(source, as_of=NOW)
    issue = next(i for i in report["issues"] if i["code"] == "missing_money_field")
    assert source["accounts"][0]["id"] in issue["records"]


def test_quality_flags_lifecycle_inconsistency():
    """prolong_wait past the documented grace period contradicts the lifecycle."""
    report = insights.inspect_source(_source(), as_of=NOW)
    issue = next(i for i in report["issues"] if i["code"] == "lifecycle_inconsistent")
    assert issue["level"] == "warning"
    assert issue["count"] == 6


def test_quality_does_not_claim_balance_ledger_reconciliation():
    """The README says balances are not derived from transactions."""
    report = insights.inspect_source(_source(), as_of=NOW)
    assert "не выводятся" in report["note"]


# ------------------------------------------------------------------- priority


def test_priority_keeps_every_applicable_reason():
    customer = {
        "id": 1, "riskCategory": "high", "overdueServiceCount": 2,
        "lifecycleInconsistentCount": 1,
        "exposureByHorizon": [{"horizonDays": 30, "revenueAtRisk": {"cents": 100}}],
    }
    categories = insights.priority_for(customer, horizon_days=30, quality_ids={1})
    assert "operational_attention" in categories
    assert "high_risk_with_exposure" in categories
    assert "data_quality_review" in categories


def test_high_risk_without_exposure_is_a_different_category():
    customer = {
        "id": 2, "riskCategory": "high",
        "exposureByHorizon": [{"horizonDays": 30, "revenueAtRisk": {"cents": 0}}],
    }
    categories = insights.priority_for(customer, horizon_days=30, quality_ids=set())
    assert categories == ["high_risk_review"]


def test_priority_falls_back_to_normal_review():
    customer = {"id": 3, "riskCategory": "medium", "exposureByHorizon": []}
    assert insights.priority_for(customer, horizon_days=30, quality_ids=set()) == ["normal_review"]


def test_urgency_orders_lifecycle_above_overdue():
    worse = {"lifecycleInconsistentCount": 1, "overdueServiceCount": 1, "riskCategory": "high"}
    better = {"lifecycleInconsistentCount": 0, "overdueServiceCount": 1, "riskCategory": "high"}
    assert insights.urgency_rank(worse) < insights.urgency_rank(better)


# --------------------------------------------------------------------- export


def test_csv_escapes_formula_prefixes():
    """A spreadsheet must not execute a value that came from the data."""
    for value in ("=cmd|calc", "+1+1", "-2+3", "@SUM(A1)"):
        assert _safe(value).startswith("'")


def test_csv_leaves_ordinary_text_alone():
    assert _safe("user-0001@example.test") == "user-0001@example.test"
    assert _safe("Кириллица") == "Кириллица"
    assert _safe(None) == ""


def test_csv_row_keeps_unknown_money_unknown():
    payload = {"id": 1, "email": "a@x", "bonusBalance": {"cents": None, "eur": None}}
    row = row_for(payload)
    assert row["bonusBalanceCents"] is None
    assert row["bonusBalanceEur"] is None


def test_csv_row_uses_horizon_exposure():
    payload = {
        "id": 1,
        "exposureByHorizon": [
            {"horizonDays": 7, "revenueAtRisk": {"cents": 10}},
            {"horizonDays": 30, "revenueAtRisk": {"cents": 20}},
            {"horizonDays": 90, "revenueAtRisk": {"cents": 30}},
        ],
    }
    row = row_for(payload)
    assert (row["exposure7dCents"], row["exposure30dCents"], row["exposure90dCents"]) == (10, 20, 30)


def test_csv_writer_round_trips_through_a_parser():
    """Quoting, separators and newlines must survive a real CSV read."""
    payload = {"id": 1, "email": 'weird,"quoted"@x', "topReasons": ["line1\nline2", "a;b"]}
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(row_for(payload)), lineterminator="\r\n")
    writer.writeheader()
    writer.writerow({k: _safe(v) for k, v in row_for(payload).items()})
    buffer.seek(0)
    rows = list(csv.DictReader(buffer))
    assert len(rows) == 1
    assert rows[0]["email"] == 'weird,"quoted"@x'
    assert "line1\nline2" in rows[0]["topReasons"]


def _export_rows(client, headers, query: str = "") -> list[dict]:
    response = client.get(f"/api/v1/export/customers.csv{query}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(body)))


def test_export_body_matches_the_customer_list(client, auth_headers):
    """The file and the interface must not be able to disagree."""
    listed = client.get("/api/v1/customers?pageSize=100", headers=auth_headers).json()
    rows = _export_rows(client, auth_headers)
    assert [row["id"] for row in rows] == [str(item["id"]) for item in listed["items"]]


def test_export_row_count_is_the_filtered_selection(client, auth_headers):
    """``X-Export-Rows`` must describe the export, not the whole customer base."""
    listed = client.get("/api/v1/customers?pageSize=100", headers=auth_headers).json()
    total = listed["total"]
    # The fixture gives categories in a repeating pattern, so a filter exists
    # that is a strict, non-empty subset of the whole selection.
    for category in ("high", "low"):
        filtered = client.get(
            f"/api/v1/customers?pageSize=100&riskCategory={category}", headers=auth_headers
        ).json()
        if not filtered["items"] or filtered["total"] == total:
            continue
        response = client.get(
            f"/api/v1/export/customers.csv?riskCategory={category}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert int(response.headers["X-Export-Rows"]) == filtered["total"]
        assert len(rows) == filtered["total"]
        assert filtered["total"] < total, "the filter must actually narrow the selection"
        return
    pytest.skip("fixture does not produce a narrowing filter")


def test_export_streams_across_pages(client, auth_headers):
    """Paging must not drop or duplicate rows, whatever the page size."""
    listed = client.get("/api/v1/customers?pageSize=100", headers=auth_headers).json()
    whole = _export_rows(client, auth_headers)
    assert len(whole) == listed["total"]
    for page_size in (1, 2, 3):
        paged = _export_rows(client, auth_headers, f"?pageSize={page_size}")
        assert [row["id"] for row in paged] == [row["id"] for row in whole]


def test_export_is_a_stream_not_a_buffer(client, auth_headers):
    """The response must be a stream so memory stays bounded by one page."""
    response = client.get("/api/v1/export/customers.csv?pageSize=1", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    # A streamed body has no reliable Content-Length up front.
    assert "content-length" not in {k.lower() for k in response.headers}


def test_export_requires_authentication(client):
    assert client.get("/api/v1/export/customers.csv").status_code == 401
