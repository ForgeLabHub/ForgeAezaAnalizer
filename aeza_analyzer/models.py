"""SQLAlchemy models mirroring the organiser fixture schema.

Column names match the source JSON exactly (including camelCase) so the mapping
from source to store is 1:1 and auditable. Money is stored as integer eurocents.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PAYMENT_TERMS = ("hour", "week", "month", "quarter_year", "half_year", "year")
SERVICE_STATUSES = ("active", "blocked", "deleted", "suspended", "prolong_wait")
TRANSACTION_STATUSES = ("not_performed", "performed")
TRANSACTION_TYPES = ("prolong", "order")
BONUS_STATES = ("locked", "unlocked")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime.

    SQLite has no native timezone support and returns naive datetimes. This type
    normalises every value to UTC on the way in and re-attaches UTC on the way
    out, so comparisons between stored and computed timestamps are always valid.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("refusing to store a naive datetime; expected UTC-aware value")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    withdrawBalance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    totalReplenished: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bonusBalance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bonusState: Mapped[str] = mapped_column(String(16), nullable=False, default="locked")

    services: Mapped[list["Service"]] = relationship(
        back_populates="owner", cascade="save-update, merge", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="accounts_balance_non_negative"),
        CheckConstraint('"withdrawBalance" >= 0', name="accounts_withdraw_non_negative"),
        CheckConstraint('"totalReplenished" >= 0', name="accounts_replenished_non_negative"),
        CheckConstraint('"bonusBalance" >= 0', name="accounts_bonus_non_negative"),
        CheckConstraint(
            "\"bonusState\" IN ('locked', 'unlocked')", name="accounts_bonus_state_valid"
        ),
    )


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ownerId: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    paymentTerm: Mapped[str] = mapped_column(String(16), nullable=False)
    autoProlong: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    createdAt: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expiresAt: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)

    owner: Mapped[Account] = relationship(back_populates="services")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="service", cascade="save-update, merge", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("price >= 0", name="services_price_non_negative"),
        CheckConstraint('"expiresAt" >= "createdAt"', name="services_dates_check"),
        CheckConstraint(
            '"paymentTerm" IN ' + str(PAYMENT_TERMS), name="services_payment_term_valid"
        ),
        CheckConstraint('"status" IN ' + str(SERVICE_STATUSES), name="services_status_valid"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_performed")
    performedAt: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    serviceId: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    service: Mapped[Service] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("amount BETWEEN 0 AND 1000", name="transactions_amount_range"),
        CheckConstraint(
            '"status" IN ' + str(TRANSACTION_STATUSES), name="transactions_status_valid"
        ),
        CheckConstraint('"type" IN ' + str(TRANSACTION_TYPES), name="transactions_type_valid"),
        CheckConstraint(
            "(\"status\" = 'not_performed' AND \"performedAt\" IS NULL)"
            " OR (\"status\" = 'performed' AND \"performedAt\" IS NOT NULL"
            ' AND "performedAt" >= "createdAt")',
            name="transactions_performed_check",
        ),
    )


class RiskWeight(Base):
    """Persisted, editable scoring weights (one row per factor key)."""

    __tablename__ = "risk_weights"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    weight: Mapped[float] = mapped_column(nullable=False)


class Meta(Base):
    """Key/value metadata (dataset snapshot time, source digest, counts)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class ImportRun(Base):
    """Audit trail of importer runs for reproducibility and repeatability checks."""

    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    services: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    notes: Mapped[str | None] = mapped_column(Text)
