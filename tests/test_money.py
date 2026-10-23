"""Money conversion tests: eurocents are canonical, euros at the boundary."""

from __future__ import annotations

from decimal import Decimal

from aeza_analyzer.money import cents_to_euros, cents_to_euros_str


def test_cents_to_euros_rule_100_to_1():
    # Case rule: 100 source units = EUR 1.
    assert cents_to_euros(100) == Decimal("1.00")
    assert cents_to_euros(83810) == Decimal("838.10")
    assert cents_to_euros(0) == Decimal("0.00")


def test_rounding_is_half_even_free_of_float_drift():
    # Values are integers, so division by 100 is exact to 2 dp.
    assert cents_to_euros_str(1) == "0.01"
    assert cents_to_euros_str(999) == "9.99"
    assert cents_to_euros_str(1_000_000) == "10000.00"


def test_unknown_stays_unknown():
    # None must never silently become 0.00 (unknown != zero risk).
    assert cents_to_euros(None) is None
    assert cents_to_euros_str(None) is None
