"""Read-only customer tools.

These are the *only* way the AI Analyst reaches business data.  Each function is
a thin, typed read over the same storage the HTTP API serves, so an AI answer can
never disagree with the interface.  Nothing here writes, recalculates or touches
the network.
"""

from __future__ import annotations

from core import ResourceNotFoundError
from backend.app.storage import Storage


def customer_profile(storage: Storage, customer_id: int) -> dict:
    """Identity, balances and aggregate risk for one customer."""

    payload = storage.customer(customer_id)
    return {
        "id": payload["id"],
        "email": payload["email"],
        "riskScore": payload["riskScore"],
        "riskCategory": payload["riskCategory"],
        "riskCategoryLabel": payload["riskCategoryLabel"],
        "serviceCount": payload["serviceCount"],
        "eligibleServiceCount": payload["eligibleServiceCount"],
        "highRiskServiceCount": payload["highRiskServiceCount"],
        "highRiskShare": payload.get("highRiskShare"),
        "overdueServiceCount": payload.get("overdueServiceCount"),
        "concludedStates": payload.get("concludedStates") or {},
        "stateNote": payload.get("stateNote") or "",
        "missingData": payload.get("missingData") or [],
        "balance": payload["balance"],
        "withdrawBalance": payload["withdrawBalance"],
        "bonusBalance": payload["bonusBalance"],
        "bonusState": payload.get("bonusState"),
        "totalReplenished": payload["totalReplenished"],
        "revenueAtRisk": payload["revenueAtRisk"],
        "upcomingRenewals": payload["upcomingRenewals"],
        "overdueOperational": payload.get("overdueOperational"),
        "lifecycleInconsistentCount": payload.get("lifecycleInconsistentCount"),
        "exposureByHorizon": payload.get("exposureByHorizon") or [],
        "version": {
            "generation": payload.get("generation"),
            "modelVersion": payload.get("modelVersion"),
            "asOf": payload.get("asOf"),
        },
    }


def customer_services(storage: Storage, customer_id: int) -> list[dict]:
    """Per-service rows: status, price, score and eligibility for forecast."""

    payload = storage.customer(customer_id)
    services = []
    for service in payload.get("services") or []:
        services.append(
            {
                "id": service["id"],
                "name": service["name"],
                "status": service["status"],
                "statusLabel": service["statusLabel"],
                "paymentTerm": service.get("paymentTerm"),
                "paymentTermLabel": service.get("paymentTermLabel"),
                "autoProlong": service.get("autoProlong"),
                "expiresAt": service.get("expiresAt"),
                "daysToExpiry": service.get("daysToExpiry"),
                "price": service["price"],
                "riskScore": service.get("riskScore"),
                "riskCategory": service.get("riskCategory"),
                "eligibleForForecast": service.get("eligibleForForecast"),
                "stateNote": service.get("stateNote") or "",
                "revenueAtRisk": service.get("revenueAtRisk"),
                "upcomingRenewalAt": service.get("upcomingRenewalAt"),
                "missingData": service.get("missingData") or [],
            }
        )
    return services


def customer_factors(storage: Storage, customer_id: int) -> list[dict]:
    """Risk factors with raw value, weight and contribution, per service.

    ``contribution`` is the backend's own number (``weight * value``), so the
    model can rank factors without doing arithmetic of its own.
    """

    payload = storage.customer(customer_id)
    rows = []
    for service in payload.get("services") or []:
        for factor in service.get("factors") or []:
            rows.append(
                {
                    "serviceId": service["id"],
                    "serviceName": service["name"],
                    "serviceRiskScore": service.get("riskScore"),
                    "key": factor["key"],
                    "label": factor["label"],
                    "value": factor.get("value"),
                    "weight": factor.get("weight"),
                    "contribution": factor.get("contribution"),
                    "available": factor.get("available"),
                    "reason": factor.get("reason") or "",
                    "deprecated": factor.get("deprecated", False),
                }
            )
    return rows


def customer_exposure(storage: Storage, customer_id: int) -> dict:
    """Renewals inside each horizon and the revenue at risk they carry."""

    payload = storage.customer(customer_id)
    return {
        "customerId": payload["id"],
        "revenueAtRisk": payload["revenueAtRisk"],
        "upcomingRenewals": payload["upcomingRenewals"],
        "overdueOperational": payload.get("overdueOperational"),
        "byHorizon": payload.get("exposureByHorizon") or [],
        "renewals": payload.get("renewalDetails") or [],
    }


def customer_recommendations(storage: Storage, customer_id: int) -> list[dict]:
    """The backend's own retention recommendations for the customer."""

    payload = storage.customer(customer_id)
    return payload.get("recommendations") or []


def resolve_customer_id(storage: Storage, customer_id: int) -> int:
    """Validate that the customer exists before building any context."""

    try:
        storage.customer(customer_id)
    except ResourceNotFoundError:
        raise
    return customer_id
