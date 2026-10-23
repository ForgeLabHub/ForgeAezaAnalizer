"""Pydantic request/response models for the public API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Money(BaseModel):
    cents: int
    eur: str


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    email: str


class FactorInfo(BaseModel):
    key: str
    label: str
    description: str
    howComputed: str
    normalization: str
    defaultWeight: float
    missingDataBehaviour: str


class ModelSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizonDays: int = Field(default=30, ge=1, le=365)
    weights: dict[str, float] = Field(default_factory=dict)
    lowMax: int = Field(default=34, ge=0, le=100)
    mediumMax: int = Field(default=64, ge=0, le=100)


class ModelSettingsResponse(BaseModel):
    settings: ModelSettingsPayload
    factors: list[FactorInfo]
    updatedAt: str | None = None
    isDefault: bool


class SettingsPatch(BaseModel):
    """PATCH payload: any subset of fields may be supplied."""

    model_config = ConfigDict(extra="forbid")

    horizonDays: int | None = Field(default=None, ge=1, le=365)
    weights: dict[str, float] | None = None
    lowMax: int | None = Field(default=None, ge=0, le=100)
    mediumMax: int | None = Field(default=None, ge=0, le=100)


class ImportReport(BaseModel):
    status: str
    accepted: dict[str, int]
    rejected: int
    duplicates: int
    previous: dict[str, int]
    message: str


class SnapshotAccepted(BaseModel):
    status: str
    accounts: int
    services: int
    transactions: int


class SourceSnapshotResponse(BaseModel):
    snapshot: SnapshotAccepted
    report: ImportReport


class ErrorResponse(BaseModel):
    detail: str
    extra: dict[str, Any] | None = None
