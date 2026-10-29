"""Read-only what-if scenario tool.

Runs the platform's own ``AnalyticsModule`` on the same snapshot and ``as_of``
with alternative settings, exactly as ``POST /api/v1/scenarios/compare`` does,
and returns only the numbers.  Nothing is persisted and the working settings are
never modified, so asking the AI about a scenario cannot change the product state.
"""

from __future__ import annotations

from core import InvalidInput
from backend.app.domain import insights


def scenario_preview(storage, calculation, *, overrides: dict, name: str = "AI scenario") -> dict:
    """Evaluate alternative parameters and return baseline/scenario/delta."""

    state = storage.load()
    if not state.generation:
        raise InvalidInput("Расчёт ещё не опубликован")

    cleaned = insights.ScenarioDefinition(name, overrides).cleaned()
    candidate = insights.apply_overrides(state.settings, cleaned)
    candidate = calculation.settings({}, candidate, reset=False)

    baseline_state = state
    scenario_state = type(state)(
        generation=state.generation,
        source_version=state.source_version,
        model_version=state.model_version,
        source=state.source,
        settings=candidate,
        captured_at=state.captured_at,
        as_of=state.as_of,
        calculated_at=state.calculated_at,
    )
    baseline = calculation.calculate(baseline_state)
    scenario = calculation.calculate(scenario_state)
    return {
        "name": name,
        "appliedOverrides": cleaned,
        "baselineSettings": state.settings,
        "scenarioSettings": candidate,
        "baseline": {
            "revenue": baseline.summary["revenue"],
            "customers": baseline.summary["customers"],
            "services": baseline.summary["services"],
        },
        "scenario": {
            "revenue": scenario.summary["revenue"],
            "customers": scenario.summary["customers"],
            "services": scenario.summary["services"],
        },
        "comparison": insights.compare(baseline.summary, scenario.summary),
        "customerChanges": insights.customer_changes(baseline.customers, scenario.customers)[:10],
        "note": (
            "Сценарий изолирован: рабочие настройки и опубликованный расчёт не изменены. "
            "Выручка под риском — денежная экспозиция, а не гарантированный убыток."
        ),
    }
