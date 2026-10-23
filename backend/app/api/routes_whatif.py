"""What-if endpoints: simulate a model change without publishing it."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from fastapi import APIRouter, Response

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import SettingsPatch, SimulationResponse
from core import InvalidInput

router = APIRouter(prefix="/whatif", tags=["whatif"])

#: Key subset of a customer payload that the comparison actually needs.
_COMPARISON_KEYS = ("id", "email", "riskCategory", "riskScore")


def _comparison_rows(customers: list[dict]) -> list[dict]:
    return [{key: customer.get(key) for key in _COMPARISON_KEYS} for customer in customers]


@router.post("", response_model=SimulationResponse)
def simulate(patch: SettingsPatch, runtime: RuntimeDep, user: UserDep, response: Response):
    """Compare candidate settings against the published generation.

    The simulation runs in memory and is never published: no generation is
    created and no settings row is written, so other users are unaffected.
    Applying a scenario still requires an explicit ``PATCH /model/settings``.

    Candidate settings go through the same validation as a real save, so a
    scenario can never accept a combination that saving would reject.
    """

    from backend.app.domain.scenarios import build_simulation

    requested = patch.model_dump(exclude_unset=True)
    requested.pop("expectedGeneration", None)
    if not requested:
        raise InvalidInput("Укажите хотя бы один параметр для симуляции")

    current = runtime.storage.load()
    if not current.generation:
        raise InvalidInput("Нет опубликованного расчёта для сравнения")

    applied = runtime.calculation.settings(
        deepcopy(current.settings), deepcopy(requested), reset=False
    )
    scenario = runtime.calculation.calculate(replace(current, settings=applied))

    baseline = runtime.storage.customers(generation=current.generation, page_size=100_000)
    payload = build_simulation(
        runtime.storage.summary(current.generation),
        scenario.summary,
        _comparison_rows(baseline["items"]),
        _comparison_rows(scenario.customers),
        settings_patch=requested,
        settings_applied=applied,
    )
    return version_headers(response, {**payload, **current.metadata()})
