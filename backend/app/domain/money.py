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


def round_cents(value: Decimal | int | float | str) -> int:
    """Round a monetary amount to whole eurocents using ROUND_HALF_UP.

    This is the single rounding rule for every money path.  ``round()`` and
    ``int()`` must not be used on monetary values: Python's built-in ``round``
    applies banker's rounding (HALF_EVEN), so ``round(62.5)`` is 62 while
    finance expects 63.  The two rules disagree on exact halves, which is
    exactly where a money report is most visible.

    ``float`` input is accepted for backwards compatibility with existing call
    sites but is converted through ``str`` so the binary representation cannot
    shift a half-cent boundary.
    """

    if isinstance(value, bool):
        raise MoneyError("boolean is not a monetary value")
    if isinstance(value, float):
        value = repr(value)
    if isinstance(value, (int, str)):
        value = Decimal(value)
    if not isinstance(value, Decimal):
        raise MoneyError(f"unsupported monetary type: {type(value).__name__}")
    if not value.is_finite():
        raise MoneyError("non-finite monetary value")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scaled_cents(cents: int | Decimal, factor: float) -> int:
    """Return ``cents * factor`` rounded to whole eurocents.

    Used for risk-weighted amounts such as ``price * risk_score / 100``.  The
    multiplication stays in ``Decimal`` so no binary floating point error can
    reach the result.
    """

    if isinstance(cents, bool) or not isinstance(cents, (int, Decimal)):
        raise MoneyError(f"unsupported monetary type: {type(cents).__name__}")
    return round_cents(Decimal(cents) * Decimal(str(factor)))


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
