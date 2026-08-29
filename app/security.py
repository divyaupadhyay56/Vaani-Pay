"""
Password hashing and session-token generation.

Deliberately stdlib-only (hashlib.pbkdf2_hmac + secrets) so the project
doesn't pick up a new third-party dependency just for this. PBKDF2-HMAC-SHA256
with a per-password random salt and a high iteration count is a
well-established, safe choice for password storage.

Passwords are NEVER stored or logged in plain text anywhere in this
codebase — only the output of hash_password() is persisted (see app/db.py).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_s, salt_hex, digest_hex = stored_hash.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def generate_token() -> str:
    """Opaque, unguessable session token — 256 bits of entropy, URL-safe."""
    return secrets.token_urlsafe(32)


# ---------------- Password policy ----------------

MIN_PASSWORD_LENGTH = 8


def password_policy_error(password: str) -> str | None:
    """Returns a human-readable error string if the password is too weak, else None."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if password.isalpha() or password.isdigit():
        return "Password must contain a mix of letters and numbers."
    return None


# ---------------- Payment-authentication-secret guard ----------------
#
# UPI PINs, card PINs, net-banking passwords, and transaction passwords
# must NEVER be accepted, stored, logged, or forwarded by Vaani Pay — that
# authentication belongs entirely to the payment provider's own interface
# (e.g. Razorpay Checkout's hosted UI). This applies to both Add Money and
# Send Money. See app/wallet.py's add_money()/initiate_transfer()
# docstrings and tests/test_no_payment_secrets.py for where this is
# enforced and verified.

FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS = (
    "upi_pin", "upipin", "mpin", "m_pin", "atm_pin", "card_pin",
    "transaction_password", "txn_password", "net_banking_password", "netbanking_password",
)


def find_forbidden_payment_secret_fields(field_names) -> list[str]:
    """
    Given an iterable of field names (e.g. a dict's keys, or a Pydantic
    model's declared fields), returns any that look like a payment
    authentication secret. Used by tests to make sure no request model,
    database column, or MCP tool parameter is ever named like one —
    catching a future accidental addition, not just today's clean state.
    """
    hits = []
    for name in field_names:
        normalized = str(name).lower().replace("-", "_")
        if any(pattern in normalized for pattern in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS):
            hits.append(name)
    return hits


def redact_payment_secrets(data: dict) -> dict:
    """
    Defense-in-depth for logging: strips any key matching a forbidden
    payment-secret pattern before a dict is ever written to a log line.
    Nothing in this codebase currently logs a raw request payload for
    wallet operations (see app/wallet.py, app/main.py) — this exists so
    that if logging is ever added later (e.g. around a real payment
    gateway's webhook payload), redaction is one call away rather than
    something that has to be remembered from scratch.
    """
    return {
        k: ("[REDACTED]" if any(p in str(k).lower().replace("-", "_") for p in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS) else v)
        for k, v in data.items()
    }
