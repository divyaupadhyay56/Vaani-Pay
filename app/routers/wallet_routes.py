from __future__ import annotations
from fastapi import APIRouter, Depends
from app.core.error_mappers import wallet_error_to_http
from app.core.exceptions import WalletError
from app.core.types import UserIdentity
from app.dependencies import get_current_user
from app.schemas import AddMoneyRequest, InitiateTransferRequest, ValidateRecipientRequest
from app.services.wallet_account_service import get_account
from app.services.wallet_query_service import get_analytics_dashboard, get_spending_summary, get_wallet_transactions
from app.services.wallet_transfer_service import (
    add_money,
    cancel_transfer,
    confirm_transfer,
    initiate_transfer,
    validate_recipient,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/account")
async def get_wallet_account(user: UserIdentity = Depends(get_current_user)):
    try:
        return get_account(user.user_id)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/add-money")
async def add_money_endpoint(payload: AddMoneyRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        return add_money(user.user_id, payload.amount, payload.description)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/validate-recipient")
async def validate_recipient_endpoint(payload: ValidateRecipientRequest, user: UserIdentity = Depends(get_current_user)):
    return validate_recipient(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)


@router.post("/transfers")
@router.post("/transfer/initiate")
async def initiate_transfer_endpoint(payload: InitiateTransferRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        return initiate_transfer(
            user.user_id, payload.recipient_name, payload.account_number, payload.ifsc, payload.amount, payload.note, payload.currency,
        )
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/transfers/{transaction_id}/confirm")
@router.post("/transfer/{transaction_id}/confirm")
async def confirm_transfer_endpoint(transaction_id: str, user: UserIdentity = Depends(get_current_user)):
    try:
        return confirm_transfer(user.user_id, transaction_id)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/transfers/{transaction_id}/cancel")
@router.post("/transfer/{transaction_id}/cancel")
async def cancel_transfer_endpoint(transaction_id: str, user: UserIdentity = Depends(get_current_user)):
    try:
        return cancel_transfer(user.user_id, transaction_id)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.get("/transactions")
async def wallet_transactions_endpoint(filter: str = "all", user: UserIdentity = Depends(get_current_user)):
    try:
        return get_wallet_transactions(user.user_id, filter)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.get("/spending-summary")
async def spending_summary_endpoint(period: str = "month", user: UserIdentity = Depends(get_current_user)):
    try:
        return get_spending_summary(user.user_id, period)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.get("/analytics")
async def analytics_endpoint(user: UserIdentity = Depends(get_current_user)):
    try:
        return get_analytics_dashboard(user.user_id)
    except WalletError as e:
        raise wallet_error_to_http(e)
