from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, JSON, String, TypeDecorator, create_engine, event, insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(timezone.utc) if value else None

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class CurrentRow(Base):
    __tablename__ = "analyzer_current"
    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, default=0)
    source_version: Mapped[int] = mapped_column(BigInteger, default=0)
    model_version: Mapped[int] = mapped_column(BigInteger, default=0)


class SourceRow(Base):
    __tablename__ = "analyzer_sources"
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict] = mapped_column(JSON)


class ModelRow(Base):
    __tablename__ = "analyzer_models"
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload: Mapped[dict] = mapped_column(JSON)


class AnalysisRow(Base):
    __tablename__ = "analyzer_analyses"
    generation: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    source_version: Mapped[int] = mapped_column(ForeignKey("analyzer_sources.version"))
    model_version: Mapped[int] = mapped_column(ForeignKey("analyzer_models.version"))
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    summary: Mapped[dict] = mapped_column(JSON)


class CustomerRow(Base):
    __tablename__ = "analyzer_customers"
    generation: Mapped[int] = mapped_column(ForeignKey("analyzer_analyses.generation"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_category: Mapped[str] = mapped_column(String(32))
    balance: Mapped[int | None] = mapped_column(BigInteger)
    total_replenished: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        Index("analyzer_customers_risk_idx", "generation", "risk_score", "customer_id"),
        Index("analyzer_customers_balance_idx", "generation", "balance", "customer_id"),
        Index("analyzer_customers_replenished_idx", "generation", "total_replenished", "customer_id"),
        Index("analyzer_customers_email_idx", "generation", "email", "customer_id"),
        Index("analyzer_customers_category_idx", "generation", "risk_category"),
    )


class ServiceIndexRow(Base):
    __tablename__ = "analyzer_service_index"
    generation: Mapped[int] = mapped_column(ForeignKey("analyzer_analyses.generation"), primary_key=True)
    service_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))
    __table_args__ = (Index("analyzer_service_status_idx", "generation", "status", "customer_id"),)


class ObservationRow(Base):
    __tablename__ = "analyzer_observations"
    source_version: Mapped[int] = mapped_column(ForeignKey("analyzer_sources.version"), primary_key=True)
    service_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    previous_status: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    previous_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditRow(Base):
    __tablename__ = "analyzer_audit"
    generation: Mapped[int] = mapped_column(ForeignKey("analyzer_analyses.generation"), primary_key=True)
    actor: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class UserRow(Base):
    __tablename__ = "analyzer_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuthSessionRow(Base):
    __tablename__ = "analyzer_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("analyzer_users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ActionStatusRow(Base):
    """Operator workflow state for one retention recommendation.

    Kept deliberately separate from the analytics tables: changing a status must
    never touch the score, the exposure or the model settings.  The row is keyed
    by ``(generation, customer_id, code)`` so a recalculated generation starts
    with a clean workflow while the previous generation's decisions stay on
    record rather than being silently rewritten.
    """

    __tablename__ = "analyzer_action_status"
    generation: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    assignee: Mapped[str | None] = mapped_column(String(320), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


ANALYTICS_TABLES = (
    CurrentRow.__table__, SourceRow.__table__, ModelRow.__table__, AnalysisRow.__table__,
    CustomerRow.__table__, ServiceIndexRow.__table__, ObservationRow.__table__, AuditRow.__table__,
    ActionStatusRow.__table__,
)
AUTH_TABLES = (UserRow.__table__, AuthSessionRow.__table__)


class Database:
    def __init__(self, url: str):
        parsed = make_url(url)
        options = {"pool_pre_ping": True}
        if parsed.get_backend_name() == "sqlite":
            if parsed.database and parsed.database != ":memory:":
                from pathlib import Path
                Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if not parsed.database or parsed.database == ":memory:":
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", self._sqlite_connect)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _sqlite_connect(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def initialize(self):
        Base.metadata.create_all(self.engine, tables=ANALYTICS_TABLES)
        try:
            with self.transaction() as session:
                if session.get(CurrentRow, 1) is None:
                    session.execute(insert(CurrentRow).values(id=1, generation=0, source_version=0, model_version=0))
        except IntegrityError:
            with self.sessions() as session:
                if session.get(CurrentRow, 1) is None:
                    raise

    def initialize_auth(self):
        Base.metadata.create_all(self.engine, tables=AUTH_TABLES)

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session
