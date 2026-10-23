"""Lenient, in-memory views over a validated source snapshot.

The runtime validates an incoming snapshot with :mod:`app.source`, which
deliberately permits *unknown* values: ``autoProlong``, ``expiresAt``,
``price``, ``createdAt`` and the monetary fields may all be ``null``.  The
strict :mod:`app.domain.schema` models forbid those nulls because they are used
for the hand-curated organiser dataset.

Analytics must therefore work on the permissive shape.  These views expose the
same snake_case attribute names as the strict models, so the domain functions
(which only read attributes) work with either, and a missing value stays
``None`` all the way into the risk calculation instead of being coerced to a
number.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any


def _utc(value: Any) -> dt.datetime | None:
    """Parse an ISO timestamp from the snapshot into aware UTC.

    Returns ``None`` for a missing value: the caller must decide whether that
    means "unknown" rather than inventing an epoch.
    """

    if value is None:
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


@dataclass(frozen=True)
class AccountView:
    id: int
    email: str
    balance: int | None = None
    withdraw_balance: int | None = None
    total_replenished: int | None = None
    bonus_balance: int | None = None
    bonus_state: str | None = None


@dataclass(frozen=True)
class ServiceView:
    id: int
    name: str
    owner_id: int
    status: str
    price: int | None = None
    auto_prolong: bool | None = None
    payment_term: str | None = None
    created_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None


@dataclass(frozen=True)
class TransactionView:
    id: int
    service_id: int
    type: str
    status: str
    amount: int
    created_at: dt.datetime | None = None
    performed_at: dt.datetime | None = None


@dataclass(frozen=True)
class SourceView:
    accounts: list[AccountView]
    services: list[ServiceView]
    transactions: list[TransactionView]

    def services_of(self, account_id: int) -> list[ServiceView]:
        return [s for s in self.services if s.owner_id == account_id]

    def transactions_of(self, service_id: int) -> list[TransactionView]:
        return [t for t in self.transactions if t.service_id == service_id]


def build_view(source: dict) -> SourceView:
    """Convert a validated snapshot payload into attribute views.

    The payload is expected to have passed :func:`app.source.validate_source`,
    but the accessors stay defensive so a partially populated snapshot produces
    ``None`` fields rather than a crash.
    """

    accounts = [
        AccountView(
            id=row["id"],
            email=row.get("email") or "",
            balance=row.get("balance"),
            withdraw_balance=row.get("withdrawBalance"),
            total_replenished=row.get("totalReplenished"),
            bonus_balance=row.get("bonusBalance"),
            bonus_state=row.get("bonusState"),
        )
        for row in source.get("accounts", [])
    ]
    services = [
        ServiceView(
            id=row["id"],
            name=row.get("name") or "",
            owner_id=row["ownerId"],
            status=row.get("status") or "",
            price=row.get("price"),
            auto_prolong=row.get("autoProlong"),
            payment_term=row.get("paymentTerm"),
            created_at=_utc(row.get("createdAt")),
            expires_at=_utc(row.get("expiresAt")),
        )
        for row in source.get("services", [])
    ]
    transactions = [
        TransactionView(
            id=row["id"],
            service_id=row["serviceId"],
            type=row.get("type") or "",
            status=row.get("status") or "",
            amount=row.get("amount") or 0,
            created_at=_utc(row.get("createdAt")),
            performed_at=_utc(row.get("performedAt")),
        )
        for row in source.get("transactions", [])
    ]
    return SourceView(accounts, services, transactions)
