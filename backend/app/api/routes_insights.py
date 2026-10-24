"""Scenario (what-if), data-quality and priority endpoints.

All three are read-only with respect to the published generation:

* a scenario is evaluated by calling the same ``AnalyticsModule`` the product
  uses, on the same snapshot and ``as_of``, with alternative settings.  The
  result is returned and discarded, so viewing a scenario can never change the
  working configuration or the stored data.
* the quality audit reads the raw snapshot and reports issues without writing.
* the priority view classifies the already calculated customers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core import InvalidInput
from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.domain import insights, llm

router = APIRouter(tags=["insights"])


class ScenarioRequest(BaseModel):
    """Alternative parameters for one comparison.

    ``overrides`` is deliberately narrow: only model parameters are accepted, so
    a scenario cannot reach balances, prices, statuses or raw transactions.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Custom", min_length=1, max_length=120)
    overrides: dict = Field(default_factory=dict)


@router.get("/quality", summary="Проверка качества исходных данных")
def quality(runtime: RuntimeDep, user: UserDep):
    """Audit the raw snapshot. Never modifies a record."""

    state = runtime.storage.load()
    as_of = state.as_of
    report = insights.inspect_source(state.source, as_of=as_of)
    report["asOf"] = as_of.isoformat() if as_of else None
    return report


@router.post("/scenarios/compare", summary="Сравнить сценарий параметров с текущими настройками")
def compare_scenario(payload: ScenarioRequest, runtime: RuntimeDep, user: UserDep):
    """Evaluate alternative parameters against the published configuration.

    Nothing is persisted: the working settings, the stored snapshot and the
    published generation are untouched.  Applying a scenario to the live
    configuration remains an explicit action on ``PATCH /model/settings``.
    """

    state = runtime.storage.load()
    definition = runtime.calculation.definition()
    baseline_settings = state.settings

    try:
        overrides = insights.ScenarioDefinition(payload.name, payload.overrides).cleaned()
        candidate_settings = insights.apply_overrides(baseline_settings, overrides)
        # Validated by the same code path the live product uses, so a scenario
        # cannot introduce a configuration the product would reject.
        candidate_settings = runtime.calculation.settings({}, candidate_settings, reset=False)
    except (insights.ScenarioError, InvalidInput, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    baseline_state = state
    scenario_state = type(state)(
        generation=state.generation,
        source_version=state.source_version,
        model_version=state.model_version,
        source=state.source,
        settings=candidate_settings,
        captured_at=state.captured_at,
        as_of=state.as_of,
        calculated_at=state.calculated_at,
    )

    try:
        baseline = runtime.calculation.calculate(baseline_state)
        scenario = runtime.calculation.calculate(scenario_state)
    except InvalidInput as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "name": payload.name,
        "baselineSettings": baseline_settings,
        "scenarioSettings": candidate_settings,
        "appliedOverrides": overrides,
        "allowedParameters": list(insights.SCENARIO_PARAMETERS),
        "asOf": state.as_of.isoformat() if state.as_of else None,
        "baseline": baseline.summary,
        "scenario": scenario.summary,
        "comparison": insights.compare(baseline.summary, scenario.summary),
        "customers": insights.customer_changes(baseline.customers, scenario.customers),
        "factorAvailability": insights.factor_availability(baseline.customers, scenario.customers),
        "note": (
            "Сценарий изолирован: рабочие настройки и опубликованный расчёт не изменяются. "
            "Чтобы применить параметры, используйте PATCH /model/settings."
        ),
    }


@router.get("/priority", summary="Очередь приоритетных действий")
def priority(
    runtime: RuntimeDep,
    user: UserDep,
    horizon_days: Annotated[int, Query(alias="horizonDays", ge=1, le=365)] = 30,
    category: Annotated[str | None, Query()] = None,
    sort_by: Annotated[Literal["urgency", "riskScore", "exposure", "id"], Query(alias="sortBy")] = "urgency",
    sort_dir: Annotated[Literal["asc", "desc"], Query(alias="sortDir")] = "asc",
):
    """Customers with independent risk, exposure, urgency and quality signals.

    The four measurements stay separate; the returned categories organise work
    and carry no probability.  Sorting is deterministic: a stable tie-breaker on
    customer id keeps the order reproducible.
    """

    state = runtime.storage.load()
    quality_report = insights.inspect_source(state.source, as_of=state.as_of)
    quality_ids = {
        record
        for issue in quality_report["issues"]
        if issue["code"] in ("missing_money_field", "negative_amount", "lifecycle_inconsistent")
        for record in issue["records"]
    }

    customers: list[dict] = []
    with runtime.storage.database.sessions() as session:
        from sqlalchemy import select

        from backend.app.db import CustomerRow

        generation = runtime.storage._generation(session, None)
        rows = session.scalars(
            select(CustomerRow).where(CustomerRow.generation == generation)
        ).all()
        payloads = [row.payload for row in rows]

    for payload in payloads:
        categories = insights.priority_for(payload, horizon_days=horizon_days, quality_ids=quality_ids)
        exposure = next(
            (h for h in (payload.get("exposureByHorizon") or []) if h.get("horizonDays") == horizon_days),
            None,
        )
        customers.append(
            {
                "id": payload["id"],
                "email": payload.get("email"),
                "riskScore": payload.get("riskScore"),
                "riskCategory": payload.get("riskCategory"),
                "serviceCount": payload.get("serviceCount"),
                "highRiskServiceCount": payload.get("highRiskServiceCount"),
                "highRiskShare": payload.get("highRiskShare"),
                "revenueAtRiskOnHorizon": (exposure or {}).get("revenueAtRisk"),
                "upcomingRenewalsOnHorizon": (exposure or {}).get("upcomingRenewals"),
                "overdueOperational": payload.get("overdueOperational"),
                "overdueServiceCount": payload.get("overdueServiceCount"),
                "lifecycleInconsistentCount": payload.get("lifecycleInconsistentCount"),
                "categories": categories,
                "urgencyRank": insights.urgency_rank(payload),
            }
        )

    if category:
        if category not in insights.PRIORITY_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"неизвестная категория: {category}")
        customers = [c for c in customers if category in c["categories"]]

    def key(item):
        if sort_by == "urgency":
            return (item["urgencyRank"], item["id"])
        if sort_by == "riskScore":
            return (item["riskScore"] is None, -(item["riskScore"] or 0.0), item["id"])
        if sort_by == "exposure":
            cents = (item["revenueAtRiskOnHorizon"] or {}).get("cents") or 0
            return (-cents, item["id"])
        return (item["id"],)

    reverse = sort_dir == "desc" and sort_by != "urgency"
    customers.sort(key=key, reverse=reverse)

    return {
        "horizonDays": horizon_days,
        "total": len(customers),
        "categories": insights.PRIORITY_CATEGORIES,
        "qualityCounts": quality_report["counts"],
        "items": customers,
        "note": (
            "Риск, финансовая экспозиция, операционная срочность и качество данных "
            "показаны раздельно. Категории организуют работу и не являются вероятностью оттока."
        ),
    }


class AiQuestion(BaseModel):
    """One analyst question about the published aggregates.

    ``extra="forbid"`` keeps the schema closed, so a caller cannot smuggle
    fields (settings, a snapshot, a provider URL) into the request. The length
    bound stops an unbounded prompt from reaching the model.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1000)


@router.post("/insights/ai", summary="Ответ на вопрос по агрегатам расчёта с помощью локальной модели")
def ai_question(payload: AiQuestion, runtime: RuntimeDep, user: UserDep):
    """Answer a portfolio question from the published aggregates.

    Read-only: the model receives only aggregated figures from the published
    calculation and the data-quality summary. Customer e-mails, individual
    records, the raw snapshot, the renewal list and every credential are never
    sent. The model narrates; it never computes or writes.

    Failure is honest: a disabled, unreachable or malformed provider returns
    **503**, and nothing is replaced by a canned answer. A response that
    invents a number is rejected as ungrounded.
    """

    state = runtime.storage.load()
    summary = runtime.storage.summary()
    quality_report = insights.inspect_source(state.source, as_of=state.as_of)
    as_of = state.as_of.isoformat() if state.as_of else None

    try:
        answer = llm.ask_aggregate(
            summary,
            quality_report,
            settings=runtime.settings,
            question=payload.question,
            as_of=as_of,
        )
    except llm.LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except llm.LlmUngrounded as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ответ модели отклонён: он содержит данные, которых нет в расчёте "
                f"({'; '.join(exc.violations[:3])}). Ответ не показан, чтобы не "
                "выдавать вымысел за результат расчёта."
            ),
        ) from exc
    except llm.LlmBadResponse as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "answer": answer.text,
        "model": answer.model,
        "generation": summary.get("generation"),
        "sources": list(llm.AGGREGATE_SOURCES),
        "grounded": True,
        "warning": (
            "AI-интерпретация не заменяет расчётный движок: числа и категории "
            "берутся из опубликованного расчёта, а текст лишь объясняет их."
        ),
    }

