"""What-if simulation: compare a candidate model against the published one.

``PATCH /model/settings`` *commits* a new model version, which is the right
behaviour for a deliberate change but the wrong one for exploring.  An analyst
needs to ask "what would happen if I doubled this weight" without leaving a new
generation behind for everyone else.

This module computes that comparison as a pure function over two summaries.  It
never writes anything, so a simulation cannot change what other users see.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.money import cents_to_eur


def _cents(value) -> int:
    if isinstance(value, dict) and isinstance(value.get("cents"), int):
        return value["cents"]
    return 0


#: Category ordering, used to detect a real move up or down the risk ladder.
_CATEGORY_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Movement:
    """A customer affected by the candidate model."""

    customer_id: int
    email: str
    before: str
    after: str
    before_score: float | None
    after_score: float | None
    delta: float | None

    @property
    def category_changed(self) -> bool:
        return self.before != self.after

    @property
    def direction(self) -> str:
        if not self.category_changed:
            return "flat"
        return "up" if _CATEGORY_ORDER.get(self.after, -1) > _CATEGORY_ORDER.get(self.before, -1) else "down"


@dataclass
class Simulation:
    baseline: dict
    scenario: dict
    movements: list[Movement] = field(default_factory=list)
    settings_patch: dict = field(default_factory=dict)
    settings_applied: dict = field(default_factory=dict)


def _category_delta(before: dict, after: dict) -> dict:
    categories = set(before) | set(after)
    return {name: after.get(name, 0) - before.get(name, 0) for name in sorted(categories)}


def compare_customers(baseline: list[dict], scenario: list[dict]) -> list[Movement]:
    """List the customers whose risk category or score changed.

    Only real changes are returned, so the UI can show "who this affects"
    instead of a wall of unchanged rows.
    """

    before_by_id = {c["id"]: c for c in baseline}
    movements: list[Movement] = []
    for customer in scenario:
        previous = before_by_id.get(customer["id"])
        if previous is None:
            continue
        if previous["riskCategory"] == customer["riskCategory"] and previous["riskScore"] == customer["riskScore"]:
            continue
        before_score = previous.get("riskScore")
        after_score = customer.get("riskScore")
        movements.append(
            Movement(
                customer_id=customer["id"],
                email=customer.get("email", ""),
                before=previous["riskCategory"],
                after=customer["riskCategory"],
                before_score=before_score,
                after_score=after_score,
                delta=(
                    round(after_score - before_score, 1)
                    if before_score is not None and after_score is not None
                    else None
                ),
            )
        )

    # Biggest category moves first, then the largest score change, then id.
    movements.sort(
        key=lambda m: (
            0 if m.category_changed else 1,
            -abs(_CATEGORY_ORDER.get(m.after, 0) - _CATEGORY_ORDER.get(m.before, 0)),
            -abs(m.delta or 0.0),
            m.customer_id,
        )
    )
    return movements


def build_simulation(
    baseline_summary: dict,
    scenario_summary: dict,
    baseline_customers: list[dict],
    scenario_customers: list[dict],
    *,
    settings_patch: dict,
    settings_applied: dict,
) -> dict:
    """Assemble the full comparison payload for the What-if Lab."""

    before_customers = baseline_summary["customers"]
    after_customers = scenario_summary["customers"]
    before_revenue = baseline_summary["revenue"]
    after_revenue = scenario_summary["revenue"]

    movements = compare_customers(baseline_customers, scenario_customers)

    return {
        "settingsPatch": settings_patch,
        "settingsApplied": settings_applied,
        "baseline": {
            "horizonDays": baseline_summary.get("horizonDays"),
            "customers": before_customers,
            "services": baseline_summary["services"],
            "revenue": before_revenue,
        },
        "scenario": {
            "horizonDays": scenario_summary.get("horizonDays"),
            "customers": after_customers,
            "services": scenario_summary["services"],
            "revenue": after_revenue,
        },
        "delta": {
            "highRisk": after_customers["highRisk"] - before_customers["highRisk"],
            "mediumRisk": after_customers["mediumRisk"] - before_customers["mediumRisk"],
            "lowRisk": after_customers["byCategory"].get("low", 0) - before_customers["byCategory"].get("low", 0),
            "insufficientData": after_customers["insufficientData"] - before_customers["insufficientData"],
            "byCategory": _category_delta(before_customers["byCategory"], after_customers["byCategory"]),
            "revenueAtRiskCents": after_revenue["revenueAtRiskCents"] - before_revenue["revenueAtRiskCents"],
            "revenueAtRiskEur": str(cents_to_eur(
                after_revenue["revenueAtRiskCents"] - before_revenue["revenueAtRiskCents"])),
            "upcomingRenewalsCents": after_revenue["upcomingRenewalsCents"] - before_revenue["upcomingRenewalsCents"],
            "servicesHighRisk": scenario_summary["services"]["highRisk"] - baseline_summary["services"]["highRisk"],
        },
        "movements": [
            {
                "customerId": m.customer_id,
                "email": m.email,
                "before": m.before,
                "after": m.after,
                "beforeScore": m.before_score,
                "afterScore": m.after_score,
                "delta": m.delta,
                "direction": m.direction,
                "categoryChanged": m.category_changed,
            }
            for m in movements
        ],
        "movedCustomers": len(movements),
        "categoryChanges": sum(1 for m in movements if m.category_changed),
        "note": (
            "Симуляция не публикуется: она не создаёт новую версию расчёта и не влияет "
            "на данные других пользователей. Чтобы применить модель, сохраните настройки."
        ),
    }
