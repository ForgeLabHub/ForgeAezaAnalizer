"""Scenario (what-if), data-quality and priority views over the analytics core.

These are *views*: they never recompute a formula of their own.  A scenario is
evaluated by handing an alternative settings dict to the same
``AnalyticsModule`` the live product uses, so a scenario can never drift from
the published numbers.  The data-quality and priority helpers read the already
calculated customer payloads and classify them; they do not touch risk maths.

Why scenarios live here rather than in storage
----------------------------------------------
The platform owns one published generation and swaps it atomically.  A scenario
must not disturb that: it is computed on demand, returned to the caller, and
discarded.  Nothing is written, so viewing a scenario cannot change the working
configuration - which is the property the task insists on.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime

#: Parameters a scenario is allowed to override.  Anything else is rejected so
#: a scenario can never reach balances, prices, statuses or raw transactions.
SCENARIO_PARAMETERS = ("weights", "horizonDays", "lowMax", "mediumMax", "failedRenewalWindowDays")


class ScenarioError(ValueError):
    """Raised when a scenario asks for something the model cannot do."""


@dataclass
class ScenarioDefinition:
    """An isolated, named set of parameter overrides."""

    name: str
    overrides: dict = field(default_factory=dict)

    def cleaned(self) -> dict:
        unknown = set(self.overrides) - set(SCENARIO_PARAMETERS)
        if unknown:
            raise ScenarioError(
                f"сценарий не может менять параметры: {sorted(unknown)}; "
                f"разрешены {list(SCENARIO_PARAMETERS)}"
            )
        return copy.deepcopy(self.overrides)


def apply_overrides(base: dict, overrides: dict) -> dict:
    """Return a new settings dict with the scenario applied.

    ``weights`` merges per key so a scenario can move one weight without having
    to restate the others.  An explicit ``None`` for the window is preserved,
    because "whole snapshot" is a meaningful value distinct from "unchanged".
    """

    candidate = copy.deepcopy(base)
    for key, value in overrides.items():
        if key == "weights" and isinstance(value, dict):
            candidate.setdefault("weights", {})
            candidate["weights"] = {**candidate["weights"], **value}
        else:
            candidate[key] = value
    return candidate


def _change(before, after) -> dict:
    """Absolute and relative change, with no division by zero."""

    absolute = None
    relative = None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        absolute = after - before
        if before:
            relative = (after - before) / abs(before)
    return {"baseline": before, "scenario": after, "absolute": absolute, "relative": relative}


def compare(baseline: dict, scenario: dict) -> dict:
    """Compare two published summaries on the same snapshot.

    Only metrics the summaries actually carry are compared; nothing is
    invented.  Every value is reported with its absolute change, and a
    relative change only when the baseline is non-zero.
    """

    base_customers = baseline.get("customers", {})
    scen_customers = scenario.get("customers", {})
    base_revenue = baseline.get("revenue", {})
    scen_revenue = scenario.get("revenue", {})
    base_services = baseline.get("services", {})
    scen_services = scenario.get("services", {})

    categories = {}
    for name in sorted(set(base_customers.get("byCategory", {})) | set(scen_customers.get("byCategory", {}))):
        categories[name] = _change(
            base_customers.get("byCategory", {}).get(name, 0),
            scen_customers.get("byCategory", {}).get(name, 0),
        )

    return {
        "horizonDays": _change(baseline.get("horizonDays"), scenario.get("horizonDays")),
        "revenueAtRiskCents": _change(
            base_revenue.get("revenueAtRiskCents"), scen_revenue.get("revenueAtRiskCents")
        ),
        "upcomingRenewalsCents": _change(
            base_revenue.get("upcomingRenewalsCents"), scen_revenue.get("upcomingRenewalsCents")
        ),
        "highRiskCustomers": _change(base_customers.get("highRisk"), scen_customers.get("highRisk")),
        "mediumRiskCustomers": _change(base_customers.get("mediumRisk"), scen_customers.get("mediumRisk")),
        "highRiskServices": _change(base_services.get("highRisk"), scen_services.get("highRisk")),
        "categories": categories,
        "note": (
            "Сценарий показывает чувствительность эвристической методологии, "
            "а не влияние на реальное поведение клиентов."
        ),
    }


def customer_changes(baseline: list[dict], scenario: list[dict]) -> list[dict]:
    """Per-customer score and category movement between two calculations."""

    base = {item["id"]: item for item in baseline}
    out = []
    for item in scenario:
        before = base.get(item["id"])
        if before is None:
            continue
        if before.get("riskScore") == item.get("riskScore") and before.get("riskCategory") == item.get("riskCategory"):
            continue
        out.append(
            {
                "id": item["id"],
                "email": item.get("email"),
                "scoreBefore": before.get("riskScore"),
                "scoreAfter": item.get("riskScore"),
                "categoryBefore": before.get("riskCategory"),
                "categoryAfter": item.get("riskCategory"),
                "categoryChanged": before.get("riskCategory") != item.get("riskCategory"),
                "revenueAtRiskBefore": (before.get("revenueAtRisk") or {}).get("cents"),
                "revenueAtRiskAfter": (item.get("revenueAtRisk") or {}).get("cents"),
            }
        )
    out.sort(key=lambda row: abs((row["scoreAfter"] or 0) - (row["scoreBefore"] or 0)), reverse=True)
    return out


def factor_availability(baseline: list[dict], scenario: list[dict]) -> dict:
    """Count services whose factors appeared or disappeared between runs.

    The approved "unknown is not zero" rule means switching the failed-renewal
    window can *raise* a score: a factor that was measured becomes unknown and
    drops out of the weighted mean.  That is easy to misread, so the counts are
    reported explicitly.
    """

    def tally(customers):
        out: dict[str, dict[str, int]] = {}
        for customer in customers:
            for service in customer.get("services", []):
                for factor in service.get("factors", []):
                    entry = out.setdefault(factor["key"], {"available": 0, "unknown": 0})
                    entry["available" if factor.get("available") else "unknown"] += 1
        return out

    before, after = tally(baseline), tally(scenario)
    result = {}
    for key in sorted(set(before) | set(after)):
        b = before.get(key, {"available": 0, "unknown": 0})
        a = after.get(key, {"available": 0, "unknown": 0})
        if b == a:
            continue
        result[key] = {
            "availableBefore": b["available"],
            "availableAfter": a["available"],
            "unknownBefore": b["unknown"],
            "unknownAfter": a["unknown"],
            "becameUnknown": max(0, a["unknown"] - b["unknown"]),
            "becameAvailable": max(0, a["available"] - b["available"]),
        }
    return result


# --------------------------------------------------------------------- quality

#: Severity levels and what they mean.  Kept next to the checks so the
#: documentation cannot drift from the code.
QUALITY_LEVELS = {
    "critical": "Расчёт по записи может быть неверным; требуется проверка данных.",
    "warning": "Данные выглядят подозрительно; расчёт возможен, но интерпретируйте осторожно.",
    "info": "Наблюдение, не влияющее на корректность расчёта.",
}

PROLONG_WAIT_GRACE_DAYS = 5


def _issue(level, code, message, records, action) -> dict:
    return {
        "level": level,
        "code": code,
        "message": message,
        "count": len(records),
        "records": records[:50],
        "action": action,
    }


def inspect_source(source: dict, *, as_of: datetime | None = None) -> dict:
    """Audit the raw snapshot without changing a single record.

    Checks are limited to what the data model can actually prove.  The README
    states balances are not derived from transactions, so no balance-versus-
    ledger reconciliation is attempted - asserting it would invent a rule the
    schema does not have.
    """

    accounts = source.get("accounts", [])
    services = source.get("services", [])
    transactions = source.get("transactions", [])
    issues: list[dict] = []

    missing_money = [
        a["id"] for a in accounts
        if any(a.get(field) is None for field in ("balance", "withdrawBalance", "totalReplenished", "bonusBalance"))
    ]
    if missing_money:
        issues.append(_issue(
            "warning", "missing_money_field",
            "У аккаунта отсутствует денежное поле; соответствующий фактор останется неизвестным.",
            missing_money, "Проверить выгрузку: пропущенное значение не трактуется как ноль.",
        ))

    negative = [
        a["id"] for a in accounts
        if any(isinstance(a.get(f), int) and a[f] < 0
               for f in ("balance", "withdrawBalance", "totalReplenished", "bonusBalance"))
    ]
    if negative:
        issues.append(_issue(
            "critical", "negative_amount",
            "Отрицательная денежная сумма противоречит схеме источника.", negative,
            "Исправить выгрузку: отрицательные балансы недопустимы.",
        ))

    dangling = [s["id"] for s in services if s.get("ownerId") not in {a["id"] for a in accounts}]
    if dangling:
        issues.append(_issue(
            "critical", "unknown_owner",
            "Услуга ссылается на несуществующий аккаунт.", dangling,
            "Восстановить связь до расчёта.",
        ))

    orphan_tx = [t["id"] for t in transactions if t.get("serviceId") not in {s["id"] for s in services}]
    if orphan_tx:
        issues.append(_issue(
            "critical", "unknown_service",
            "Транзакция ссылается на несуществующую услугу.", orphan_tx,
            "Восстановить связь до расчёта.",
        ))

    if as_of is not None:
        overdue = []
        inconsistent = []
        for service in services:
            expires = service.get("expiresAt")
            if not expires:
                continue
            parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if parsed < as_of and service.get("status") in ("active", "suspended", "prolong_wait"):
                overdue.append(service["id"])
                if service.get("status") == "prolong_wait" and (as_of - parsed).days > PROLONG_WAIT_GRACE_DAYS:
                    inconsistent.append(service["id"])
        if overdue:
            issues.append(_issue(
                "info", "overdue_open_service",
                "Услуга открыта, но срок окончания уже прошёл: нет будущего продления, нужна проверка.",
                overdue, "Проверить операционное состояние услуги.",
            ))
        if inconsistent:
            issues.append(_issue(
                "warning", "lifecycle_inconsistent",
                f"prolong_wait дольше {PROLONG_WAIT_GRACE_DAYS} дней: по регламенту услуга должна была перейти в deleted.",
                inconsistent, "Сверить состояние с регламентом перехода статусов.",
            ))

    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue["level"]] += 1

    return {
        "levels": QUALITY_LEVELS,
        "issues": issues,
        "counts": counts,
        "recordsInspected": {
            "accounts": len(accounts), "services": len(services), "transactions": len(transactions)
        },
        "note": (
            "Проверка только читает снимок и не меняет записи. Балансы не сверяются "
            "с транзакциями: README источника прямо указывает, что они не выводятся из них."
        ),
    }


# -------------------------------------------------------------------- priority

#: Categorical work queues.  These organise attention; they are NOT risk classes
#: and carry no probability.  A customer can belong to several.
PRIORITY_CATEGORIES = {
    "operational_attention": "Подтверждённая операционная проблема: просроченное продление или противоречие регламенту.",
    "high_risk_with_exposure": "Высокий риск и ненулевая будущая экспозиция на выбранном горизонте.",
    "high_risk_review": "Высокий риск без ненулевой экспозиции на выбранном горизонте.",
    "data_quality_review": "Есть проблема качества данных, влияющая на доверие к оценке.",
    "normal_review": "Ни одно из перечисленных оснований не сработало.",
}


def priority_for(customer: dict, *, horizon_days: int, quality_ids: set[int]) -> list[str]:
    """Return every category that applies, most urgent first.

    All matching reasons are kept rather than collapsed to one label, so the
    operator can see why a row is in the queue.
    """

    reasons: list[str] = []
    if (customer.get("overdueServiceCount") or 0) > 0 or (customer.get("lifecycleInconsistentCount") or 0) > 0:
        reasons.append("operational_attention")

    exposure = (customer.get("exposureByHorizon") or [])
    on_horizon = next((h for h in exposure if h.get("horizonDays") == horizon_days), None)
    exposed_cents = None
    if on_horizon is not None:
        exposed_cents = (on_horizon.get("revenueAtRisk") or {}).get("cents")

    if customer.get("riskCategory") == "high":
        if exposed_cents:
            reasons.append("high_risk_with_exposure")
        else:
            reasons.append("high_risk_review")

    if customer.get("id") in quality_ids:
        reasons.append("data_quality_review")

    if not reasons:
        reasons.append("normal_review")
    return reasons


def urgency_rank(customer: dict) -> int:
    """Ordinal urgency used only for ordering, never shown as a probability."""

    if (customer.get("lifecycleInconsistentCount") or 0) > 0:
        return 0
    if (customer.get("overdueServiceCount") or 0) > 0:
        return 1
    if customer.get("riskCategory") == "high":
        return 2
    if customer.get("riskCategory") == "medium":
        return 3
    return 4
