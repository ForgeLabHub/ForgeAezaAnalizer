"""Unit tests for money conversion, schema validation and risk scoring."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.money import MoneyError, cents_to_eur, eur_to_cents, validate_non_negative_cents
from app.domain.risk import (
    DEFAULT_WEIGHTS,
    FACTOR_BY_KEY,
    RiskConfigError,
    RiskSettings,
    classify,
    compute_customer_risk,
    compute_service_risk,
    validate_settings,
)
from app.domain.schema import Account, Service, Snapshot, Transaction

NOW = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)


# --------------------------------------------------------------------------- money


def test_cents_to_eur_documented_examples():
    # 100 source units == EUR 1, so eurocents map 1:1 to 0.01 EUR.
    assert cents_to_eur(100) == Decimal("1.00")
    assert cents_to_eur(0) == Decimal("0.00")
    assert cents_to_eur(1) == Decimal("0.01")
    assert cents_to_eur(83810) == Decimal("838.10")
    assert cents_to_eur(96922) == Decimal("969.22")


def test_cents_to_eur_rounds_half_up():
    assert cents_to_eur(3) == Decimal("0.03")
    assert eur_to_cents(Decimal("1.00")) == 100


def test_cents_to_eur_is_not_double_converted():
    # A value already expressed in euros must not be divided twice: the helper
    # takes cents only, so calling it with the euro figure is a caller error.
    assert cents_to_eur(83810) != Decimal("83810.00")


@pytest.mark.parametrize("bad", [None, "100", 1.5, True])
def test_validate_non_negative_cents_rejects_bad_values(bad):
    with pytest.raises(MoneyError):
        validate_non_negative_cents(bad, "balance")


def test_validate_non_negative_cents_rejects_negative():
    with pytest.raises(MoneyError):
        validate_non_negative_cents(-1, "balance")


def test_cents_to_eur_rejects_bool():
    with pytest.raises(MoneyError):
        cents_to_eur(True)


# --------------------------------------------------------------------------- schema


def _service(**overrides) -> dict:
    base = {
        "id": 1,
        "name": "svc-1",
        "ownerId": 1,
        "paymentTerm": "month",
        "autoProlong": True,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "expiresAt": "2026-02-01T00:00:00.000Z",
        "status": "active",
        "price": 500,
    }
    base.update(overrides)
    return base


def test_service_rejects_expiry_before_creation():
    with pytest.raises(ValueError):
        Service.model_validate(
            _service(createdAt="2026-02-01T00:00:00.000Z", expiresAt="2026-01-01T00:00:00.000Z")
        )


def test_service_rejects_unknown_status():
    with pytest.raises(ValueError):
        Service.model_validate(_service(status="cancelled"))


def test_service_rejects_negative_price():
    with pytest.raises(ValueError):
        Service.model_validate(_service(price=-1))


def test_account_rejects_withdraw_above_balance():
    with pytest.raises(ValueError):
        Account.model_validate({"id": 1, "email": "a@b.c", "balance": 10, "withdrawBalance": 20})


def test_transaction_requires_performed_at_when_performed():
    with pytest.raises(ValueError):
        Transaction.model_validate(
            {
                "id": 1,
                "amount": 10,
                "status": "performed",
                "performedAt": None,
                "createdAt": "2026-01-01T00:00:00.000Z",
                "type": "order",
                "serviceId": 1,
            }
        )


def test_transaction_rejects_performed_at_for_not_performed():
    with pytest.raises(ValueError):
        Transaction.model_validate(
            {
                "id": 1,
                "amount": 10,
                "status": "not_performed",
                "performedAt": "2026-01-02T00:00:00.000Z",
                "createdAt": "2026-01-01T00:00:00.000Z",
                "type": "prolong",
                "serviceId": 1,
            }
        )


def test_snapshot_rejects_duplicate_and_dangling_ids():
    account = {"id": 1, "email": "a@b.c"}
    with pytest.raises(ValueError, match="duplicate"):
        Snapshot.model_validate({"accounts": [account, account], "services": [], "transactions": []})
    with pytest.raises(ValueError, match="unknown owner"):
        Snapshot.model_validate(
            {"accounts": [], "services": [_service()], "transactions": []}
        )
    with pytest.raises(ValueError, match="unknown service"):
        Snapshot.model_validate(
            {
                "accounts": [account],
                "services": [_service()],
                "transactions": [
                    {
                        "id": 1,
                        "amount": 1,
                        "status": "not_performed",
                        "performedAt": None,
                        "createdAt": "2026-01-01T00:00:00.000Z",
                        "type": "order",
                        "serviceId": 999,
                    }
                ],
            }
        )


def test_snapshot_accepts_valid_bundle():
    snapshot = Snapshot.model_validate(
        {
            "accounts": [{"id": 1, "email": "a@b.c"}],
            "services": [_service()],
            "transactions": [],
        }
    )
    assert len(snapshot.accounts) == 1
    assert snapshot.services[0].owner_id == 1


# --------------------------------------------------------------------------- settings


def test_validate_settings_rejects_negative_weight():
    with pytest.raises(RiskConfigError):
        validate_settings(RiskSettings(weights={**DEFAULT_WEIGHTS, "expiry_proximity": -1}))


def test_validate_settings_rejects_unknown_factor():
    with pytest.raises(RiskConfigError):
        validate_settings(RiskSettings(weights={"nope": 1.0}))


def test_validate_settings_rejects_inverted_thresholds():
    with pytest.raises(RiskConfigError):
        validate_settings(RiskSettings(low_max=70, medium_max=50))


@pytest.mark.parametrize("horizon", [0, -1, 400])
def test_validate_settings_rejects_bad_horizon(horizon):
    with pytest.raises(RiskConfigError):
        validate_settings(RiskSettings(horizon_days=horizon))


def test_all_zero_weights_is_allowed_but_yields_no_score():
    settings = RiskSettings(weights={k: 0.0 for k in DEFAULT_WEIGHTS})
    assert validate_settings(settings) is None


def test_classify_boundaries():
    settings = RiskSettings()
    assert classify(0, settings) == "low"
    assert classify(34, settings) == "low"
    assert classify(34.1, settings) == "medium"
    assert classify(64, settings) == "medium"
    assert classify(64.1, settings) == "high"
    assert classify(100, settings) == "high"
    assert classify(None, settings) == "insufficient_data"


# --------------------------------------------------------------------------- risk


def _account(**overrides):
    balance = overrides.get("balance", 10_000)
    base = {
        "id": 1,
        "email": "a@b.c",
        "balance": balance,
        # Keep the documented invariant (withdrawBalance <= balance) satisfied
        # while letting tests vary the balance freely.
        "withdrawBalance": min(1_000, balance),
        "totalReplenished": max(50_000, balance),
        "bonusBalance": 500,
        "bonusState": "locked",
    }
    base.update(overrides)
    return Account.model_validate(base)


def _tx(id_, status, type_="prolong", amount=100):
    performed = "2026-10-01T00:00:00.000Z" if status == "performed" else None
    return Transaction.model_validate(
        {
            "id": id_,
            "amount": amount,
            "status": status,
            "performedAt": performed,
            "createdAt": "2026-10-01T00:00:00.000Z",
            "type": type_,
            "serviceId": 1,
        }
    )


def test_risk_score_is_reproducible():
    service = Service.model_validate(_service(autoProlong=False, price=1000))
    account = _account(balance=0)
    txs = [_tx(1, "not_performed"), _tx(2, "not_performed")]
    first = compute_service_risk(
        service=service, account=account, transactions=txs, settings=RiskSettings(), now=NOW
    )
    second = compute_service_risk(
        service=service, account=account, transactions=txs, settings=RiskSettings(), now=NOW
    )
    assert first.score == second.score
    assert first.score is not None


def test_risk_score_matches_formula():
    """Verify the published formula on a hand-computed case."""

    # month service expiring in 15 days of a 30-day horizon, no autoprolong,
    # zero balance vs price, no transactions.
    service = Service.model_validate(
        _service(
            autoProlong=False,
            price=1000,
            expiresAt="2026-11-03T15:00:00.000Z",
            status="active",
        )
    )
    account = _account(balance=0)
    result = compute_service_risk(
        service=service, account=account, transactions=[], settings=RiskSettings(), now=NOW
    )
    expected_features = {
        "expiry_proximity": 0.5,
        "auto_prolong_disabled": 1.0,
        "insufficient_balance": 1.0,
        "prolong_wait_status": 0.0,
        "suspended_status": 0.0,
    }
    total_weight = sum(DEFAULT_WEIGHTS[k] for k in expected_features)
    expected = 100 * sum(
        DEFAULT_WEIGHTS[k] * v for k, v in expected_features.items()
    ) / total_weight
    assert result.score == pytest.approx(round(expected, 1))
    # No renewal history: the *rate* is unknown, so it is reported as missing.
    # The deprecated diagnostic factor must not appear in missing_data, since
    # it never contributes to the score.
    assert "Доля неуспешных продлений" in result.missing_data
    assert "Неуспешные продления" not in result.missing_data


def test_high_risk_scenario_scores_high():
    service = Service.model_validate(
        _service(
            autoProlong=False,
            price=1000,
            status="prolong_wait",
            expiresAt="2026-10-18T15:00:00.000Z",
        )
    )
    result = compute_service_risk(
        service=service,
        account=_account(balance=0),
        transactions=[_tx(1, "not_performed"), _tx(2, "not_performed")],
        settings=RiskSettings(),
        now=NOW,
    )
    assert result.score is not None and result.score >= 65
    assert result.category == "high"
    assert result.reasons


def test_low_risk_scenario_scores_low():
    service = Service.model_validate(
        _service(autoProlong=True, price=100, expiresAt="2027-10-01T00:00:00.000Z")
    )
    result = compute_service_risk(
        service=service,
        account=_account(balance=1_000_000),
        transactions=[_tx(1, "performed")],
        settings=RiskSettings(),
        now=NOW,
    )
    assert result.score is not None and result.score <= 34
    assert result.category == "low"


def test_changing_weights_changes_the_score():
    service = Service.model_validate(
        _service(autoProlong=False, price=1000, expiresAt="2027-10-01T00:00:00.000Z")
    )
    account = _account(balance=1_000_000)
    neutral = compute_service_risk(
        service=service, account=account, transactions=[], settings=RiskSettings(), now=NOW
    )
    boosted = RiskSettings(weights={**DEFAULT_WEIGHTS, "auto_prolong_disabled": 50.0})
    weighted = compute_service_risk(
        service=service, account=account, transactions=[], settings=boosted, now=NOW
    )
    assert weighted.score > neutral.score


def test_zero_weight_excludes_factor():
    settings = RiskSettings(
        weights={
            "expiry_proximity": 0.0,
            "auto_prolong_disabled": 1.0,
            "insufficient_balance": 0.0,
            "prolong_wait_status": 0.0,
            "failed_renewals": 0.0,
            "suspended_status": 0.0,
            "renewal_failure_rate": 0.0,
        }
    )
    service = Service.model_validate(_service(autoProlong=False, price=1000))
    result = compute_service_risk(
        service=service, account=_account(balance=0), transactions=[], settings=settings, now=NOW
    )
    # Only the autoprolong factor carries weight and it is fully present.
    assert result.score == 100.0
    assert [f.key for f in result.factors if f.available] == ["auto_prolong_disabled"]


def test_all_zero_weights_produce_insufficient_data():
    settings = RiskSettings(weights={k: 0.0 for k in DEFAULT_WEIGHTS})
    service = Service.model_validate(_service())
    result = compute_service_risk(
        service=service, account=_account(), transactions=[], settings=settings, now=NOW
    )
    assert result.score is None
    assert result.category == "insufficient_data"


def test_zero_price_makes_balance_factor_unavailable():
    service = Service.model_validate(_service(price=0))
    result = compute_service_risk(
        service=service, account=_account(balance=0), transactions=[], settings=RiskSettings(), now=NOW
    )
    assert "Недостаточно средств для продления" in result.missing_data


def test_deleted_and_blocked_services_are_not_forecast():
    for status in ("deleted", "blocked"):
        service = Service.model_validate(_service(status=status, expiresAt="2026-10-01T00:00:00.000Z"))
        result = compute_service_risk(
            service=service,
            account=_account(balance=0),
            transactions=[],
            settings=RiskSettings(),
            now=NOW,
        )
        assert result.eligible is False
        assert result.score is None
        assert result.category == "not_applicable"
        assert result.status_note


def test_expiry_boundary_at_horizon_is_zero():
    # Exactly on the horizon edge: proximity feature must be 0, not 1.
    service = Service.model_validate(_service(expiresAt="2026-11-18T15:00:00.000Z", autoProlong=True))
    settings = RiskSettings(horizon_days=30)
    result = compute_service_risk(
        service=service,
        account=_account(balance=1_000_000),
        transactions=[],
        settings=settings,
        now=NOW,
    )
    proximity = next(f for f in result.factors if f.key == "expiry_proximity")
    assert proximity.value == 0.0


def test_expiry_just_inside_horizon_is_positive():
    service = Service.model_validate(_service(expiresAt="2026-11-17T15:00:00.000Z", autoProlong=True))
    result = compute_service_risk(
        service=service,
        account=_account(balance=1_000_000),
        transactions=[],
        settings=RiskSettings(horizon_days=30),
        now=NOW,
    )
    proximity = next(f for f in result.factors if f.key == "expiry_proximity")
    assert 0.0 < proximity.value < 0.1


def test_failed_renewals_is_diagnostic_only():
    """The approved model counts failures once, via renewal_failure_rate.

    ``failed_renewals`` stays in the payload for compatibility but carries no
    weight, so it must not change the score however many failures exist.
    """
    service = Service.model_validate(_service())
    one = compute_service_risk(
        service=service,
        account=_account(),
        transactions=[_tx(1, "not_performed")],
        settings=RiskSettings(),
        now=NOW,
    )
    many = compute_service_risk(
        service=service,
        account=_account(),
        transactions=[_tx(1, "not_performed"), _tx(2, "not_performed"), _tx(3, "not_performed")],
        settings=RiskSettings(),
        now=NOW,
    )
    diag1 = next(f for f in one.factors if f.key == "failed_renewals")
    diag3 = next(f for f in many.factors if f.key == "failed_renewals")

    # Diagnostics report the raw historical count, normalised by nothing.
    assert diag1.value == pytest.approx(1.0)
    assert diag3.value == pytest.approx(3.0)
    # ...but it is deprecated, unweighted and therefore not "available".
    assert diag1.deprecated is True
    assert diag1.weight == 0.0
    assert diag1.available is False
    assert diag1.contribution == 0.0

    # The rate is the single rating factor and does move with the failures.
    rate1 = next(f for f in one.factors if f.key == "renewal_failure_rate")
    rate3 = next(f for f in many.factors if f.key == "renewal_failure_rate")
    assert rate1.value == pytest.approx(1.0)  # 1 failed of 1 attempt
    assert rate3.value == pytest.approx(1.0)  # 3 failed of 3 attempts
    assert rate1.weight == pytest.approx(2.5)


def test_failed_renewals_does_not_double_count():
    """Removing the duplicate must not change the rating at all.

    With the same rate but different absolute failure counts, the score has to
    stay identical: only the rate is weighted.
    """
    service = Service.model_validate(_service())
    few = compute_service_risk(
        service=service,
        account=_account(),
        transactions=[_tx(1, "not_performed"), _tx(2, "performed")],
        settings=RiskSettings(),
        now=NOW,
    )
    lots = compute_service_risk(
        service=service,
        account=_account(),
        transactions=[
            _tx(1, "not_performed"),
            _tx(2, "not_performed"),
            _tx(3, "performed"),
            _tx(4, "performed"),
        ],
        settings=RiskSettings(),
        now=NOW,
    )
    # Both are 1 failed of 2 attempts -> identical rate -> identical score.
    assert few.score == pytest.approx(lots.score)


def test_customer_risk_uses_maximum_not_average():
    high = Service.model_validate(
        _service(id=1, autoProlong=False, price=1000, status="prolong_wait", expiresAt="2026-10-18T15:00:00.000Z")
    )
    low = Service.model_validate(
        _service(id=2, autoProlong=True, price=100, expiresAt="2027-10-01T00:00:00.000Z")
    )
    account = _account(balance=0)
    risks = [
        compute_service_risk(service=high, account=account, transactions=[], settings=RiskSettings(), now=NOW),
        compute_service_risk(service=low, account=account, transactions=[], settings=RiskSettings(), now=NOW),
    ]
    customer = compute_customer_risk(customer_id=1, service_risks=risks, settings=RiskSettings())
    assert customer.score == max(r.score for r in risks)
    assert customer.service_count == 2
    assert customer.eligible_service_count == 2


def test_customer_with_only_concluded_services_is_not_applicable():
    deleted = Service.model_validate(_service(status="deleted"))
    blocked = Service.model_validate(_service(id=2, status="blocked"))
    account = _account()
    risks = [
        compute_service_risk(service=s, account=account, transactions=[], settings=RiskSettings(), now=NOW)
        for s in (deleted, blocked)
    ]
    customer = compute_customer_risk(customer_id=1, service_risks=risks, settings=RiskSettings())
    assert customer.category == "not_applicable"
    assert customer.score is None
    assert customer.concluded_states == {"deleted": 1, "blocked": 1}
    assert "не прогноз" in customer.state_note or "не строится" in customer.state_note


def test_customer_with_no_services_is_insufficient_data():
    customer = compute_customer_risk(customer_id=9, service_risks=[], settings=RiskSettings())
    assert customer.category == "insufficient_data"
    assert customer.score is None


def test_factor_metadata_covers_every_factor():
    assert set(FACTOR_BY_KEY) == set(DEFAULT_WEIGHTS)
    for definition in FACTOR_BY_KEY.values():
        assert definition.label and definition.description and definition.normalization
