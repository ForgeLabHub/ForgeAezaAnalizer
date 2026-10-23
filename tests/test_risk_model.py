"""Risk model tests: formula, normalisation, unknown handling, band edges."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aeza_analyzer.analytics.risk import (
    DEFAULT_WEIGHTS,
    eligible_for_renewal,
    level_for,
    score_service,
    validate_weights,
)

REF = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def _score(**overrides):
    base = dict(
        service_id=1,
        service_name="svc",
        status="active",
        price_cents=1000,
        expires_at=REF + timedelta(days=30),
        auto_prolong=True,
        withdraw_balance=10_000,
        failed_renewals=0,
        reference=REF,
        horizon_days=30,
        weights=dict(DEFAULT_WEIGHTS),
    )
    base.update(overrides)
    return score_service(**base)


def test_formula_is_weighted_average_of_features():
    # Force every feature to a known value via a fully-deterministic setup:
    # expiry far away (0), auto on (0), balance covers (0), no failures (0),
    # active (0) -> score 0.
    assert _score().score == 0.0


def test_score_never_exceeds_100():
    risk = _score(
        expires_at=REF - timedelta(days=1),
        auto_prolong=False,
        withdraw_balance=0,
        failed_renewals=99,
        status="blocked",
    )
    assert risk.score == 100.0
    assert risk.level == "high"


def test_unknown_balance_is_excluded_not_zeroed():
    # Two services with identical known signals, differing only in whether the
    # withdrawable balance is known. Expiry is inside the horizon so there is a
    # real known signal to score against.
    common = dict(
        expires_at=REF + timedelta(days=15),  # expiry_proximity = 0.5
        auto_prolong=False,                   # autoprolong_off = 1.0
        status="blocked",                     # status_risk = 1.0
        failed_renewals=1,                    # failed_renewals = 0.5
    )
    unknown = _score(withdraw_balance=None, **common)
    known_shortfall = _score(withdraw_balance=0, **common)  # balance feature = 1.0

    # The unknown feature is dropped from both sums (renormalised), so it lowers
    # confidence and is never counted as a zero-risk contribution.
    assert unknown.confidence < 1.0
    assert any(f.key == "insufficient_balance" and f.unknown for f in unknown.factors)

    # Naive "treat unknown as 0" would keep the weight in the denominator with a
    # zero contribution, yielding a lower score. Renormalising avoids that.
    weights = DEFAULT_WEIGHTS
    contributions = (
        weights["expiry_proximity"] * 0.5
        + weights["autoprolong_off"] * 1.0
        + weights["failed_renewals"] * 0.5
        + weights["status_risk"] * 1.0
    )
    naive_zero_fill = 100 * contributions / sum(weights.values())
    assert unknown.score > naive_zero_fill
    assert unknown.score == pytest.approx(100 * contributions / (sum(weights.values())
                                            - weights["insufficient_balance"]))
    # And a known shortfall scores higher still, because the signal is present.
    assert known_shortfall.score > unknown.score


def test_band_boundaries_are_inclusive():
    assert level_for(0) == "low"
    assert level_for(34) == "low"
    assert level_for(34.999) == "low"
    assert level_for(35) == "medium"
    assert level_for(64) == "medium"
    assert level_for(64.999) == "medium"
    assert level_for(65) == "high"
    assert level_for(100) == "high"


def test_weights_validation():
    assert validate_weights({"expiry_proximity": 2})["expiry_proximity"] == 2
    with pytest.raises(ValueError, match="unknown weight keys"):
        validate_weights({"nope": 1})
    with pytest.raises(ValueError, match=">= 0"):
        validate_weights({"expiry_proximity": -1})
    with pytest.raises(ValueError, match="must be a number"):
        validate_weights({"expiry_proximity": "high"})
    with pytest.raises(ValueError, match="at least one weight"):
        validate_weights({k: 0 for k in DEFAULT_WEIGHTS})


def test_weight_change_changes_score():
    # Expiry 15 days into a 30-day horizon => expiry_proximity = 0.5 (non-zero),
    # with all other signals neutral, so only the expiry weight matters.
    neutral = dict(
        expires_at=REF + timedelta(days=15),
        auto_prolong=True,
        withdraw_balance=10_000,
        failed_renewals=0,
        status="active",
    )
    weak = _score(weights={**DEFAULT_WEIGHTS, "expiry_proximity": 0}, **neutral)
    strong = _score(weights={**DEFAULT_WEIGHTS, "expiry_proximity": 5}, **neutral)
    # A service expiring inside the horizon must score higher when the expiry
    # weight dominates.
    assert strong.score > weak.score


def test_deleted_service_is_not_live():
    assert _score(status="deleted").is_live is False
    assert _score(status="active").is_live is True


def test_eligible_for_renewal_excludes_past_and_far_future():
    assert eligible_for_renewal(REF + timedelta(days=10), REF, 30) is True
    assert eligible_for_renewal(REF, REF, 30) is True
    assert eligible_for_renewal(REF + timedelta(days=30), REF, 30) is True
    assert eligible_for_renewal(REF - timedelta(days=1), REF, 30) is False  # already expired
    assert eligible_for_renewal(REF + timedelta(days=31), REF, 30) is False  # beyond horizon
