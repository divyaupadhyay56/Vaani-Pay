from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import db
from app.services.wallet_account_service import _get_account_row

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
            continue

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
            "currency": (r["currency"] if r["currency"] is not None else "INR").upper(),
            "original_amount": r["original_amount"],
            "original_currency": (r["original_currency"] or "INR").upper(),
            "exchange_rate": r["exchange_rate"],
            "inr_amount": r["inr_amount"],
            "counterparty": counterparty,
            "status": r["status"],
            "description": r["description"],
            "date": r["created_at"],
        })

    return {"transactions": results}


def get_spending_summary(user_id: str, period: str = "month") -> dict:
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


def _transaction_category(description: str | None) -> str:
    text = (description or "").lower()
    categories = {
        "Bills": ("bill", "rent", "utility", "electric", "internet"),
        "Food": ("food", "lunch", "dinner", "breakfast", "restaurant", "grocery"),
        "Shopping": ("shop", "store", "purchase", "order"),
        "Travel": ("travel", "flight", "hotel", "cab", "train", "uber"),
    }
    for category, keywords in categories.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "Other"


def get_analytics_dashboard(user_id: str) -> dict:
    """Return chart-ready spending data using INR ledger values."""
    conn = db.get_connection()
    account = _get_account_row(conn, user_id)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=180)
    rows = conn.execute(
        "SELECT amount, description, created_at FROM wallet_transactions "
        "WHERE sender_account_id = ? AND transaction_type = 'TRANSFER_OUT' "
        "AND status = 'SUCCESS' AND created_at >= ? ORDER BY created_at ASC",
        (account["id"], start.isoformat()),
    ).fetchall()

    weekly = defaultdict(float)
    monthly = defaultdict(float)
    categories = defaultdict(float)
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            continue
        week_start = (created - timedelta(days=created.weekday())).date().isoformat()
        month = created.strftime("%Y-%m")
        weekly[week_start] += row["amount"]
        monthly[month] += row["amount"]
        categories[_transaction_category(row["description"])] += row["amount"]

    week_labels = [(now.date() - timedelta(days=now.weekday()) - timedelta(weeks=i)).isoformat() for i in range(7, -1, -1)]
    month_labels = []
    cursor = now.replace(day=1)
    for _ in range(6):
        month_labels.append(cursor.strftime("%Y-%m"))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    month_labels.reverse()

    current_month = now.strftime("%Y-%m")
    current_total = round(monthly.get(current_month, 0), 2)
    peer_rows = conn.execute(
        "SELECT pa.user_id, SUM(wt.amount) AS total FROM wallet_transactions wt "
        "JOIN payment_accounts pa ON pa.id = wt.sender_account_id "
        "WHERE wt.transaction_type = 'TRANSFER_OUT' AND wt.status = 'SUCCESS' "
        "AND wt.created_at LIKE ? GROUP BY pa.user_id",
        (f"{current_month}%",),
    ).fetchall()
    peer_average = round(sum(row["total"] for row in peer_rows) / len(peer_rows), 2) if peer_rows else 0
    difference = round((1 - current_total / peer_average) * 100) if peer_average else 0

    return {
        "currency": "INR",
        "weekly": [{"label": label, "amount": round(weekly.get(label, 0), 2)} for label in week_labels],
        "monthly": [{"label": label, "amount": round(monthly.get(label, 0), 2)} for label in month_labels],
        "categories": [{"name": name, "amount": round(amount, 2)} for name, amount in sorted(categories.items(), key=lambda item: item[1], reverse=True)],
        "peer_comparison": {"your_spend": current_total, "peer_average": peer_average, "difference_percent": difference},
    }
