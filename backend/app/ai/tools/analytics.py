"""Read-only aggregate analytics tools.

Summary, model settings, data quality and the priority queue.  As with the
customer tools, everything is read from the published generation — the AI never
triggers a recalculation.
"""

from __future__ import annotations

from backend.app.domain import insights
from backend.app.storage import Storage


def analytics_summary(storage: Storage) -> dict:
    """Portfolio-level counts, revenue exposure and model provenance."""

    summary = storage.summary()
    return {
        "horizonDays": summary["horizonDays"],
        "generatedAt": summary["generatedAt"],
        "customers": summary["customers"],
        "services": summary["services"],
        "revenue": summary["revenue"],
        "topRiskReasons": summary["topRiskReasons"],
        "upcomingRenewals": summary["upcomingRenewals"][:5],
        "historyAvailable": summary["historyAvailable"],
        "historyNote": summary["historyNote"],
        "model": summary["model"],
        "version": summary["version"],
    }


def model_settings(storage: Storage) -> dict:
    """Active weights, thresholds and the factor catalogue."""

    generation = storage.summary()["generation"]
    payload = storage.model(generation)
    definition = storage.summary(generation)["modelDefinition"]
    return {
        "settings": payload["settings"],
        "factors": definition["factors"],
        "isDefault": payload["settings"] == definition["defaults"],
        "engineVersion": storage.summary(generation)["engineVersion"],
        "updatedAt": payload.get("updatedAt"),
    }


def quality_report(storage: Storage) -> dict:
    """The data-quality audit of the raw snapshot."""

    state = storage.load()
    report = insights.inspect_source(state.source, as_of=state.as_of)
    return {
        "counts": report["counts"],
        "issues": [
            {"level": issue["level"], "code": issue["code"], "message": issue["message"],
             "records": issue.get("records", [])}
            for issue in report["issues"]
        ],
    }


def priority_queue(storage: Storage, *, horizon_days: int = 30, limit: int = 10) -> list[dict]:
    """Operational priority rows, ordered by urgency."""

    state = storage.load()
    quality = insights.inspect_source(state.source, as_of=state.as_of)
    quality_ids = {
        record
        for issue in quality["issues"]
        if issue["code"] in ("missing_money_field", "negative_amount", "lifecycle_inconsistent")
        for record in issue["records"]
    }
    generation = storage.summary()["generation"]
    with storage.database.sessions() as session:
        from sqlalchemy import select

        from backend.app.db import CustomerRow

        rows = session.scalars(select(CustomerRow).where(CustomerRow.generation == generation)).all()
        payloads = [row.payload for row in rows]

    items = []
    for payload in payloads:
        exposure = next(
            (h for h in (payload.get("exposureByHorizon") or []) if h.get("horizonDays") == horizon_days),
            None,
        )
        items.append(
            {
                "id": payload["id"],
                "email": payload.get("email"),
                "riskScore": payload.get("riskScore"),
                "riskCategory": payload.get("riskCategory"),
                "revenueAtRiskOnHorizon": (exposure or {}).get("revenueAtRisk"),
                "overdueServiceCount": payload.get("overdueServiceCount"),
                "lifecycleInconsistentCount": payload.get("lifecycleInconsistentCount"),
                "categories": insights.priority_for(payload, horizon_days=horizon_days, quality_ids=quality_ids),
                "urgencyRank": insights.urgency_rank(payload),
            }
        )
    items.sort(key=lambda item: (item["urgencyRank"], item["id"]))
    return items[:limit]
