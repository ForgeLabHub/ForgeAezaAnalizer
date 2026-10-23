from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily

from core import NotReadyError


class PublishedCollector:
    def __init__(self, storage):
        self.storage = storage

    def collect(self):
        ready = GaugeMetricFamily("aeza_analysis_ready", "A published analysis is available")
        try:
            summary = self.storage.summary()
        except NotReadyError:
            ready.add_metric([], 0)
            yield ready
            return
        ready.add_metric([], 1)
        yield ready
        for name, help_text, value in (
            ("aeza_analysis_generation", "Published analysis generation", summary["generation"]),
            ("aeza_customers_total", "Customers in the published analysis", summary["customers"]["total"]),
            ("aeza_services_total", "Services in the published analysis", summary["services"]["total"]),
            ("aeza_services_open_total", "Open services in the published analysis", summary["services"]["open"]),
            ("aeza_revenue_at_risk_eur", "Scenario weighted payments in EUR", summary["revenue"]["revenueAtRiskCents"] / 100),
            ("aeza_upcoming_renewals_eur", "Planned payments in EUR", summary["revenue"]["upcomingRenewalsCents"] / 100),
        ):
            metric = GaugeMetricFamily(name, help_text)
            metric.add_metric([], value)
            yield metric
        categories = GaugeMetricFamily("aeza_customers_by_risk_category", "Published customer categories", labels=["category"])
        for category in ("low", "medium", "high", "insufficient_data", "not_applicable"):
            categories.add_metric([category], summary["customers"]["byCategory"].get(category, 0))
        yield categories
        from datetime import datetime
        calculated = GaugeMetricFamily("aeza_analysis_calculated_timestamp_seconds", "Last successful calculation")
        calculated.add_metric([], datetime.fromisoformat(summary["calculatedAt"]).timestamp())
        yield calculated


class Metrics:
    def __init__(self, storage):
        self.registry = CollectorRegistry()
        self.registry.register(PublishedCollector(storage))
        self.requests = Counter("aeza_api_requests_total", "API responses", ["route", "method", "status_class"], registry=self.registry)
        self.duration = Histogram("aeza_api_duration_seconds", "API response duration", ["route"], registry=self.registry)

    def observe(self, route: str, method: str, status: int, duration: float):
        method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER"
        self.requests.labels(route, method, f"{status // 100}xx").inc()
        self.duration.labels(route).observe(duration)

    def render(self) -> bytes:
        return generate_latest(self.registry)
