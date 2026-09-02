

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mean_stddev(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, math.sqrt(variance)

_W_AMOUNT    = 0.40
_W_VELOCITY  = 0.25
_W_NEW_RECIP = 0.20
_W_TIME      = 0.10
_W_ROUND     = 0.05

_HIGH_THRESHOLD   = 0.65
_MEDIUM_THRESHOLD = 0.35
_VELOCITY_LIMIT   = 3    
_Z_SCORE_MEDIUM   = 2.0  
_Z_SCORE_HIGH     = 3.5  


def analyse(
    user_id: str,
    amount: float,
    recipient_account_number: str,
    recipient_ifsc: str,
) -> dict:
    
    conn          = db.get_connection()
    now           = _now()
    hour_ago      = (now - timedelta(hours=1)).isoformat()
    thirty_days   = (now - timedelta(days=30)).isoformat()

    account = conn.execute(
        "SELECT * FROM payment_accounts WHERE user_id = ?", (user_id,)
    ).fetchone()
    if account is None:
        return {"risk_level": "LOW", "risk_score": 0.1, "reasons": [], "block": False}

    acc_id = account["id"]

  
    past_amounts = [
        r["amount"] for r in conn.execute(
            "SELECT amount FROM wallet_transactions "
            "WHERE sender_account_id = ? AND transaction_type = 'TRANSFER_OUT' "
            "  AND status = 'SUCCESS' AND created_at > ?",
            (acc_id, thirty_days),
        ).fetchall()
    ]

    recent_count = conn.execute(
        "SELECT COUNT(*) AS c FROM wallet_transactions "
        "WHERE sender_account_id = ? AND transaction_type IN ('TRANSFER_OUT', 'PENDING') "
        "  AND created_at > ?",
        (acc_id, hour_ago),
    ).fetchone()["c"]

    seen_before = conn.execute(
        "SELECT COUNT(*) AS c FROM wallet_transactions "
        "WHERE sender_account_id = ? AND recipient_account_number = ? AND status = 'SUCCESS'",
        (acc_id, recipient_account_number),
    ).fetchone()["c"]
    is_new_recipient = seen_before == 0

    reasons: list[str] = []

   
    amount_score = 0.0
    mean, stddev = _mean_stddev(past_amounts)
    if stddev > 0 and past_amounts:
        z = (amount - mean) / stddev
        if z >= _Z_SCORE_HIGH:
            amount_score = 1.0
            reasons.append(
                f"Amount ₹{amount:,.0f} is {z:.1f}x your typical transfer size"
            )
        elif z >= _Z_SCORE_MEDIUM:
            amount_score = 0.55
            reasons.append(
                f"Amount is higher than your usual transaction range"
            )
    elif amount > 50_000:
        amount_score = 0.6
        reasons.append("Large amount with no recent transfer history to compare against")
    elif amount > 10_000 and not past_amounts:
        amount_score = 0.35

    # Velocity
    velocity_score = 0.0
    if recent_count >= _VELOCITY_LIMIT:
        velocity_score = min(1.0, recent_count / 5)
        reasons.append(f"Unusually high transfer frequency: {recent_count} transfers in the last hour")
    elif recent_count >= 2:
        velocity_score = 0.3

   
    new_recip_score = 0.0
    if is_new_recipient:
        new_recip_score = 0.5
        reasons.append("First transfer to this recipient")

    hour = now.hour
    time_score = 0.0
    if 21 <= hour or hour < 5:
        time_score = 0.5
        reasons.append("Transfer initiated during unusual hours")

    round_score = 0.0
    if amount >= 1000 and amount % 1000 == 0:
        round_score = 1.0  
    score = (
        amount_score    * _W_AMOUNT
        + velocity_score  * _W_VELOCITY
        + new_recip_score * _W_NEW_RECIP
        + time_score      * _W_TIME
        + round_score     * _W_ROUND
    )
    score = min(1.0, round(score, 3))

    if score >= _HIGH_THRESHOLD:
        level = "HIGH"
    elif score >= _MEDIUM_THRESHOLD:
        level = "MEDIUM"
    else:
        level = "LOW"

    block = level == "HIGH"

    if not reasons:
        reasons.append("Transaction pattern appears normal")

    return {
        "risk_level":  level,
        "risk_score":  score,
        "reasons":     reasons,
        "block":       block,
    }
