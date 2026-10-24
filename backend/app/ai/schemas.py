"""Strict request/response contracts for the AI Analyst.

The response shape is fixed so the model cannot invent fields and the API can
reject a malformed generation instead of serving it.  Every list has bounded
length, because an unbounded list is a cheap way for a model to exhaust the
context or the response budget.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Lifecycle of the AI subsystem, surfaced on ``GET /ai/status``.
AIStatus = Literal["disabled", "ready", "unavailable"]

AITask = Literal["chat", "customer_explain", "scenario_explain", "report_summary"]


class Citation(BaseModel):
    """A reference to the exact input an answer was grounded in."""

    model_config = ConfigDict(extra="forbid")
    #: ``fact`` for backend values, ``document`` for RAG chunks.
    kind: Literal["fact", "document"]
    source: str
    detail: str = ""


class AIAnswer(BaseModel):
    """The structured answer every task must produce."""

    model_config = ConfigDict(extra="forbid")

    summary: Annotated[str, Field(min_length=1, max_length=1200)]
    facts: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)
    factor_explanation: Annotated[str, Field(max_length=2000)] = ""
    recommendations: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)
    limitations: Annotated[str, Field(max_length=1200)] = ""
    citations: Annotated[list[Citation], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_substance(self):
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        return self


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    customer_id: Annotated[int | None, Field(ge=1)] = None


class AIExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Optional analyst question; when omitted the service uses a default prompt.
    question: Annotated[str | None, Field(max_length=2000)] = None


class AIReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: Annotated[str | None, Field(max_length=400)] = None


class AIResponse(BaseModel):
    """Envelope returned by every AI endpoint."""

    task: AITask
    model: str
    provider: str
    grounded: bool
    #: Non-empty when the answer was repaired or a claim was dropped.
    warnings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    answer: AIAnswer
    #: Backend facts that were placed in the prompt, so the UI can show them.
    context: dict = Field(default_factory=dict)


class AIStatusResponse(BaseModel):
    status: AIStatus
    provider: str
    model: str
    enabled: bool
    reason: str = ""
    #: True when the runtime was confirmed reachable during this request.
    reachable: bool = False
    rag_indexed: bool = False
    rag_chunks: int = 0
