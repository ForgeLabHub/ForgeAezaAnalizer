"""Prometheus metrics.

Only aggregated, non-personal counters are exposed.  No email, customer id or
other identifier ever becomes a label, and every label set is low cardinality.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

CUSTOMERS_TOTAL = Gauge(
    "aeza_customers_total", "Number of customers in the current dataset", registry=REGISTRY
)
SERVICES_TOTAL = Gauge(
    "aeza_services_total", "Number of services in the current dataset", registry=REGISTRY
)
SERVICES_OPEN_TOTAL = Gauge(
    "aeza_services_open_total",
    "Number of services whose state still allows a future churn event",
    registry=REGISTRY,
)
CUSTOMERS_BY_RISK = Gauge(
    "aeza_customers_by_risk_category",
    "Customers grouped by risk category",
    ["category"],
    registry=REGISTRY,
)
REVENUE_AT_RISK = Gauge(
    "aeza_revenue_at_risk_eur",
    "Projected revenue at risk for the configured horizon, in EUR",
    registry=REGISTRY,
)
IMPORTS_TOTAL = Counter(
    "aeza_snapshot_imports_total",
    "Snapshot imports by outcome",
    ["status"],
    registry=REGISTRY,
)
API_ERRORS_TOTAL = Counter(
    "aeza_api_errors_total",
    "API errors by HTTP status class",
    ["status_class"],
    registry=REGISTRY,
)
API_REQUESTS_TOTAL = Counter(
    "aeza_api_requests_total", "API requests by route and method", ["route", "method"], registry=REGISTRY
)
ANALYTICS_DURATION = Histogram(
    "aeza_analytics_duration_seconds",
    "Time spent computing analytics",
    ["operation"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


def risk_category_labels() -> list[str]:
    return ["low", "medium", "high", "insufficient_data", "not_applicable"]


def update_dataset_gauges(*, summary: dict, customers_total: int, services_total: int) -> None:
    """Refresh the dataset gauges from a computed summary."""

    CUSTOMERS_TOTAL.set(customers_total)
    SERVICES_TOTAL.set(services_total)
    SERVICES_OPEN_TOTAL.set(summary["services"]["open"])
    by_category = summary["customers"]["byCategory"]
    for category in risk_category_labels():
        CUSTOMERS_BY_RISK.labels(category=category).set(by_category.get(category, 0))
    REVENUE_AT_RISK.set(float(summary["revenue"]["revenueAtRiskEur"]))


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
