from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from modules.payments.exceptions import OptimisticLockingException
from modules.payments.models import (
    DriverEarning,
    IdempotencyRecord,
    PaymentAuditLog,
    PlatformCommissionRule,
    ReconciliationReport,
    Refund,
    RidePayment,
    Transaction,
    Wallet,
)


class WalletRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        wallet_type: str,
        user_id: str | None = None,
        driver_id: str | None = None,
        currency: str = "USD",
    ) -> Wallet:
        wallet = Wallet(
            wallet_type=wallet_type,
            user_id=user_id,
            driver_id=driver_id,
            currency=currency,
            balance=Decimal("0.00"),
            locked_balance=Decimal("0.00"),
            status="ACTIVE",
            version=1,
        )
        self.db.add(wallet)
        self.db.flush()
        self.db.refresh(wallet)
        return wallet

    def get_by_id(self, wallet_id: str) -> Wallet | None:
        return self.db.query(Wallet).filter(Wallet.id == wallet_id).one_or_none()

    def get_by_user_id(self, user_id: str) -> Wallet | None:
        # Defensive: some legacy data has duplicate USER wallets.
        # Return the most recently created one until a unique constraint is added.
        return (
            self.db.query(Wallet)
            .filter(Wallet.user_id == user_id, Wallet.wallet_type == "USER")
            .order_by(Wallet.created_at.desc())
            .first()
        )

    def get_by_driver_id(self, driver_id: str) -> Wallet | None:
        return (
            self.db.query(Wallet)
            .filter(Wallet.driver_id == driver_id, Wallet.wallet_type == "DRIVER")
            .order_by(Wallet.created_at.desc())
            .first()
        )

    def get_or_create_platform_wallet(self, currency: str = "USD") -> Wallet:
        platform_wallet = (
            self.db.query(Wallet)
            .filter(Wallet.wallet_type == "PLATFORM", Wallet.currency == currency)
            .one_or_none()
        )
        if not platform_wallet:
            platform_wallet = self.create(
                wallet_type="PLATFORM", currency=currency
            )
        return platform_wallet

    def get_for_update(self, wallet_id: str) -> Wallet | None:
        return (
            self.db.query(Wallet)
            .filter(Wallet.id == wallet_id)
            .with_for_update()
            .one_or_none()
        )

    def get_wallets_for_update_sorted(self, wallet_ids: list[str]) -> dict[str, Wallet]:
        """Locks wallets in sorted primary key order to prevent deadlocks in multi-wallet transactions."""
        unique_sorted_ids = sorted(list(set(wallet_ids)))
        wallets_map: dict[str, Wallet] = {}
        for wid in unique_sorted_ids:
            w = self.get_for_update(wid)
            if w:
                wallets_map[wid] = w
        return wallets_map

    def update_balance_optimistic(
        self, wallet: Wallet, balance_delta: Decimal, locked_delta: Decimal = Decimal("0.00")
    ) -> Wallet:
        """Executes optimistic locking update on wallet balance."""
        new_balance = wallet.balance + balance_delta
        new_locked = wallet.locked_balance + locked_delta

        if new_balance < 0 or new_locked < 0:
            raise ValueError("Balance cannot drop below zero")

        rows_updated = (
            self.db.query(Wallet)
            .filter(Wallet.id == wallet.id, Wallet.version == wallet.version)
            .update(
                {
                    Wallet.balance: new_balance,
                    Wallet.locked_balance: new_locked,
                    Wallet.version: Wallet.version + 1,
                    Wallet.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )

        if rows_updated == 0:
            raise OptimisticLockingException("Wallet", wallet.id)

        self.db.expire(wallet)
        return self.get_by_id(wallet.id)  # type: ignore

    def list_all_wallets(self, limit: int = 1000, offset: int = 0) -> list[Wallet]:
        return self.db.query(Wallet).limit(limit).offset(offset).all()


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> Transaction:
        txn = Transaction(**data)
        self.db.add(txn)
        self.db.flush()
        self.db.refresh(txn)
        return txn

    def get_by_id(self, txn_id: str) -> Transaction | None:
        return self.db.query(Transaction).filter(Transaction.id == txn_id).one_or_none()

    def get_by_reference(self, reference: str) -> Transaction | None:
        return (
            self.db.query(Transaction)
            .filter(Transaction.reference == reference)
            .one_or_none()
        )

    def get_by_idempotency_key(self, idempotency_key: str) -> Transaction | None:
        return (
            self.db.query(Transaction)
            .filter(Transaction.idempotency_key == idempotency_key)
            .one_or_none()
        )

    def list_for_wallet(
        self,
        wallet_id: str,
        transaction_type: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        query = self.db.query(Transaction).filter(
            or_(
                Transaction.source_wallet_id == wallet_id,
                Transaction.target_wallet_id == wallet_id,
            )
        )

        if transaction_type:
            query = query.filter(Transaction.transaction_type == transaction_type)
        if status:
            query = query.filter(Transaction.status == status)
        if start_date:
            query = query.filter(Transaction.created_at >= start_date)
        if end_date:
            query = query.filter(Transaction.created_at <= end_date)

        total = query.count()
        items = (
            query.order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return items, total

    def calculate_wallet_ledger_net(self, wallet_id: str) -> Decimal:
        """Sums all completed incoming credits and subtracts outgoing debits to get true ledger net balance."""
        credits = (
            self.db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0.00")))
            .filter(
                Transaction.target_wallet_id == wallet_id,
                Transaction.status == "COMPLETED",
            )
            .scalar()
        )
        debits = (
            self.db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0.00")))
            .filter(
                Transaction.source_wallet_id == wallet_id,
                Transaction.status == "COMPLETED",
            )
            .scalar()
        )
        return Decimal(str(credits)) - Decimal(str(debits))


class RidePaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> RidePayment:
        payment = RidePayment(**data)
        self.db.add(payment)
        self.db.flush()
        self.db.refresh(payment)
        return payment

    def get_by_id(self, payment_id: str) -> RidePayment | None:
        return self.db.query(RidePayment).filter(RidePayment.id == payment_id).one_or_none()

    def get_by_ride_id(self, ride_id: str) -> RidePayment | None:
        return self.db.query(RidePayment).filter(RidePayment.ride_id == ride_id).one_or_none()

    def get_by_idempotency_key(self, idempotency_key: str) -> RidePayment | None:
        return (
            self.db.query(RidePayment)
            .filter(RidePayment.idempotency_key == idempotency_key)
            .one_or_none()
        )


class RefundRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> Refund:
        refund = Refund(**data)
        self.db.add(refund)
        self.db.flush()
        self.db.refresh(refund)
        return refund

    def get_by_id(self, refund_id: str) -> Refund | None:
        return self.db.query(Refund).filter(Refund.id == refund_id).one_or_none()

    def get_by_idempotency_key(self, idempotency_key: str) -> Refund | None:
        return (
            self.db.query(Refund)
            .filter(Refund.idempotency_key == idempotency_key)
            .one_or_none()
        )

    def list_for_payment(self, payment_id: str) -> list[Refund]:
        return self.db.query(Refund).filter(Refund.payment_id == payment_id).all()


class DriverEarningRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> DriverEarning:
        earning = DriverEarning(**data)
        self.db.add(earning)
        self.db.flush()
        self.db.refresh(earning)
        return earning

    def get_by_driver_and_ride(self, driver_id: str, ride_id: str) -> DriverEarning | None:
        return (
            self.db.query(DriverEarning)
            .filter(DriverEarning.driver_id == driver_id, DriverEarning.ride_id == ride_id)
            .one_or_none()
        )

    def get_summary_for_driver(self, driver_id: str) -> dict[str, Any]:
        result = (
            self.db.query(
                func.coalesce(func.sum(DriverEarning.gross_fare), Decimal("0.00")).label("total_gross"),
                func.coalesce(func.sum(DriverEarning.commission_deducted), Decimal("0.00")).label("total_commission"),
                func.coalesce(func.sum(DriverEarning.tip_amount), Decimal("0.00")).label("total_tips"),
                func.coalesce(func.sum(DriverEarning.net_earning), Decimal("0.00")).label("total_net"),
                func.count(DriverEarning.id).label("total_rides"),
            )
            .filter(DriverEarning.driver_id == driver_id)
            .one()
        )

        pending_payout = (
            self.db.query(func.coalesce(func.sum(DriverEarning.net_earning), Decimal("0.00")))
            .filter(DriverEarning.driver_id == driver_id, DriverEarning.payout_status == "PENDING")
            .scalar()
        )

        paid_out = (
            self.db.query(func.coalesce(func.sum(DriverEarning.net_earning), Decimal("0.00")))
            .filter(DriverEarning.driver_id == driver_id, DriverEarning.payout_status == "COMPLETED")
            .scalar()
        )

        return {
            "driver_id": driver_id,
            "total_gross_fare": Decimal(str(result.total_gross)),
            "total_commission": Decimal(str(result.total_commission)),
            "total_tips": Decimal(str(result.total_tips)),
            "total_net_earnings": Decimal(str(result.total_net)),
            "total_rides": int(result.total_rides),
            "pending_payout_amount": Decimal(str(pending_payout)),
            "paid_out_amount": Decimal(str(paid_out)),
        }


class CommissionRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_active_rule(self) -> PlatformCommissionRule | None:
        return (
            self.db.query(PlatformCommissionRule)
            .filter(PlatformCommissionRule.is_active == True)  # noqa: E712
            .order_by(PlatformCommissionRule.created_at.desc())
            .first()
        )

    def create_rule(self, data: dict[str, Any]) -> PlatformCommissionRule:
        rule = PlatformCommissionRule(**data)
        self.db.add(rule)
        self.db.flush()
        self.db.refresh(rule)
        return rule


class IdempotencyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_record(self, key: str) -> IdempotencyRecord | None:
        return (
            self.db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.idempotency_key == key)
            .one_or_none()
        )

    def create_record(
        self,
        key: str,
        request_path: str,
        request_hash: str,
        response_code: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        rec = IdempotencyRecord(
            idempotency_key=key,
            request_path=request_path,
            request_hash=request_hash,
            response_code=response_code,
            response_body=response_body,
        )
        self.db.add(rec)
        self.db.flush()
        self.db.refresh(rec)
        return rec


class PaymentAuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def log_event(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> PaymentAuditLog:
        log = PaymentAuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            before_state=before_state,
            after_state=after_state,
            ip_address=ip_address,
        )
        self.db.add(log)
        self.db.flush()
        self.db.refresh(log)
        return log


class ReconciliationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_report(
        self,
        status: str,
        total_wallets_checked: int,
        discrepancies_count: int,
        details_json: dict[str, Any],
    ) -> ReconciliationReport:
        report = ReconciliationReport(
            status=status,
            total_wallets_checked=total_wallets_checked,
            discrepancies_count=discrepancies_count,
            details_json=details_json,
        )
        self.db.add(report)
        self.db.flush()
        self.db.refresh(report)
        return report
