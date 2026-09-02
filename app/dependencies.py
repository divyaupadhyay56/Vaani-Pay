from __future__ import annotations

import time
from typing import Optional

from fastapi import Header, HTTPException, Request

from app.core.types import UserIdentity
from app.services.auth_service import verify_token

RATE_LIMIT_MAX_ATTEMPTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60

_rate_limit_buckets: dict[str, list[float]] = {}


def check_rate_limit(key: str) -> None:
    now = time.time()
    bucket = [t for t in _rate_limit_buckets.get(key, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    bucket.append(now)
    _rate_limit_buckets[key] = bucket


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> UserIdentity:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    identity = verify_token(token)
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return identity


def get_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    return authorization.split(" ", 1)[1].strip()
