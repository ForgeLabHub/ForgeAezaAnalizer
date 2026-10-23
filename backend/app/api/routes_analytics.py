"""Analytics summary route."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, get_db
from app.domain.analytics import AnalyticsService
from app.domain.settings_store import load_settings
from app.metrics import ANALYTICS_DURATION, update_dataset_gauges

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", summary="Сводная аналитика по клиентской базе")
def summary(
    session: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> dict:
    """Aggregate KPIs: customers, services, risk distribution and revenue at risk.

    ``historyAvailable`` is reported explicitly as ``false`` because the source
    snapshot carries no churn history; the UI must not draw a fabricated trend
    line where the data does not support one.
    """

    with ANALYTICS_DURATION.labels(operation="summary").time():
        settings = load_settings(session)
        analytics = AnalyticsService(session, settings)
        payload = analytics.summary()
        update_dataset_gauges(
            summary=payload,
            customers_total=payload["customers"]["total"],
            services_total=payload["services"]["total"],
        )
    return payload
