"""Model settings routes: read, patch and reset the scoring configuration."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, get_db
from app.api.schemas import FactorInfo, ModelSettingsPayload, ModelSettingsResponse, SettingsPatch
from app.db import ModelSettingsRow
from app.domain.risk import DEFAULT_WEIGHTS, FACTORS, RiskConfigError, RiskSettings, validate_settings
from app.domain.settings_store import load_settings, reset_settings, save_settings

router = APIRouter(prefix="/model", tags=["model"])


def _factor_info() -> list[FactorInfo]:
    return [
        FactorInfo(
            key=f.key,
            label=f.label,
            description=f.description,
            howComputed=f.how_computed,
            normalization=f.normalization,
            defaultWeight=f.default_weight,
            missingDataBehaviour=f.missing_data_behaviour,
        )
        for f in FACTORS
    ]


def _payload(settings: RiskSettings) -> ModelSettingsPayload:
    return ModelSettingsPayload(
        horizonDays=settings.horizon_days,
        weights={k: float(v) for k, v in settings.weights.items()},
        lowMax=settings.low_max,
        mediumMax=settings.medium_max,
    )


def _response(session: Session, settings: RiskSettings) -> ModelSettingsResponse:
    row = session.get(ModelSettingsRow, 1)
    updated = row.updated_at.isoformat() if row is not None and row.updated_at else None
    is_default = (
        settings.horizon_days == 30
        and settings.low_max == 34
        and settings.medium_max == 64
        and all(
            abs(settings.weights.get(k, 0.0) - v) < 1e-9 for k, v in DEFAULT_WEIGHTS.items()
        )
    )
    return ModelSettingsResponse(
        settings=_payload(settings), factors=_factor_info(), updatedAt=updated, isDefault=is_default
    )


@router.get("/settings", response_model=ModelSettingsResponse, summary="Текущие настройки модели")
def get_model_settings(
    session: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> ModelSettingsResponse:
    return _response(session, load_settings(session))


@router.patch("/settings", response_model=ModelSettingsResponse, summary="Изменить настройки модели")
def patch_model_settings(
    patch: SettingsPatch,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ModelSettingsResponse:
    """Update weights, horizon and thresholds.

    The merged configuration is validated as a whole, so a partial patch can
    never persist an inconsistent state.  Weights must be non-negative and
    finite; unknown factor keys are rejected.
    """

    current = load_settings(session)

    weights = dict(current.weights)
    if patch.weights is not None:
        unknown = set(patch.weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Неизвестные факторы: {sorted(unknown)}",
            )
        for key, value in patch.weights.items():
            weights[key] = float(value)

    candidate_weights = weights
    candidate_horizon = (
        patch.horizonDays if patch.horizonDays is not None else current.horizon_days
    )
    candidate_low = patch.lowMax if patch.lowMax is not None else current.low_max
    candidate_medium = patch.mediumMax if patch.mediumMax is not None else current.medium_max

    # RiskSettings validates on construction, so the whole merge must be inside
    # the guard to turn a bad payload into a 422 rather than a 500.
    try:
        candidate = RiskSettings(
            horizon_days=candidate_horizon,
            weights=candidate_weights,
            low_max=candidate_low,
            medium_max=candidate_medium,
        )
        validate_settings(candidate)
    except RiskConfigError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    save_settings(session, candidate)
    session.commit()
    return _response(session, candidate)


@router.post(
    "/settings/reset", response_model=ModelSettingsResponse, summary="Сбросить настройки модели"
)
def reset_model_settings(
    session: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> ModelSettingsResponse:
    settings = reset_settings(session)
    session.commit()
    return _response(session, settings)
