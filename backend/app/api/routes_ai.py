"""AI Analyst HTTP routes.

All routes sit behind the existing bearer-token dependency, so the AI surface is
exactly as protected as the analytics API it explains.  When the subsystem is
disabled or the model is unreachable the endpoints answer ``503`` with a clear
message; the rest of the product keeps working, because nothing here is on the
analytics path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.ai.service import AIService, AIUnavailable
from backend.app.api.deps import RuntimeDep, UserDep

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    customerId: Annotated[int | None, Field(ge=1)] = None


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str | None, Field(max_length=2000)] = None


class ScenarioExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: dict = Field(default_factory=dict)
    question: Annotated[str | None, Field(max_length=2000)] = None


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: Annotated[str | None, Field(max_length=400)] = None


def _service(runtime) -> AIService:
    service = getattr(runtime, "ai", None)
    if service is None:
        raise AIUnavailable("AI Analyst не инициализирован")
    return service


@router.get("/status", summary="Состояние AI Analyst")
def status(runtime: RuntimeDep, user: UserDep, probe: Annotated[bool, Query()] = False):
    return _service(runtime).status(probe=probe)


@router.post("/chat", summary="Вопрос AI-аналитику")
def chat(payload: ChatRequest, runtime: RuntimeDep, user: UserDep):
    return _service(runtime).chat(question=payload.question, customer_id=payload.customerId)


@router.post("/customers/{customer_id}/explain", summary="Объяснить оценку клиента")
def explain_customer(customer_id: int, payload: ExplainRequest, runtime: RuntimeDep, user: UserDep):
    return _service(runtime).explain_customer(customer_id=customer_id, question=payload.question)


@router.post("/scenarios/explain", summary="Объяснить результат what-if сценария")
def explain_scenario(payload: ScenarioExplainRequest, runtime: RuntimeDep, user: UserDep):
    return _service(runtime).explain_scenario(overrides=payload.overrides, question=payload.question)


@router.post("/reports/summary", summary="Краткий отчёт по картине риска")
def report(payload: ReportRequest, runtime: RuntimeDep, user: UserDep):
    return _service(runtime).report_summary(focus=payload.focus)
