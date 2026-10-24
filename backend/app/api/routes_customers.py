from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import (
    CustomerPage,
    PublishedCustomerDetail,
    RecommendationStatusPatch,
    RiskCategory,
)
from backend.app.storage import RECOMMENDATION_STATUSES

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=CustomerPage)
def customers(
    runtime: RuntimeDep, user: UserDep, response: Response,
    generation: Annotated[int | None, Query(ge=1)] = None,
    search: Annotated[str | None, Query(max_length=320)] = None,
    risk_category: Annotated[RiskCategory | None, Query(alias="riskCategory")] = None,
    service_status: Annotated[Literal["active", "suspended", "prolong_wait", "deleted", "blocked"] | None, Query(alias="serviceStatus")] = None,
    sort_by: Annotated[Literal["id", "email", "riskScore", "balance", "totalReplenished"], Query(alias="sortBy")] = "riskScore",
    sort_dir: Annotated[Literal["asc", "desc"], Query(alias="sortDir")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
):
    payload = runtime.storage.customers(generation=generation, search=search,
        risk_category=risk_category, service_status=service_status, sort_by=sort_by,
        sort_dir=sort_dir, page=page, page_size=page_size)
    return version_headers(response, payload)


@router.get("/{customer_id}", response_model=PublishedCustomerDetail)
def customer(customer_id: int, runtime: RuntimeDep, user: UserDep, response: Response,
             generation: Annotated[int | None, Query(ge=1)] = None):
    return version_headers(response, runtime.storage.customer(customer_id, generation))


@router.get("/{customer_id}/recommendations", summary="Рекомендации по удержанию и их статусы")
def customer_recommendations(
    customer_id: int,
    runtime: RuntimeDep,
    user: UserDep,
    generation: Annotated[int | None, Query(ge=1)] = None,
):
    """Return the customer's playbooks with their workflow status attached.

    A recommendation without a stored row is reported as ``new``, so the list
    is always complete and an untouched playbook needs no write.
    """

    detail = runtime.storage.customer(customer_id, generation)
    stored = runtime.storage.recommendation_statuses(customer_id)
    items = []
    for recommendation in detail.get("recommendations", []):
        state = stored.get(recommendation["code"], {})
        items.append(
            {
                **recommendation,
                "status": state.get("status", "new"),
                "statusUpdatedAt": state.get("updatedAt"),
                "statusUpdatedBy": state.get("updatedBy"),
            }
        )
    return {
        "customerId": customer_id,
        "items": items,
        "statuses": list(RECOMMENDATION_STATUSES),
        "note": (
            "Статус — это состояние рабочего процесса, а не аналитический сигнал. "
            "Он не влияет на score, экспозицию и настройки модели. «Выполнена» означает "
            "только то, что действие отмечено пользователем, а не подтверждённое удержание."
        ),
    }


@router.patch(
    "/{customer_id}/recommendations/{code}",
    summary="Изменить статус рекомендации",
)
def patch_recommendation(
    customer_id: int,
    code: str,
    payload: RecommendationStatusPatch,
    runtime: RuntimeDep,
    user: UserDep,
):
    """Move one playbook to a new status.

    Only the addressed ``(customer, code)`` pair changes. The recommendation must
    exist in the current calculation, so a stale or invented code is rejected
    rather than silently stored.
    """

    detail = runtime.storage.customer(customer_id, None)
    known = {item["code"] for item in detail.get("recommendations", [])}
    if code not in known:
        raise HTTPException(
            status_code=404,
            detail=f"Рекомендация '{code}' не найдена у клиента {customer_id}",
        )
    updated = runtime.storage.set_recommendation_status(
        customer_id, code, payload.status, actor=user.email
    )
    return {
        "customerId": customer_id,
        **updated,
        "note": "Статус сохранён. Аналитические расчёты не изменялись.",
    }
