from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable, Protocol


class ConflictError(Exception):
    pass


class InvalidInput(ValueError):
    pass


class NotReadyError(Exception):
    pass


class ResourceNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class State:
    generation: int
    source_version: int
    model_version: int
    source: dict
    settings: dict
    captured_at: datetime | None = None
    as_of: datetime | None = None
    calculated_at: datetime | None = None

    def metadata(self) -> dict:
        return {
            "generation": self.generation,
            "sourceVersion": self.source_version,
            "modelVersion": self.model_version,
            "capturedAt": self.captured_at.isoformat() if self.captured_at else None,
            "asOf": self.as_of.isoformat() if self.as_of else None,
            "calculatedAt": self.calculated_at.isoformat() if self.calculated_at else None,
        }


@dataclass(frozen=True)
class Analysis:
    summary: dict
    customers: list[dict]


class CalculationModule(Protocol):
    def source(self, payload: dict) -> dict: ...
    def settings(self, current: dict, patch: dict, *, reset: bool) -> dict: ...
    def calculate(self, state: State) -> Analysis: ...


class StorageModule(Protocol):
    def load(self) -> State: ...
    def publish(self, previous: State, candidate: State, result: Analysis, actor: str) -> bool: ...


class Core:
    def __init__(
        self, storage: StorageModule, calculation: CalculationModule,
        reference_time: Callable[[], datetime],
    ) -> None:
        self.storage = storage
        self.calculation = calculation
        self.reference_time = reference_time

    def update(
        self, *, source: dict | None = None, patch: dict | None = None,
        reset: bool = False, expected_generation: int | None = None,
        actor: str = "system", force: bool = False,
    ) -> State:
        source = self.calculation.source(deepcopy(source)) if source is not None else None
        for _ in range(3):
            previous = self.storage.load()
            if expected_generation is not None and previous.generation != expected_generation:
                raise ConflictError("Результаты уже изменились; обновите данные")
            settings = self.calculation.settings(deepcopy(previous.settings), deepcopy(patch or {}), reset=reset)
            next_source = source if source is not None else previous.source
            source_changed = next_source != previous.source or previous.generation == 0
            model_changed = settings != previous.settings or previous.generation == 0
            as_of = self.reference_time()
            # A new generation is published only for a real input change: source,
            # settings, or the reference instant. ``force`` exists for the one case
            # not visible in the inputs — the analytics engine itself changed
            # version, so the same inputs must be re-evaluated. A plain
            # "recalculate" tick does *not* force a publication on its own, which
            # keeps ``generation`` a version of the inputs rather than a tick
            # counter and stops the analysis tables growing with no change.
            if not (source_changed or model_changed or force or as_of != previous.as_of):
                return previous
            now = datetime.now(timezone.utc)
            candidate = replace(
                previous, generation=previous.generation + 1,
                source_version=previous.source_version + int(source_changed),
                model_version=previous.model_version + int(model_changed),
                source=next_source, settings=settings, as_of=as_of,
                captured_at=now if source_changed else previous.captured_at,
                calculated_at=now,
            )
            result = self.calculation.calculate(deepcopy(candidate))
            result.summary.update(candidate.metadata())
            if self.storage.publish(previous, candidate, result, actor):
                return candidate
            if expected_generation is not None:
                raise ConflictError("Результаты уже изменились; обновите данные")
        raise ConflictError("Конкурирующие обновления; повторите запрос")
