from __future__ import annotations
from fastapi import APIRouter, Depends
from app import auth, wallet
from app.dependencies import get_current_user
from app.routers.wallet_routes import wallet_error_to_http
from app.schemas import SaveBeneficiaryRequest

router = APIRouter(tags=["beneficiaries"])


@router.get("/beneficiaries")
@router.get("/wallet/beneficiaries")
async def list_beneficiaries_endpoint(user: auth.UserIdentity = Depends(get_current_user)):
    return {"beneficiaries": wallet.list_beneficiaries(user.user_id)}


@router.post("/beneficiaries")
@router.post("/wallet/beneficiaries")
async def save_beneficiary_endpoint(payload: SaveBeneficiaryRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.save_beneficiary(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)


@router.delete("/beneficiaries/{beneficiary_id}")
async def delete_beneficiary_endpoint(beneficiary_id: int, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        wallet.delete_beneficiary(user.user_id, beneficiary_id)
    except wallet.WalletError as e:
        raise wallet_error_to_http(e)
    return {"status": "deleted"}