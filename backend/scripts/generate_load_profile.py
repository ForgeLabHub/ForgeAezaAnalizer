#!/usr/bin/env python3
"""Generate synthetic snapshot profiles for load and capacity testing.

The organiser snapshot is tiny (10 accounts / 30 services / 100 transactions), so
it cannot say anything about behaviour on a real customer base. This script
produces larger snapshots with the *same schema* and the same invariants the
importer validates, so the running application accepts them unchanged.

Everything here is fabricated. No real customer data is read, copied or hashed,
and nothing is written outside the directory passed with ``--out``.

Usage:
    python backend/scripts/generate_load_profile.py --profile medium --out /tmp/profiles
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


REFERENCE = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)

TERMS = ("hour", "week", "month", "quarter_year", "half_year", "year")
STATUSES = ("active", "blocked", "deleted", "suspended", "prolong_wait")


PROFILES = {
    "baseline": {"accounts": 10, "services_per_account": 3, "transactions_per_service": 3},
    "small": {"accounts": 500, "services_per_account": 4, "transactions_per_service": 6},
    "medium": {"accounts": 5_000, "services_per_account": 5, "transactions_per_service": 8},


    "stress": {"accounts": 50_000, "services_per_account": 4, "transactions_per_service": 2},
}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _add_term(value: datetime, term: str) -> datetime:
    if term == "hour":
        return value + timedelta(hours=1)
    if term == "week":
        return value + timedelta(weeks=1)
    days = {"month": 30, "quarter_year": 91, "half_year": 182, "year": 365}[term]
    return value + timedelta(days=days)


def generate(profile: str, seed: int) -> dict:
    spec = PROFILES[profile]
    rng = random.Random(seed)

    accounts = []
    services = []
    transactions = []
    service_id = 0

    for account_id in range(1, spec["accounts"] + 1):
        balance = rng.randint(0, 100_000)
        accounts.append(
            {
                "id": account_id,
                "email": f"load-{account_id:06d}@example.test",
                "balance": balance,
                "withdrawBalance": rng.randint(0, balance),
                "totalReplenished": balance + rng.randint(0, 500_000),
                "bonusBalance": rng.randint(0, 10_000),
                "bonusState": ("locked", "unlocked")[(account_id - 1) % 2],
            }
        )

        for offset in range(spec["services_per_account"]):
            service_id += 1
            term = TERMS[service_id % len(TERMS)]
            status = STATUSES[service_id % len(STATUSES)]


            created = REFERENCE - timedelta(days=rng.randint(1, 400))
            services.append(
                {
                    "id": service_id,
                    "name": f"load-svc-{service_id:06d}",
                    "ownerId": account_id,
                    "paymentTerm": term,
                    "autoProlong": bool(rng.getrandbits(1)),
                    "createdAt": _iso(created),
                    "expiresAt": _iso(_add_term(created, term)),
                    "status": status,
                    "price": rng.randint(1, 1000),
                }
            )

            for n in range(spec["transactions_per_service"]):
                created_at = created + timedelta(minutes=rng.randint(0, 5) + n)
                performed = n % 3 != 0
                transactions.append(
                    {
                        "id": len(transactions) + 1,
                        "amount": rng.randint(0, 1000),
                        "status": "performed" if performed else "not_performed",
                        "performedAt": _iso(created_at + timedelta(seconds=30)) if performed else None,
                        "createdAt": _iso(created_at),
                        "type": "order" if n == 0 else "prolong",
                        "serviceId": service_id,
                    }
                )

    return {"accounts": accounts, "services": services, "transactions": transactions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload = generate(args.profile, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.profile}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(
        f"{args.profile}: accounts={len(payload['accounts'])} "
        f"services={len(payload['services'])} transactions={len(payload['transactions'])} "
        f"-> {target} ({target.stat().st_size} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
