"""Engine/session helpers and schema bootstrap."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class StoreError(RuntimeError):
    """The on-disk store is unusable (corrupt, wrong format, unreadable)."""


def _enable_sqlite_fk(dbapi_connection, _record) -> None:
    """Enforce ON DELETE RESTRICT / ON UPDATE RESTRICT semantics on SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = settings.database_url()
        connect_args = {"check_same_thread": False} if _is_sqlite(url) else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        if _is_sqlite(url):
            event.listen(_engine, "connect", _enable_sqlite_fk)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def check_store() -> None:
    """Fail fast with a clear message when the store file is not a valid database.

    A truncated or foreign file would otherwise surface as an opaque
    ``DatabaseError`` deep inside a query. SQLite defers reading the file, so a
    plain ``SELECT 1`` is not enough — the check must touch the schema, which
    also works as a generic connectivity probe on other backends.
    """
    engine = get_engine()
    probe = (
        "SELECT count(*) FROM sqlite_master"
        if engine.dialect.name == "sqlite"
        else "SELECT 1"
    )
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(probe)
    except DatabaseError as exc:
        raise StoreError(
            f"the data store at {settings.db_path} is not a usable database "
            f"({type(exc).__name__}). Back it up, delete it, and re-import: "
            f"python -m aeza_analyzer.cli import"
        ) from exc


def init_db() -> None:
    check_store()
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_state() -> None:
    """Drop cached engine/session (used by tests switching databases)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
