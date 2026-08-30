from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app import auth, wallet
from app.dependencies import get_current_user
from app.schemas import AddMoneyRequest, InitiateTransferRequest, ValidateRecipientRequest

router = APIRouter(prefix="/wallet", tags=["wallet"])


def wallet_error_to_http(e: "wallet.WalletError") -> HTTPException:
    status = e.status_code
    if e.code == "insufficient_balance":
        status = 402  
    return HTTPException(status_code=status, detail=e.message)


@router.get("/account")
async def get_wallet_account(user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_account(user.user_id)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/add-money")
async def add_money_endpoint(payload: AddMoneyRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.add_money(user.user_id, payload.amount, payload.description)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/validate-recipient")
async def validate_recipient_endpoint(payload: ValidateRecipientRequest, user: auth.UserIdentity = Depends(get_current_user)):
    return wallet.validate_recipient(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)


@router.post("/transfers")
@router.post("/transfer/initiate")
async def initiate_transfer_endpoint(payload: InitiateTransferRequest, user: auth.UserIdentity = Depends(get_current_user)):
    
    try:
        return wallet.initiate_transfer(
            user.user_id, payload.recipient_name, payload.account_number, payload.ifsc, payload.amount, payload.note,
        )
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/transfers/{transaction_id}/confirm")
@router.post("/transfer/{transaction_id}/confirm")
async def confirm_transfer_endpoint(transaction_id: str, user: auth.UserIdentity = Depends(get_current_user)):
    
    try:
        return wallet.confirm_transfer(user.user_id, transaction_id)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.post("/transfers/{transaction_id}/cancel")
@router.post("/transfer/{transaction_id}/cancel")
async def cancel_transfer_endpoint(transaction_id: str, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.cancel_transfer(user.user_id, transaction_id)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.get("/transactions")
async def wallet_transactions_endpoint(filter: str = "all", user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_wallet_transactions(user.user_id, filter)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.get("/spending-summary")
async def spending_summary_endpoint(period: str = "month", user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_spending_summary(user.user_id, period)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)