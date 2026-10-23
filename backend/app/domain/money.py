"""Money handling for the Aéza dataset.

Aéza - это быстрый хостинг

All monetary fields in the source snapshot are integer **eurocents**:
``balance``, ``withdrawBalance``, ``bonusBalance``, ``totalReplenished`` and
``services.price``.  The case brief states that 100 source units equal EUR 1,
which is exactly the eurocent convention, so conversion is a single division by
100 and must happen **exactly once**, at the boundary where raw integers become
domain values.

Every helper here is pure and total: it never performs a second conversion and
never mixes the semantically different amounts (available balance, bonus
balance, historical top-ups, service price, projected revenue).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

#: Number of source units that make up one euro (eurocents convention).
CENTS_PER_EURO = Decimal(100)

#: Display precision for euro amounts.
EURO_QUANT = Decimal("0.01")


class MoneyError(ValueError):
    """Raised when a monetary value cannot be interpreted safely."""


def cents_to_eur(cents: int | Decimal) -> Decimal:
    """Convert an integer eurocent amount to euros.

    The result is quantised to two decimal places using half-up rounding, which
    is what a finance-facing report expects.  Booleans are rejected explicitly
    because ``bool`` is a subclass of ``int`` in Python and silently accepting
    ``True`` as 1 cent would hide upstream data bugs.
    """

    if isinstance(cents, bool):
        raise MoneyError("boolean is not a monetary value")
    if not isinstance(cents, (int, Decimal)):
        raise MoneyError(f"unsupported monetary type: {type(cents).__name__}")
    if isinstance(cents, Decimal) and not cents.is_finite():
        raise MoneyError("non-finite monetary value")
    return (Decimal(cents) / CENTS_PER_EURO).quantize(EURO_QUANT, rounding=ROUND_HALF_UP)


def eur_to_cents(eur: Decimal | int | float) -> int:
    """Convert euros back to eurocents.

    Only used by tests and import validation helpers; the runtime pipeline keeps
    the raw cents and converts for display.
    """

    value = Decimal(str(eur))
    if not value.is_finite():
        raise MoneyError("non-finite monetary value")
    return int((value * CENTS_PER_EURO).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_non_negative_cents(value: object, field: str) -> int:
    """Validate a raw source monetary field.

    Returns the value as ``int`` so downstream code always deals with cents.
    Raises :class:`MoneyError` with a field-qualified message when the value is
    missing, non-integer or negative.
    """

    if value is None:
        raise MoneyError(f"{field}: monetary value is missing")
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{field}: expected integer eurocents, got {value!r}")
    if value < 0:
        raise MoneyError(f"{field}: negative monetary value {value}")
    return value
