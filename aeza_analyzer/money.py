"""Monetary handling.

Case rule: 100 source units correspond to €1. The organiser README confirms the
account money fields and ``services.price`` are non-negative integers in
eurocents, so dividing by 100 yields euros.

Canonical internal representation is **integer eurocents** — no floats, so no
rounding drift and no double conversion. Euros are derived once, at the API/UI
boundary, from the stored cents.
"""

from __future__ import annotations

from decimal import Decimal

CENTS_PER_EURO = 100

# Source columns that the organiser documents as eurocents.
CENTS_FIELDS = (
    "balance",
    "withdrawBalance",
    "totalReplenished",
    "bonusBalance",
    "price",
    "amount",
)


def cents_to_euros(cents: int | None) -> Decimal | None:
    """Convert integer eurocents to a 2-decimal euro amount.

    ``None`` (unknown) stays ``None`` — it must never silently become 0.
    """
    if cents is None:
        return None
    return (Decimal(cents) / CENTS_PER_EURO).quantize(Decimal("0.01"))


def cents_to_euros_str(cents: int | None) -> str | None:
    value = cents_to_euros(cents)
    return None if value is None else f"{value:.2f}"
