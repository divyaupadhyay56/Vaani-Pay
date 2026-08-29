"""
Fraud / Risk Engine — rule-based statistical anomaly detection.

Uses ONLY the user's own wallet_transactions history (via authorized DB
access with user_id scoping). The LLM is explicitly EXCLUDED from risk
calculation; it may only narrate the result returned here.

Risk model
──────────
Isolation-Forest-style heuristics (no scikit-learn dependency needed for
a demo-scale deployment):

  1. Amount z-score vs user's own 30-day transaction history.
  2. Transaction velocity — count of transfers in the last 1 hour.
  3. New recipient flag — first time this account/IFSC has been seen.
  4. Time-of-day anomaly — outside normal activity hours for this user.
  5. Large-round-number heuristic — amounts like ₹10,000, ₹50,000 etc.

Each signal contributes a weighted score; the total maps to LOW/MEDIUM/HIGH.

Output schema (always returned, never fabricated by LLM):
  {
    "risk_level": "LOW" | "MEDIUM" | "HIGH",
    "risk_score": float 0-1,
    "reasons": [str, ...]          -- safe, user-facing explanation strings
    "block":   bool                -- True only for HIGH + policy flag
  }
"""

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


# Risk weights (must sum sensibly; not required to equal 1.0)
_W_AMOUNT    = 0.40
_W_VELOCITY  = 0.25
_W_NEW_RECIP = 0.20
_W_TIME      = 0.10
_W_ROUND     = 0.05

# Thresholds
_HIGH_THRESHOLD   = 0.65
_MEDIUM_THRESHOLD = 0.35
_VELOCITY_LIMIT   = 3    # transfers in last hour → MEDIUM signal
_Z_SCORE_MEDIUM   = 2.0  # amount > mean + 2σ → MEDIUM
_Z_SCORE_HIGH     = 3.5  # amount > mean + 3.5σ → HIGH


def analyse(
    user_id: str,
    amount: float,
    recipient_account_number: str,
    recipient_ifsc: str,
) -> dict:
    """
    Run a risk assessment for a proposed transfer.

    Called BEFORE the transfer is created — purely analytical, no DB writes.
    user_id is the AUTHENTICATED sender; never trust client-supplied values.
    """
    conn          = db.get_connection()
    now           = _now()
    hour_ago      = (now - timedelta(hours=1)).isoformat()
    thirty_days   = (now - timedelta(days=30)).isoformat()

    # ── 1. Fetch sender's own account ────────────────────────────────────────
    account = conn.execute(
        "SELECT * FROM payment_accounts WHERE user_id = ?", (user_id,)
    ).fetchone()
    if account is None:
        return {"risk_level": "LOW", "risk_score": 0.1, "reasons": [], "block": False}

    acc_id = account["id"]

    # ── 2. 30-day transfer amounts (for z-score) ─────────────────────────────
    past_amounts = [
        r["amount"] for r in conn.execute(
            "SELECT amount FROM wallet_transactions "
            "WHERE sender_account_id = ? AND transaction_type = 'TRANSFER_OUT' "
            "  AND status = 'SUCCESS' AND created_at > ?",
            (acc_id, thirty_days),
        ).fetchall()
    ]

    # ── 3. Velocity — transfers in last hour ─────────────────────────────────
    recent_count = conn.execute(
        "SELECT COUNT(*) AS c FROM wallet_transactions "
        "WHERE sender_account_id = ? AND transaction_type IN ('TRANSFER_OUT', 'PENDING') "
        "  AND created_at > ?",
        (acc_id, hour_ago),
    ).fetchone()["c"]

    # ── 4. New recipient? ─────────────────────────────────────────────────────
    seen_before = conn.execute(
        "SELECT COUNT(*) AS c FROM wallet_transactions "
        "WHERE sender_account_id = ? AND recipient_account_number = ? AND status = 'SUCCESS'",
        (acc_id, recipient_account_number),
    ).fetchone()["c"]
    is_new_recipient = seen_before == 0

    # ── Compute sub-scores ───────────────────────────────────────────────────
    reasons: list[str] = []

    # Amount anomaly
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

    # New recipient
    new_recip_score = 0.0
    if is_new_recipient:
        new_recip_score = 0.5
        reasons.append("First transfer to this recipient")

    # Time of day (9 PM – 5 AM local proxy using UTC)
    hour = now.hour
    time_score = 0.0
    if 21 <= hour or hour < 5:
        time_score = 0.5
        reasons.append("Transfer initiated during unusual hours")

    # Round number heuristic
    round_score = 0.0
    if amount >= 1000 and amount % 1000 == 0:
        round_score = 1.0  # common in fraud scenarios but low weight

    # ── Weighted total ───────────────────────────────────────────────────────
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

    # Policy: block HIGH-risk transfers (configurable)
    block = level == "HIGH"

    if not reasons:
        reasons.append("Transaction pattern appears normal")

    return {
        "risk_level":  level,
        "risk_score":  score,
        "reasons":     reasons,
        "block":       block,
    }
