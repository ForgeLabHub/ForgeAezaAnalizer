"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WeightsPayload(BaseModel):
    weights: dict[str, float] = Field(
        ..., description="Partial or full mapping of factor key -> weight (>= 0)"
    )


class ImportPayload(BaseModel):
    source: str | None = Field(
        default=None, description="Optional path to a ZIP archive or extracted directory"
    )
    horizon_days: int = Field(default=30, ge=1, le=365)
