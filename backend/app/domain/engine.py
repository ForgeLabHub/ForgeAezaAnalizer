"""Concrete analytics module that connects the domain layer to the runtime.

``backend/app/modules.py`` defines the ``AnalyticsModule`` contract and ships
only a 503 stub.  This module is the real implementation: it validates settings
through :mod:`app.domain.risk`, computes results with
:class:`app.domain.analytics.AnalyticsService`, and serialises them into the
payload shapes the API already publishes.

It contains no formulas of its own.  Risk, exposure and recommendations are
produced by the domain functions, so the numbers the API returns and the numbers
the domain tests assert are the same by construction.

Wire it up with::

    AEZA_ANALYTICS_FACTORY=app.domain.engine:create
"""

from __future__ import annotations

from core import Analysis, InvalidInput, State

from app.domain.analytics import AnalyticsService
from app.domain.risk import (
    DEFAULT_MEDIUM_MAX,
    DEFAULT_LOW_MAX,
    DEFAULT_WEIGHTS,
    FAILED_RENEWAL_WINDOW_DAYS,
    FACTORS,
    RiskConfigError,
    RiskSettings,
    validate_settings,
)
from app.domain.source_view import build_view
from app.modules import ModelDefinition

#: Bumped whenever the algorithm or the settings contract changes, so the
#: runtime recalculates a previously published result after a deploy.
ENGINE_VERSION = "aeza-domain-2"

DEFAULT_SETTINGS = {
    "horizonDays": 30,
    "weights": dict(DEFAULT_WEIGHTS),
    "lowMax": DEFAULT_LOW_MAX,
    "mediumMax": DEFAULT_MEDIUM_MAX,
    "failedRenewalWindowDays": FAILED_RENEWAL_WINDOW_DAYS,
}

#: Settings keys accepted from a patch.  Anything else is rejected instead of
#: being silently dropped, because a typo in a weight name would otherwise look
#: like a successful update that changed nothing.
ALLOWED_SETTING_KEYS = frozenset(DEFAULT_SETTINGS)


def _factor_documents() -> tuple[dict, ...]:
    """Describe every factor from its single source of truth in the domain."""

    return tuple(
        {
            "key": f.key,
            "label": f.label,
            "description": f.description,
            "howComputed": f.how_computed,
            "normalization": f.normalization,
            "defaultWeight": f.default_weight,
            "missingDataBehaviour": f.missing_data_behaviour,
        }
        for f in FACTORS
    )


def _to_settings(payload: dict) -> RiskSettings:
    """Build a validated :class:`RiskSettings` from an API settings payload."""

    weights = dict(payload.get("weights") or {})
    window = payload.get("failedRenewalWindowDays", FAILED_RENEWAL_WINDOW_DAYS)
    try:
        return RiskSettings(
            horizon_days=int(payload.get("horizonDays", 30)),
            weights={key: float(value) for key, value in weights.items()},
            low_max=int(payload.get("lowMax", DEFAULT_LOW_MAX)),
            medium_max=int(payload.get("mediumMax", DEFAULT_MEDIUM_MAX)),
            failed_renewal_window_days=None if window is None else int(window),
        )
    except RiskConfigError as exc:
        raise InvalidInput(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise InvalidInput(f"Некорректные настройки модели: {exc}") from exc


class DomainAnalytics:
    """Real analytics module: domain formulas behind the runtime contract."""

    def definition(self) -> ModelDefinition:
        return ModelDefinition(dict(DEFAULT_SETTINGS), _factor_documents(), ENGINE_VERSION)

    def validate_settings(self, settings: dict) -> dict:
        """Reject unknown keys and out-of-range values before persisting."""

        unknown = set(settings) - ALLOWED_SETTING_KEYS
        if unknown:
            raise InvalidInput(f"Неизвестные параметры модели: {sorted(unknown)}")
        unknown_factors = set(settings.get("weights") or {}) - set(DEFAULT_WEIGHTS)
        if unknown_factors:
            raise InvalidInput(f"Неизвестные факторы: {sorted(unknown_factors)}")
        validated = _to_settings(settings)
        validate_settings(validated)
        return {
            "horizonDays": validated.horizon_days,
            "weights": dict(validated.weights),
            "lowMax": validated.low_max,
            "mediumMax": validated.medium_max,
            "failedRenewalWindowDays": validated.failed_renewal_window_days,
        }

    def calculate(self, state: State) -> Analysis:
        if state.as_of is None:
            # The runtime always stamps ``as_of``; refusing here turns a silent
            # "everything is overdue" result into an explicit contract error.
            raise InvalidInput("Время расчёта (as_of) не задано")
        settings = _to_settings(state.settings)
        view = build_view(state.source)
        service = AnalyticsService(view, settings, state.as_of)
        analyses = service.analyze_all()
        summary = service.summary(analyses)
        return Analysis(summary, [self._customer(analysis) for analysis in analyses])

    @staticmethod
    def _customer(analysis) -> dict:
        from app.api.serializers import customer_detail_payload

        return customer_detail_payload(analysis)


def create() -> DomainAnalytics:
    """Zero-argument factory used by ``AEZA_ANALYTICS_FACTORY``."""

    return DomainAnalytics()
