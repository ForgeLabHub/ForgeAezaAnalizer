"""Derive the deck's canonical figures from the domain modules.

The deck README claims every number comes from the product. This script is the
check that makes that claim true: it runs the same scoring and exposure code the
API runs, over the organiser snapshot at the fixed reference instant, and prints
the values the slides must show.

Run from the repository root:

    env -u LD_LIBRARY_PATH python3 docs/deck/deck_figures.py

It is deliberately dependency-light: it imports the domain package only.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from core import State  # noqa: E402
from backend.app.domain.module import create  # noqa: E402

AS_OF = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
DEMO_WEIGHT = "expiry_proximity"
DEMO_FROM, DEMO_TO = 3.0, 9.0


def analyse(settings: dict) -> tuple[dict, list[dict]]:
    source = json.loads((ROOT / "dataset" / "data.json").read_text(encoding="utf-8"))
    module = create()
    state = State(generation=1, source_version=1, model_version=1,
                  source=source, settings=settings, as_of=AS_OF)
    result = module.calculate(state)
    return result.summary, result.customers


def baseline_settings() -> dict:
    return dict(create().definition().defaults)


def show(label: str, value) -> None:
    print(f"{label}: {value}")


def main() -> int:
    base = baseline_settings()
    summary, customers = analyse(base)

    rev = summary["revenue"]
    cust = summary["customers"]
    svc = summary["services"]

    print("== baseline (defaults) ==")
    show("revenueAtRisk", rev["revenueAtRiskEur"])
    show("upcomingRenewals", rev["upcomingRenewalsEur"])
    show("historicalReplenished", rev["historicalReplenishedEur"])
    show("customers.byCategory", json.dumps(cust["byCategory"], ensure_ascii=False))
    show("services.open/total", f"{svc['open']}/{svc['total']}")
    show("services.highRisk", svc["highRisk"])
    show("topRiskReasons",
         [(r["label"], r["count"]) for r in summary["topRiskReasons"]])
    show("upcoming renewal amounts",
         [(r["serviceName"], r["amountEur"], r["revenueAtRiskEur"])
          for r in summary["upcomingRenewals"]])

    c10 = next(c for c in customers if c["id"] == 10)
    show("customer 10 score/category", f"{c10['riskScore']} {c10['riskCategory']}")
    show("customer 10 revenueAtRisk", c10["revenueAtRisk"]["eur"])
    show("customer 10 balance/replenished",
         f"{c10['balance']['eur']} / {c10['totalReplenished']['eur']}")

    s30 = next(s for s in c10["services"] if s["name"] == "service-0030")
    show("service-0030 score", s30["riskScore"])
    show("service-0030 reasons", s30["reasons"])
    rated = [f for f in s30["factors"] if f["available"] and f["weight"] > 0]
    show("service-0030 rated factors",
         [(f["label"], f["value"], f["weight"], f["contribution"]) for f in rated])
    wsum = sum(f["weight"] for f in rated)
    csum = sum(f["contribution"] for f in rated)
    show("service-0030 weight sum / contribution sum", f"{wsum} / {csum}")
    show("service-0030 implied score", round(100.0 * csum / wsum, 1))

    # The demo re-weights one factor; report exactly what that changes.
    tuned = dict(base)
    tuned_weights = dict(base["weights"])
    tuned_weights[DEMO_WEIGHT] = DEMO_TO
    tuned["weights"] = tuned_weights
    t_summary, t_customers = analyse(tuned)
    t_c10 = next(c for c in t_customers if c["id"] == 10)

    print(f"== after {DEMO_WEIGHT} {DEMO_FROM} -> {DEMO_TO} ==")
    show("sum of weights", f"{sum(base['weights'].values())} -> {sum(tuned_weights.values())}")
    show("customer 10 score", f"{c10['riskScore']} -> {t_c10['riskScore']}")
    show("services.highRisk", f"{svc['highRisk']} -> {t_summary['services']['highRisk']}")
    show("customers.byCategory", json.dumps(t_summary["customers"]["byCategory"], ensure_ascii=False))
    show("revenueAtRisk",
         f"{rev['revenueAtRiskEur']} -> {t_summary['revenue']['revenueAtRiskEur']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
