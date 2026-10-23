"""Database engine, session factory and ORM models.

The schema mirrors the source snapshot: ``accounts``, ``services`` and
``transactions``, plus operational tables for model settings, users and import
reports.  Monetary columns keep the raw integer eurocent values from the
snapshot so no lossy round-trip happens on import.
"""

from __future__ import annotations

import datetime as dt
import os
from contextlib import contextmanager

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime that survives SQLite round-trips.

    SQLite has no native timezone support and returns naive datetimes, which
    would make every horizon comparison fail.  This type normalises values to
    UTC on the way in and re-attaches UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    withdraw_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_replenished: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bonus_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bonus_state: Mapped[str] = mapped_column(String(16), nullable=False, default="locked")

    services: Mapped[list["ServiceRow"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="selectin"
    )


class ServiceRow(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    payment_term: Mapped[str] = mapped_column(String(16), nullable=False)
    auto_prolong: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)

    owner: Mapped[AccountRow] = relationship(back_populates="services")
    transactions: Mapped[list["TransactionRow"]] = relationship(
        back_populates="service", cascade="all, delete-orphan", lazy="selectin"
    )


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    performed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False, index=True)

    service: Mapped[ServiceRow] = relationship(back_populates="transactions")


class ModelSettingsRow(Base):
    __tablename__ = "model_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    low_max: Mapped[int] = mapped_column(Integer, nullable=False, default=34)
    medium_max: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    weights_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    #: Trailing window (days) for failed renewals.  ``NULL`` means the whole
    #: snapshot, which is a valid configuration, so the column is nullable.
    failed_renewal_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)


class ImportRunRow(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    services: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Session:
    """Transactional session scope that commits on success and rolls back on error."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests() -> None:
    """Drop cached engine/session so tests can point at a fresh database."""

    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def _ensure_columns() -> None:
    """Add columns introduced after a database was first created.

    ``create_all`` only creates missing *tables*, so an existing SQLite file
    would keep the old ``model_settings`` shape and every query would fail with
    "no such column".  Adding the column when absent keeps old stores usable
    instead of forcing a re-import.
    """

    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as connection:
        existing = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(model_settings)"
            ).fetchall()
        }
        if not existing:
            return
        if "failed_renewal_window_days" not in existing:
            connection.exec_driver_sql(
                "ALTER TABLE model_settings ADD COLUMN failed_renewal_window_days INTEGER"
            )
            connection.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    _ensure_columns()
