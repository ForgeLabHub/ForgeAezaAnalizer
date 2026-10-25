"""Versioned schema reconciliation for the analytics database.

Why this exists
---------------
``Base.metadata.create_all()`` only *creates* missing tables. It never alters a
table that already exists, so a release that adds a column (or changes a table
that a previous implementation created with different columns) starts against a
database whose shape no longer matches the ORM. That produced a production
outage:

    psycopg.errors.UndefinedColumn: column analyzer_telegram_links.telegram_user_id does not exist

The concrete collision: an earlier Telegram implementation created
``analyzer_telegram_links`` with ``chat_id``/``user_email``/``username``, while the
current ORM expects ``telegram_user_id``/``account_id``/``notifications_enabled``/
``consent_at``/``updated_at``. ``create_all`` saw the table, skipped it, and every
read or write of a link failed.

What this module does
---------------------
1. :func:`reconcile` — an additive, non-destructive pass: for every ORM table that
   already exists, it adds any missing column (nullable, with a server default
   where the model has one). Adding a column never loses data, so this is safe to
   run on every start and fixes the whole class of "new release expects a column
   that is not there" problems, not just the one reported.
2. :func:`apply_migrations` — a small, ordered, recorded migration registry for
   changes an additive pass cannot express (renames, backfills, constraint
   changes). Applied versions are recorded in ``schema_migrations``, so each runs
   at most once and a re-run is a no-op.

Both run inside ``Database.initialize()`` after ``create_all``.

Safety rules this module follows
--------------------------------
* Nothing is dropped or truncated. No data is deleted.
* A column is only made ``NOT NULL`` when the table is empty; otherwise it stays
  nullable so an existing row is never rejected (the ORM still writes a value).
* A backfill runs only when the source column exists; it never invents values.
* A migration that cannot proceed safely raises a clear error instead of
  guessing, so an operator sees the reason rather than silent corruption.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import ANALYTICS_TABLES

logger = logging.getLogger("aeza.schema")


MIGRATIONS_TABLE = "schema_migrations"


def _quote(identifier: str, dialect: str) -> str:
    """Quote an identifier for the dialect (Postgres folds unquoted names)."""

    if dialect == "postgresql":
        return '"' + identifier.replace('"', '""') + '"'
    return '"' + identifier.replace('"', '""') + '"'


def _column_ddl(column, dialect) -> str:
    """Render an ``ADD COLUMN`` clause for a model column that is missing.

    The column is always added nullable: a ``NOT NULL`` column cannot be added to
    a table that already holds rows without a default, and rejecting existing rows
    is worse than a temporarily nullable column the ORM will populate anyway.
    """

    type_sql = column.type.compile(dialect=dialect)
    ddl = f"{_quote(column.name, dialect)} {type_sql}"


    default = column.default
    if default is not None and not default.is_callable and not default.is_sequence:
        value = default.arg
        if isinstance(value, bool):
            ddl += f" DEFAULT {'true' if value else 'false'}"
        elif isinstance(value, (int, float)):
            ddl += f" DEFAULT {value}"
        elif isinstance(value, str):
            ddl += " DEFAULT '" + value.replace("'", "''") + "'"
    return ddl


def reconcile(engine: Engine) -> list[str]:
    """Add missing columns to existing tables. Returns the changes made.

    Additive only: it never drops, renames or retypes a column, and never touches
    a table that does not exist (``create_all`` has already made it).
    """

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect_name = engine.dialect.name
    changes: list[str] = []

    with engine.begin() as connection:
        for table in ANALYTICS_TABLES:
            name = table.name
            if name not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = _column_ddl(column, engine.dialect)
                connection.execute(text(f"ALTER TABLE {_quote(name, dialect_name)} ADD COLUMN {ddl}"))
                change = f"{name}.{column.name}"
                changes.append(change)
                logger.warning("schema.reconcile: added missing column %s", change)
    return changes


def _recorded(connection, dialect: str) -> set[str]:
    connection.execute(text(
        f"CREATE TABLE IF NOT EXISTS {_quote(MIGRATIONS_TABLE, dialect)} ("
        "version varchar(64) PRIMARY KEY, applied_at timestamptz NOT NULL)"
        if dialect == "postgresql" else
        f"CREATE TABLE IF NOT EXISTS {_quote(MIGRATIONS_TABLE, dialect)} ("
        "version varchar(64) PRIMARY KEY, applied_at datetime NOT NULL)"
    ))
    rows = connection.execute(text(f"SELECT version FROM {_quote(MIGRATIONS_TABLE, dialect)}")).fetchall()
    return {row[0] for row in rows}


def _has_column(connection, dialect: str, table: str, column: str) -> bool:
    if dialect == "sqlite":

        columns = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in columns)
    row = connection.execute(
        text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _table_exists(connection, dialect: str, table: str) -> bool:
    if dialect == "sqlite":
        row = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}
        ).fetchone()
        return row is not None
    row = connection.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"), {"n": table}
    ).fetchone()
    return row is not None


def _migration_telegram_link_legacy_shape(connection, dialect: str) -> None:
    """Reconcile ``analyzer_telegram_links`` created by the earlier implementation.

    The old table carried ``chat_id``/``user_email``/``username``; the current ORM
    needs ``telegram_user_id``/``account_id``/``notifications_enabled``/
    ``consent_at``/``updated_at``. :func:`reconcile` has already added the missing
    columns as nullable, so this migration only backfills them:

    * ``telegram_user_id`` ← ``chat_id`` (the bot only served private chats, where
      ``chat_id`` *is* the user id — the old code used it as the identity);
    * ``account_id`` ← the analytics account whose email matches ``user_email``,
      when that lookup is unambiguous.

    A row that cannot be mapped is left with a NULL ``account_id`` and reported,
    rather than deleted or assigned to an arbitrary account.
    """

    if not _table_exists(connection, dialect, "analyzer_telegram_links"):
        return
    if not _has_column(connection, dialect, "analyzer_telegram_links", "chat_id"):
        return


    connection.execute(text(
        "UPDATE analyzer_telegram_links SET telegram_user_id = chat_id "
        "WHERE telegram_user_id IS NULL AND chat_id IS NOT NULL"
    ))


    if _has_column(connection, dialect, "analyzer_telegram_links", "user_email") and _table_exists(
        connection, dialect, "accounts"
    ):
        connection.execute(text(
            "UPDATE analyzer_telegram_links SET account_id = ("
            "  SELECT a.id FROM accounts AS a WHERE lower(a.email) = lower(analyzer_telegram_links.user_email)"
            ") WHERE account_id IS NULL AND user_email IS NOT NULL AND ("
            "  SELECT count(*) FROM accounts AS a2 WHERE lower(a2.email) = lower(analyzer_telegram_links.user_email)"
            ") = 1"
        ))

    unmapped = connection.execute(text(
        "SELECT count(*) FROM analyzer_telegram_links WHERE account_id IS NULL"
    )).scalar()
    if unmapped:
        logger.warning(
            "schema.migration: %s legacy telegram link(s) have no matching account and were left "
            "with a NULL account_id; they will be ignored until re-linked", unmapped,
        )


MIGRATIONS: tuple[tuple[str, object], ...] = (
    ("2026_10_24_telegram_link_legacy_shape", _migration_telegram_link_legacy_shape),
)


def apply_migrations(engine: Engine) -> list[str]:
    """Run every migration not yet recorded. Returns the versions applied.

    Each migration runs in its own transaction: a failure rolls that migration back
    and is not recorded, so the next start retries it rather than leaving the
    database half-updated.
    """

    dialect = engine.dialect.name
    applied: list[str] = []
    with engine.begin() as connection:
        done = _recorded(connection, dialect)
    for version, migration in MIGRATIONS:
        if version in done:
            continue
        with engine.begin() as connection:
            migration(connection, dialect)
            connection.execute(
                text(f"INSERT INTO {_quote(MIGRATIONS_TABLE, dialect)} (version, applied_at) "
                     "VALUES (:v, :t)"),
                {"v": version, "t": datetime.now(timezone.utc)},
            )
        applied.append(version)
        logger.warning("schema.migration: applied %s", version)
    return applied


def ensure_schema(engine: Engine) -> dict:
    """Reconcile columns, then apply migrations. Safe to call on every start."""

    return {"columnsAdded": reconcile(engine), "migrationsApplied": apply_migrations(engine)}
