"""Retention actions: the human-confirmed end of the loop.

The AI Analyst explains a risk and proposes a retention step; a person decides.
This router is where that decision is written.  It is intentionally the only
write surface for actions — the AI module has read-only access — so an action
can never appear without a human having confirmed it.

Nothing here recomputes risk or money: ``title`` and ``detail`` are copied from
the Risk Engine's own recommendation for that customer.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.domain import actions as actions_domain

router = APIRouter(prefix="/actions", tags=["actions"])

StatusLiteral = Literal["open", "in_progress", "done", "dismissed"]


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customerId: Annotated[int, Field(ge=1)]
    code: Annotated[str, Field(min_length=1, max_length=64)]
    serviceId: Annotated[int | None, Field(ge=1)] = None
    note: Annotated[str | None, Field(max_length=2000)] = None


class ActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: StatusLiteral | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None


@router.get("", summary="Список подтверждённых действий по удержанию")
def list_actions(
    runtime: RuntimeDep, user: UserDep, response: Response,
    customer_id: Annotated[int | None, Query(alias="customerId", ge=1)] = None,
    status: Annotated[StatusLiteral | None, Query()] = None,
):
    payload = {
        "items": runtime.storage.actions(customer_id=customer_id, status=status),
        "statuses": list(actions_domain.ACTION_STATUSES),
        "note": "Действия создаёт человек через API. AI Analyst их только читает и не изменяет.",
    }
    return version_headers(response, payload)


@router.post("", status_code=201, summary="Подтвердить действие по удержанию")
def create_action(payload: ActionCreate, runtime: RuntimeDep, user: UserDep, response: Response):
    customer = runtime.storage.customer(payload.customerId)
    validated = actions_domain.validate_new_action(
        customer,
        actions_domain.ActionInput(
            customer_id=payload.customerId,
            service_id=payload.serviceId,
            code=payload.code,
            note=payload.note,
        ),
    )
    generation = customer.get("generation", 0)
    created = runtime.storage.create_action(
        customer_id=validated["customer_id"], service_id=validated["service_id"],
        code=validated["code"], title=validated["title"], detail=validated["detail"],
        note=validated["note"], generation=generation, actor=user.email,
    )
    return version_headers(response, created)


@router.patch("/{action_id}", summary="Изменить статус или комментарий действия")
def update_action(action_id: int, payload: ActionUpdate, runtime: RuntimeDep, user: UserDep, response: Response):
    if payload.status is None and payload.note is None:
        raise actions_domain.ActionError("нужно передать status или note")
    status = actions_domain.validate_status(payload.status) if payload.status is not None else None
    return version_headers(response, runtime.storage.update_action(
        action_id, status=status, note=payload.note))
