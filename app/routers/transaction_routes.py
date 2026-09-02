from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.types import UserIdentity
from app.dependencies import get_current_user
from mcp_server import data_layer

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(user: UserIdentity = Depends(get_current_user)):
    return data_layer.get_transaction_history(user.user_id)


@router.get("/{txn_id}")
async def get_transaction(txn_id: str, user: UserIdentity = Depends(get_current_user)):
    history = data_layer.get_transaction_history(user.user_id)["transactions"]
    for txn in history:
        if txn["txn_id"] == txn_id:
            return txn
    raise HTTPException(status_code=404, detail="Transaction not found.")
