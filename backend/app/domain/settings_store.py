"""Persistence and validation of model settings (weights, horizon, thresholds)."""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ModelSettingsRow
from app.domain.risk import DEFAULT_WEIGHTS, RiskSettings, validate_settings


class SettingsValidationError(ValueError):
    """Raised when a settings update payload is invalid."""


def load_settings(session: Session) -> RiskSettings:
    """Read the persisted settings, falling back to documented defaults."""

    row = session.get(ModelSettingsRow, 1)
    if row is None:
        return RiskSettings()
    try:
        weights = json.loads(row.weights_json)
    except json.JSONDecodeError:
        weights = dict(DEFAULT_WEIGHTS)
    merged = dict(DEFAULT_WEIGHTS)
    for key, value in weights.items():
        if key in merged and isinstance(value, (int, float)) and not isinstance(value, bool):
            merged[key] = float(value)
    try:
        return RiskSettings(
            horizon_days=row.horizon_days,
            weights=merged,
            low_max=row.low_max,
            medium_max=row.medium_max,
            failed_renewal_window_days=row.failed_renewal_window_days,
        )
    except ValueError:
        return RiskSettings()


def save_settings(session: Session, settings: RiskSettings) -> RiskSettings:
    """Persist settings after full validation, upserting the singleton row."""

    validate_settings(settings)
    row = session.get(ModelSettingsRow, 1)
    if row is None:
        row = ModelSettingsRow(id=1)
        session.add(row)
    row.horizon_days = settings.horizon_days
    row.low_max = settings.low_max
    row.medium_max = settings.medium_max
    row.failed_renewal_window_days = settings.failed_renewal_window_days
    row.weights_json = json.dumps(settings.weights, sort_keys=True)
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    return settings


def reset_settings(session: Session) -> RiskSettings:
    """Restore the documented default model configuration."""

    return save_settings(session, RiskSettings())
