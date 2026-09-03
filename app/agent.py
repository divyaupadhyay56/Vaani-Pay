from __future__ import annotations

from typing import Callable

from app.config import settings
from app.core.formatting import format_money, parse_amount
from app.i18n import t
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

    if nlu.response_language in ("en", "hi"):
        session["language"] = nlu.response_language

    user_id  = session["user_id"]
    lang     = _lang(session)
    sim_mode = session.get("simulation_mode", False)
    pending  = session.get("pending_action")

    if pending:
        return await _continue_pending(pending, nlu, session, user_id, lang, _emit, sim_mode)

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
        sim_note = t("simulation_on_suffix", lang) if sim_mode else ""
        greeting = t("greeting", lang) + sim_note
        return greeting

    skill = skill_registry.select_skill(nlu.intent, nlu.english_translation)
    if skill is None:
        if nlu.intent == "general_question":
            return t("general_question", lang)
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
    skill = skill_registry.select_skill(intent, nlu.english_translation)
    if skill is None:
        return t("fallback_capabilities", lang)
    gateway = _make_mcp_gateway(skill.ALLOWED_TOOLS)
    result  = await skill.execute(
        intent=intent, entities=nlu.entities or {},
        session=session, user_id=user_id, lang=lang,
        mcp_call=gateway, emit=emit, sim_mode=sim_mode,
    )
    return result.reply
