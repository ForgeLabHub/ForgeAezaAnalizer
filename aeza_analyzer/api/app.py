"""FastAPI application: real dataset endpoints for the Aéza Analyzer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..analytics import DEFAULT_HORIZON_DAYS, AnalyticsService, FACTOR_TITLES, RISK_LEVEL_BANDS
from ..analytics.risk import DEFAULT_WEIGHTS
from ..config import settings
from ..db import StoreError, get_session_factory, init_db
from ..importer import ArchiveError, import_dataset
from ..money import cents_to_euros_str
from .schemas import ImportPayload, WeightsPayload

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Aéza Analyzer",
    description="Churn-risk and revenue-at-risk analytics on the organiser dataset.",
    version="1.0.0",
)


def _analytics() -> AnalyticsService:
    init_db()
    return AnalyticsService(get_session_factory()())


def _euro_fields(payload: dict) -> dict:
    """Attach euro-denominated mirrors of the canonical cent fields."""
    mapping = {
        "balance_cents": "balance_eur",
        "withdraw_balance_cents": "withdraw_balance_eur",
        "bonus_balance_cents": "bonus_balance_eur",
        "total_replenished_cents": "total_replenished_eur",
        "revenue_at_risk_cents": "revenue_at_risk_eur",
        "eligible_renewal_cents": "eligible_renewal_eur",
        "price_cents": "price_eur",
    }
    for cents_key, euro_key in mapping.items():
        if cents_key in payload:
            payload[euro_key] = cents_to_euros_str(payload[cents_key])
    return payload


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    analytics = _analytics()
    try:
        return {
            **analytics.meta(),
            "last_import": analytics.last_import(),
            "default_horizon_days": DEFAULT_HORIZON_DAYS,
        }
    finally:
        analytics.session.close()


@app.get("/api/weights")
def get_weights() -> dict:
    analytics = _analytics()
    try:
        return {
            "weights": analytics.get_weights(),
            "defaults": DEFAULT_WEIGHTS,
            "factors": FACTOR_TITLES,
        }
    finally:
        analytics.session.close()


@app.put("/api/weights")
def put_weights(payload: WeightsPayload) -> dict:
    analytics = _analytics()
    try:
        try:
            updated = analytics.set_weights(payload.weights)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        analytics.session.commit()
        return {"weights": updated}
    finally:
        analytics.session.close()


@app.post("/api/weights/reset")
def reset_weights() -> dict:
    analytics = _analytics()
    try:
        weights = analytics.reset_weights()
        analytics.session.commit()
        return {"weights": weights}
    finally:
        analytics.session.close()


@app.get("/api/dashboard")
def dashboard(horizon_days: int = Query(default=DEFAULT_HORIZON_DAYS, ge=1, le=365)) -> dict:
    analytics = _analytics()
    try:
        data = analytics.dashboard(horizon_days)
        data["revenue_at_risk_eur"] = cents_to_euros_str(data["revenue_at_risk_cents"])
        data["eligible_renewal_eur"] = cents_to_euros_str(data["eligible_renewal_cents"])
        data["risk_bands"] = [
            {"min": low, "max": high, "level": name} for low, high, name in RISK_LEVEL_BANDS
        ]
        return data
    finally:
        analytics.session.close()


@app.get("/api/customers")
def customers(
    horizon_days: int = Query(default=DEFAULT_HORIZON_DAYS, ge=1, le=365),
    search: str | None = None,
    level: str | None = None,
    sort: str = Query(default="risk_score"),
    order: str = Query(default="desc"),
) -> dict:
    analytics = _analytics()
    try:
        results = analytics.customer_risk(horizon_days=horizon_days)
        items = [c.as_dict() for c in results]

        if search:
            needle = search.lower()
            items = [i for i in items if needle in i["email"].lower()]
        if level:
            items = [i for i in items if i["risk_level"] == level]

        allowed_sort = {
            "risk_score",
            "revenue_at_risk_cents",
            "balance_cents",
            "account_id",
            "service_count",
        }
        if sort not in allowed_sort:
            raise HTTPException(status_code=400, detail=f"cannot sort by '{sort}'")
        reverse = order != "asc"
        items.sort(key=lambda i: i[sort], reverse=reverse)
        return {"total": len(items), "items": [_euro_fields(i) for i in items]}
    finally:
        analytics.session.close()


@app.get("/api/customers/{account_id}")
def customer_detail(
    account_id: int, horizon_days: int = Query(default=DEFAULT_HORIZON_DAYS, ge=1, le=365)
) -> dict:
    analytics = _analytics()
    try:
        results = analytics.customer_risk(horizon_days=horizon_days)
        match = next((c for c in results if c.account_id == account_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"account {account_id} not found")
        payload = match.as_dict(include_services=True)
        _euro_fields(payload)
        for item in payload["services"]:
            _euro_fields(item)
        return payload
    finally:
        analytics.session.close()


@app.get("/api/services")
def services(
    horizon_days: int = Query(default=DEFAULT_HORIZON_DAYS, ge=1, le=365),
    status: str | None = None,
) -> dict:
    analytics = _analytics()
    try:
        weights = analytics.get_weights()
        scores, _ = analytics._score_services(weights, horizon_days)
        items = [s.as_dict() for s in scores.values()]
        if status:
            items = [i for i in items if i["status"] == status]
        items.sort(key=lambda i: i["score"], reverse=True)
        for item in items:
            _euro_fields(item)
        return {"total": len(items), "items": items}
    finally:
        analytics.session.close()


@app.post("/api/import")
def run_import(body: ImportPayload | None = None) -> dict:
    body = body or ImportPayload()
    try:
        result = import_dataset(Path(body.source) if body.source else None)
    except (FileNotFoundError, ValueError, ArchiveError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "success",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        **result.as_dict(),
    }


@app.get("/api/audit")
def audit() -> dict:
    """Reproducible data profile of what is currently stored."""
    from ..audit import profile_store

    analytics = _analytics()
    try:
        return profile_store(analytics.session)
    finally:
        analytics.session.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(ValueError)
def _value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(StoreError)
def _store_error_handler(_request, exc: StoreError) -> JSONResponse:
    """A broken store is a server-side condition, not a bad request."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
