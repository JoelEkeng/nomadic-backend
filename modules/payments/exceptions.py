from typing import Any


class PaymentException(Exception):
    """Base exception for all payment-related domain errors."""

    def __init__(self, message: str, code: str = "PAYMENT_ERROR", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class WalletNotFoundException(PaymentException):
    """Raised when a requested wallet cannot be found."""

    def __init__(self, identifier: str):
        super().__init__(
            message=f"Wallet not found for identifier: {identifier}",
            code="WALLET_NOT_FOUND",
            details={"identifier": identifier},
        )


class InsufficientBalanceException(PaymentException):
    """Raised when a wallet lacks sufficient funds for a debit or authorization."""

    def __init__(self, wallet_id: str, available_balance: Any, required_amount: Any):
        super().__init__(
            message=f"Insufficient balance in wallet {wallet_id}. Required: {required_amount}, Available: {available_balance}",
            code="INSUFFICIENT_BALANCE",
            details={
                "wallet_id": wallet_id,
                "available_balance": str(available_balance),
                "required_amount": str(required_amount),
            },
        )


class WalletFrozenException(PaymentException):
    """Raised when an operation is attempted on a frozen or closed wallet."""

    def __init__(self, wallet_id: str, status: str):
        super().__init__(
            message=f"Wallet {wallet_id} is unavailable for transactions (status: {status})",
            code="WALLET_FROZEN",
            details={"wallet_id": wallet_id, "status": status},
        )


class DuplicateIdempotencyException(PaymentException):
    """Raised when an idempotency key is reused with mismatched parameters."""

    def __init__(self, idempotency_key: str):
        super().__init__(
            message=f"Idempotency key '{idempotency_key}' has already been processed with different parameters.",
            code="DUPLICATE_IDEMPOTENCY_KEY",
            details={"idempotency_key": idempotency_key},
        )


class OptimisticLockingException(PaymentException):
    """Raised when a concurrent update collides on entity version."""

    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            message=f"Concurrent update conflict on {entity_name} ({entity_id}). Please retry the operation.",
            code="OPTIMISTIC_LOCK_CONFLICT",
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class InvalidPaymentStatusException(PaymentException):
    """Raised when a transition is requested from an incompatible payment status."""

    def __init__(self, current_status: str, target_action: str):
        super().__init__(
            message=f"Cannot execute '{target_action}' for payment currently in status '{current_status}'.",
            code="INVALID_PAYMENT_STATUS",
            details={"current_status": current_status, "target_action": target_action},
        )


class PaymentNotFoundException(PaymentException):
    """Raised when a ride payment record is not found."""

    def __init__(self, payment_id: str):
        super().__init__(
            message=f"Payment not found for ID: {payment_id}",
            code="PAYMENT_NOT_FOUND",
            details={"payment_id": payment_id},
        )


class RefundNotAllowedException(PaymentException):
    """Raised when a refund request violates business constraints."""

    def __init__(self, reason: str):
        super().__init__(
            message=f"Refund operation failed: {reason}",
            code="REFUND_NOT_ALLOWED",
            details={"reason": reason},
        )


class DriverEarningsNotFoundException(PaymentException):
    """Raised when a driver earning record is missing."""

    def __init__(self, driver_id: str, ride_id: str | None = None):
        super().__init__(
            message=f"Driver earnings not found for driver {driver_id}" + (f" and ride {ride_id}" if ride_id else ""),
            code="EARNINGS_NOT_FOUND",
            details={"driver_id": driver_id, "ride_id": ride_id},
        )


class CommissionConfigException(PaymentException):
    """Raised when platform commission rule is missing or improperly configured."""

    def __init__(self, detail: str):
        super().__init__(
            message=f"Commission configuration error: {detail}",
            code="COMMISSION_CONFIG_ERROR",
            details={"detail": detail},
        )


class ReconciliationMismatchException(PaymentException):
    """Raised when ledger and wallet balance auditing detects discrepancy."""

    def __init__(self, wallet_id: str, expected_balance: Any, actual_balance: Any):
        super().__init__(
            message=f"Reconciliation mismatch on wallet {wallet_id}. Expected: {expected_balance}, Actual: {actual_balance}",
            code="RECONCILIATION_MISMATCH",
            details={
                "wallet_id": wallet_id,
                "expected_balance": str(expected_balance),
                "actual_balance": str(actual_balance),
            },
        )
