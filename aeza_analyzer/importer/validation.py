"""Validation and normalisation of organiser records.

The source JSON is the contract. Every record is validated against it; anything
that fails is **rejected with a reason**, never silently rewritten. The importer
reports rejected rows so data problems stay visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models import (
    BONUS_STATES,
    PAYMENT_TERMS,
    SERVICE_STATUSES,
    TRANSACTION_STATUSES,
    TRANSACTION_TYPES,
)

SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ValidationError(ValueError):
    """A single record failed validation."""


@dataclass
class Rejection:
    table: str
    row_id: Any
    reason: str


@dataclass
class ValidationReport:
    rejections: list[Rejection] = field(default_factory=list)

    def reject(self, table: str, row_id: Any, reason: str) -> None:
        self.rejections.append(Rejection(table=table, row_id=row_id, reason=reason))

    @property
    def ok(self) -> bool:
        return not self.rejections


def parse_iso_utc(value: Any, *, field_name: str) -> datetime:
    """Parse a source timestamp, requiring an explicit UTC offset.

    Source values use the ``...Z`` form with millisecond precision. Naive
    timestamps are rejected rather than assumed to be UTC, so timezone handling
    stays explicit.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field_name}: expected ISO string, got {type(value).__name__}")
    if not ISO_Z_RE.match(value):
        raise ValidationError(f"{field_name}: expected 'YYYY-MM-DDTHH:MM:SS.mmmZ', got {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name}: timezone offset missing")
    return parsed.astimezone(timezone.utc)


def _require_int(value: Any, field_name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name}: expected integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{field_name}: must be >= {minimum}, got {value}")
    return value


def _require_str(value: Any, field_name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{field_name}: expected one of {allowed}, got {value!r}")
    return value


def validate_account(row: dict[str, Any]) -> dict[str, Any]:
    account_id = _require_int(row.get("id"), "id", minimum=1)
    email = row.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise ValidationError(f"email: invalid value {email!r}")
    return {
        "id": account_id,
        "email": email,
        "balance": _require_int(row.get("balance"), "balance", minimum=0),
        "withdrawBalance": _require_int(
            row.get("withdrawBalance"), "withdrawBalance", minimum=0
        ),
        "totalReplenished": _require_int(
            row.get("totalReplenished"), "totalReplenished", minimum=0
        ),
        "bonusBalance": _require_int(row.get("bonusBalance"), "bonusBalance", minimum=0),
        "bonusState": _require_str(row.get("bonusState"), "bonusState", BONUS_STATES),
    }


def validate_service(row: dict[str, Any]) -> dict[str, Any]:
    service_id = _require_int(row.get("id"), "id", minimum=1)
    name = row.get("name")
    if not isinstance(name, str) or not SERVICE_NAME_RE.match(name):
        raise ValidationError(f"name: invalid service name {name!r}")
    created = parse_iso_utc(row.get("createdAt"), field_name="createdAt")
    expires = parse_iso_utc(row.get("expiresAt"), field_name="expiresAt")
    if expires < created:
        raise ValidationError(f"expiresAt {expires} precedes createdAt {created}")
    auto = row.get("autoProlong")
    if not isinstance(auto, bool):
        raise ValidationError(f"autoProlong: expected boolean, got {auto!r}")
    return {
        "id": service_id,
        "name": name,
        "ownerId": _require_int(row.get("ownerId"), "ownerId", minimum=1),
        "paymentTerm": _require_str(row.get("paymentTerm"), "paymentTerm", PAYMENT_TERMS),
        "autoProlong": auto,
        "createdAt": created,
        "expiresAt": expires,
        "status": _require_str(row.get("status"), "status", SERVICE_STATUSES),
        "price": _require_int(row.get("price"), "price", minimum=0),
    }


def validate_transaction(row: dict[str, Any]) -> dict[str, Any]:
    tx_id = _require_int(row.get("id"), "id", minimum=1)
    amount = _require_int(row.get("amount"), "amount", minimum=0)
    if amount > 1000:
        raise ValidationError(f"amount: must be <= 1000, got {amount}")
    status = _require_str(row.get("status"), "status", TRANSACTION_STATUSES)
    created = parse_iso_utc(row.get("createdAt"), field_name="createdAt")
    performed_raw = row.get("performedAt")
    performed = (
        parse_iso_utc(performed_raw, field_name="performedAt")
        if performed_raw is not None
        else None
    )
    if status == "not_performed" and performed is not None:
        raise ValidationError("not_performed transaction must have performedAt = null")
    if status == "performed":
        if performed is None:
            raise ValidationError("performed transaction must have performedAt")
        if performed < created:
            raise ValidationError(f"performedAt {performed} precedes createdAt {created}")
    return {
        "id": tx_id,
        "amount": amount,
        "status": status,
        "performedAt": performed,
        "createdAt": created,
        "type": _require_str(row.get("type"), "type", TRANSACTION_TYPES),
        "serviceId": _require_int(row.get("serviceId"), "serviceId", minimum=1),
    }
