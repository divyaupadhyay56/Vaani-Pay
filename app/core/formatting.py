from __future__ import annotations
import re

_AMOUNT_RE = re.compile(r"[\d,]+(?:\.\d+)?")
_CURRENCY_SYMBOL_MAP = {
    "₹": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}
_CURRENCY_WORD_MAP = {
    "rupee": "INR",
    "rupees": "INR",
    "rs": "INR",
    "inr": "INR",
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "pound": "GBP",
    "pounds": "GBP",
    "gbp": "GBP",
}

_AFFIRMATIVE = {
    "yes", "y", "yeah", "yep", "confirm", "confirmed", "ok", "okay",
    "sure", "haan", "ha", "proceed", "go ahead",
}
_NEGATIVE = {
    "no", "n", "nope", "cancel", "nahi", "nahin", "stop", "don't", "dont",
}


def format_money(amount: float, currency: str = "INR") -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "₹")
    return f"{symbol}{amount:,.2f}"


def parse_amount(text: str) -> tuple[float | None, str]:
    """Parse amount and currency from text.
    Returns (amount, currency_code) or (None, "INR") if not found."""
    text = text or ""
    lower = text.lower()

    # Detect explicit currency symbols or words
    currency = "INR"  # default
    for symbol, code in _CURRENCY_SYMBOL_MAP.items():
        if symbol in text:
            currency = code
            break
    if currency == "INR":
        for word, code in _CURRENCY_WORD_MAP.items():
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lower):
                currency = code
                break

    # Extract amount
    match = _AMOUNT_RE.search(text.replace(",", ""))
    if not match:
        return None, currency
    try:
        v = float(match.group())
    except ValueError:
        return None, currency
    return (v if v > 0 else None, currency)


def mask_account(account_number: str) -> str:
    return f"XXXX{account_number[-4:]}" if len(account_number) >= 4 else "XXXX"


def is_affirmative(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".!") in _AFFIRMATIVE


def is_negative(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".!") in _NEGATIVE
