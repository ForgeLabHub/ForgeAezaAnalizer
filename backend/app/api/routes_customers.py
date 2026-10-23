from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import CustomerPage, PublishedCustomerDetail, RiskCategory

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
