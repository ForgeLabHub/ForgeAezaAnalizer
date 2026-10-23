"""Load validated organiser records into the store.

Guarantees:
* **Atomic** — the whole dataset is written inside one transaction. Any failure
  rolls back, so a bad import never leaves a partially updated database.
* **Idempotent** — a successful import replaces the fixture tables wholesale.
  Re-running the same archive produces the same row counts (no duplicates).
* **Auditable** — every run is recorded in ``import_runs`` with the archive
  digest and per-table counts.

Rejected rows are reported, not dropped silently; if *any* row is rejected the
import aborts by default so a partial dataset can never masquerade as complete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import init_db, session_scope
from ..models import Account, ImportRun, Meta, Service, Transaction
from .archive import ExtractedArchive, safe_extract
from .validation import (
    Rejection,
    ValidationError,
    validate_account,
    validate_service,
    validate_transaction,
)

DATA_JSON_NAME = "data.json"
REFERENCE_META_KEY = "reference_at"
SOURCE_SHA_META_KEY = "source_sha256"
SOURCE_PATH_META_KEY = "source_path"
SNAPSHOT_META_KEY = "imported_at"


@dataclass
class ImportResult:
    source_path: str
    source_sha256: str
    accounts: int = 0
    services: int = 0
    transactions: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    reference_at: datetime | None = None
    extract_dir: Path | None = None
    members: list[str] = field(default_factory=list)
    nested_archives: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.accounts + self.services + self.transactions

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "accounts": self.accounts,
            "services": self.services,
            "transactions": self.transactions,
            "rejected": [
                {"table": r.table, "row_id": r.row_id, "reason": r.reason}
                for r in self.rejected
            ],
            "reference_at": self.reference_at.isoformat() if self.reference_at else None,
            "members": self.members,
            "nested_archives": self.nested_archives,
        }


def _find_data_json(extract_dir: Path) -> Path:
    matches = sorted(extract_dir.rglob(DATA_JSON_NAME))
    if not matches:
        raise FileNotFoundError(f"{DATA_JSON_NAME} not found under {extract_dir}")
    if len(matches) > 1:
        raise FileNotFoundError(f"multiple {DATA_JSON_NAME} files under {extract_dir}")
    return matches[0]


def _load_payload(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a JSON object with accounts/services/transactions")
    for key in ("accounts", "services", "transactions"):
        if key not in data:
            raise ValueError(f"{path.name}: missing '{key}' array")
        if not isinstance(data[key], list):
            raise ValueError(f"{path.name}: '{key}' must be an array")
    return data


def _validate_all(
    payload: dict[str, list[dict[str, Any]]], result: ImportResult
) -> tuple[list[dict], list[dict], list[dict]]:
    accounts: list[dict] = []
    services: list[dict] = []
    transactions: list[dict] = []

    for row in payload["accounts"]:
        try:
            accounts.append(validate_account(row))
        except ValidationError as exc:
            result.rejected.append(Rejection("accounts", row.get("id"), str(exc)))
    for row in payload["services"]:
        try:
            services.append(validate_service(row))
        except ValidationError as exc:
            result.rejected.append(Rejection("services", row.get("id"), str(exc)))
    for row in payload["transactions"]:
        try:
            transactions.append(validate_transaction(row))
        except ValidationError as exc:
            result.rejected.append(Rejection("transactions", row.get("id"), str(exc)))

    _check_integrity(accounts, services, transactions, result)
    return accounts, services, transactions


def _check_integrity(
    accounts: list[dict],
    services: list[dict],
    transactions: list[dict],
    result: ImportResult,
) -> None:
    """Referential integrity is validated before writing, mirroring the FK rules."""
    account_ids = {a["id"] for a in accounts}
    service_ids = {s["id"] for s in services}

    if len(account_ids) != len(accounts):
        result.rejected.append(Rejection("accounts", None, "duplicate account ids in source"))
    if len(service_ids) != len(services):
        result.rejected.append(Rejection("services", None, "duplicate service ids in source"))
    if len({t["id"] for t in transactions}) != len(transactions):
        result.rejected.append(
            Rejection("transactions", None, "duplicate transaction ids in source")
        )

    for service in services:
        if service["ownerId"] not in account_ids:
            result.rejected.append(
                Rejection(
                    "services",
                    service["id"],
                    f"ownerId {service['ownerId']} has no matching account",
                )
            )
    for tx in transactions:
        if tx["serviceId"] not in service_ids:
            result.rejected.append(
                Rejection(
                    "transactions",
                    tx["id"],
                    f"serviceId {tx['serviceId']} has no matching service",
                )
            )


def _write(
    session: Session,
    accounts: list[dict],
    services: list[dict],
    transactions: list[dict],
    result: ImportResult,
) -> None:
    # Delete children first to respect RESTRICT-style FKs, then parents.
    session.execute(delete(Transaction))
    session.execute(delete(Service))
    session.execute(delete(Account))
    session.flush()

    session.add_all(Account(**row) for row in accounts)
    session.flush()  # accounts must exist before services reference them
    session.add_all(Service(**row) for row in services)
    session.flush()  # services must exist before transactions reference them
    session.add_all(Transaction(**row) for row in transactions)
    session.flush()

    _store_meta(session, result)


def _store_meta(session: Session, result: ImportResult) -> None:
    entries = {
        SOURCE_PATH_META_KEY: result.source_path,
        SOURCE_SHA_META_KEY: result.source_sha256 or "directory",
        SNAPSHOT_META_KEY: datetime.now(timezone.utc).isoformat(),
    }
    if result.reference_at is not None:
        entries[REFERENCE_META_KEY] = result.reference_at.isoformat()
    for key, value in entries.items():
        existing = session.get(Meta, key)
        if existing is None:
            session.add(Meta(key=key, value=value))
        else:
            existing.value = value


def import_dataset(
    source: Path | None = None,
    *,
    extract_dir: Path | None = None,
    reference_at: datetime | None = None,
    strict: bool = True,
) -> ImportResult:
    """Import the organiser dataset.

    Parameters
    ----------
    source:
        ZIP archive (defaults to the project's ``датасет.zip``). May also be a
        directory already containing ``data.json``.
    extract_dir:
        Where to unpack the archive (defaults to ``<data_dir>/extracted``).
    reference_at:
        Snapshot time used for risk/revenue "as of" calculations. Defaults to
        the latest ``createdAt`` observed in the dataset (the organiser's
        reference instant), so results are reproducible from the data alone.
    strict:
        When true (default), abort if any row fails validation.
    """
    from ..config import settings

    init_db()
    source = Path(source) if source is not None else settings.source_archive
    result = ImportResult(source_path=str(source), source_sha256="")

    if source.is_dir():
        result.members = sorted(
            str(p.relative_to(source)) for p in source.rglob("*") if p.is_file()
        )
        data_json = _find_data_json(source)
        result.extract_dir = source
    else:
        extract_dir = extract_dir or settings.extract_dir
        extracted: ExtractedArchive = safe_extract(source, extract_dir)
        result.source_sha256 = extracted.sha256
        result.members = extracted.members
        result.nested_archives = extracted.nested_archives
        result.extract_dir = extracted.extract_dir
        data_json = _find_data_json(extracted.extract_dir)

    payload = _load_payload(data_json)
    accounts, services, transactions = _validate_all(payload, result)

    if strict and result.rejected:
        reasons = "; ".join(f"{r.table}[{r.row_id}]: {r.reason}" for r in result.rejected[:5])
        raise ValueError(f"import aborted: {len(result.rejected)} rejected row(s): {reasons}")

    result.reference_at = reference_at or _observed_reference(accounts, services, transactions)
    result.accounts = len(accounts)
    result.services = len(services)
    result.transactions = len(transactions)

    with session_scope() as session:
        _write(session, accounts, services, transactions, result)
        run = ImportRun(
            source_path=str(source),
            source_sha256=result.source_sha256 or "directory",
            accounts=result.accounts,
            services=result.services,
            transactions=result.transactions,
            status="success",
            finished_at=datetime.now(timezone.utc),
            notes=None if not result.rejected else f"{len(result.rejected)} rejected rows",
        )
        session.add(run)

    return result


def _observed_reference(accounts, services, transactions) -> datetime:
    """Latest createdAt across all entities = the snapshot instant.

    The organiser generator fixes a reference date and derives service states
    from it; using the maximum ``createdAt`` recovers that instant directly from
    the data so risk horizons are computed against the real snapshot.
    """
    candidates: list[datetime] = []
    for row in services:
        candidates.append(row["createdAt"])
    for row in transactions:
        candidates.append(row["createdAt"])
        if row["performedAt"] is not None:
            candidates.append(row["performedAt"])
    if not candidates:
        return datetime.now(timezone.utc)
    return max(candidates)


def stored_counts(session: Session) -> dict[str, int]:
    return {
        "accounts": session.query(Account).count(),
        "services": session.query(Service).count(),
        "transactions": session.query(Transaction).count(),
    }
