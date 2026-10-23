"""Reproducible data profile of the imported store.

Produces the quantitative audit the task requires (row counts, uniqueness,
missing values, distributions, ranges) directly from stored data, so the profile
can be regenerated after any change to the source archives.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, Meta, Service, Transaction


def _numeric_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 2),
        "median": statistics.median(values),
    }


def _distribution(values: list[str]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for value in values:
        dist[value] = dist.get(value, 0) + 1
    return dict(sorted(dist.items()))


def profile_store(session: Session, reference_at: datetime | None = None) -> dict[str, Any]:
    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    services = list(session.scalars(select(Service).order_by(Service.id)))
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.id)))

    if reference_at is None:
        meta = session.get(Meta, "reference_at")
        if meta is not None:
            reference_at = datetime.fromisoformat(meta.value)
        else:
            reference_at = max(
                (s.createdAt for s in services), default=datetime.now(timezone.utc)
            )

    account_ids = {a.id for a in accounts}
    service_ids = {s.id for s in services}

    account_emails = [a.email for a in accounts]
    service_names = [s.name for s in services]
    tx_created = [t.createdAt for t in transactions]

    return {
        "row_counts": {
            "accounts": len(accounts),
            "services": len(services),
            "transactions": len(transactions),
        },
        "reference_at": reference_at.isoformat(),
        "accounts": {
            "unique_ids": len(account_ids),
            "unique_emails": len(set(account_emails)),
            "duplicate_emails": sorted(
                {e for e in account_emails if account_emails.count(e) > 1}
            ),
            "missing_values": {
                field: sum(
                    1
                    for a in accounts
                    if getattr(a, field) is None
                )
                for field in ("email", "balance", "withdrawBalance", "totalReplenished",
                              "bonusBalance", "bonusState")
            },
            "balance_cents": _numeric_summary([a.balance for a in accounts]),
            "withdrawBalance_cents": _numeric_summary([a.withdrawBalance for a in accounts]),
            "totalReplenished_cents": _numeric_summary([a.totalReplenished for a in accounts]),
            "bonusBalance_cents": _numeric_summary([a.bonusBalance for a in accounts]),
            "bonusState": _distribution([a.bonusState for a in accounts]),
        },
        "services": {
            "unique_ids": len(service_ids),
            "unique_names": len(set(service_names)),
            "status": _distribution([s.status for s in services]),
            "paymentTerm": _distribution([s.paymentTerm for s in services]),
            "autoProlong": _distribution([str(s.autoProlong) for s in services]),
            "price_cents": _numeric_summary([s.price for s in services]),
            "services_per_owner": _distribution([str(s.ownerId) for s in services]),
            "orphan_owner_ids": sorted({s.ownerId for s in services} - account_ids),
            "expired_at_snapshot": sum(
                1 for s in services if s.expiresAt < reference_at
            ),
        },
        "transactions": {
            "unique_ids": len({t.id for t in transactions}),
            "status": _distribution([t.status for t in transactions]),
            "type": _distribution([t.type for t in transactions]),
            "amount": _numeric_summary([t.amount for t in transactions]),
            "performed_at_null": sum(1 for t in transactions if t.performedAt is None),
            "orphan_service_ids": sorted({t.serviceId for t in transactions} - service_ids),
            "created_range": [
                min(tx_created).isoformat() if tx_created else None,
                max(tx_created).isoformat() if tx_created else None,
            ],
        },
        "integrity": {
            "services_without_account": sum(1 for s in services if s.ownerId not in account_ids),
            "transactions_without_service": sum(
                1 for t in transactions if t.serviceId not in service_ids
            ),
        },
    }
