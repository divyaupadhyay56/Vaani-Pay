from __future__ import annotations

from fastapi import HTTPException

from app.core.exceptions import WalletError


def wallet_error_to_http(e: WalletError) -> HTTPException:
    status = e.status_code
    if e.code == "insufficient_balance":
        status = 402
    return HTTPException(status_code=status, detail=e.message)
