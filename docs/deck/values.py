"""Computed facts for the defence decks.

Every number the slides print is derived here by running the real scoring and
revenue engine over the organiser dataset, so a slide cannot drift away from
the product. The module was introduced because the generator used to hold the
figures as string literals captured under an older weighting (73,3 / 5,74 EUR)
while the shipped configuration reproduces 71.4 / 5.80 EUR — the deck and the
product disagreed and nothing caught it.

Import this from ``build_deck.py`` instead of typing a number into a slide.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here, *here.parents):
        if (cand / "dataset").is_dir() and (cand / "backend" / "app" / "domain").is_dir():
            return cand
    raise RuntimeError("repository root with dataset/ and backend/app/domain/ not found")


ROOT = _repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import State  # noqa: E402
from backend.app.domain.module import create as create_engine  # noqa: E402

#: Reference instant of the organiser dataset, so results are reproducible.
AS_OF = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)

#: The client the walkthrough follows.
CUSTOMER_ID = 10
#: The service whose factor breakdown the deck explains.
SERVICE_ID = 30
#: The weight the demo raises, and the value it is raised to.
DEMO_FACTOR = "expiry_proximity"
DEMO_FROM = 3.0
DEMO_TO = 9.0


def _eur(cents: int | None) -> str:
    """Format eurocents the way the interface does: 420669 -> '4 206,69'."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", "\u00a0")
    return f"{sign}{grouped},{rest:02d}"


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


def _run(weights: dict[str, float]) -> tuple[dict, dict]:
    """Score the organiser dataset under ``weights``; return (customer, summary)."""
    data = json.loads((ROOT / "dataset" / "data.json").read_text(encoding="utf-8"))
    engine = create_engine()
    state = State(
        generation=1, source_version=1, model_version=1, source=data,
        settings={"horizonDays": 30, "weights": weights, "lowMax": 34, "mediumMax": 64},
        captured_at=AS_OF, as_of=AS_OF, calculated_at=AS_OF,
    )
    analysis = engine.calculate(state)
    customer = {item["id"]: item for item in analysis.customers}[CUSTOMER_ID]
    return customer, analysis.summary


def facts() -> dict:
    """All slide values, computed from the engine."""

    engine = create_engine()
    defaults = engine.definition().defaults
    base_weights = dict(defaults["weights"])
    demo_weights = {**base_weights, DEMO_FACTOR: DEMO_TO}

    customer, summary = _run(base_weights)
    after_customer, after_summary = _run(demo_weights)

    service = {item["id"]: item for item in customer["services"]}[SERVICE_ID]
    after_service = {item["id"]: item for item in after_customer["services"]}[SERVICE_ID]
    factors = [f for f in service["factors"] if f.get("available")]
    top = sorted(factors, key=lambda f: f["contribution"], reverse=True)

    contrib_sum = round(sum(f["contribution"] for f in factors), 1)
    weight_total = round(sum(f["weight"] for f in factors), 1)
    # The three factors with the largest contribution, formatted as the deck
    # spells them out: "3,0 + 2,5 + 2,0 = 7,5".
    top3 = top[:3]
    top3_sum = round(sum(f["contribution"] for f in top3), 1)

    return {
        "as_of": AS_OF.strftime("%Y-%m-%d %H:%M UTC"),
        "dataset": {"accounts": 10, "services": 30, "transactions": 100},
        "weight_sum": round(sum(base_weights.values()), 1),
        "weights": base_weights,
        "demo": {"factor": DEMO_FACTOR, "from": DEMO_FROM, "to": DEMO_TO,
                 "weight_sum_after": round(sum(demo_weights.values()), 1)},
        "customer": {
            "id": CUSTOMER_ID,
            "email": customer["email"],
            "score": _score(customer["riskScore"]),
            "score_raw": customer["riskScore"],
            "category": customer["riskCategory"],
            "balance_eur": _eur(customer["balance"]["cents"]),
            "replenished_eur": _eur(customer["totalReplenished"]["cents"]),
            "revenue_eur": _eur(customer["revenueAtRisk"]["cents"]),
            "services": len(customer["services"]),
        },
        "service": {
            "id": SERVICE_ID,
            "score": _score(service["riskScore"]),
            "days_to_expiry": service.get("daysToExpiry"),
            "top": [(f["label"], f["weight"], f["contribution"]) for f in top[:3]],
            "factors": [(f["label"], f["weight"], f["contribution"]) for f in factors],
            "contrib_sum": _score(contrib_sum),
            "weight_total": _score(weight_total),
            "top3_terms": " + ".join(_score(f["contribution"]) for f in top3),
            "top3_sum": _score(top3_sum),
        },
        "revenue": {
            "total_eur": summary["revenue"]["revenueAtRiskEur"].replace(".", ","),
            "upcoming_eur": summary["revenue"]["upcomingRenewalsEur"].replace(".", ","),
            "historical_eur": _eur(summary["revenue"]["historicalReplenishedCents"]),
            "after_eur": after_summary["revenue"]["revenueAtRiskEur"].replace(".", ","),
        },
        "categories": summary["customers"]["byCategory"],
        "after": {
            "score": _score(after_customer["riskScore"]),
            "service_score": _score(after_service["riskScore"]),
        },
    }


if __name__ == "__main__":
    print(json.dumps(facts(), ensure_ascii=False, indent=2))
