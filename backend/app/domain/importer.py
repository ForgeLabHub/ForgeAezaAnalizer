"""Atomic snapshot import.

The whole snapshot is validated *before* any row is written, and the write
itself happens inside a single transaction, so a rejected payload can never
leave the database partially updated.
"""

from __future__ import annotations

import datetime as dt

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import AccountRow, ImportRunRow, ServiceRow, TransactionRow
from app.domain.schema import Snapshot


class SnapshotValidationError(ValueError):
    """Raised when an incoming snapshot is structurally or semantically invalid."""

    def __init__(self, message: str, *, rejected: int = 0) -> None:
        super().__init__(message)
        self.rejected = rejected


class ImportResult:
    def __init__(
        self,
        *,
        accounts: int,
        services: int,
        transactions: int,
        rejected: int,
        duplicate_ids: int,
        previous_counts: dict[str, int],
        message: str,
    ) -> None:
        self.accounts = accounts
        self.services = services
        self.transactions = transactions
        self.rejected = rejected
        self.duplicate_ids = duplicate_ids
        self.previous_counts = previous_counts
        self.message = message


def parse_snapshot(payload: object) -> Snapshot:
    """Validate a raw payload into a :class:`Snapshot`.

    Pydantic reports every structural problem (wrong types, negative money,
    bad enum values, broken foreign keys); we convert that into a single
    readable message so the API can return a 422 with an actionable reason.
    """

    if not isinstance(payload, dict):
        raise SnapshotValidationError("snapshot must be a JSON object")
    try:
        return Snapshot.model_validate(payload)
    except ValidationError as exc:
        problems = []
        for err in exc.errors()[:10]:
            loc = ".".join(str(p) for p in err["loc"])
            problems.append(f"{loc}: {err['msg']}")
        raise SnapshotValidationError("; ".join(problems), rejected=len(exc.errors())) from exc


def current_counts(session: Session) -> dict[str, int]:
    return {
        "accounts": session.scalar(select(func.count()).select_from(AccountRow)) or 0,
        "services": session.scalar(select(func.count()).select_from(ServiceRow)) or 0,
        "transactions": session.scalar(select(func.count()).select_from(TransactionRow)) or 0,
    }


def import_snapshot(session: Session, snapshot: Snapshot) -> ImportResult:
    """Replace the dataset with ``snapshot`` atomically.

    The caller owns the transaction (see :func:`app.db.session_scope`).  We
    delete children before parents to respect the foreign keys, then insert in
    the opposite order.
    """

    previous = current_counts(session)
    run = ImportRunRow(
        started_at=dt.datetime.now(dt.timezone.utc),
        status="running",
        message="import in progress",
    )
    session.add(run)
    session.flush()

    try:
        session.execute(delete(TransactionRow))
        session.execute(delete(ServiceRow))
        session.execute(delete(AccountRow))
        session.flush()

        session.bulk_save_objects(
            [
                AccountRow(
                    id=a.id,
                    email=a.email,
                    balance=a.balance,
                    withdraw_balance=a.withdraw_balance,
                    total_replenished=a.total_replenished,
                    bonus_balance=a.bonus_balance,
                    bonus_state=a.bonus_state,
                )
                for a in snapshot.accounts
            ]
        )
        session.flush()
        session.bulk_save_objects(
            [
                ServiceRow(
                    id=s.id,
                    name=s.name,
                    owner_id=s.owner_id,
                    payment_term=s.payment_term,
                    auto_prolong=s.auto_prolong,
                    created_at=s.created_at,
                    expires_at=s.expires_at,
                    status=s.status,
                    price=s.price,
                )
                for s in snapshot.services
            ]
        )
        session.flush()
        session.bulk_save_objects(
            [
                TransactionRow(
                    id=t.id,
                    amount=t.amount,
                    status=t.status,
                    performed_at=t.performed_at,
                    created_at=t.created_at,
                    type=t.type,
                    service_id=t.service_id,
                )
                for t in snapshot.transactions
            ]
        )
        session.flush()

        run.status = "succeeded"
        run.accounts = len(snapshot.accounts)
        run.services = len(snapshot.services)
        run.transactions = len(snapshot.transactions)
        run.rejected = 0
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        run.message = "snapshot applied"
        session.flush()
    except Exception as exc:  # pragma: no cover - defensive
        run.status = "failed"
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        run.message = f"import failed: {exc}"
        session.flush()
        raise

    return ImportResult(
        accounts=len(snapshot.accounts),
        services=len(snapshot.services),
        transactions=len(snapshot.transactions),
        rejected=0,
        duplicate_ids=0,
        previous_counts=previous,
        message="snapshot applied",
    )
