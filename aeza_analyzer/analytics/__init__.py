"""Analytics: churn risk, revenue at risk, dashboard aggregates."""

from .risk import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_WEIGHTS,
    FACTOR_TITLES,
    RISK_LEVEL_BANDS,
    level_for,
    validate_weights,
)
from .service import AnalyticsService, get_analytics

__all__ = [
    "AnalyticsService",
    "get_analytics",
    "DEFAULT_HORIZON_DAYS",
    "DEFAULT_WEIGHTS",
    "FACTOR_TITLES",
    "RISK_LEVEL_BANDS",
    "level_for",
    "validate_weights",
]
