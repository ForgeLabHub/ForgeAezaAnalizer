from __future__ import annotations

from datetime import timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core import InvalidInput

Identifier = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
Cents = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Account(SourceRecord):
    id: Identifier
    email: str = Field(min_length=3, max_length=320)
    balance: Cents | None = None
    withdraw_balance: Cents | None = Field(default=None, alias="withdrawBalance")
    total_replenished: Cents | None = Field(default=None, alias="totalReplenished")
    bonus_balance: Cents | None = Field(default=None, alias="bonusBalance")
    bonus_state: Literal["locked", "unlocked"] | None = Field(default=None, alias="bonusState")

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value.count("@") != 1 or not all(value.split("@")) or any(char.isspace() for char in value):
            raise ValueError("email must contain a local part and a domain without whitespace")
        return value


class Service(SourceRecord):
    id: Identifier
    name: str = Field(min_length=1, max_length=500)
    owner_id: Identifier = Field(alias="ownerId")
    payment_term: Literal["hour", "week", "month", "quarter_year", "half_year", "year"] | None = Field(default=None, alias="paymentTerm")
    auto_prolong: Annotated[bool, Field(strict=True)] | None = Field(default=None, alias="autoProlong")
    created_at: AwareDatetime | None = Field(default=None, alias="createdAt")
    expires_at: AwareDatetime | None = Field(default=None, alias="expiresAt")
    status: Literal["active", "blocked", "deleted", "suspended", "prolong_wait"]
    price: Cents | None = None

    @field_validator("created_at", "expires_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if value else None


class Transaction(SourceRecord):
    id: Identifier
    amount: Annotated[int, Field(strict=True, ge=0, le=1000)]
    status: Literal["performed", "not_performed"]
    performed_at: AwareDatetime | None = Field(default=None, alias="performedAt")
    created_at: AwareDatetime = Field(alias="createdAt")
    type: Literal["prolong", "order"]
    service_id: Identifier = Field(alias="serviceId")

    @field_validator("created_at", "performed_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if value else None


class Snapshot(SourceRecord):
    accounts: tuple[Account, ...] = Field(max_length=100_000)
    services: tuple[Service, ...] = Field(max_length=200_000)
    transactions: tuple[Transaction, ...] = Field(max_length=500_000)

    @model_validator(mode="after")
    def references(self):
        keys = {}
        for name in ("accounts", "services", "transactions"):
            rows = getattr(self, name)
            keys[name] = {row.id for row in rows}
            if len(keys[name]) != len(rows):
                raise ValueError(f"{name}: duplicate id")
        emails = [account.email for account in self.accounts]
        if len(set(emails)) != len(emails):
            raise ValueError("accounts: duplicate email")
        for index, service in enumerate(self.services):
            if service.owner_id not in keys["accounts"]:
                raise ValueError(f"services[{index}].ownerId: unknown account")
        for index, transaction in enumerate(self.transactions):
            if transaction.service_id not in keys["services"]:
                raise ValueError(f"transactions[{index}].serviceId: unknown service")
        return self


def validate_source(payload: dict) -> dict:
    try:
        snapshot = Snapshot.model_validate(payload)
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in exc.errors()[:20]]
        raise InvalidInput("; ".join(errors)) from exc
    result = snapshot.model_dump(mode="json", by_alias=True)
    for rows in result.values():
        rows.sort(key=lambda row: row["id"])
    return result
