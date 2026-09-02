from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from app.core.exceptions import AuthError
from app.core.types import UserIdentity
from app.dependencies import check_rate_limit, client_key, get_bearer_token
from app.schemas import LoginRequest, RegisterRequest
from app.services.auth_service import login, logout, register
from app.services.wallet_account_service import get_account

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register")
async def register_endpoint(payload: RegisterRequest, request: Request):
    check_rate_limit(f"register:{client_key(request)}")
    try:
        identity = register(
            name=payload.name, email=payload.email, password=payload.password,
            phone=payload.phone, language=payload.language,
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    account = get_account(identity.user_id)
    return {
        "user_id": identity.user_id, "name": identity.name, "email": identity.email, "language": identity.language,
        "message": "Your payment account has been successfully created.",
        "account": account,
    }


@router.post("/login")
async def login_endpoint(payload: LoginRequest, request: Request):
    check_rate_limit(f"login:{client_key(request)}")
    try:
        identity, token = login(payload.email, payload.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {
        "token": token,
        "user": {"user_id": identity.user_id, "name": identity.name, "email": identity.email, "language": identity.language},
    }


@router.post("/logout")
async def logout_endpoint(authorization: Optional[str] = Header(default=None)):
    token = get_bearer_token(authorization)
    logout(token)
    return {"status": "logged_out"}
