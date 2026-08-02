from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    driver_id: str | None = None
    wallet_type: str
    currency: str
    balance: Decimal
    locked_balance: Decimal
    available_balance: Decimal
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Deposit amount must be positive")
    currency: str = Field("USD", min_length=3, max_length=3)
    description: str | None = Field("Wallet deposit", max_length=512)
    idempotency_key: str | None = Field(None, max_length=128)


class WithdrawalRequest(BaseModel):
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Withdrawal amount must be positive")
    currency: str = Field("USD", min_length=3, max_length=3)
    destination_account: str | None = Field(None, max_length=255, description="Bank or mobile money account identifier")
    description: str | None = Field("Wallet withdrawal", max_length=512)
    idempotency_key: str | None = Field(None, max_length=128)


class TransferRequest(BaseModel):
    target_wallet_id: str = Field(..., max_length=36)
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Transfer amount must be positive")
    currency: str = Field("USD", min_length=3, max_length=3)
    description: str | None = Field("Peer-to-peer transfer", max_length=512)
    idempotency_key: str | None = Field(None, max_length=128)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    idempotency_key: str | None = None
    source_wallet_id: str | None = None
    target_wallet_id: str | None = None
    transaction_type: str
    amount: Decimal
    fee_amount: Decimal
    currency: str
    status: str
    description: str | None = None
    ride_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None


class TransactionSummary(BaseModel):
    total_debits: Decimal
    total_credits: Decimal
    net_flow: Decimal
    total_count: int
    currency: str


class RidePaymentAuthorizeRequest(BaseModel):
    ride_id: str = Field(..., max_length=36)
    student_id: str = Field(..., max_length=36)
    estimated_fare: Decimal = Field(..., ge=Decimal("0.00"))
    idempotency_key: str | None = Field(None, max_length=128)


class RidePaymentCaptureRequest(BaseModel):
    final_fare: Decimal = Field(..., ge=Decimal("0.00"))
    tip_amount: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"))
    idempotency_key: str | None = Field(None, max_length=128)


class RidePaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ride_id: str
    student_id: str
    driver_id: str | None = None
    gross_amount: Decimal
    platform_commission: Decimal
    driver_net_earnings: Decimal
    tip_amount: Decimal
    discount_amount: Decimal
    status: str
    idempotency_key: str | None = None
    authorized_at: datetime | None = None
    captured_at: datetime | None = None
    refunded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RefundCreateRequest(BaseModel):
    payment_id: str = Field(..., max_length=36)
    amount: Decimal = Field(..., gt=Decimal("0.00"))
    reason: str = Field(..., min_length=3, max_length=512)
    idempotency_key: str | None = Field(None, max_length=128)


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    payment_id: str
    transaction_id: str | None = None
    amount: Decimal
    reason: str
    status: str
    idempotency_key: str | None = None
    requested_by: str
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DriverEarningResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    driver_id: str
    ride_id: str
    gross_fare: Decimal
    commission_deducted: Decimal
    tip_amount: Decimal
    net_earning: Decimal
    payout_status: str
    payout_id: str | None = None
    created_at: datetime
    updated_at: datetime


class DriverEarningsSummary(BaseModel):
    driver_id: str
    total_gross_fare: Decimal
    total_commission: Decimal
    total_tips: Decimal
    total_net_earnings: Decimal
    total_rides: int
    pending_payout_amount: Decimal
    paid_out_amount: Decimal


class DriverPayoutRequest(BaseModel):
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Payout amount must be positive")
    idempotency_key: str | None = Field(None, max_length=128)


class CommissionRuleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    percentage: Decimal = Field(..., ge=Decimal("0.00"), le=Decimal("100.00"))
    fixed_fee: Decimal = Field(Decimal("0.00"), ge=Decimal("0.00"))
    is_active: bool = True


class CommissionRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    percentage: Decimal
    fixed_fee: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaymentHistoryFilter(BaseModel):
    wallet_id: str | None = None
    transaction_type: str | None = None
    status: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class PaginatedPaymentHistory(BaseModel):
    items: list[TransactionResponse]
    total: int
    limit: int
    offset: int


class ReconciliationTriggerRequest(BaseModel):
    auto_fix: bool = Field(False, description="Whether to automatically attempt to resolve detected balance mismatches")


class ReconciliationReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_at: datetime
    status: str
    total_wallets_checked: int
    discrepancies_count: int
    details_json: dict[str, Any]
    created_at: datetime
