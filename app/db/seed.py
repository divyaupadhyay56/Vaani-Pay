from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.db.connection import get_connection, tx
from app.db.schema import SCHEMA

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SEED_DATA_DIR = PROJECT_ROOT / "mcp_server" / "data"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_currency_columns(conn) -> None:
    payment_accounts_cols = conn.execute("PRAGMA table_info(payment_accounts)").fetchall()
    if not any(col[1] == "currency" for col in payment_accounts_cols):
        conn.execute("ALTER TABLE payment_accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'")

    wallet_tx_cols = conn.execute("PRAGMA table_info(wallet_transactions)").fetchall()
    column_names = {col[1] for col in wallet_tx_cols}
    for name, default_sql in {
        "currency": "TEXT NOT NULL DEFAULT 'INR'",
        "original_amount": "REAL",
        "original_currency": "TEXT",
        "exchange_rate": "REAL",
        "inr_amount": "REAL",
    }.items():
        if name not in column_names:
            conn.execute(f"ALTER TABLE wallet_transactions ADD COLUMN {name} {default_sql}")

    conn.execute("UPDATE payment_accounts SET currency = 'INR' WHERE currency IN ('₹', 'INR')")
    conn.execute("UPDATE payment_accounts SET currency = 'USD' WHERE currency = '$'")
    conn.execute("UPDATE payment_accounts SET currency = 'EUR' WHERE currency = '€'")
    conn.execute("UPDATE payment_accounts SET currency = 'GBP' WHERE currency = '£'")
    conn.execute("UPDATE wallet_transactions SET currency = 'INR' WHERE currency IN ('₹', 'INR')")
    conn.execute("UPDATE wallet_transactions SET currency = 'USD' WHERE currency = '$'")
    conn.execute("UPDATE wallet_transactions SET currency = 'EUR' WHERE currency = '€'")
    conn.execute("UPDATE wallet_transactions SET currency = 'GBP' WHERE currency = '£'")
    conn.commit()


def init_db(seed_if_empty: bool = True) -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_currency_columns(conn)
    conn.commit()

    if seed_if_empty:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row["c"] == 0:
            _seed_from_legacy_json(conn)


def _seed_from_legacy_json(conn) -> None:
    from app.security import hash_password

    users_path = _SEED_DATA_DIR / "users.json"
    if not users_path.exists():
        return

    with open(users_path, "r", encoding="utf-8") as f:
        legacy_users = json.load(f)

    now = _now()
    demo_password_hash = hash_password("Demo@1234")
    for uid, u in legacy_users.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, email, phone, password_hash, language, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, u["name"], u["email"], u.get("phone"), demo_password_hash, "en", now, now),
        )

    def _load(name: str) -> dict:
        p = _SEED_DATA_DIR / name
        if not p.exists():
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    for pid, p in _load("payments.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO payments (payment_id, user_id, status, amount, method, failure_reason, date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, p["user_id"], p["status"], p["amount"], p.get("method"), p.get("failure_reason"), p.get("date")),
        )

    for oid, o in _load("orders.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO orders (order_id, user_id, status, total, items, date) VALUES (?, ?, ?, ?, ?, ?)",
            (oid, o["user_id"], o["status"], o["total"], json.dumps(o.get("items", [])), o.get("date")),
        )

    for rid, r in _load("refunds.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO refunds (refund_id, user_id, payment_id, amount, status, date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rid, r["user_id"], r.get("payment_id"), r["amount"], r["status"], r.get("date")),
        )

    for uid, txns in _load("transactions.json").items():
        for t_item in txns:
            conn.execute(
                "INSERT OR IGNORE INTO transactions (txn_id, user_id, type, amount, status, date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t_item["txn_id"], uid, t_item["type"], t_item["amount"], t_item["status"], t_item.get("date")),
            )

    from app import wallet
    accounts = {}
    for uid in legacy_users.keys():
        accounts[uid] = wallet.insert_account_row(conn, uid)

    demo_uids = list(legacy_users.keys())
    if len(demo_uids) >= 2:
        u1, u2 = demo_uids[0], demo_uids[1]
        acc1_id = conn.execute("SELECT id FROM payment_accounts WHERE user_id = ?", (u1,)).fetchone()["id"]
        acc2_id = conn.execute("SELECT id FROM payment_accounts WHERE user_id = ?", (u2,)).fetchone()["id"]
        acc1_num = accounts[u1]["account_number"]
        acc2_num = accounts[u2]["account_number"]

        conn.execute("UPDATE payment_accounts SET balance = 8500 WHERE id = ?", (acc1_id,))
        conn.execute("UPDATE payment_accounts SET balance = 8000 WHERE id = ?", (acc2_id,))

        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, NULL, ?, 10000, 'CREDIT', 'SUCCESS', 'Wallet top-up', 'Self (Add Money)', 'Self (Add Money)', ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, now, now),
        )
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, NULL, ?, 6500, 'CREDIT', 'SUCCESS', 'Wallet top-up', 'Self (Add Money)', 'Self (Add Money)', ?, ?)",
            (wallet.generate_transaction_id(), acc2_id, now, now),
        )

        u1_name = legacy_users[u1]["name"]
        u2_name = legacy_users[u2]["name"]
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, recipient_account_number, recipient_ifsc, created_at, updated_at) "
            "VALUES (?, ?, ?, 1500, 'TRANSFER_OUT', 'SUCCESS', 'Demo transfer', 'You', ?, ?, ?, ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, acc2_id, u2_name, acc2_num, wallet.FIXED_IFSC, now, now),
        )
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, ?, ?, 1500, 'TRANSFER_IN', 'SUCCESS', 'Demo transfer', ?, ?, ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, acc2_id, u1_name, u2_name, now, now),
        )

    conn.commit()


if __name__ == "__main__":
    init_db()
    from app.db.connection import DB_PATH
    print(f"Database ready at {DB_PATH}")
