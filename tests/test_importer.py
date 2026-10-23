"""Importer tests: real dataset, idempotency, atomicity, rejection handling."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from aeza_analyzer.importer import import_dataset
from aeza_analyzer.importer.loader import stored_counts
from aeza_analyzer.db import get_session_factory


def _counts():
    session = get_session_factory()()
    try:
        return stored_counts(session)
    finally:
        session.close()


def test_imports_real_dataset(data_dir):
    result = import_dataset()
    assert (result.accounts, result.services, result.transactions) == (10, 30, 100)
    assert result.rejected == []
    assert _counts() == {"accounts": 10, "services": 30, "transactions": 100}


def test_reference_is_derived_from_data(data_dir):
    result = import_dataset()
    # Organiser reference instant recovered from the data, not wall-clock now.
    assert result.reference_at is not None
    assert result.reference_at.year == 2026
    assert result.reference_at.tzinfo is not None


def test_reimport_is_idempotent(data_dir):
    import_dataset()
    import_dataset()
    import_dataset()
    assert _counts() == {"accounts": 10, "services": 30, "transactions": 100}


def test_rejected_row_aborts_by_default(data_dir, tmp_path):
    payload = {
        "accounts": [
            {"id": 1, "email": "a@example.test", "balance": 100, "withdrawBalance": 10,
             "totalReplenished": 200, "bonusBalance": 0, "bonusState": "locked"},
            {"id": 2, "email": "b@example.test", "balance": -5, "withdrawBalance": 0,
             "totalReplenished": 0, "bonusBalance": 0, "bonusState": "locked"},
        ],
        "services": [],
        "transactions": [],
    }
    dataset = tmp_path / "ds"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="rejected"):
        import_dataset(dataset)
    # Nothing was written: the invalid dataset never partially applied.
    assert _counts() == {"accounts": 0, "services": 0, "transactions": 0}


def test_failed_import_leaves_previous_data_intact(data_dir, tmp_path):
    import_dataset()
    before = _counts()

    dataset = tmp_path / "broken"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps(
        {"accounts": [{"id": 1}], "services": [], "transactions": []}
    ))
    with pytest.raises(ValueError):
        import_dataset(dataset)
    assert _counts() == before


def test_orphan_service_is_rejected(data_dir, tmp_path):
    payload = {
        "accounts": [{"id": 1, "email": "a@example.test", "balance": 0, "withdrawBalance": 0,
                      "totalReplenished": 0, "bonusBalance": 0, "bonusState": "locked"}],
        "services": [{"id": 1, "name": "svc", "ownerId": 999, "paymentTerm": "month",
                      "autoProlong": False, "createdAt": "2026-10-19T15:00:00.000Z",
                      "expiresAt": "2026-11-19T15:00:00.000Z", "status": "active", "price": 1}],
        "transactions": [],
    }
    dataset = tmp_path / "orphan"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="rejected"):
        import_dataset(dataset)


def test_naive_timestamp_is_rejected(data_dir, tmp_path):
    payload = {
        "accounts": [{"id": 1, "email": "a@example.test", "balance": 0, "withdrawBalance": 0,
                      "totalReplenished": 0, "bonusBalance": 0, "bonusState": "locked"}],
        "services": [{"id": 1, "name": "svc", "ownerId": 1, "paymentTerm": "month",
                      "autoProlong": False, "createdAt": "2026-10-19T15:00:00",
                      "expiresAt": "2026-11-19T15:00:00", "status": "active", "price": 1}],
        "transactions": [],
    }
    dataset = tmp_path / "naive"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="rejected"):
        import_dataset(dataset)


def test_lenient_mode_reports_rejections(data_dir, tmp_path):
    payload = {
        "accounts": [{"id": 1, "email": "a@example.test", "balance": 0, "withdrawBalance": 0,
                      "totalReplenished": 0, "bonusBalance": 0, "bonusState": "locked"},
                     {"id": 2, "email": "bad", "balance": 0, "withdrawBalance": 0,
                      "totalReplenished": 0, "bonusBalance": 0, "bonusState": "locked"}],
        "services": [],
        "transactions": [],
    }
    dataset = tmp_path / "lenient"
    dataset.mkdir()
    (dataset / "data.json").write_text(json.dumps(payload))
    result = import_dataset(dataset, strict=False)
    assert result.accounts == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].row_id == 2
