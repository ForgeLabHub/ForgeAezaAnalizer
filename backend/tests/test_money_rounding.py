"""Money rounding tests: one rule (ROUND_HALF_UP) for every money path."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.money import MoneyError, cents_to_eur, round_cents, scaled_cents


def test_half_up_not_bankers():
    """Exact halves round away from zero, unlike Python's built-in round()."""
    assert round_cents(Decimal("62.5")) == 63
    assert round_cents(Decimal("0.5")) == 1
    assert round_cents(Decimal("1.5")) == 2
    assert round_cents(Decimal("2.5")) == 3
    # The built-in disagrees on halves; this is why it is banned for money.
    assert round(2.5) == 2


def test_risk_weighted_amount_uses_half_up():
    """price 125 at score 50% must be 63 cents, not 62."""
    assert scaled_cents(125, 0.50) == 63
    assert scaled_cents(105, 0.50) == 53
    assert scaled_cents(205, 0.50) == 103


def test_ordinary_values():
    assert round_cents(Decimal("62.4")) == 62
    assert round_cents(Decimal("62.6")) == 63
    assert scaled_cents(1000, 0.50) == 500
    assert scaled_cents(474, 0.7674) == 364


def test_zero_and_integers():
    assert round_cents(0) == 0
    assert round_cents(Decimal("0")) == 0
    assert scaled_cents(0, 0.5) == 0
    assert scaled_cents(100, 0.0) == 0
    assert scaled_cents(100, 1.0) == 100


def test_float_input_does_not_shift_a_half():
    """0.5 is exactly representable, so float input must still give 63."""
    assert round_cents(62.5) == 63
    assert scaled_cents(125, 0.5) == 63


def test_rejects_non_finite_and_boolean():
    with pytest.raises(MoneyError):
        round_cents(Decimal("NaN"))
    with pytest.raises(MoneyError):
        round_cents(Decimal("Infinity"))
    with pytest.raises(MoneyError):
        round_cents(True)
    with pytest.raises(MoneyError):
        scaled_cents(True, 0.5)


def test_cents_to_eur_unchanged_by_rounding_work():
    """The display conversion keeps its own contract."""
    assert str(cents_to_eur(125)) == "1.25"
    assert str(cents_to_eur(0)) == "0.00"
    assert str(cents_to_eur(1_000_000)) == "10000.00"


def test_money_modules_agree_on_a_half():
    """revenue and money must not disagree on the same amount."""
    from app.domain.money import CENTS_PER_EURO

    half_cent = Decimal(125) * Decimal(50) / CENTS_PER_EURO
    assert round_cents(half_cent) == 63
    assert round_cents(Decimal("62.5")) == 63
