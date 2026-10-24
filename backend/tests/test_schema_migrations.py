"""Schema reconciliation and migration tests.

These pin the fix for the production outage:

    psycopg.errors.UndefinedColumn: column analyzer_telegram_links.telegram_user_id does not exist

``Base.metadata.create_all()`` never alters an existing table, so a database
created by the *earlier* Telegram implementation kept its legacy
``chat_id``/``user_email``/``username`` columns while the current ORM expected
``telegram_user_id``/``account_id``/``notifications_enabled``/``consent_at``/
``updated_at``. Every read or write of a link then failed.

The tests build that legacy table, run ``Database.initialize()`` and assert the
schema is reconciled, the migration is recorded, a re-run is a no-op, and no data
was lost. They run on the default SQLite test database; the same code path runs on
PostgreSQL in production (the SQL used is portable: ``ALTER TABLE ADD COLUMN``,
``information_schema``/``PRAGMA`` detection, and a plain ``UPDATE``).
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import inspect, text

from backend.app.db import Database
from backend.app.schema import MIGRATIONS, MIGRATIONS_TABLE, reconcile

LEGACY_LINK_DDL = """
CREATE TABLE analyzer_telegram_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id VARCHAR(64) NOT NULL UNIQUE,
    user_email VARCHAR(320) NOT NULL,
    username VARCHAR(64),
    created_at DATETIME NOT NULL,
    revoked_at DATETIME
)
"""


@pytest.fixture
def legacy_db(tmp_path):
    """A database whose ``analyzer_telegram_links`` has the legacy shape."""

    db = Database(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with db.engine.begin() as connection:
        connection.execute(text(LEGACY_LINK_DDL))
        connection.execute(text(
            "INSERT INTO analyzer_telegram_links (chat_id, user_email, username, created_at) "
            "VALUES ('424242', 'user-0001@example.test', 'tester', '2026-01-01 00:00:00')"
        ))
    return db


def _columns(db, table: str) -> set[str]:
    return {column["name"] for column in inspect(db.engine).get_columns(table)}


# --------------------------------------------------------------------------- #
# The reported defect
# --------------------------------------------------------------------------- #

def test_initialize_adds_the_columns_the_orm_needs(legacy_db):
    before = _columns(legacy_db, "analyzer_telegram_links")
    assert "telegram_user_id" not in before  # the reported state

    legacy_db.initialize()

    after = _columns(legacy_db, "analyzer_telegram_links")
    for column in ("telegram_user_id", "account_id", "notifications_enabled", "consent_at", "updated_at"):
        assert column in after, f"{column} must be added for the ORM to work"


def test_initialize_does_not_lose_existing_rows(legacy_db):
    legacy_db.initialize()
    with legacy_db.engine.begin() as connection:
        rows = connection.execute(text("SELECT chat_id, user_email FROM analyzer_telegram_links")).fetchall()
    assert rows == [("424242", "user-0001@example.test")]


def test_the_legacy_identity_is_backfilled_from_chat_id(legacy_db):
    legacy_db.initialize()
    with legacy_db.engine.begin() as connection:
        value = connection.execute(text("SELECT telegram_user_id FROM analyzer_telegram_links")).scalar()
    assert value == "424242"


def test_the_orm_can_read_a_link_after_reconciliation(legacy_db):
    """The query that raised UndefinedColumn must now succeed."""

    from sqlalchemy import select

    from backend.app.db import TelegramLinkRow

    legacy_db.initialize()
    with legacy_db.sessions() as session:
        row = session.scalars(select(TelegramLinkRow)).first()
    assert row is not None
    assert row.telegram_user_id == "424242"


# --------------------------------------------------------------------------- #
# Idempotency and repeatability
# --------------------------------------------------------------------------- #

def test_initialize_is_idempotent(legacy_db):
    legacy_db.initialize()
    after_first = _columns(legacy_db, "analyzer_telegram_links")

    legacy_db.initialize()  # must not raise
    assert _columns(legacy_db, "analyzer_telegram_links") == after_first


def test_the_migration_is_recorded_once(legacy_db):
    legacy_db.initialize()
    legacy_db.initialize()
    with legacy_db.engine.begin() as connection:
        versions = connection.execute(text(f"SELECT version FROM {MIGRATIONS_TABLE}")).fetchall()
    assert [row[0] for row in versions] == [version for version, _ in MIGRATIONS]


def test_reconcile_reports_only_real_changes(legacy_db):
    # First pass adds the missing columns; a second pass adds nothing.
    added = reconcile(legacy_db.engine)
    assert "analyzer_telegram_links.telegram_user_id" in added
    assert reconcile(legacy_db.engine) == []


# --------------------------------------------------------------------------- #
# A fresh database needs no reconciliation
# --------------------------------------------------------------------------- #

def test_a_fresh_database_needs_no_reconciliation(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    db.initialize()
    # create_all made every table in the correct shape, so nothing is added.
    assert reconcile(db.engine) == []
    columns = _columns(db, "analyzer_telegram_links")
    assert "telegram_user_id" in columns


def test_a_missing_column_on_any_table_is_added(tmp_path):
    """The fix covers the whole class, not only the reported table."""

    db = Database(f"sqlite:///{(tmp_path / 'partial.db').as_posix()}")
    db.initialize()
    # Drop a column by rebuilding the table without it, as an older release would
    # have left it.
    with db.engine.begin() as connection:
        connection.execute(text("ALTER TABLE analyzer_support_conversations RENAME TO _old_conv"))
        connection.execute(text(
            "CREATE TABLE analyzer_support_conversations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, account_id BIGINT, status VARCHAR(16), "
            "created_at DATETIME, updated_at DATETIME)"  # closed_at missing
        ))
        connection.execute(text("DROP TABLE _old_conv"))

    assert "closed_at" not in _columns(db, "analyzer_support_conversations")
    db.initialize()
    assert "closed_at" in _columns(db, "analyzer_support_conversations")


def test_reconciliation_leaves_unrelated_columns_untouched(legacy_db):
    """The legacy columns are not dropped: an operator may still need them."""

    legacy_db.initialize()
    columns = _columns(legacy_db, "analyzer_telegram_links")
    assert {"chat_id", "user_email", "username"} <= columns
