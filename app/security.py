

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



MIN_PASSWORD_LENGTH = 8


def password_policy_error(password: str) -> str | None:
    """Returns a human-readable error string if the password is too weak, else None."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if password.isalpha() or password.isdigit():
        return "Password must contain a mix of letters and numbers."
    return None


FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS = (
    "upi_pin", "upipin", "mpin", "m_pin", "atm_pin", "card_pin",
    "transaction_password", "txn_password", "net_banking_password", "netbanking_password",
)


def find_forbidden_payment_secret_fields(field_names) -> list[str]:
    
    hits = []
    for name in field_names:
        normalized = str(name).lower().replace("-", "_")
        if any(pattern in normalized for pattern in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS):
            hits.append(name)
    return hits


def redact_payment_secrets(data: dict) -> dict:
    
    return {
        k: ("[REDACTED]" if any(p in str(k).lower().replace("-", "_") for p in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS) else v)
        for k, v in data.items()
    }
