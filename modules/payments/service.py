import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from modules.payments.exceptions import (
    CommissionConfigException,
    DuplicateIdempotencyException,
    InvalidPaymentStatusException,
    PaymentNotFoundException,
    RefundNotAllowedException,
    WalletFrozenException,
    WalletNotFoundException,
    InsufficientBalanceException,
)
from modules.payments.models import (
    DriverEarning,
    PlatformCommissionRule,
    RidePayment,
    Transaction,
    Wallet,
)
from modules.payments.repository import (
    CommissionRuleRepository,
    DriverEarningRepository,
    IdempotencyRepository,
    PaymentAuditLogRepository,
    ReconciliationRepository,
    RefundRepository,
    RidePaymentRepository,
    TransactionRepository,
    WalletRepository,
)


class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        self.txn_repo = TransactionRepository(db)
        self.ride_payment_repo = RidePaymentRepository(db)
        self.refund_repo = RefundRepository(db)
        self.driver_earning_repo = DriverEarningRepository(db)
        self.commission_repo = CommissionRuleRepository(db)
        self.idempotency_repo = IdempotencyRepository(db)
        self.audit_repo = PaymentAuditLogRepository(db)
        self.reconcile_repo = ReconciliationRepository(db)

    # ------------------------------------------------------------------
    # Idempotency Helper
    # ------------------------------------------------------------------
    def _hash_request(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _check_idempotency(self, key: str | None, request_path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not key:
            return None
        rec = self.idempotency_repo.get_record(key)
        if rec:
            req_hash = self._hash_request(payload)
            if rec.request_hash != req_hash:
                raise DuplicateIdempotencyException(key)
            return rec.response_body
        return None

    def _save_idempotency(self, key: str | None, request_path: str, payload: dict[str, Any], response_code: int, response_body: dict[str, Any]) -> None:
        if key:
            req_hash = self._hash_request(payload)
            self.idempotency_repo.create_record(
                key=key,
                request_path=request_path,
                request_hash=req_hash,
                response_code=response_code,
                response_body=response_body,
            )

    # ------------------------------------------------------------------
    # Wallet Management
    # ------------------------------------------------------------------
    def _persist_new_wallet(self) -> None:
        """Make a freshly created wallet usable without stealing the transaction.

        These helpers are called both standalone and from inside a
        ``begin_nested()`` block. Committing unconditionally would close the
        caller's transaction context mid-block, after which any further statement
        fails with "Can't operate on closed transaction inside context manager".
        So the commit happens only when no caller owns a transaction; otherwise a
        flush is enough to make the row visible to the rest of that transaction.
        """
        self.db.flush()
        if not self.db.in_nested_transaction():
            self.db.commit()

    def get_or_create_user_wallet(self, user_id: str, currency: str = "USD") -> Wallet:
        wallet = self.wallet_repo.get_by_user_id(user_id)
        if not wallet:
            wallet = self.wallet_repo.create(wallet_type="USER", user_id=user_id, currency=currency)
            self.audit_repo.log_event("Wallet", wallet.id, "WALLET_CREATED", actor_id=user_id)
            self._persist_new_wallet()
        return wallet

    def get_or_create_driver_wallet(self, driver_id: str, currency: str = "USD") -> Wallet:
        wallet = self.wallet_repo.get_by_driver_id(driver_id)
        if not wallet:
            wallet = self.wallet_repo.create(wallet_type="DRIVER", driver_id=driver_id, currency=currency)
            self.audit_repo.log_event("Wallet", wallet.id, "DRIVER_WALLET_CREATED", actor_id=driver_id)
            self._persist_new_wallet()
        return wallet

    def get_wallet_by_id(self, wallet_id: str) -> Wallet:
        wallet = self.wallet_repo.get_by_id(wallet_id)
        if not wallet:
            raise WalletNotFoundException(wallet_id)
        return wallet

    def deposit(
        self,
        wallet_id: str,
        amount: Decimal,
        currency: str = "USD",
        description: str | None = None,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> Transaction:
        payload = {"wallet_id": wallet_id, "amount": str(amount), "currency": currency}
        cached = self._check_idempotency(idempotency_key, "/wallets/deposit", payload)
        if cached:
            return self.txn_repo.get_by_id(cached["id"])  # type: ignore

        if amount <= 0:
            raise ValueError("Deposit amount must be positive")

        with self.db.begin_nested():
            wallet = self.wallet_repo.get_for_update(wallet_id)
            if not wallet:
                raise WalletNotFoundException(wallet_id)
            if wallet.status != "ACTIVE":
                raise WalletFrozenException(wallet.id, wallet.status)

            before_balance = wallet.balance
            wallet = self.wallet_repo.update_balance_optimistic(wallet, balance_delta=amount)

            txn_ref = f"DEP-{uuid.uuid4().hex[:12].upper()}"
            txn = self.txn_repo.create(
                {
                    "reference": txn_ref,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": None,
                    "target_wallet_id": wallet.id,
                    "transaction_type": "DEPOSIT",
                    "amount": amount,
                    "fee_amount": Decimal("0.00"),
                    "currency": currency,
                    "status": "COMPLETED",
                    "description": description or "Wallet deposit",
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            self.audit_repo.log_event(
                "Wallet",
                wallet.id,
                "DEPOSIT",
                actor_id=actor_id,
                before_state={"balance": str(before_balance)},
                after_state={"balance": str(wallet.balance)},
            )

            response_data = {"id": txn.id, "reference": txn.reference, "amount": str(txn.amount)}
            self._save_idempotency(idempotency_key, "/wallets/deposit", payload, 200, response_data)

        self.db.commit()
        return txn

    def withdraw(
        self,
        wallet_id: str,
        amount: Decimal,
        currency: str = "USD",
        destination_account: str | None = None,
        description: str | None = None,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> Transaction:
        payload = {"wallet_id": wallet_id, "amount": str(amount), "currency": currency}
        cached = self._check_idempotency(idempotency_key, "/wallets/withdraw", payload)
        if cached:
            return self.txn_repo.get_by_id(cached["id"])  # type: ignore

        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")

        with self.db.begin_nested():
            wallet = self.wallet_repo.get_for_update(wallet_id)
            if not wallet:
                raise WalletNotFoundException(wallet_id)
            if wallet.status != "ACTIVE":
                raise WalletFrozenException(wallet.id, wallet.status)
            if wallet.available_balance < amount:
                raise InsufficientBalanceException(wallet.id, wallet.available_balance, amount)

            before_balance = wallet.balance
            wallet = self.wallet_repo.update_balance_optimistic(wallet, balance_delta=-amount)

            txn_ref = f"WTH-{uuid.uuid4().hex[:12].upper()}"
            txn = self.txn_repo.create(
                {
                    "reference": txn_ref,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": wallet.id,
                    "target_wallet_id": None,
                    "transaction_type": "WITHDRAWAL",
                    "amount": amount,
                    "fee_amount": Decimal("0.00"),
                    "currency": currency,
                    "status": "COMPLETED",
                    "description": description or f"Withdrawal to {destination_account or 'bank'}",
                    "metadata_json": {"destination_account": destination_account},
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            self.audit_repo.log_event(
                "Wallet",
                wallet.id,
                "WITHDRAWAL",
                actor_id=actor_id,
                before_state={"balance": str(before_balance)},
                after_state={"balance": str(wallet.balance)},
            )

            response_data = {"id": txn.id, "reference": txn.reference, "amount": str(txn.amount)}
            self._save_idempotency(idempotency_key, "/wallets/withdraw", payload, 200, response_data)

        self.db.commit()
        return txn

    def transfer(
        self,
        source_wallet_id: str,
        target_wallet_id: str,
        amount: Decimal,
        currency: str = "USD",
        description: str | None = None,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> Transaction:
        if source_wallet_id == target_wallet_id:
            raise ValueError("Source and target wallets must be different")

        payload = {
            "source_wallet_id": source_wallet_id,
            "target_wallet_id": target_wallet_id,
            "amount": str(amount),
        }
        cached = self._check_idempotency(idempotency_key, "/wallets/transfer", payload)
        if cached:
            return self.txn_repo.get_by_id(cached["id"])  # type: ignore

        if amount <= 0:
            raise ValueError("Transfer amount must be positive")

        with self.db.begin_nested():
            wallets = self.wallet_repo.get_wallets_for_update_sorted([source_wallet_id, target_wallet_id])
            source_w = wallets.get(source_wallet_id)
            target_w = wallets.get(target_wallet_id)

            if not source_w:
                raise WalletNotFoundException(source_wallet_id)
            if not target_w:
                raise WalletNotFoundException(target_wallet_id)

            if source_w.status != "ACTIVE":
                raise WalletFrozenException(source_w.id, source_w.status)
            if target_w.status != "ACTIVE":
                raise WalletFrozenException(target_w.id, target_w.status)

            if source_w.available_balance < amount:
                raise InsufficientBalanceException(source_w.id, source_w.available_balance, amount)

            before_src = source_w.balance
            before_tgt = target_w.balance

            source_w = self.wallet_repo.update_balance_optimistic(source_w, balance_delta=-amount)
            target_w = self.wallet_repo.update_balance_optimistic(target_w, balance_delta=amount)

            txn_ref = f"TRF-{uuid.uuid4().hex[:12].upper()}"
            txn = self.txn_repo.create(
                {
                    "reference": txn_ref,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": source_w.id,
                    "target_wallet_id": target_w.id,
                    "transaction_type": "TRANSFER",
                    "amount": amount,
                    "fee_amount": Decimal("0.00"),
                    "currency": currency,
                    "status": "COMPLETED",
                    "description": description or "Wallet transfer",
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            self.audit_repo.log_event(
                "Transaction",
                txn.id,
                "TRANSFER",
                actor_id=actor_id,
                before_state={"source_balance": str(before_src), "target_balance": str(before_tgt)},
                after_state={"source_balance": str(source_w.balance), "target_balance": str(target_w.balance)},
            )

            response_data = {"id": txn.id, "reference": txn.reference, "amount": str(txn.amount)}
            self._save_idempotency(idempotency_key, "/wallets/transfer", payload, 200, response_data)

        self.db.commit()
        return txn

    # ------------------------------------------------------------------
    # Ride Payments Lifecycle
    # ------------------------------------------------------------------
    def authorize_ride_payment(
        self,
        ride_id: str,
        student_id: str,
        estimated_fare: Decimal,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> RidePayment:
        payload = {"ride_id": ride_id, "student_id": student_id, "estimated_fare": str(estimated_fare)}
        cached = self._check_idempotency(idempotency_key, f"/rides/{ride_id}/authorize", payload)
        if cached:
            return self.ride_payment_repo.get_by_id(cached["id"])  # type: ignore

        with self.db.begin_nested():
            # Get or create student wallet using user_id via student table or direct student_id fallback
            student_wallet = self.wallet_repo.get_by_user_id(student_id)
            if not student_wallet:
                student_wallet = self.wallet_repo.get_by_id(student_id)
            if not student_wallet:
                student_wallet = self.get_or_create_user_wallet(student_id)

            student_wallet = self.wallet_repo.get_for_update(student_wallet.id)
            if student_wallet.status != "ACTIVE":
                raise WalletFrozenException(student_wallet.id, student_wallet.status)

            if student_wallet.available_balance < estimated_fare:
                raise InsufficientBalanceException(student_wallet.id, student_wallet.available_balance, estimated_fare)

            # Lock funds in student wallet
            student_wallet = self.wallet_repo.update_balance_optimistic(
                student_wallet, balance_delta=Decimal("0.00"), locked_delta=estimated_fare
            )

            # Check if payment record exists
            payment = self.ride_payment_repo.get_by_ride_id(ride_id)
            if not payment:
                payment = self.ride_payment_repo.create(
                    {
                        "ride_id": ride_id,
                        "student_id": student_id,
                        "gross_amount": estimated_fare,
                        "status": "AUTHORIZED",
                        "idempotency_key": idempotency_key,
                        "authorized_at": datetime.now(timezone.utc),
                    }
                )
            else:
                payment.status = "AUTHORIZED"
                payment.gross_amount = estimated_fare
                payment.authorized_at = datetime.now(timezone.utc)

            self.audit_repo.log_event(
                "RidePayment",
                payment.id,
                "RIDE_PAYMENT_AUTHORIZED",
                actor_id=actor_id,
                after_state={"ride_id": ride_id, "amount": str(estimated_fare)},
            )

            response_data = {"id": payment.id, "status": payment.status, "gross_amount": str(payment.gross_amount)}
            self._save_idempotency(idempotency_key, f"/rides/{ride_id}/authorize", payload, 200, response_data)

        self.db.commit()
        return payment

    def capture_ride_payment(
        self,
        ride_id: str,
        final_fare: Decimal,
        tip_amount: Decimal = Decimal("0.00"),
        idempotency_key: str | None = None,
        actor_id: str | None = None,
        driver_id: str | None = None,
    ) -> RidePayment:
        payload = {"ride_id": ride_id, "final_fare": str(final_fare), "tip_amount": str(tip_amount)}
        cached = self._check_idempotency(idempotency_key, f"/rides/{ride_id}/capture", payload)
        if cached:
            return self.ride_payment_repo.get_by_id(cached["id"])  # type: ignore

        with self.db.begin_nested():
            payment = self.ride_payment_repo.get_by_ride_id(ride_id)
            if not payment:
                raise PaymentNotFoundException(ride_id)
            if payment.status != "AUTHORIZED":
                raise InvalidPaymentStatusException(payment.status, "capture")

            rule = self.commission_repo.get_active_rule()
            if not rule:
                # Default 15% fallback rule if none created yet
                rule = self.commission_repo.create_rule(
                    {"name": "Default 15%", "percentage": Decimal("15.00"), "fixed_fee": Decimal("0.00"), "is_active": True}
                )

            commission = (final_fare * rule.percentage / Decimal("100.00")) + rule.fixed_fee
            driver_net = (final_fare - commission) + tip_amount
            total_charge = final_fare + tip_amount

            effective_driver_id = driver_id or payment.driver_id or "DRIVER_SYSTEM"
            driver_wallet = self.wallet_repo.get_by_driver_id(effective_driver_id)
            if not driver_wallet:
                driver_wallet = self.get_or_create_driver_wallet(effective_driver_id)

            platform_wallet = self.wallet_repo.get_or_create_platform_wallet()
            student_wallet = self.wallet_repo.get_by_user_id(payment.student_id)
            if not student_wallet:
                student_wallet = self.get_wallet_by_id(payment.student_id)

            # Sort primary keys to lock wallets in deterministic order
            wallet_map = self.wallet_repo.get_wallets_for_update_sorted(
                [student_wallet.id, driver_wallet.id, platform_wallet.id]
            )

            s_wallet = wallet_map[student_wallet.id]
            d_wallet = wallet_map[driver_wallet.id]
            p_wallet = wallet_map[platform_wallet.id]

            # Unlock initial reserved amount from student wallet
            locked_reservation = payment.gross_amount
            if s_wallet.locked_balance < locked_reservation:
                locked_reservation = s_wallet.locked_balance

            # Deduct total charge from balance & release locked funds
            s_wallet = self.wallet_repo.update_balance_optimistic(
                s_wallet, balance_delta=-total_charge, locked_delta=-locked_reservation
            )

            # Credit driver net earnings & platform commission
            d_wallet = self.wallet_repo.update_balance_optimistic(d_wallet, balance_delta=driver_net)
            p_wallet = self.wallet_repo.update_balance_optimistic(p_wallet, balance_delta=commission)

            # Create Transactions
            txn_ref_drv = f"PAY-DRV-{uuid.uuid4().hex[:10].upper()}"
            self.txn_repo.create(
                {
                    "reference": txn_ref_drv,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": s_wallet.id,
                    "target_wallet_id": d_wallet.id,
                    "transaction_type": "RIDE_PAYMENT",
                    "amount": driver_net,
                    "fee_amount": Decimal("0.00"),
                    "status": "COMPLETED",
                    "description": f"Ride payment for ride {ride_id}",
                    "ride_id": ride_id,
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            txn_ref_com = f"PAY-COM-{uuid.uuid4().hex[:10].upper()}"
            self.txn_repo.create(
                {
                    "reference": txn_ref_com,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": s_wallet.id,
                    "target_wallet_id": p_wallet.id,
                    "transaction_type": "PLATFORM_COMMISSION",
                    "amount": commission,
                    "fee_amount": Decimal("0.00"),
                    "status": "COMPLETED",
                    "description": f"Platform commission for ride {ride_id}",
                    "ride_id": ride_id,
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            # Create Driver Earning record
            self.driver_earning_repo.create(
                {
                    "driver_id": effective_driver_id,
                    "ride_id": ride_id,
                    "gross_fare": final_fare,
                    "commission_deducted": commission,
                    "tip_amount": tip_amount,
                    "net_earning": driver_net,
                    "payout_status": "PENDING",
                }
            )

            # Update Payment Record
            payment.driver_id = effective_driver_id
            payment.gross_amount = total_charge
            payment.platform_commission = commission
            payment.driver_net_earnings = driver_net
            payment.tip_amount = tip_amount
            payment.status = "CAPTURED"
            payment.captured_at = datetime.now(timezone.utc)

            self.audit_repo.log_event(
                "RidePayment",
                payment.id,
                "RIDE_PAYMENT_CAPTURED",
                actor_id=actor_id,
                after_state={
                    "ride_id": ride_id,
                    "gross": str(total_charge),
                    "commission": str(commission),
                    "driver_net": str(driver_net),
                },
            )

            response_data = {"id": payment.id, "status": payment.status, "gross_amount": str(payment.gross_amount)}
            self._save_idempotency(idempotency_key, f"/rides/{ride_id}/capture", payload, 200, response_data)

        self.db.commit()
        return payment

    def cancel_ride_payment_auth(
        self,
        ride_id: str,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> RidePayment:
        payload = {"ride_id": ride_id}
        cached = self._check_idempotency(idempotency_key, f"/rides/{ride_id}/cancel-auth", payload)
        if cached:
            return self.ride_payment_repo.get_by_id(cached["id"])  # type: ignore

        with self.db.begin_nested():
            payment = self.ride_payment_repo.get_by_ride_id(ride_id)
            if not payment:
                raise PaymentNotFoundException(ride_id)
            if payment.status != "AUTHORIZED":
                raise InvalidPaymentStatusException(payment.status, "cancel_authorization")

            student_wallet = self.wallet_repo.get_by_user_id(payment.student_id) or self.get_wallet_by_id(
                payment.student_id
            )
            student_wallet = self.wallet_repo.get_for_update(student_wallet.id)

            locked_to_release = payment.gross_amount
            if student_wallet.locked_balance < locked_to_release:
                locked_to_release = student_wallet.locked_balance

            # Release locked funds
            student_wallet = self.wallet_repo.update_balance_optimistic(
                student_wallet, balance_delta=Decimal("0.00"), locked_delta=-locked_to_release
            )

            payment.status = "CANCELLED"

            self.audit_repo.log_event(
                "RidePayment",
                payment.id,
                "RIDE_PAYMENT_AUTH_CANCELLED",
                actor_id=actor_id,
                after_state={"ride_id": ride_id, "released_locked": str(locked_to_release)},
            )

            response_data = {"id": payment.id, "status": payment.status}
            self._save_idempotency(idempotency_key, f"/rides/{ride_id}/cancel-auth", payload, 200, response_data)

        self.db.commit()
        return payment

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------
    def process_refund(
        self,
        payment_id: str,
        amount: Decimal,
        reason: str,
        idempotency_key: str | None = None,
        requested_by: str = "SYSTEM",
    ):
        payload = {"payment_id": payment_id, "amount": str(amount), "reason": reason}
        cached = self._check_idempotency(idempotency_key, "/refunds", payload)
        if cached:
            return self.refund_repo.get_by_id(cached["id"])  # type: ignore

        if amount <= 0:
            raise ValueError("Refund amount must be positive")

        with self.db.begin_nested():
            payment = self.ride_payment_repo.get_by_id(payment_id)
            if not payment:
                raise PaymentNotFoundException(payment_id)

            if payment.status not in ("CAPTURED", "PARTIALLY_REFUNDED"):
                raise RefundNotAllowedException(f"Payment status '{payment.status}' is not eligible for refund")

            existing_refunds = self.refund_repo.list_for_payment(payment_id)
            total_refunded = sum(r.amount for r in existing_refunds if r.status == "COMPLETED")
            if total_refunded + amount > payment.gross_amount:
                raise RefundNotAllowedException(
                    f"Requested refund ({amount}) exceeds remaining refundable amount ({payment.gross_amount - total_refunded})"
                )

            student_wallet = self.wallet_repo.get_by_user_id(payment.student_id) or self.get_wallet_by_id(
                payment.student_id
            )
            platform_wallet = self.wallet_repo.get_or_create_platform_wallet()

            # Reverse platform commission and credit student
            wallet_map = self.wallet_repo.get_wallets_for_update_sorted([student_wallet.id, platform_wallet.id])
            s_wallet = wallet_map[student_wallet.id]
            p_wallet = wallet_map[platform_wallet.id]

            s_wallet = self.wallet_repo.update_balance_optimistic(s_wallet, balance_delta=amount)
            p_wallet = self.wallet_repo.update_balance_optimistic(p_wallet, balance_delta=-amount)

            txn_ref = f"RFD-{uuid.uuid4().hex[:12].upper()}"
            txn = self.txn_repo.create(
                {
                    "reference": txn_ref,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": p_wallet.id,
                    "target_wallet_id": s_wallet.id,
                    "transaction_type": "REFUND",
                    "amount": amount,
                    "fee_amount": Decimal("0.00"),
                    "status": "COMPLETED",
                    "description": f"Refund for payment {payment_id}: {reason}",
                    "ride_id": payment.ride_id,
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            refund = self.refund_repo.create(
                {
                    "payment_id": payment_id,
                    "transaction_id": txn.id,
                    "amount": amount,
                    "reason": reason,
                    "status": "COMPLETED",
                    "idempotency_key": idempotency_key,
                    "requested_by": requested_by,
                    "processed_at": datetime.now(timezone.utc),
                }
            )

            new_total_refunded = total_refunded + amount
            if new_total_refunded >= payment.gross_amount:
                payment.status = "REFUNDED"
            else:
                payment.status = "PARTIALLY_REFUNDED"
            payment.refunded_at = datetime.now(timezone.utc)

            self.audit_repo.log_event(
                "Refund",
                refund.id,
                "REFUND_PROCESSED",
                actor_id=requested_by,
                after_state={"amount": str(amount), "reason": reason, "payment_id": payment_id},
            )

            response_data = {"id": refund.id, "status": refund.status, "amount": str(refund.amount)}
            self._save_idempotency(idempotency_key, "/refunds", payload, 200, response_data)

        self.db.commit()
        return refund

    # ------------------------------------------------------------------
    # Driver Earnings & Payouts
    # ------------------------------------------------------------------
    def get_driver_earnings_summary(self, driver_id: str) -> dict[str, Any]:
        return self.driver_earning_repo.get_summary_for_driver(driver_id)

    def payout_driver(
        self,
        driver_id: str,
        amount: Decimal,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
    ) -> Transaction:
        payload = {"driver_id": driver_id, "amount": str(amount)}
        cached = self._check_idempotency(idempotency_key, "/driver/payout", payload)
        if cached:
            return self.txn_repo.get_by_id(cached["id"])  # type: ignore

        if amount <= 0:
            raise ValueError("Payout amount must be positive")

        with self.db.begin_nested():
            driver_wallet = self.wallet_repo.get_by_driver_id(driver_id)
            if not driver_wallet:
                raise WalletNotFoundException(f"Driver wallet for {driver_id}")

            driver_wallet = self.wallet_repo.get_for_update(driver_wallet.id)
            if driver_wallet.available_balance < amount:
                raise InsufficientBalanceException(driver_wallet.id, driver_wallet.available_balance, amount)

            before_bal = driver_wallet.balance
            driver_wallet = self.wallet_repo.update_balance_optimistic(driver_wallet, balance_delta=-amount)

            txn_ref = f"POUT-{uuid.uuid4().hex[:12].upper()}"
            txn = self.txn_repo.create(
                {
                    "reference": txn_ref,
                    "idempotency_key": idempotency_key,
                    "source_wallet_id": driver_wallet.id,
                    "target_wallet_id": None,
                    "transaction_type": "DRIVER_PAYOUT",
                    "amount": amount,
                    "fee_amount": Decimal("0.00"),
                    "status": "COMPLETED",
                    "description": f"Driver payout for driver {driver_id}",
                    "completed_at": datetime.now(timezone.utc),
                }
            )

            self.audit_repo.log_event(
                "DriverEarning",
                driver_id,
                "DRIVER_PAYOUT",
                actor_id=actor_id or driver_id,
                before_state={"balance": str(before_bal)},
                after_state={"balance": str(driver_wallet.balance)},
            )

            response_data = {"id": txn.id, "reference": txn.reference, "amount": str(txn.amount)}
            self._save_idempotency(idempotency_key, "/driver/payout", payload, 200, response_data)

        self.db.commit()
        return txn

    # ------------------------------------------------------------------
    # Commission Rules & Admin Configuration
    # ------------------------------------------------------------------
    def create_commission_rule(self, name: str, percentage: Decimal, fixed_fee: Decimal = Decimal("0.00")) -> PlatformCommissionRule:
        rule = self.commission_repo.create_rule(
            {"name": name, "percentage": percentage, "fixed_fee": fixed_fee, "is_active": True}
        )
        self.audit_repo.log_event("PlatformCommissionRule", rule.id, "RULE_CREATED", after_state={"name": name, "percentage": str(percentage)})
        self.db.commit()
        return rule

    def get_active_commission_rule(self) -> PlatformCommissionRule:
        rule = self.commission_repo.get_active_rule()
        if not rule:
            rule = self.create_commission_rule("Default 15%", Decimal("15.00"), Decimal("0.00"))
        return rule

    # ------------------------------------------------------------------
    # Payment History
    # ------------------------------------------------------------------
    def get_payment_history(
        self,
        wallet_id: str,
        transaction_type: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        return self.txn_repo.list_for_wallet(
            wallet_id=wallet_id,
            transaction_type=transaction_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Background Reconciliation
    # ------------------------------------------------------------------
    def reconcile_wallets_and_ledger(self, auto_fix: bool = False) -> dict[str, Any]:
        """Scans all wallets, compares wallet.balance against calculated sum of completed transactions, and reports discrepancies."""
        wallets = self.wallet_repo.list_all_wallets(limit=5000)
        discrepancies = []

        for wallet in wallets:
            ledger_net = self.txn_repo.calculate_wallet_ledger_net(wallet.id)
            if wallet.balance != ledger_net:
                discrepancy_item = {
                    "wallet_id": wallet.id,
                    "user_id": wallet.user_id,
                    "driver_id": wallet.driver_id,
                    "stored_balance": str(wallet.balance),
                    "ledger_calculated_balance": str(ledger_net),
                    "diff": str(wallet.balance - ledger_net),
                }

                if auto_fix:
                    with self.db.begin_nested():
                        before = wallet.balance
                        wallet.balance = ledger_net
                        self.audit_repo.log_event(
                            "Wallet",
                            wallet.id,
                            "RECONCILIATION_AUTO_FIX",
                            before_state={"balance": str(before)},
                            after_state={"balance": str(ledger_net)},
                        )
                    discrepancy_item["auto_fixed"] = True

                discrepancies.append(discrepancy_item)

        status_str = "PASSED" if not discrepancies else "DISCREPANCY_FOUND"
        report = self.reconcile_repo.create_report(
            status=status_str,
            total_wallets_checked=len(wallets),
            discrepancies_count=len(discrepancies),
            details_json={"discrepancies": discrepancies, "auto_fixed": auto_fix},
        )
        self.db.commit()

        return {
            "id": report.id,
            "run_at": report.run_at,
            "status": report.status,
            "total_wallets_checked": report.total_wallets_checked,
            "discrepancies_count": report.discrepancies_count,
            "details_json": report.details_json,
            "created_at": report.created_at,
        }
