from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from core.auth import AuthenticatedUser, get_current_user
from modules.payments.dependencies import (
    get_current_user_wallet,
    get_payment_service,
    require_admin_user,
)
from modules.payments.exceptions import PaymentException
from modules.payments.models import Wallet
from modules.payments.schemas import (
    CommissionRuleCreate,
    CommissionRuleResponse,
    DepositRequest,
    DriverEarningResponse,
    DriverEarningsSummary,
    DriverPayoutRequest,
    PaginatedPaymentHistory,
    ReconciliationReportResponse,
    ReconciliationTriggerRequest,
    RefundCreateRequest,
    RefundResponse,
    RidePaymentAuthorizeRequest,
    RidePaymentCaptureRequest,
    RidePaymentResponse,
    TransactionResponse,
    TransferRequest,
    WalletResponse,
    WithdrawalRequest,
)
from modules.payments.service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def _handle_domain_exception(e: Exception):
    if isinstance(e, PaymentException):
        status_code = status.HTTP_400_BAD_REQUEST
        if e.code == "WALLET_NOT_FOUND" or e.code == "PAYMENT_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        elif e.code in ("OPTIMISTIC_LOCK_CONFLICT", "DUPLICATE_IDEMPOTENCY_KEY"):
            status_code = status.HTTP_409_CONFLICT
        elif e.code == "WALLET_FROZEN":
            status_code = status.HTTP_403_FORBIDDEN
        raise HTTPException(
            status_code=status_code,
            detail={"code": e.code, "message": e.message, "details": e.details},
        )
    raise e


# ------------------------------------------------------------------
# Wallet Endpoints
# ------------------------------------------------------------------
@router.get("/wallets/me", response_model=WalletResponse)
def get_my_wallet(
    wallet: Wallet = Depends(get_current_user_wallet),
):
    """Retrieve current authenticated user's wallet."""
    return wallet


@router.post("/wallets/deposit", response_model=TransactionResponse)
def deposit_to_wallet(
    req: DepositRequest,
    wallet: Wallet = Depends(get_current_user_wallet),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Deposit funds into the user's wallet."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.deposit(
            wallet_id=wallet.id,
            amount=req.amount,
            currency=req.currency,
            description=req.description,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/wallets/withdraw", response_model=TransactionResponse)
def withdraw_from_wallet(
    req: WithdrawalRequest,
    wallet: Wallet = Depends(get_current_user_wallet),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Withdraw funds from the user's wallet to an external destination."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.withdraw(
            wallet_id=wallet.id,
            amount=req.amount,
            currency=req.currency,
            destination_account=req.destination_account,
            description=req.description,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/wallets/transfer", response_model=TransactionResponse)
def transfer_funds(
    req: TransferRequest,
    wallet: Wallet = Depends(get_current_user_wallet),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Transfer funds from current user's wallet to another target wallet."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.transfer(
            source_wallet_id=wallet.id,
            target_wallet_id=req.target_wallet_id,
            amount=req.amount,
            currency=req.currency,
            description=req.description,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


# ------------------------------------------------------------------
# Ride Payments
# ------------------------------------------------------------------
@router.post("/rides/{ride_id}/authorize", response_model=RidePaymentResponse)
def authorize_ride_payment(
    ride_id: str,
    req: RidePaymentAuthorizeRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Reserves estimated ride fare from student's available wallet balance."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.authorize_ride_payment(
            ride_id=ride_id,
            student_id=req.student_id or current_user.id,
            estimated_fare=req.estimated_fare,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/rides/{ride_id}/capture", response_model=RidePaymentResponse)
def capture_ride_payment(
    ride_id: str,
    req: RidePaymentCaptureRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Settles completed ride fare: splits payment into driver net earnings and platform commission."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.capture_ride_payment(
            ride_id=ride_id,
            final_fare=req.final_fare,
            tip_amount=req.tip_amount,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/rides/{ride_id}/cancel-auth", response_model=RidePaymentResponse)
def cancel_ride_payment_authorization(
    ride_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Releases reserved funds if ride is cancelled prior to completion."""
    try:
        return service.cancel_ride_payment_auth(
            ride_id=ride_id,
            idempotency_key=idempotency_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


# ------------------------------------------------------------------
# Refunds
# ------------------------------------------------------------------
@router.post("/refunds", response_model=RefundResponse)
def create_refund(
    req: RefundCreateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Process a full or partial refund for a captured ride payment."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.process_refund(
            payment_id=req.payment_id,
            amount=req.amount,
            reason=req.reason,
            idempotency_key=effective_key,
            requested_by=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


# ------------------------------------------------------------------
# Driver Earnings & Payouts
# ------------------------------------------------------------------
@router.get("/driver/earnings", response_model=DriverEarningsSummary)
def get_driver_earnings(
    driver_id: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Get breakdown and summary of driver earnings, commissions, tips, and payouts."""
    try:
        effective_driver_id = driver_id or current_user.id
        return service.get_driver_earnings_summary(driver_id=effective_driver_id)
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/driver/payout", response_model=TransactionResponse)
def request_driver_payout(
    req: DriverPayoutRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Transfer available driver earnings out of driver wallet."""
    try:
        effective_key = req.idempotency_key or idempotency_key
        return service.payout_driver(
            driver_id=current_user.id,
            amount=req.amount,
            idempotency_key=effective_key,
            actor_id=current_user.id,
        )
    except Exception as e:
        _handle_domain_exception(e)


# ------------------------------------------------------------------
# Payment History
# ------------------------------------------------------------------
@router.get("/history", response_model=PaginatedPaymentHistory)
def get_payment_history(
    transaction_type: str | None = Query(None),
    status: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    wallet: Wallet = Depends(get_current_user_wallet),
    service: PaymentService = Depends(get_payment_service),
):
    """Fetch paginated, filtered transaction history for current user's wallet."""
    try:
        items, total = service.get_payment_history(
            wallet_id=wallet.id,
            transaction_type=transaction_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return PaginatedPaymentHistory(
            items=[TransactionResponse.model_validate(t) for t in items],
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        _handle_domain_exception(e)


# ------------------------------------------------------------------
# Admin & Platform Management
# ------------------------------------------------------------------
@router.post("/admin/commission-rules", response_model=CommissionRuleResponse)
def create_commission_rule(
    req: CommissionRuleCreate,
    admin_user: AuthenticatedUser = Depends(require_admin_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Configure platform commission percentage and fixed fees (Admin only)."""
    try:
        return service.create_commission_rule(
            name=req.name,
            percentage=req.percentage,
            fixed_fee=req.fixed_fee,
        )
    except Exception as e:
        _handle_domain_exception(e)


@router.get("/admin/commission-rules/active", response_model=CommissionRuleResponse)
def get_active_commission_rule(
    service: PaymentService = Depends(get_payment_service),
):
    """Get current active platform commission rule."""
    try:
        return service.get_active_commission_rule()
    except Exception as e:
        _handle_domain_exception(e)


@router.post("/admin/reconcile", response_model=ReconciliationReportResponse)
def trigger_reconciliation(
    req: ReconciliationTriggerRequest,
    admin_user: AuthenticatedUser = Depends(require_admin_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Triggers background audit reconciling stored wallet balances with ledger totals (Admin only)."""
    try:
        return service.reconcile_wallets_and_ledger(auto_fix=req.auto_fix)
    except Exception as e:
        _handle_domain_exception(e)
