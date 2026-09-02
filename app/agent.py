from __future__ import annotations

from typing import Callable

from app.config import settings
from app.core.formatting import format_money, parse_amount
from app.i18n import t, tpl
from app.mcp_client import mcp_client
from app.nlu import NLUResult
from app import skills as skill_registry

ACCESS_DENIED_MESSAGE = "Access denied. You are not authorized to access this information."

_money = format_money
_parse_amount = parse_amount


def _lang(session: dict) -> str:
    return session.get("language") or "en"


def _make_mcp_gateway(allowed_tools: set[str]) -> Callable:
    async def _gateway(tool_name: str, arguments: dict) -> dict:
        if tool_name not in allowed_tools:
            raise PermissionError(
                f"Skill attempted to call tool '{tool_name}' which is not in its allowlist."
            )
        return await mcp_client.call_tool(tool_name, arguments)
    return _gateway


async def handle_message(nlu: NLUResult, session: dict, emit=None) -> str:
    async def _emit(event_type: str, payload: dict):
        if emit is not None:
            await emit(event_type, payload)

    user_id  = session["user_id"]
    lang     = _lang(session)
    sim_mode = session.get("simulation_mode", False)
    pending  = session.get("pending_action")

    if pending:
        return await _continue_pending(pending, nlu, session, user_id, lang, _emit, sim_mode)

    text_lower = nlu.english_translation.lower()
    if "simulation mode" in text_lower or "dry run" in text_lower or "dry-run" in text_lower:
        if "off" in text_lower or "disable" in text_lower or "exit" in text_lower:
            session["simulation_mode"] = False
            return ("🔴 Simulation mode **off** — real payments are now active."
                    if lang == "en" else "🔴 सिमुलेशन मोड **बंद** — वास्तविक भुगतान अब सक्रिय हैं।")
        session["simulation_mode"] = True
        return ("🧪 **Simulation mode on.** I'll plan and validate payment workflows without executing real transactions. "
                "Say 'simulation mode off' to switch back."
                if lang == "en" else
                "🧪 **सिमुलेशन मोड चालू।** मैं वास्तविक लेनदेन किए बिना वर्कफ़्लो प्लान करूंगा।")

    if nlu.intent == "fallback_human_handoff" or nlu.confidence < settings.CONFIDENCE_THRESHOLD:
        return t("not_understood", lang)

    entities = dict(nlu.entities or {})
    if entities.get("amount") is not None and "currency" not in entities:
        amount_text = nlu.english_translation or ""
        parsed_amount, parsed_currency = _parse_amount(amount_text)
        if parsed_amount is not None:
            entities["amount"] = parsed_amount
            entities["currency"] = parsed_currency
    nlu.entities = entities

    if nlu.intent == "greeting":
        sim_note = " 🧪 Simulation mode is ON." if sim_mode else ""
        greeting = t("greeting", lang) + sim_note
        return greeting

    text_lower = (nlu.english_translation or "").lower()
    if "saved recipient" in text_lower or "saved recipients" in text_lower or "beneficiary" in text_lower or "beneficiaries" in text_lower:
        from app import wallet
        beneficiaries = wallet.list_beneficiaries(user_id)
        if not beneficiaries:
            return ("No saved recipients yet." if lang == "en" else "अभी कोई सहेजा गया प्राप्तकर्ता नहीं है।")

        lines = [
            f"• {b['recipient_name']} — {b['account_number']} ({b['ifsc']})"
            for b in beneficiaries
        ]
        return ("**Saved recipients:**\n" + "\n".join(lines) if lang == "en"
                else "**सहेजे गए प्राप्तकर्ता:**\n" + "\n".join(lines))

    if nlu.intent == "general_question":
        return t("general_question", lang)

    skill = skill_registry.select_skill(nlu.intent)
    if skill is None:
        return t("fallback_capabilities", lang)

    gateway = _make_mcp_gateway(skill.ALLOWED_TOOLS)
    result  = await skill.execute(
        intent=nlu.intent,
        entities=nlu.entities or {},
        session=session,
        user_id=user_id,
        lang=lang,
        mcp_call=gateway,
        emit=_emit,
        sim_mode=sim_mode,
    )
    return result.reply


async def _continue_pending(
    pending: str, nlu: NLUResult, session: dict,
    user_id: str, lang: str, emit, sim_mode: bool,
) -> str:
    text = nlu.english_translation.strip()
    parts = pending.split(":")
    if len(parts) >= 2:
        skill_name = parts[1]
        for skill in skill_registry.SKILL_REGISTRY:
            if skill.NAME == skill_name:
                result = await skill.handle_pending(
                    pending, text, nlu, session,
                    user_id, lang, emit, sim_mode,
                    _dispatch_skill, _make_mcp_gateway,
                )
                if result is not None:
                    return result
    return t("lost_track", lang)


async def _dispatch_skill(intent: str, nlu: NLUResult, session: dict,
                          user_id: str, lang: str, emit, sim_mode: bool) -> str:
    """Re-route to a skill after gathering missing entities."""
    skill = skill_registry.select_skill(intent)
    if skill is None:
        return t("fallback_capabilities", lang)
    gateway = _make_mcp_gateway(skill.ALLOWED_TOOLS)
    result  = await skill.execute(
        intent=intent, entities=nlu.entities or {},
        session=session, user_id=user_id, lang=lang,
        mcp_call=gateway, emit=emit, sim_mode=sim_mode,
    )
    return result.reply
