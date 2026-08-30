from __future__ import annotations

import random
import re
import string
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app import db

_WALLET_LOCK = threading.Lock()


FIXED_IFSC = "VPAY0000001"  
CURRENCY = "INR"

MIN_ADD_MONEY = Decimal("1.00")
MAX_ADD_MONEY = Decimal("200000.00")   
MIN_TRANSFER = Decimal("1.00")
MAX_TRANSFER = Decimal("200000.00")
TRANSACTION_FEE = Decimal("0.00")      

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_NUMBER_RE = re.compile(r"^\d{9,18}$")


class WalletError(Exception):
    """User-facing wallet error. `message` is always safe to show the user."""

    def __init__(self, message: str, code: str = "validation_error", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code  
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value) -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception:
        raise WalletError("Amount must be a valid number.")
    if d.is_nan() or d.is_infinite():
        raise WalletError("Amount must be a valid number.")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_float(d: Decimal) -> float:
    return float(d)


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
                (user_id, payment_id, account_number, FIXED_IFSC, CURRENCY, now),
            )
            return {"payment_id": payment_id, "account_number": account_number, "ifsc": FIXED_IFSC, "balance": 0.0, "currency": CURRENCY}
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


def add_money(user_id: str, amount, description: str | None = None) -> dict:
   
    amount = _money(amount)
    if amount < MIN_ADD_MONEY:
        raise WalletError(f"Amount must be greater than ₹0.")
    if amount > MAX_ADD_MONEY:
        raise WalletError(f"Amount exceeds the maximum allowed per transaction (₹{MAX_ADD_MONEY:,.2f}).")

    with _WALLET_LOCK, db.tx() as conn:
        account = _get_account_row(conn, user_id)
        if account["status"] != "active":
            raise WalletError("Your account is not active. Please contact support.", code="account_inactive")

        txn_id = generate_transaction_id()
        now = _now()
        new_balance = _money(account["balance"]) + amount

        conn.execute("UPDATE payment_accounts SET balance = ? WHERE id = ?", (_to_float(new_balance), account["id"]))
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(transaction_id, sender_account_id, receiver_account_id, amount, transaction_type, status, description, "
            " sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, NULL, ?, ?, 'CREDIT', 'SUCCESS', ?, 'Self (Add Money)', 'Self (Add Money)', ?, ?)",
            (txn_id, account["id"], _to_float(amount), description or "Wallet top-up", now, now),
        )

    return {
        "transaction_id": txn_id,
        "amount": _to_float(amount),
        "type": "CREDIT",
        "status": "SUCCESS",
        "balance": _to_float(new_balance),
        "date": now,
    }


def validate_recipient(user_id: str, recipient_name: str, account_number: str | None = None, ifsc: str | None = None) -> dict:
   
    recipient_name = (recipient_name or "").strip()
    if not recipient_name:
        return {"status": "invalid", "message": "Recipient name is required."}

    conn = db.get_connection()

    if not account_number:
        rows = conn.execute(
            "SELECT * FROM beneficiaries WHERE user_id = ? AND LOWER(recipient_name) LIKE ?",
            (user_id, f"%{recipient_name.lower()}%"),
        ).fetchall()
        if len(rows) == 0:
            return {"status": "not_found", "message": f"No saved beneficiary matching '{recipient_name}'. Please provide account number and IFSC."}
        if len(rows) > 1:
            return {
                "status": "ambiguous",
                "message": "Multiple saved beneficiaries match that name.",
                "matches": [{"recipient_name": r["recipient_name"], "account_number": _mask_account(r["account_number"])} for r in rows],
            }
        row = rows[0]
        account_number, ifsc = row["account_number"], row["ifsc"]
        recipient_name = row["recipient_name"]

    account_number = str(account_number).strip()
    ifsc = (ifsc or FIXED_IFSC).strip().upper()

    if not ACCOUNT_NUMBER_RE.match(account_number):
        return {"status": "invalid", "message": "Account number must be 9–18 digits."}
    if not IFSC_RE.match(ifsc):
        return {"status": "invalid", "message": "IFSC code format is invalid (expected e.g. VPAY0000001)."}

    sender_account = _get_account_row(conn, user_id)
    if account_number == sender_account["account_number"]:
        return {"status": "invalid", "message": "You cannot transfer money to your own account."}

    internal = conn.execute("SELECT * FROM payment_accounts WHERE account_number = ?", (account_number,)).fetchone()
    if internal is not None and internal["ifsc"] != ifsc:
        return {"status": "invalid", "message": "IFSC code does not match the account number provided."}

    return {
        "status": "resolved",
        "recipient_name": recipient_name,
        "account_number": account_number,
        "ifsc": ifsc,
        "is_internal": internal is not None,
    }


def _mask_account(account_number: str) -> str:
    return f"XXXX{account_number[-4:]}" if len(account_number) >= 4 else "XXXX"


def initiate_transfer(user_id: str, recipient_name: str, account_number: str, ifsc: str, amount, note: str | None = None) -> dict:

    amount = _money(amount)
    if amount < MIN_TRANSFER:
        raise WalletError("Amount must be greater than ₹0.")
    if amount > MAX_TRANSFER:
        raise WalletError(f"Amount exceeds the maximum allowed per transfer (₹{MAX_TRANSFER:,.2f}).")

    resolution = validate_recipient(user_id, recipient_name, account_number, ifsc)
    if resolution["status"] != "resolved":
        raise WalletError(resolution["message"], code=resolution["status"])

    conn = db.get_connection()
    sender_account = _get_account_row(conn, user_id)
    if sender_account["status"] != "active":
        raise WalletError("Your account is not active. Please contact support.", code="account_inactive")
    if _money(sender_account["balance"]) < amount:
        raise WalletError("Insufficient balance for this transfer.", code="insufficient_balance")

    receiver_account = None
    if resolution["is_internal"]:
        receiver_account = conn.execute(
            "SELECT * FROM payment_accounts WHERE account_number = ?", (resolution["account_number"],)
        ).fetchone()

    txn_id = generate_transaction_id()
    now = _now()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO wallet_transactions "
            "(transaction_id, sender_account_id, receiver_account_id, amount, transaction_type, status, description, "
            " sender_name, receiver_name, recipient_account_number, recipient_ifsc, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'TRANSFER_OUT', 'PENDING', ?, ?, ?, ?, ?, ?, ?)",
            (
                txn_id, sender_account["id"], receiver_account["id"] if receiver_account else None, _to_float(amount),
                note or "", "You", resolution["recipient_name"], resolution["account_number"], resolution["ifsc"], now, now,
            ),
        )

    return {
        "transaction_id": txn_id,
        "recipient_name": resolution["recipient_name"],
        "account_number_masked": _mask_account(resolution["account_number"]),
        "ifsc": resolution["ifsc"],
        "amount": _to_float(amount),
        "fee": _to_float(TRANSACTION_FEE),
        "total_debit": _to_float(amount + TRANSACTION_FEE),
        "status": "PENDING",
    }


def _get_pending_transfer_owned_by(conn, user_id: str, transaction_id: str):
    row = conn.execute(
        "SELECT wt.*, pa.user_id AS sender_user_id, pa.id AS sender_account_pk, pa.balance AS sender_balance, pa.status AS sender_status "
        "FROM wallet_transactions wt JOIN payment_accounts pa ON pa.id = wt.sender_account_id "
        "WHERE wt.transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None or row["sender_user_id"] != user_id:
        
        raise WalletError("Transfer not found.", code="not_found", status_code=404)
    return row


def confirm_transfer(user_id: str, transaction_id: str) -> dict:
    with _WALLET_LOCK, db.tx() as conn:
        txn = _get_pending_transfer_owned_by(conn, user_id, transaction_id)
        if txn["status"] != "PENDING":
            raise WalletError(f"This transfer is already {txn['status'].lower()}.", code="invalid_state")

        amount = _money(txn["amount"])
        now = _now()

        if txn["sender_status"] != "active":
            conn.execute("UPDATE wallet_transactions SET status='FAILED', failure_reason=?, updated_at=? WHERE transaction_id=?",
                         ("Sender account inactive", now, transaction_id))
            raise WalletError("Your account is not active. Please contact support.", code="account_inactive")

        if _money(txn["sender_balance"]) < amount:
            conn.execute("UPDATE wallet_transactions SET status='FAILED', failure_reason=?, updated_at=? WHERE transaction_id=?",
                         ("Insufficient balance", now, transaction_id))
            raise WalletError("Insufficient balance for this transfer.", code="insufficient_balance")

        new_sender_balance = _money(txn["sender_balance"]) - amount
        conn.execute("UPDATE payment_accounts SET balance = ? WHERE id = ?", (_to_float(new_sender_balance), txn["sender_account_pk"]))

        if txn["receiver_account_id"] is not None:
            receiver = conn.execute("SELECT * FROM payment_accounts WHERE id = ?", (txn["receiver_account_id"],)).fetchone()
            if receiver is not None:
                new_receiver_balance = _money(receiver["balance"]) + amount
                conn.execute("UPDATE payment_accounts SET balance = ? WHERE id = ?", (_to_float(new_receiver_balance), receiver["id"]))
                sender_user = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
                sender_display_name = sender_user["name"] if sender_user else "Unknown"
                conn.execute(
                    "INSERT INTO wallet_transactions "
                    "(transaction_id, sender_account_id, receiver_account_id, amount, transaction_type, status, description, "
                    " sender_name, receiver_name, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'TRANSFER_IN', 'SUCCESS', ?, ?, ?, ?, ?)",
                    (generate_transaction_id(), txn["sender_account_id"], receiver["id"], _to_float(amount),
                     txn["description"], sender_display_name, txn["receiver_name"], now, now),
                )

        conn.execute("UPDATE wallet_transactions SET status='SUCCESS', updated_at=? WHERE transaction_id=?", (now, transaction_id))

    return {
        "transaction_id": transaction_id,
        "status": "SUCCESS",
        "amount": _to_float(amount),
        "recipient_name": txn["receiver_name"],
        "balance": _to_float(new_sender_balance),
        "date": now,
    }


def cancel_transfer(user_id: str, transaction_id: str) -> dict:
    with db.tx() as conn:
        txn = _get_pending_transfer_owned_by(conn, user_id, transaction_id)
        if txn["status"] != "PENDING":
            raise WalletError(f"This transfer is already {txn['status'].lower()}.", code="invalid_state")
        now = _now()
        conn.execute("UPDATE wallet_transactions SET status='CANCELLED', updated_at=? WHERE transaction_id=?", (now, transaction_id))
    return {"transaction_id": transaction_id, "status": "CANCELLED"}



_VALID_FILTERS = {"all", "add_money", "sent", "received", "failed", "pending"}


def get_wallet_transactions(user_id: str, tx_filter: str = "all") -> dict:
    tx_filter = (tx_filter or "all").lower()
    if tx_filter not in _VALID_FILTERS:
        tx_filter = "all"

    conn = db.get_connection()
    account = _get_account_row(conn, user_id)

    rows = conn.execute(
        "SELECT * FROM wallet_transactions WHERE sender_account_id = ? OR receiver_account_id = ? ORDER BY created_at DESC",
        (account["id"], account["id"]),
    ).fetchall()

    results = []
    for r in rows:
        is_sender = r["sender_account_id"] == account["id"]
        if r["transaction_type"] == "CREDIT":
            kind, signed_amount, counterparty = "ADD_MONEY", r["amount"], "Self"
        elif r["transaction_type"] == "TRANSFER_OUT" and is_sender:
            kind, signed_amount, counterparty = "SENT", -r["amount"], r["receiver_name"] or "Unknown"
        elif r["transaction_type"] == "TRANSFER_IN" and not is_sender:
            kind, signed_amount, counterparty = "RECEIVED", r["amount"], r["sender_name"] or "Unknown"
        else:
            continue  # e.g. the TRANSFER_OUT leg as seen from the sender's own duplicate join — skip

        if tx_filter == "add_money" and kind != "ADD_MONEY":
            continue
        if tx_filter == "sent" and kind != "SENT":
            continue
        if tx_filter == "received" and kind != "RECEIVED":
            continue
        if tx_filter == "failed" and r["status"] != "FAILED":
            continue
        if tx_filter == "pending" and r["status"] != "PENDING":
            continue

        results.append({
            "transaction_id": r["transaction_id"],
            "type": kind,
            "amount": signed_amount,
            "signed_amount": signed_amount,
            "counterparty": counterparty,
            "status": r["status"],
            "description": r["description"],
            "date": r["created_at"],
        })

    return {"transactions": results}


def get_spending_summary(user_id: str, period: str = "month") -> dict:
    """Sum of successful outgoing transfers in the current calendar month (read-only aggregation)."""
    conn = db.get_connection()
    account = _get_account_row(conn, user_id)
    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

    rows = conn.execute(
        "SELECT amount FROM wallet_transactions WHERE sender_account_id = ? AND transaction_type = 'TRANSFER_OUT' "
        "AND status = 'SUCCESS' AND created_at LIKE ?",
        (account["id"], f"{month_prefix}%"),
    ).fetchall()

    total = sum(r["amount"] for r in rows)
    return {"period": "this_month", "total_spent": round(total, 2), "transaction_count": len(rows)}


# ---------------- Beneficiaries ----------------

def save_beneficiary(user_id: str, recipient_name: str, account_number: str, ifsc: str) -> dict:
    recipient_name = (recipient_name or "").strip()
    account_number = (account_number or "").strip()
    ifsc = (ifsc or "").strip().upper()

    if not recipient_name:
        raise WalletError("Recipient name is required.")
    if not ACCOUNT_NUMBER_RE.match(account_number):
        raise WalletError("Account number must be 9–18 digits.")
    if not IFSC_RE.match(ifsc):
        raise WalletError("IFSC code format is invalid.")

    now = _now()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO beneficiaries (user_id, recipient_name, account_number, ifsc, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, account_number) DO UPDATE SET recipient_name = excluded.recipient_name, ifsc = excluded.ifsc",
            (user_id, recipient_name, account_number, ifsc, now),
        )
        row = conn.execute(
            "SELECT * FROM beneficiaries WHERE user_id = ? AND account_number = ?", (user_id, account_number)
        ).fetchone()
    return {"id": row["id"], "recipient_name": row["recipient_name"], "account_number": _mask_account(row["account_number"]), "ifsc": row["ifsc"]}


def list_beneficiaries(user_id: str) -> list[dict]:
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM beneficiaries WHERE user_id = ? ORDER BY recipient_name", (user_id,)).fetchall()
    return [
        {"id": r["id"], "recipient_name": r["recipient_name"], "account_number": _mask_account(r["account_number"]), "ifsc": r["ifsc"]}
        for r in rows
    ]


def delete_beneficiary(user_id: str, beneficiary_id: int) -> None:
    with db.tx() as conn:
        result = conn.execute("DELETE FROM beneficiaries WHERE id = ? AND user_id = ?", (beneficiary_id, user_id))
        if result.rowcount == 0:
            raise WalletError("Beneficiary not found.", code="not_found", status_code=404)
