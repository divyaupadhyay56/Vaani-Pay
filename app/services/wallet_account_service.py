from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone

from app import db
from app.core.exceptions import WalletError

FIXED_IFSC = "VPAY0000001"
SUPPORTED_CURRENCIES = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}

DEFAULT_CURRENCY = "INR"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_payment_id() -> str:
    return f"PAY{uuid.uuid4().hex[:10].upper()}"


def _generate_account_number() -> str:
    return "".join(random.choices(string.digits, k=12))


def generate_transaction_id() -> str:
    return f"TXN{uuid.uuid4().hex[:12].upper()}"


def insert_account_row(conn, user_id: str) -> dict:
    now = _now()
    for _ in range(5):
        payment_id = _generate_payment_id()
        account_number = _generate_account_number()
        try:
            conn.execute(
                "INSERT INTO payment_accounts (user_id, payment_id, account_number, ifsc, balance, currency, status, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?, 'active', ?)",
                (user_id, payment_id, account_number, FIXED_IFSC, DEFAULT_CURRENCY, now),
            )
            return {"payment_id": payment_id, "account_number": account_number, "ifsc": FIXED_IFSC, "balance": 0.0, "currency": DEFAULT_CURRENCY}
        except db.sqlite3.IntegrityError:
            continue
    raise WalletError("Could not allocate a payment account. Please try again.", status_code=500)


def create_payment_account(user_id: str) -> dict:
    """Standalone version (opens its own transaction) — used for backfilling
    accounts for users created before this feature existed, if ever needed."""
    with db.tx() as conn:
        existing = conn.execute("SELECT id FROM payment_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if existing is not None:
            raise WalletError("A payment account already exists for this user.", code="already_exists")
        return insert_account_row(conn, user_id)


def _get_account_row(conn, user_id: str):
    row = conn.execute("SELECT * FROM payment_accounts WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise WalletError("No payment account found for this user.", code="not_found", status_code=404)
    return row


def get_account(user_id: str) -> dict:
    """Public account info for the authenticated user — safe to return to the frontend as-is."""
    conn = db.get_connection()
    row = _get_account_row(conn, user_id)
    return {
        "payment_id": row["payment_id"],
        "account_number": row["account_number"],
        "ifsc": row["ifsc"],
        "balance": row["balance"],
        "currency": row["currency"],
        "status": row["status"],
    }


def get_balance(user_id: str) -> float:
    conn = db.get_connection()
    row = _get_account_row(conn, user_id)
    return row["balance"]
