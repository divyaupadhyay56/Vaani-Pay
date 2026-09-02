from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.core.exceptions import WalletError
from app.core.formatting import mask_account
from app.services.wallet_transfer_service import ACCOUNT_NUMBER_RE, IFSC_RE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return {"id": row["id"], "recipient_name": row["recipient_name"], "account_number": mask_account(row["account_number"]), "ifsc": row["ifsc"]}


def list_beneficiaries(user_id: str) -> list[dict]:
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM beneficiaries WHERE user_id = ? ORDER BY recipient_name", (user_id,)).fetchall()
    return [
        {"id": r["id"], "recipient_name": r["recipient_name"], "account_number": mask_account(r["account_number"]), "ifsc": r["ifsc"]}
        for r in rows
    ]


def delete_beneficiary(user_id: str, beneficiary_id: int) -> None:
    with db.tx() as conn:
        result = conn.execute("DELETE FROM beneficiaries WHERE id = ? AND user_id = ?", (beneficiary_id, user_id))
        if result.rowcount == 0:
            raise WalletError("Beneficiary not found.", code="not_found", status_code=404)
