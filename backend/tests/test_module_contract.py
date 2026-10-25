"""Contract tests for the analytics plug-in that the platform runtime loads.

These guard the wiring rather than the formulas: the platform owns storage,
versions and HTTP, and asks an ``AnalyticsModule`` for the numbers.  If the
adapter stops satisfying that contract the whole product degrades to 503, so
the shape is worth testing directly.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from backend.app.modules import CalculationAdapter, ModuleContractError, load_module
from backend.app.api.schemas import CustomerDetail, SettingsPayload, Summary
from core import InvalidInput, State

from backend.app.domain.module import MODEL_VERSION, create

SNAPSHOT = Path(__file__).resolve().parents[2] / "dataset" / "data.json"


def _source() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _state(**overrides) -> State:
    base = dict(
        generation=1,
        source_version=1,
        model_version=1,
        source=_source(),
        settings={
            "horizonDays": 30,
            "weights": {
                "expiry_proximity": 3.0,
                "auto_prolong_disabled": 2.0,
                "insufficient_balance": 2.0,
                "prolong_wait_status": 2.5,
                "failed_renewals": 0.0,
                "suspended_status": 1.0,
                "renewal_failure_rate": 2.5,
            },
            "lowMax": 34,
            "mediumMax": 64,
            "failedRenewalWindowDays": 90,
        },
        as_of=dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc),
    )
    base.update(overrides)
    return State(**base)


def test_factory_is_loadable_by_path():
    """The runtime resolves the module by dotted path from the environment."""
    module = load_module("backend.app.domain.module:create")
    definition = module.definition()
    assert definition.version == MODEL_VERSION


def test_definition_satisfies_platform_contract():
    """CalculationAdapter validates defaults, factors and version."""
    adapter = CalculationAdapter(create())
    definition = adapter.definition()
    SettingsPayload.model_validate(definition.defaults)
    keys = [factor["key"] for factor in definition.factors]
    assert len(set(keys)) == len(keys)

    assert set(definition.defaults["weights"]) == set(keys)


def test_calculate_produces_a_valid_summary_and_customers():
    """Full contract validation, including the money and identity checks."""
    adapter = CalculationAdapter(create())
    state = _state()
    result = adapter.calculate(state)
    Summary.model_validate(result.summary)
    for item in result.customers:
        CustomerDetail.model_validate(item)


def test_calculate_covers_every_source_account_and_service():
    adapter = CalculationAdapter(create())
    result = adapter.calculate(_state())
    source = _source()
    assert {c["id"] for c in result.customers} == {a["id"] for a in source["accounts"]}
    owned = [(s["id"], c["id"]) for c in result.customers for s in c["services"]]
    assert dict(owned) == {s["id"]: s["ownerId"] for s in source["services"]}


def test_money_matches_the_source_accounts_exactly():
    adapter = CalculationAdapter(create())
    result = adapter.calculate(_state())
    accounts = {a["id"]: a for a in _source()["accounts"]}
    for customer in result.customers:
        account = accounts[customer["id"]]
        for name in ("balance", "withdrawBalance", "totalReplenished", "bonusBalance"):
            assert customer[name]["cents"] == account[name]

        cents = customer["balance"]["cents"]
        assert customer["balance"]["eur"] == f"{cents // 100}.{cents % 100:02d}"


def test_unknown_amounts_stay_unknown():
    """A missing amount must not be presented as zero."""
    source = _source()
    source["accounts"][0]["bonusBalance"] = None
    adapter = CalculationAdapter(create())
    result = adapter.calculate(_state(source=source))
    customer = next(c for c in result.customers if c["id"] == source["accounts"][0]["id"])
    assert customer["bonusBalance"] == {"cents": None, "eur": None}


def test_calculation_is_deterministic():
    adapter = CalculationAdapter(create())
    first = adapter.calculate(_state())
    second = adapter.calculate(_state())
    assert first.summary["revenue"] == second.summary["revenue"]
    assert [c["riskScore"] for c in first.customers] == [c["riskScore"] for c in second.customers]


def test_calculation_does_not_mutate_the_input_state():
    adapter = CalculationAdapter(create())
    state = _state()
    before = json.dumps(state.source, sort_keys=True)
    adapter.calculate(state)
    assert json.dumps(state.source, sort_keys=True) == before


def test_module_does_not_claim_calibration():
    """The dataset has no churn labels, so no calibrated model may be claimed."""
    adapter = CalculationAdapter(create())
    summary = adapter.calculate(_state()).summary
    assert summary["model"]["calibrated"] is False
    assert summary["model"]["type"] == "rule_based_weighted"
    assert summary["historyAvailable"] is False


def test_approved_methodology_reaches_the_output():
    """The decisions approved for this stage must be visible in the result."""
    adapter = CalculationAdapter(create())
    result = adapter.calculate(_state())

    assert result.summary["revenue"]["revenueAtRiskEur"] == "5.80"
    assert result.summary["revenue"]["upcomingRenewalsEur"] == "17.03"
    categories = result.summary["customers"]["byCategory"]
    assert categories["high"] == 3 and categories["medium"] == 3
    assert categories["not_applicable"] == 4


    customer = next(c for c in result.customers if c["services"])
    factors = {f["key"]: f for f in customer["services"][0]["factors"]}
    assert factors["failed_renewals"]["deprecated"] is True
    assert factors["failed_renewals"]["weight"] == 0.0
    assert factors["renewal_failure_rate"]["weight"] > 0


def test_settings_validation_rejects_bad_values():
    adapter = CalculationAdapter(create())
    with pytest.raises(InvalidInput):
        adapter.settings({}, {"horizonDays": 0}, reset=False)
    with pytest.raises(InvalidInput):
        adapter.settings({}, {"weights": {"nope": 1.0}}, reset=False)


def test_settings_accept_null_window_as_whole_snapshot():
    adapter = CalculationAdapter(create())
    settings = adapter.settings({}, {"failedRenewalWindowDays": None}, reset=False)
    assert settings["failedRenewalWindowDays"] is None

    adapter.calculate(_state(settings=settings))


def test_source_rejects_a_broken_snapshot():
    adapter = CalculationAdapter(create())
    source = _source()
    source["services"][0]["ownerId"] = 999_999
    with pytest.raises(InvalidInput):
        adapter.source(source)


def test_default_window_is_the_approved_ninety_days():
    """A fresh database must use the approved 90-day window, not "everything".

    Regression guard: ModelDefinition.defaults once omitted this field, so the
    platform filled it with its own None and a fresh install silently scored
    against the whole snapshot (4 medium / 2 high instead of 3 / 3).
    """
    definition = CalculationAdapter(create()).definition()
    assert definition.defaults["failedRenewalWindowDays"] == 90


    result = CalculationAdapter(create()).calculate(_state(settings=definition.defaults))
    categories = result.summary["customers"]["byCategory"]
    assert categories["high"] == 3 and categories["medium"] == 3
    assert result.summary["revenue"]["revenueAtRiskEur"] == "5.80"


def test_null_window_differs_from_the_default():
    """The two window modes must not collapse into one another."""
    adapter = CalculationAdapter(create())
    default = adapter.calculate(_state(settings=adapter.definition().defaults))
    whole = adapter.calculate(_state(settings={**adapter.definition().defaults,
                                              "failedRenewalWindowDays": None}))
    assert default.summary["customers"]["byCategory"] != whole.summary["customers"]["byCategory"]
