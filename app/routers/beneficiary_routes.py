from __future__ import annotations
from fastapi import APIRouter, Depends
from app.core.error_mappers import wallet_error_to_http
from app.core.exceptions import WalletError
from app.core.types import UserIdentity
from app.dependencies import get_current_user
from app.schemas import SaveBeneficiaryRequest
from app.services.beneficiary_service import delete_beneficiary, list_beneficiaries, save_beneficiary

router = APIRouter(tags=["beneficiaries"])


@router.get("/beneficiaries")
@router.get("/wallet/beneficiaries")
async def list_beneficiaries_endpoint(user: UserIdentity = Depends(get_current_user)):
    return {"beneficiaries": list_beneficiaries(user.user_id)}


@router.post("/beneficiaries")
@router.post("/wallet/beneficiaries")
async def save_beneficiary_endpoint(payload: SaveBeneficiaryRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        return save_beneficiary(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)
    except WalletError as e:
        raise wallet_error_to_http(e)


@router.delete("/beneficiaries/{beneficiary_id}")
async def delete_beneficiary_endpoint(beneficiary_id: int, user: UserIdentity = Depends(get_current_user)):
    try:
        delete_beneficiary(user.user_id, beneficiary_id)
    except WalletError as e:
        raise wallet_error_to_http(e)
    return {"status": "deleted"}
