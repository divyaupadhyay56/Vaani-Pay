from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.exceptions import AuthError
from app.core.types import UserIdentity
from app.dependencies import get_current_user
from app.schemas import ChangePasswordRequest, DeleteAccountRequest, UpdatePreferencesRequest, UpdateProfileRequest
from app.services.profile_service import (
    change_password,
    delete_account,
    get_profile,
    update_language,
    update_profile,
)

router = APIRouter(prefix="/users/me", tags=["profile"])


@router.get("")
async def get_me(user: UserIdentity = Depends(get_current_user)):
    return get_profile(user.user_id)


@router.put("")
async def update_me(payload: UpdateProfileRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        return update_profile(user.user_id, name=payload.name, phone=payload.phone)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("")
async def delete_me(payload: DeleteAccountRequest, user: UserIdentity = Depends(get_current_user)):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Deletion must be explicitly confirmed.")
    try:
        delete_account(user.user_id, payload.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"status": "account_deleted"}


@router.post("/change-password")
async def change_password_endpoint(payload: ChangePasswordRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        change_password(user.user_id, payload.current_password, payload.new_password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"status": "password_changed"}


@router.get("/preferences")
async def get_preferences(user: UserIdentity = Depends(get_current_user)):
    profile = get_profile(user.user_id)
    return {"language": profile["language"]}


@router.put("/preferences")
async def update_preferences(payload: UpdatePreferencesRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        profile = update_language(user.user_id, payload.language)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"language": profile["language"]}
