"""Validated models for the Aéza source snapshot.

The snapshot shape mirrors the upstream ``data.json`` (and the PostgreSQL
``accounts`` / ``services`` / ``transactions`` tables) one-to-one.  Field names
keep the source camelCase spelling so that an imported snapshot is byte-for-byte
recognisable, while Python code uses snake_case attributes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BonusState = Literal["locked", "unlocked"]
ServiceStatus = Literal["active", "blocked", "deleted", "suspended", "prolong_wait"]
PaymentTerm = Literal["hour", "week", "month", "quarter_year", "half_year", "year"]
TransactionStatus = Literal["performed", "not_performed"]
TransactionType = Literal["prolong", "order"]

NonNegativeCents = Annotated[int, Field(ge=0)]


def _ensure_utc(value: datetime) -> datetime:
    """Normalise any datetime to timezone-aware UTC.

    The snapshot always carries ``Z``-suffixed timestamps, but a hand-edited
    import could omit the offset; treating naive timestamps as UTC keeps every
    downstream comparison (horizon maths, "expires soon" windows) deterministic.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class _SourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Account(_SourceModel):
    id: int
    email: str = Field(min_length=3, max_length=320)


    balance: NonNegativeCents | None = None
    withdraw_balance: NonNegativeCents | None = Field(default=None, alias="withdrawBalance")
    total_replenished: NonNegativeCents | None = Field(default=None, alias="totalReplenished")
    bonus_balance: NonNegativeCents | None = Field(default=None, alias="bonusBalance")
    bonus_state: BonusState | None = Field(default=None, alias="bonusState")

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must contain a local part and a domain")
        return value

    @model_validator(mode="after")
    def _check_balances(self) -> "Account":


        if (
            self.withdraw_balance is not None
            and self.balance is not None
            and self.withdraw_balance > self.balance
        ):
            raise ValueError("withdrawBalance cannot exceed balance")
        if (
            self.total_replenished is not None
            and self.balance is not None
            and self.total_replenished < self.balance
        ):
            raise ValueError("totalReplenished cannot be lower than balance")
        return self


class Service(_SourceModel):
    id: int
    name: str = Field(min_length=1, max_length=128)
    owner_id: int = Field(alias="ownerId")
    payment_term: PaymentTerm = Field(alias="paymentTerm")
    auto_prolong: bool = Field(default=False, alias="autoProlong")
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    status: ServiceStatus
    price: NonNegativeCents

    @field_validator("created_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not all(ch.isalnum() or ch == "-" for ch in value) or not value.isascii():
            raise ValueError("service name allows only ASCII letters, digits and hyphen")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "Service":
        if self.expires_at < self.created_at:
            raise ValueError("expiresAt cannot be earlier than createdAt")
        return self


class Transaction(_SourceModel):
    id: int
    amount: int = Field(ge=0, le=1000)
    status: TransactionStatus = "not_performed"
    performed_at: datetime | None = Field(default=None, alias="performedAt")
    created_at: datetime = Field(alias="createdAt")
    type: TransactionType
    service_id: int = Field(alias="serviceId")

    @field_validator("performed_at", "created_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _ensure_utc(value)

    @model_validator(mode="after")
    def _check_performed(self) -> "Transaction":
        if self.status == "not_performed" and self.performed_at is not None:
            raise ValueError("not_performed transaction cannot carry performedAt")
        if self.status == "performed":
            if self.performed_at is None:
                raise ValueError("performed transaction requires performedAt")
            if self.performed_at < self.created_at:
                raise ValueError("performedAt cannot be earlier than createdAt")
        return self


class Snapshot(BaseModel):
    """A full, self-consistent export of the Aéza dataset."""

    model_config = ConfigDict(extra="forbid")

    accounts: list[Account] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "Snapshot":
        account_ids = [a.id for a in self.accounts]
        service_ids = [s.id for s in self.services]
        if len(set(account_ids)) != len(account_ids):
            raise ValueError("duplicate account ids in snapshot")
        if len(set(service_ids)) != len(service_ids):
            raise ValueError("duplicate service ids in snapshot")
        tx_ids = [t.id for t in self.transactions]
        if len(set(tx_ids)) != len(tx_ids):
            raise ValueError("duplicate transaction ids in snapshot")
        known_accounts = set(account_ids)
        known_services = set(service_ids)
        for service in self.services:
            if service.owner_id not in known_accounts:
                raise ValueError(f"service {service.id} references unknown owner {service.owner_id}")
        for tx in self.transactions:
            if tx.service_id not in known_services:
                raise ValueError(f"transaction {tx.id} references unknown service {tx.service_id}")
        return self
