

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from app.config import settings

SUPPORTED_INTENTS = [
    "check_payment_status",
    "check_payment_failure",
    "check_refund_status",
    "check_order_details",
    "view_transactions",
    "check_fraud_risk",
    "payment_statistics",
    "check_balance",
    "add_money",
    "send_money",
    "view_wallet_transactions",
    "spending_summary",
    "view_beneficiaries",
    "set_simulation_mode",
    "general_question",
    "greeting",
    "fallback_human_handoff",
]

NLU_SYSTEM_PROMPT = f"""You are the natural-language understanding layer for
a bilingual (English + Hindi) AI payment agent called Vaani Pay. Users ask about
their own payments, orders, refunds, transactions, wallet balance, and can
add money or send money to another person, in either English or Hindi (or
a mix). Always translate the message to English for `english_translation`.

You do NOT answer the user directly and do NOT know any real account data.
Your only job is to read their message and output structured JSON.

Return ONLY a JSON object with this exact shape, nothing else:

{{
  "english_translation": "<the message in plain English>",
  "intent": "<one of: {', '.join(SUPPORTED_INTENTS)}>",
  "entities": {{
      "payment_id": "<if mentioned, or null>",
      "order_id": "<if mentioned, or null>",
      "refund_id": "<if mentioned, or null>",
      "amount": "<numeric amount if mentioned, or null>",
      "currency": "<currency code like INR, USD, EUR, GBP if explicitly stated, or null>",
      "recipient_name": "<the person's name being sent money, if mentioned, or null>",
      "recipient_account_number": "<if an account number is explicitly stated, or null>",
      "recipient_ifsc": "<if an IFSC code is explicitly stated, or null>",
      "note": "<a short message/reference for the transfer, if mentioned, or null>"
  }},
    "response_language": "<en or hi, based on the user's latest message>",
  "confidence": <float between 0 and 1>
}}

Rules:
- "check_balance": asking about their current wallet balance.
- "add_money": wants to add/top-up money into their own wallet.
- "send_money": wants to transfer/send money to someone else.
- "view_wallet_transactions": wants wallet transaction history.
- "spending_summary": asking how much they've spent recently.
- "view_beneficiaries": asking to list or show saved recipients/beneficiaries.
- "set_simulation_mode": asking to enable or disable simulation/dry-run mode. Put the requested state in `simulation_enabled`.
- "general_question": general how-to questions, not account-specific.
- NEVER extract user_id, customer_id, account_id, or sender_id.
- NEVER extract, echo, or store a UPI PIN, card PIN, OTP, or any
  payment authentication secret — not in any field, not in english_translation.
  If a message contains one, treat the intent as payment-related and omit
  the secret entirely.
- confidence should reflect genuine uncertainty.
- Use `hi` for Hindi and Hinglish messages, including Hindi written in Latin
    script (for example, "mera account m kitna paisa h"). Use `en` for English.
- Keep the selected response language for short follow-ups whose language is
    clear from context (for example, "acha" after a Hindi/Hinglish message).
"""


@dataclass
class NLUResult:
    english_translation: str
    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    response_language: str | None = None


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.GROK_API_KEY, base_url=settings.GROK_BASE_URL)
    return _client


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _response_language(message: str, model_language: str | None) -> str | None:
    if re.search(r"[\u0900-\u097f]", message):
        return "hi"
    hindi_markers = {
        "acha", "accha", "apna", "bhi", "hai", "h", "kitna", "meri",
        "mera", "mere", "mujhe", "paisa", "paise", "kaha", "kya",
    }
    words = set(re.findall(r"[a-z]+", message.lower()))
    if words & hindi_markers:
        return "hi"
    return model_language if model_language in ("en", "hi") else None


def understand(message: str, conversation_context: str = "") -> NLUResult:
    user_content = message if not conversation_context else (
        f"Recent conversation:\n{conversation_context}\n\nLatest message:\n{message}"
    )
    response = _get_client().chat.completions.create(
        model=settings.GROK_MODEL,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": NLU_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )
    raw  = response.choices[0].message.content or ""
    data = {}
    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        return NLUResult(english_translation=message, intent="fallback_human_handoff",
                         entities={}, confidence=0.0, response_language=None)
    return NLUResult(
        english_translation=data.get("english_translation", message),
        intent=data.get("intent", "fallback_human_handoff"),
        entities=data.get("entities", {}) or {},
        confidence=float(data.get("confidence", 0.0) or 0.0),
        response_language=_response_language(message, data.get("response_language")),
    )
