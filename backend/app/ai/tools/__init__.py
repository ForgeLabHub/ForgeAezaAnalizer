"""Read-only tools the AI Analyst may call.

Every tool reads the published analytics generation or evaluates an isolated
scenario.  None of them writes, recalculates the live configuration, executes
SQL from model output, or reaches the network.
"""

from __future__ import annotations

from .actions import customer_actions
from .analytics import analytics_summary, model_settings, priority_queue, quality_report
from .customers import (
    customer_exposure,
    customer_factors,
    customer_profile,
    customer_recommendations,
    customer_services,
)
from .scenarios import scenario_preview

__all__ = [
    "analytics_summary",
    "customer_actions",
    "customer_exposure",
    "customer_factors",
    "customer_profile",
    "customer_recommendations",
    "customer_services",
    "model_settings",
    "priority_queue",
    "quality_report",
    "scenario_preview",
]
