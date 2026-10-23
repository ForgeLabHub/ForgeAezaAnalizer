"""Customer listing and detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, get_db
from app.api.serializers import customer_detail_payload, customer_summary_payload
from app.domain.analytics import AnalyticsService
from app.domain.settings_store import load_settings
from app.metrics import ANALYTICS_DURATION, API_ERRORS_TOTAL

router = APIRouter(prefix="/customers", tags=["customers"])

#: Sortable fields and whether they sort numerically.
SORTABLE = {
    "id": True,
    "email": False,
    "riskScore": True,
    "balance": True,
    "totalReplenished": True,
}

SORT_EXPR = {
    "id": lambda a: a.account.id,
    "email": lambda a: a.account.email.lower(),
    "riskScore": lambda a: (a.risk.score is None, -(a.risk.score or 0.0)),
    "balance": lambda a: a.account.balance,
    "totalReplenished": lambda a: a.account.total_replenished,
}


@router.get("", summary="Список клиентов с фильтрацией, поиском и сортировкой")
def list_customers(
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
    search: str | None = Query(default=None, description="Поиск по email или id"),
    risk_category: str | None = Query(
        default=None,
        alias="riskCategory",
        description="Фильтр по категории риска: low, medium, high, insufficient_data, not_applicable",
    ),
    service_status: str | None = Query(
        default=None, alias="serviceStatus", description="Фильтр по статусу хотя бы одной услуги"
    ),
    sort_by: str = Query(default="riskScore", alias="sortBy"),
    sort_dir: str = Query(default="desc", alias="sortDir", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, alias="pageSize", ge=1, le=200),
) -> dict:
    """Return a filtered, sorted, paginated page of customers.

    Sorting is applied to the real underlying value (numeric for scores and
    balances, case-insensitive string for email), never to a formatted string.
    """

    if sort_by not in SORTABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимое поле сортировки: {sort_by}. Доступно: {sorted(SORTABLE)}",
        )
    if risk_category and risk_category not in {
        "low",
        "medium",
        "high",
        "insufficient_data",
        "not_applicable",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимая категория риска: {risk_category}",
        )

    with ANALYTICS_DURATION.labels(operation="customers_list").time():
        settings = load_settings(session)
        analytics = AnalyticsService(session, settings)
        analyses = analytics.analyze_all()

    if search:
        needle = search.strip().lower()
        analyses = [
            a
            for a in analyses
            if needle in a.account.email.lower() or needle in str(a.account.id)
        ]
    if risk_category:
        analyses = [a for a in analyses if a.risk.category == risk_category]
    if service_status:
        analyses = [
            a for a in analyses if any(sa.service.status == service_status for sa in a.services)
        ]

    reverse = sort_dir == "desc"
    key = SORT_EXPR[sort_by]
    if sort_by == "riskScore":
        # Secondary key keeps ordering stable and readable for equal scores.
        analyses.sort(key=lambda a: (key(a), -a.account.id), reverse=not reverse)
    else:
        analyses.sort(key=key, reverse=reverse)

    total = len(analyses)
    start = (page - 1) * page_size
    window = analyses[start : start + page_size]

    return {
        "items": [customer_summary_payload(a) for a in window],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "sortBy": sort_by,
        "sortDir": sort_dir,
    }


@router.get("/{customer_id}", summary="Карточка клиента")
def get_customer(
    customer_id: int,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> dict:
    with ANALYTICS_DURATION.labels(operation="customer_detail").time():
        settings = load_settings(session)
        analytics = AnalyticsService(session, settings)
        analyses = analytics.analyze_all()

    for analysis in analyses:
        if analysis.account.id == customer_id:
            return customer_detail_payload(analysis)

    API_ERRORS_TOTAL.labels(status_class="4xx").inc()
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Клиент {customer_id} не найден"
    )
