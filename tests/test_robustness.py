"""Robustness tests: corrupt store, empty dataset, CLI exit codes."""

from __future__ import annotations

import json

import pytest

from aeza_analyzer.db import StoreError, get_session_factory, init_db, reset_state


def test_corrupt_store_raises_clear_error(data_dir):
    """A foreign/corrupt DB file must not leak a raw DatabaseError."""
    (data_dir / "aeza.sqlite").write_bytes(b"definitely not a sqlite database")
    reset_state()
    with pytest.raises(StoreError, match="not a usable database"):
        init_db()


def test_corrupt_store_cli_exit_code(data_dir, capsys):
    from aeza_analyzer.cli import main

    (data_dir / "aeza.sqlite").write_bytes(b"garbage")
    reset_state()
    code = main(["audit"])
    assert code == 2
    assert "not a usable database" in capsys.readouterr().err


def test_empty_dataset_is_handled(data_dir, tmp_path):
    """A structurally valid but empty dataset must not crash analytics."""
    from aeza_analyzer.analytics import AnalyticsService
    from aeza_analyzer.importer import import_dataset

    dataset = tmp_path / "empty"
    dataset.mkdir()
    (dataset / "data.json").write_text(
        json.dumps({"accounts": [], "services": [], "transactions": []})
    )
    result = import_dataset(dataset)
    assert (result.accounts, result.services, result.transactions) == (0, 0, 0)

    init_db()
    session = get_session_factory()()
    try:
        dashboard = AnalyticsService(session).dashboard()
    finally:
        session.close()
    assert dashboard["counts"] == {"accounts": 0, "services": 0, "transactions": 0}
    assert dashboard["revenue_at_risk_cents"] == 0


def test_account_without_services_is_unknown_not_low(data_dir, tmp_path):
    """No services means unscoreable, not 'low risk'."""
    from aeza_analyzer.analytics import AnalyticsService
    from aeza_analyzer.importer import import_dataset

    dataset = tmp_path / "nosvc"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps({
        "accounts": [{"id": 1, "email": "a@example.test", "balance": 100,
                      "withdrawBalance": 10, "totalReplenished": 200,
                      "bonusBalance": 0, "bonusState": "locked"}],
        "services": [], "transactions": [],
    }))
    import_dataset(dataset)
    init_db()
    session = get_session_factory()()
    try:
        customers = AnalyticsService(session).customer_risk()
    finally:
        session.close()
    assert customers[0].risk_level == "unknown"
    assert customers[0].confidence == 0.0
