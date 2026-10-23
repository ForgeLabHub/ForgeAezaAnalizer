"""Retention priority endpoints: the ranked Action Center worklist."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import PriorityResponse

router = APIRouter(prefix="/priority", tags=["priority"])


@router.get("", response_model=PriorityResponse)
def priority(
    runtime: RuntimeDep,
    user: UserDep,
    response: Response,
    tier: Annotated[Literal["p1", "p2", "p3"] | None, Query()] = None,
    sort: Annotated[Literal["priority", "risk"], Query()] = "priority",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    generation: Annotated[int | None, Query(ge=1)] = None,
):
    """Return the ranked worklist for the pinned (or current) generation.

    Ranking is computed from the stored generation, so the numbers match the
    dashboard and the customer card exactly instead of being recalculated from
    live inputs.
    """

    return version_headers(response, runtime.storage.priority(
        generation=generation, limit=limit, tier=tier, sort=sort))
