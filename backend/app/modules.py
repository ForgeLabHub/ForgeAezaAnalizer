from __future__ import annotations

import importlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from core import Analysis, InvalidInput, NotReadyError, State
from backend.app.api.schemas import CustomerDetail, FactorInfo, SettingsPayload, Summary
from backend.app.source import validate_source


class ModuleContractError(Exception):
    pass


@dataclass(frozen=True)
class ModelDefinition:
    defaults: dict
    factors: tuple[dict, ...]
    version: str


class AnalyticsModule(Protocol):
    def definition(self) -> ModelDefinition: ...
    def validate_settings(self, settings: dict) -> dict: ...
    def calculate(self, state: State) -> Analysis: ...


class UnavailableAnalytics:
    def definition(self) -> ModelDefinition:
        raise NotReadyError("Модуль аналитики и risk-engine пока не подключён")

    def validate_settings(self, settings: dict) -> dict:
        raise NotReadyError("Модуль аналитики и risk-engine пока не подключён")

    def calculate(self, state: State) -> Analysis:
        raise NotReadyError("Модуль аналитики и risk-engine пока не подключён")


def load_module(path: str) -> AnalyticsModule:
    if not path:
        return UnavailableAnalytics()
    module_name, separator, factory_name = path.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("AEZA_ANALYTICS_FACTORY must be module:factory")
    return getattr(importlib.import_module(module_name), factory_name)()


class CalculationAdapter:
    def __init__(self, module: AnalyticsModule):
        self.module = module

    def definition(self) -> ModelDefinition:
        definition = self.module.definition()
        try:
            SettingsPayload.model_validate(definition.defaults)
            factors = [FactorInfo.model_validate(item) for item in definition.factors]
            keys = [factor.key for factor in factors]
            if len(set(keys)) != len(keys) or set(definition.defaults["weights"]) != set(keys):
                raise ValueError("factor keys must match default weights")
            if not definition.version:
                raise ValueError("module version is required")
        except (ValidationError, ValueError, KeyError, AttributeError, TypeError) as exc:
            raise ModuleContractError("Некорректное описание внешнего модуля") from exc
        return definition

    def source(self, payload: dict) -> dict:
        return validate_source(payload)

    def settings(self, current: dict, patch: dict, *, reset: bool) -> dict:
        definition = self.definition()
        base = dict(definition.defaults if reset or not current else current)
        candidate = {**base, **patch}
        if "weights" in patch and isinstance(patch["weights"], dict):
            candidate["weights"] = {**base["weights"], **patch["weights"]}
        try:
            candidate = SettingsPayload.model_validate(candidate).model_dump()
            if candidate["weights"].keys() - definition.defaults["weights"].keys():
                raise ValueError("unknown factor keys")
        except (ValidationError, ValueError) as exc:
            raise InvalidInput(str(exc)) from exc
        try:
            validated = self.module.validate_settings(candidate)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        try:
            result = SettingsPayload.model_validate(validated).model_dump()
            if result["weights"].keys() - definition.defaults["weights"].keys():
                raise ValueError("unknown factor keys returned by module")
            return result
        except (ValidationError, ValueError) as exc:
            raise ModuleContractError("Модуль вернул некорректные настройки") from exc

    def calculate(self, state: State) -> Analysis:
        original = deepcopy(state)
        result = self.module.calculate(state)
        if state != original:
            raise ModuleContractError("Расчётный модуль изменил входные данные")
        try:
            summary = Summary.model_validate(result.summary).model_dump(mode="json")
            customers = [CustomerDetail.model_validate(item).model_dump(mode="json") for item in result.customers]
            ids = [item["id"] for item in customers]
            if len(set(ids)) != len(ids) or set(ids) != {item["id"] for item in state.source["accounts"]}:
                raise ValueError("customer ids must match source")
            accounts = {item["id"]: item for item in state.source["accounts"]}
            for customer in customers:
                account = accounts[customer["id"]]
                if customer["email"] != account["email"]:
                    raise ValueError("customer email must match source")
                for name in ("balance", "withdrawBalance", "totalReplenished", "bonusBalance"):
                    if customer[name]["cents"] != account.get(name):
                        raise ValueError(f"customer {name} must match source")
            source_services = {item["id"]: item["ownerId"] for item in state.source["services"]}
            actual_services = [(service["id"], customer["id"]) for customer in customers for service in customer["services"]]
            if len(actual_services) != len(source_services) or dict(actual_services) != source_services:
                raise ValueError("service ids and owners must match source")
        except (ValidationError, ValueError, AttributeError, TypeError) as exc:
            raise ModuleContractError("Модуль вернул некорректный результат расчёта") from exc
        summary["version"] = state.metadata()
        definition = self.definition()
        summary["engineVersion"] = definition.version
        summary["modelDefinition"] = {"defaults": definition.defaults, "factors": list(definition.factors)}
        return Analysis(summary, customers)
