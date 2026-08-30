
from __future__ import annotations

import json

from app import db, wallet

ACCESS_DENIED_MESSAGE = "Access denied. You are not authorized to access this information."


def _access_denied() -> dict:
    return {"error": "access_denied", "message": ACCESS_DENIED_MESSAGE}


# ---------------- Payments ----------------

def get_payment_status(payment_id: str, requesting_user_id: str) -> dict:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM payments WHERE payment_id = ? AND user_id = ?",
        (payment_id, requesting_user_id),
    ).fetchone()
    if row is None:
        return _access_denied()
    return {
        "payment_id": row["payment_id"],
        "status": row["status"],
        "amount": row["amount"],
        "method": row["method"],
        "failure_reason": row["failure_reason"],
        "date": row["date"],
    }


def check_fraud_risk(payment_id: str, requesting_user_id: str) -> dict:
    """Simple rule-based check, not a trained ML model — flagged honestly as such."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM payments WHERE payment_id = ? AND user_id = ?",
        (payment_id, requesting_user_id),
    ).fetchone()
    if row is None:
        return _access_denied()

    risk = "high" if row["amount"] > 4000 else "low"
    return {
        "payment_id": payment_id,
        "risk_level": risk,
        "reason": "amount exceeds typical range" if risk == "high" else "within normal range",
    }


# ---------------- Orders ----------------

def get_order_details(order_id: str, requesting_user_id: str) -> dict:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ? AND user_id = ?",
        (order_id, requesting_user_id),
    ).fetchone()
    if row is None:
        return _access_denied()
    return {
        "order_id": row["order_id"],
        "status": row["status"],
        "total": row["total"],
        "items": json.loads(row["items"]),
        "date": row["date"],
    }


# ---------------- Refunds ----------------

def get_refund_status(refund_id: str, requesting_user_id: str) -> dict:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM refunds WHERE refund_id = ? AND user_id = ?",
        (refund_id, requesting_user_id),
    ).fetchone()
    if row is None:
        return _access_denied()
    return {
        "refund_id": row["refund_id"],
        "payment_id": row["payment_id"],
        "amount": row["amount"],
        "status": row["status"],
        "date": row["date"],
    }


# ---------------- Customer / self-only (no ID manipulation surface at all) ----------------

def get_customer_details(requesting_user_id: str) -> dict:
    """Always returns the caller's own profile — takes no target ID, so there's nothing to manipulate."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT id, name, email, language FROM users WHERE id = ?",
        (requesting_user_id,),
    ).fetchone()
    if row is None:
        return _access_denied()
    return {"user_id": row["id"], "name": row["name"], "email": row["email"], "language": row["language"]}


def get_transaction_history(requesting_user_id: str) -> dict:
    """Always returns the caller's own transactions — no target ID parameter."""
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT txn_id, type, amount, status, date FROM transactions WHERE user_id = ? ORDER BY date DESC",
        (requesting_user_id,),
    ).fetchall()
    return {"transactions": [dict(r) for r in rows]}


# ---------------- Analytics / self-only ----------------

def get_payment_statistics(requesting_user_id: str) -> dict:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT amount, status FROM transactions WHERE user_id = ? AND type = 'payment'",
        (requesting_user_id,),
    ).fetchall()
    total = sum(r["amount"] for r in rows)
    successful = [r for r in rows if r["status"] == "success"]
    count = len(rows)
    return {
        "transaction_count": count,
        "successful_count": len(successful),
        "total_amount": round(total, 2),
        "average_amount": round(total / count, 2) if count else 0,
        "success_rate": round(len(successful) / count * 100, 1) if count else 0,
    }


# ==================== Wallet (real money-movement system) ====================
# Thin wrappers around app/wallet.py — the single source of truth for all
# wallet business logic (also used directly by the REST endpoints in
# app/main.py). Every function here takes `requesting_user_id` and passes
# it straight through; wallet.py itself is what enforces that a user can
# only ever act on their own account. WalletError is translated into the
# same {"error": ..., "message": ...} shape the rest of this file uses, so
# the AI agent (app/agent.py) has one consistent error format to handle.

def _wallet_error_response(e: "wallet.WalletError") -> dict:
    return {"error": e.code, "message": e.message}


def get_balance(requesting_user_id: str) -> dict:
    try:
        account = wallet.get_account(requesting_user_id)
    except wallet.WalletError as e:
        return _wallet_error_response(e)
    return {"balance": account["balance"], "currency": account["currency"]}


def add_money(requesting_user_id: str, amount, description: str | None = None) -> dict:
    try:
        return wallet.add_money(requesting_user_id, amount, description)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


def get_wallet_transactions(requesting_user_id: str, tx_filter: str = "all") -> dict:
    try:
        return wallet.get_wallet_transactions(requesting_user_id, tx_filter)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


def validate_recipient(requesting_user_id: str, recipient_name: str, account_number: str | None = None, ifsc: str | None = None) -> dict:
    return wallet.validate_recipient(requesting_user_id, recipient_name, account_number, ifsc)


def create_transfer(requesting_user_id: str, recipient_name: str, account_number: str, ifsc: str, amount, note: str | None = None) -> dict:
    try:
        return wallet.initiate_transfer(requesting_user_id, recipient_name, account_number, ifsc, amount, note)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


def confirm_transfer(requesting_user_id: str, transaction_id: str) -> dict:
    try:
        return wallet.confirm_transfer(requesting_user_id, transaction_id)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


def cancel_transfer(requesting_user_id: str, transaction_id: str) -> dict:
    try:
        return wallet.cancel_transfer(requesting_user_id, transaction_id)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


def get_spending_summary(requesting_user_id: str, period: str = "month") -> dict:
    try:
        return wallet.get_spending_summary(requesting_user_id, period)
    except wallet.WalletError as e:
        return _wallet_error_response(e)


# ── Fraud / Risk Engine ──────────────────────────────────────────────────────

def analyse_transfer_risk(
    requesting_user_id: str,
    amount: float,
    recipient_account_number: str,
    recipient_ifsc: str,
) -> dict:
    """
    Thin wrapper around app/fraud.analyse() — keeps the data layer as
    the single gateway between MCP tools and application logic.
    requesting_user_id scopes all DB reads inside fraud.analyse().
    """
    from app import fraud
    return fraud.analyse(requesting_user_id, amount, recipient_account_number, recipient_ifsc)
