from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, TypeDecorator, UniqueConstraint, create_engine, event, insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("aeza.db")


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


class RecommendationStatusRow(Base):
    """Workflow status of one retention playbook for one customer.

    Deliberately **not** keyed by ``generation``. A generation is republished on
    every recalculation, so tying a status to it would silently reset the
    operator's work whenever the snapshot or the model settings changed. The
    natural key is the pair the analytics layer already uses to deduplicate
    recommendations: the customer and the stable recommendation ``code``.

    Nothing here feeds back into the model: a status is a workflow fact, not an
    analytical signal, so it can never change a score or an exposure.
    """

    __tablename__ = "analyzer_recommendation_status"
    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_by: Mapped[str] = mapped_column(String(320))


class ActionRow(Base):
    """A retention action a human confirmed for a customer.

    Deliberately *not* keyed by analysis generation: an action is a human
    decision and must survive the next import or model change.  ``generation``
    records only the context in which the action was created.
    """

    __tablename__ = "analyzer_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    service_id: Mapped[int | None] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(32), default="open")
    note: Mapped[str | None] = mapped_column(String(2000))
    generation: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (Index("analyzer_actions_customer_idx", "customer_id", "created_at"),)


class TelegramLinkRow(Base):
    __tablename__ = "analyzer_telegram_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TelegramOtpRow(Base):
    __tablename__ = "analyzer_telegram_otps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_user_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    account_id: Mapped[int] = mapped_column(BigInteger)
    code_hash: Mapped[str] = mapped_column(String(128))
    code_salt: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    next_send_at: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (Index("analyzer_telegram_otp_lookup_idx", "telegram_user_id", "email", "created_at"),)


class TelegramChatStateRow(Base):
    __tablename__ = "analyzer_telegram_chat_states"
    telegram_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(320))
    otp_id: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TelegramClientSessionRow(Base):
    __tablename__ = "analyzer_telegram_sessions"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("analyzer_telegram_links.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SupportConversationRow(Base):
    __tablename__ = "analyzer_support_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (Index("analyzer_support_conversation_account_idx", "account_id", "updated_at"),)


class SupportMessageRow(Base):
    __tablename__ = "analyzer_support_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("analyzer_support_conversations.id", ondelete="CASCADE"), index=True)
    sender: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(4000))
    telegram_message_id: Mapped[str | None] = mapped_column(String(128))
    delivery_status: Mapped[str] = mapped_column(String(16), default="received")
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (
        Index("analyzer_support_message_conversation_idx", "conversation_id", "created_at"),
        UniqueConstraint("telegram_message_id", name="analyzer_support_telegram_message_key"),
    )


class SupportMessageDeliveryRow(Base):
    __tablename__ = "analyzer_support_message_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("analyzer_support_messages.id", ondelete="CASCADE"), index=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("analyzer_telegram_links.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (UniqueConstraint("message_id", "link_id", name="analyzer_support_delivery_key"),)


class NotificationQueueRow(Base):
    __tablename__ = "analyzer_telegram_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    service_id: Mapped[int] = mapped_column(BigInteger, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    interval_days: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (
        UniqueConstraint("account_id", "service_id", "expires_at", "interval_days", name="analyzer_telegram_notification_key"),
        Index("analyzer_telegram_notification_due_idx", "status", "scheduled_at"),
    )


class NotificationDeliveryRow(Base):
    __tablename__ = "analyzer_telegram_notification_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("analyzer_telegram_notifications.id", ondelete="CASCADE"), index=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("analyzer_telegram_links.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (UniqueConstraint("notification_id", "link_id", name="analyzer_telegram_delivery_key"),)


class TelegramUpdateRow(Base):
    """One processed Telegram ``update_id``, for at-most-once webhook handling.

    Telegram redelivers an update when the webhook does not answer in time. The
    primary key is the update id, so a concurrent duplicate loses the insert and
    the business action runs once. ``processed_at`` lets a cleanup drop old rows.
    """

    __tablename__ = "analyzer_telegram_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


ANALYTICS_TABLES = (
    CurrentRow.__table__, SourceRow.__table__, ModelRow.__table__, AnalysisRow.__table__,
    CustomerRow.__table__, ServiceIndexRow.__table__, ObservationRow.__table__, AuditRow.__table__,


    RecommendationStatusRow.__table__,

    ActionRow.__table__,
    TelegramLinkRow.__table__, TelegramOtpRow.__table__, TelegramChatStateRow.__table__,
    TelegramClientSessionRow.__table__, SupportConversationRow.__table__, SupportMessageRow.__table__,
    SupportMessageDeliveryRow.__table__, NotificationQueueRow.__table__, NotificationDeliveryRow.__table__,
    TelegramUpdateRow.__table__,
)
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


        from backend.app.schema import ensure_schema

        result = ensure_schema(self.engine)
        if result["columnsAdded"] or result["migrationsApplied"]:
            logger.warning("schema.ensure: %s", result)
        try:
            with self.transaction() as session:
                if session.get(CurrentRow, 1) is None:
                    session.execute(insert(CurrentRow).values(id=1, generation=0, source_version=0, model_version=0))
        except IntegrityError:
            with self.sessions() as session:
                if session.get(CurrentRow, 1) is None:
                    raise

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session
