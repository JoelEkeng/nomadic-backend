import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint(
            "wallet_type IN ('USER', 'DRIVER', 'PLATFORM')",
            name="ck_wallets_wallet_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'FROZEN', 'CLOSED')",
            name="ck_wallets_status",
        ),
        CheckConstraint("balance >= 0", name="ck_wallets_balance_non_negative"),
        CheckConstraint("locked_balance >= 0", name="ck_wallets_locked_balance_non_negative"),
        Index("ix_wallets_user_id", "user_id"),
        Index("ix_wallets_driver_id", "driver_id"),
        Index("ix_wallets_type_status", "wallet_type", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("drivers.id", ondelete="CASCADE"),
        nullable=True,
    )
    wallet_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="USER", server_default="USER"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    locked_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def available_balance(self) -> Decimal:
        """Returns liquid unreserved balance."""
        return self.balance - self.locked_balance


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("fee_amount >= 0", name="ck_transactions_fee_non_negative"),
        CheckConstraint(
            "transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'RIDE_PAYMENT', 'DRIVER_PAYOUT', 'REFUND', 'PLATFORM_COMMISSION', 'TRANSFER', 'SYSTEM_ADJUSTMENT')",
            name="ck_transactions_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'REVERSED')",
            name="ck_transactions_status",
        ),
        Index("ix_transactions_reference", "reference", unique=True),
        Index("ix_transactions_idempotency_key", "idempotency_key"),
        Index("ix_transactions_source_wallet", "source_wallet_id"),
        Index("ix_transactions_target_wallet", "target_wallet_id"),
        Index("ix_transactions_ride_id", "ride_id"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    source_wallet_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True
    )
    target_wallet_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_wallet: Mapped[Wallet | None] = relationship("Wallet", foreign_keys=[source_wallet_id])
    target_wallet: Mapped[Wallet | None] = relationship("Wallet", foreign_keys=[target_wallet_id])


class RidePayment(Base):
    __tablename__ = "ride_payments"
    __table_args__ = (
        CheckConstraint("gross_amount >= 0", name="ck_ride_payments_gross_non_negative"),
        CheckConstraint("platform_commission >= 0", name="ck_ride_payments_commission_non_negative"),
        CheckConstraint("driver_net_earnings >= 0", name="ck_ride_payments_net_non_negative"),
        CheckConstraint(
            "status IN ('PENDING', 'AUTHORIZED', 'CAPTURED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'FAILED', 'CANCELLED')",
            name="ck_ride_payments_status",
        ),
        Index("ix_ride_payments_ride_id", "ride_id", unique=True),
        Index("ix_ride_payments_student_id", "student_id"),
        Index("ix_ride_payments_driver_id", "driver_id"),
        Index("ix_ride_payments_status", "status"),
        Index("ix_ride_payments_idempotency", "idempotency_key"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    platform_commission: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    driver_net_earnings: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    tip_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED')",
            name="ck_refunds_status",
        ),
        Index("ix_refunds_payment_id", "payment_id"),
        Index("ix_refunds_transaction_id", "transaction_id"),
        Index("ix_refunds_status", "status"),
        Index("ix_refunds_idempotency_key", "idempotency_key"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ride_payments.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DriverEarning(Base):
    __tablename__ = "driver_earnings"
    __table_args__ = (
        CheckConstraint("gross_fare >= 0", name="ck_driver_earnings_gross_non_negative"),
        CheckConstraint("net_earning >= 0", name="ck_driver_earnings_net_non_negative"),
        CheckConstraint(
            "payout_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_driver_earnings_payout_status",
        ),
        Index("ix_driver_earnings_driver_id", "driver_id"),
        Index("ix_driver_earnings_ride_id", "ride_id", unique=True),
        Index("ix_driver_earnings_payout_status", "payout_status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    driver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    gross_fare: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    commission_deducted: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tip_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    net_earning: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payout_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlatformCommissionRule(Base):
    __tablename__ = "platform_commission_rules"
    __table_args__ = (
        CheckConstraint("percentage >= 0 AND percentage <= 100", name="ck_commission_percentage_range"),
        CheckConstraint("fixed_fee >= 0", name="ck_commission_fixed_fee_non_negative"),
        Index("ix_commission_rules_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("15.00"), server_default="15.00"
    )
    fixed_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("ix_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    request_path: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentAuditLog(Base):
    __tablename__ = "payment_audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_actor", "actor_id"),
        Index("ix_audit_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"
    __table_args__ = (
        Index("ix_reconciliation_status", "status"),
        Index("ix_reconciliation_run_at", "run_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_wallets_checked: Mapped[int] = mapped_column(Integer, nullable=False)
    discrepancies_count: Mapped[int] = mapped_column(Integer, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
