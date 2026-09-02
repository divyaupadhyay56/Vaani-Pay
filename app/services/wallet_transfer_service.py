from __future__ import annotations

import re
import threading
from decimal import ROUND_HALF_UP, Decimal

from app import db
from app.core.exceptions import WalletError
from app.core.formatting import mask_account
from app.services.wallet_account_service import (
    FIXED_IFSC,
    _get_account_row,
    _now,
    generate_transaction_id,
)

_WALLET_LOCK = threading.Lock()

FX_RATES = {
    "INR": 1.0,
    "USD": 91.0,
    "EUR": 109.91,
    "GBP": 128.01,
}

MIN_ADD_MONEY = Decimal("1.00")
MAX_ADD_MONEY = Decimal("200000.00")
MIN_TRANSFER = Decimal("1.00")
MAX_TRANSFER = Decimal("200000.00")
TRANSACTION_FEE = Decimal("0.00")

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_NUMBER_RE = re.compile(r"^\d{9,18}$")


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


def get_exchange_rate(currency: str | None) -> float:
    code = (currency or "INR").upper()
    if code not in FX_RATES:
        return FX_RATES["INR"]
    return float(FX_RATES[code])


def convert_to_inr(amount, currency: str | None) -> tuple[Decimal, float]:
    amount_dec = _money(amount)
    rate = get_exchange_rate(currency)
    converted = amount_dec * Decimal(str(rate))
    return _money(converted), rate


def add_money(user_id: str, amount, description: str | None = None, currency: str | None = None) -> dict:
    amount = _money(amount)
    currency = (currency or "INR").upper()
    
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
        "currency": currency,
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
                "matches": [{"recipient_name": r["recipient_name"], "account_number": mask_account(r["account_number"])} for r in rows],
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


def initiate_transfer(user_id: str, recipient_name: str, account_number: str, ifsc: str, amount, note: str | None = None, currency: str | None = None) -> dict:
    original_amount = _money(amount)
    original_currency = (currency or "INR").upper()
    inr_amount, exchange_rate = convert_to_inr(original_amount, original_currency)

    if inr_amount < MIN_TRANSFER:
        raise WalletError("Amount must be greater than ₹0.")
    if inr_amount > MAX_TRANSFER:
        raise WalletError(f"Amount exceeds the maximum allowed per transfer (₹{MAX_TRANSFER:,.2f}).")

    resolution = validate_recipient(user_id, recipient_name, account_number, ifsc)
    if resolution["status"] != "resolved":
        raise WalletError(resolution["message"], code=resolution["status"])

    conn = db.get_connection()
    sender_account = _get_account_row(conn, user_id)
    if sender_account["status"] != "active":
        raise WalletError("Your account is not active. Please contact support.", code="account_inactive")
    if _money(sender_account["balance"]) < inr_amount:
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
            "(transaction_id, sender_account_id, receiver_account_id, amount, currency, original_amount, original_currency, exchange_rate, inr_amount, transaction_type, status, description, "
            "sender_name, receiver_name, recipient_account_number, recipient_ifsc, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'TRANSFER_OUT', 'PENDING', ?, ?, ?, ?, ?, ?, ?)",
            (
                txn_id,
                sender_account["id"],
                receiver_account["id"] if receiver_account else None,
                _to_float(inr_amount),
                "INR",
                _to_float(original_amount),
                original_currency,
                exchange_rate,
                _to_float(inr_amount),
                note or "",
                "You",
                resolution["recipient_name"],
                resolution["account_number"],
                resolution["ifsc"],
                now,
                now,
            ),
        )

    return {
        "transaction_id": txn_id,
        "recipient_name": resolution["recipient_name"],
        "account_number_masked": mask_account(resolution["account_number"]),
        "ifsc": resolution["ifsc"],
        "amount": _to_float(inr_amount),
        "currency": "INR",
        "original_amount": _to_float(original_amount),
        "original_currency": original_currency,
        "exchange_rate": exchange_rate,
        "inr_amount": _to_float(inr_amount),
        "fee": _to_float(TRANSACTION_FEE),
        "total_debit": _to_float(inr_amount + TRANSACTION_FEE),
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

        inr_amount = _money(txn["inr_amount"] if txn["inr_amount"] is not None else txn["amount"])
        amount = _money(txn["amount"])
        now = _now()

        if txn["sender_status"] != "active":
            conn.execute("UPDATE wallet_transactions SET status='FAILED', failure_reason=?, updated_at=? WHERE transaction_id=?",
                         ("Sender account inactive", now, transaction_id))
            raise WalletError("Your account is not active. Please contact support.", code="account_inactive")

        if _money(txn["sender_balance"]) < inr_amount:
            conn.execute("UPDATE wallet_transactions SET status='FAILED', failure_reason=?, updated_at=? WHERE transaction_id=?",
                         ("Insufficient balance", now, transaction_id))
            raise WalletError("Insufficient balance for this transfer.", code="insufficient_balance")

        new_sender_balance = _money(txn["sender_balance"]) - inr_amount
        conn.execute("UPDATE payment_accounts SET balance = ? WHERE id = ?", (_to_float(new_sender_balance), txn["sender_account_pk"]))

        if txn["receiver_account_id"] is not None:
            receiver = conn.execute("SELECT * FROM payment_accounts WHERE id = ?", (txn["receiver_account_id"],)).fetchone()
            if receiver is not None:
                new_receiver_balance = _money(receiver["balance"]) + inr_amount
                conn.execute("UPDATE payment_accounts SET balance = ? WHERE id = ?", (_to_float(new_receiver_balance), receiver["id"]))
                sender_user = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
                sender_display_name = sender_user["name"] if sender_user else "Unknown"
                conn.execute(
                    "INSERT INTO wallet_transactions "
                    "(transaction_id, sender_account_id, receiver_account_id, amount, currency, original_amount, original_currency, exchange_rate, inr_amount, transaction_type, status, description, "
                    "sender_name, receiver_name, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'TRANSFER_IN', 'SUCCESS', ?, ?, ?, ?, ?)",
                    (
                        generate_transaction_id(),
                        txn["sender_account_id"],
                        receiver["id"],
                        _to_float(inr_amount),
                        "INR",
                        txn["original_amount"],
                        txn["original_currency"],
                        txn["exchange_rate"],
                        _to_float(inr_amount),
                        txn["description"],
                        sender_display_name,
                        txn["receiver_name"],
                        now,
                        now,
                    ),
                )

        conn.execute(
            "UPDATE wallet_transactions SET amount=?, currency='INR', inr_amount=?, status='SUCCESS', updated_at=? WHERE transaction_id=?",
            (_to_float(inr_amount), _to_float(inr_amount), now, transaction_id),
        )

    return {
        "transaction_id": transaction_id,
        "status": "SUCCESS",
        "amount": _to_float(inr_amount),
        "currency": "INR",
        "original_amount": _to_float(txn["original_amount"] if txn["original_amount"] is not None else amount),
        "original_currency": (txn["original_currency"] or "INR").upper(),
        "exchange_rate": float(txn["exchange_rate"] if txn["exchange_rate"] is not None else 1.0),
        "inr_amount": _to_float(inr_amount),
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
