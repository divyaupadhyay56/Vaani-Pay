"""
AI Agent — Agentic Payment Orchestrator.

Architecture
────────────
User message
  → NLU (intent + entities, via Grok — no DB access)
  → Agent Planner (this module)
  → Skill Selection (app/skills.py)
  → MCP Gateway (app/mcp_client.py → mcp_server/)
  → Authorized Tools only (allowlist enforced here)
  → Human-in-the-Loop confirmation for money-moving ops
  → Execution
  → Real-time timeline via WebSocket emit

Security contracts enforced here
─────────────────────────────────
• user_id is ALWAYS session["user_id"] — set once at auth, never from NLU.
• Only tools in the skill's ALLOWED_TOOLS set are callable.
• No money moves in a single step; every financial skill goes through
  preview → user-confirm → execute.
• Simulation mode runs the full workflow but never calls execute tools.
• No UPI PIN or payment secret ever enters this layer.
"""

import re
from typing import Callable

from app.config import settings
from app.i18n import t, tpl
from app.mcp_client import mcp_client
from app.nlu import NLUResult
from app import skills as skill_registry

# Kept for backwards-compat imports
ACCESS_DENIED_MESSAGE = "Access denied. You are not authorized to access this information."

_AFFIRMATIVE = {"yes", "y", "yeah", "yep", "confirm", "confirmed", "ok", "okay",
                "sure", "haan", "ha", "proceed", "go ahead"}
_NEGATIVE    = {"no", "n", "nope", "cancel", "nahi", "nahin", "stop", "don't", "dont"}
_AMOUNT_RE   = re.compile(r"[\d,]+(?:\.\d+)?")


# ── Shared utilities (also used by skills.py) ─────────────────────────────────

def _lang(session: dict) -> str:
    return session.get("language") or "en"


def _money(amount: float) -> str:
    return f"₹{amount:,.2f}"


def _parse_amount(text: str) -> float | None:
    match = _AMOUNT_RE.search((text or "").replace(",", ""))
    if not match:
        return None
    try:
        v = float(match.group())
    except ValueError:
        return None
    return v if v > 0 else None


def _is_affirmative(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".!") in _AFFIRMATIVE


def _is_negative(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".!") in _NEGATIVE


def _wallet_error_reply(result: dict, lang: str) -> str:
    code = result.get("error")
    key_map = {"insufficient_balance": "error_insufficient_balance"}
    if code in key_map:
        return t(key_map[code], lang)
    return f"{t('wallet_error_generic', lang)} ({result.get('message', code)})"


# ── Secure MCP gateway ────────────────────────────────────────────────────────

def _make_mcp_gateway(allowed_tools: set[str]) -> Callable:
    """
    Returns an async function that calls MCP tools — but ONLY tools in
    `allowed_tools`. Any attempt to call a tool outside that set raises
    PermissionError, preventing prompt-injection-based tool abuse.
    """
    async def _gateway(tool_name: str, arguments: dict) -> dict:
        if tool_name not in allowed_tools:
            raise PermissionError(
                f"Skill attempted to call tool '{tool_name}' which is not in its allowlist."
            )
        return await mcp_client.call_tool(tool_name, arguments)
    return _gateway


# ── Entry point ───────────────────────────────────────────────────────────────

async def handle_message(nlu: NLUResult, session: dict, emit=None) -> str:
    async def _emit(event_type: str, payload: dict):
        if emit is not None:
            await emit(event_type, payload)

    user_id  = session["user_id"]   # authenticated identity, never from NLU
    lang     = _lang(session)
    sim_mode = session.get("simulation_mode", False)
    pending  = session.get("pending_action")

    # ── Resume a pending multi-turn flow ──────────────────────────────────────
    if pending:
        return await _continue_pending(pending, nlu, session, user_id, lang, _emit, sim_mode)

    # ── Simulation mode toggle ────────────────────────────────────────────────
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

    # ── Low-confidence / fallback ─────────────────────────────────────────────
    if nlu.intent == "fallback_human_handoff" or nlu.confidence < settings.CONFIDENCE_THRESHOLD:
        return t("not_understood", lang)

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

    # ── Route to Payment Skill ────────────────────────────────────────────────
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


# ── Pending multi-turn state machine ─────────────────────────────────────────

async def _continue_pending(
    pending: str, nlu: NLUResult, session: dict,
    user_id: str, lang: str, emit, sim_mode: bool,
) -> str:
    text    = nlu.english_translation.strip()
    payload = session.get("pending_payload") or {}

    # ────────────────── Add Money flows ──────────────────────────────────────
    if pending == "skill:add_money:await_amount":
        amount = _parse_amount(text)
        if amount is None:
            return ("Please enter a valid amount (e.g. ₹500)." if lang == "en"
                    else "कृपया एक वैध राशि दर्ज करें।")
        session["pending_action"]  = "skill:add_money:await_confirm"
        session["pending_payload"] = {"amount": amount}
        await emit("preview", {"action": "Add Money", "amount": f"₹{amount:,.2f}",
                               "risk_level": "LOW", "sim_mode": sim_mode})
        return (f"💳 Add **₹{amount:,.2f}** to your wallet?\n\nReply **yes** to confirm or **no** to cancel."
                if lang == "en" else
                f"💳 अपने वॉलेट में **₹{amount:,.2f}** जोड़ें?\n\nपुष्टि के लिए **हाँ** टाइप करें।")

    if pending == "skill:add_money:await_confirm":
        amount = payload.get("amount")
        session["pending_action"]  = None
        session["pending_payload"] = {}
        if not _is_affirmative(text):
            return t("add_money_cancelled", lang)
        if sim_mode:
            return f"🧪 SIMULATION — Would add ₹{amount:,.2f} to your wallet. No real credit applied."
        from app import skills as sk
        gateway = _make_mcp_gateway(sk.AddMoneySkill.ALLOWED_TOOLS)
        steps   = [skill_registry.WorkflowStep("Credit wallet", "add_money",
                    {"requesting_user_id": user_id, "amount": amount})]
        await emit("timeline", {"steps": skill_registry._serialize_steps(steps)})
        steps[0].status = "running"; await emit("timeline", {"steps": skill_registry._serialize_steps(steps)})
        result = await gateway("add_money", {"requesting_user_id": user_id, "amount": amount, "description": "Wallet top-up"})
        if result.get("error"):
            steps[0].status = "failed"; await emit("timeline", {"steps": skill_registry._serialize_steps(steps)})
            return _wallet_error_reply(result, lang)
        steps[0].status = "done"; await emit("timeline", {"steps": skill_registry._serialize_steps(steps)})
        return tpl("add_money_success", lang,
                   amount=_money(result["amount"]), balance=_money(result["balance"]),
                   transaction_id=result["transaction_id"])

    # ────────────────── Send Money flows ─────────────────────────────────────
    if pending == "skill:send_money:await_recipient":
        session["pending_action"]  = None
        session["pending_payload"] = {**payload, "recipient_name": text}
        nlu.entities["recipient_name"] = text
        return await _dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:send_money:await_amount":
        amount = _parse_amount(text)
        if amount is None:
            return ("Please enter a valid amount." if lang == "en" else "कृपया वैध राशि दर्ज करें।")
        session["pending_action"]  = None
        merged = {**payload, "amount": amount}
        session["pending_payload"] = merged
        nlu.entities = {**nlu.entities, "recipient_name": merged.get("recipient_name"),
                        "recipient_account_number": merged.get("account_number"),
                        "recipient_ifsc": merged.get("ifsc"), "amount": amount,
                        "note": merged.get("note")}
        return await _dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:send_money:await_account":
        parts = [p.strip() for p in re.split(r"[\s,]+", text) if p.strip()]
        if len(parts) < 2:
            return ("Please provide account number and IFSC separated by space (e.g. 123456789012 VPAY0000001)."
                    if lang == "en" else "कृपया खाता नंबर और IFSC दें।")
        session["pending_action"]  = None
        merged = {**payload, "account_number": parts[0], "ifsc": parts[1]}
        session["pending_payload"] = merged
        nlu.entities = {**nlu.entities, "recipient_name": merged.get("recipient_name"),
                        "recipient_account_number": parts[0], "recipient_ifsc": parts[1],
                        "amount": merged.get("amount"), "note": merged.get("note")}
        return await _dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:send_money:await_confirm":
        session["pending_action"]  = None
        session["pending_payload"] = {}
        if _is_negative(text):
            return t("transfer_cancelled", lang)
        if not _is_affirmative(text):
            return ("Please reply **yes** to confirm or **no** to cancel."
                    if lang == "en" else "पुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।")

        # Execute the two-step transfer
        from app import skills as sk
        gateway  = _make_mcp_gateway(sk.SendMoneySkill.ALLOWED_TOOLS)
        old_steps = [skill_registry.WorkflowStep(**{**s, "tool": s.get("tool")})
                     for s in (payload.get("steps") or [])]

        await emit("timeline", {"steps": payload.get("steps", [])})

        # Initiate
        init_step = skill_registry.WorkflowStep("Initiate transfer", "create_transfer", {
            "requesting_user_id": user_id,
            "recipient_name":     payload["recipient_name"],
            "account_number":     payload["account_number"],
            "ifsc":               payload["ifsc"],
            "amount":             payload["amount"],
            "note":               payload.get("note") or "",
        })
        init_step.status = "running"
        await emit("timeline", {"steps": skill_registry._serialize_steps(old_steps) +
                                         [{"label": init_step.label, "tool": init_step.tool, "status": init_step.status}]})
        transfer = await gateway("create_transfer", init_step.params)
        if transfer.get("error"):
            return _wallet_error_reply(transfer, lang)

        # Confirm
        confirm_step = skill_registry.WorkflowStep("Execute transfer", "confirm_transfer",
                            {"requesting_user_id": user_id, "transaction_id": transfer["transaction_id"]})
        confirm_step.status = "running"
        await emit("timeline", {"steps": [{"label": confirm_step.label, "tool": confirm_step.tool,
                                            "status": confirm_step.status}]})
        result = await gateway("confirm_transfer", confirm_step.params)
        if result.get("error"):
            return _wallet_error_reply(result, lang)

        confirm_step.status = "done"
        await emit("timeline", {"steps": [{"label": confirm_step.label, "tool": confirm_step.tool,
                                            "status": confirm_step.status}]})
        return tpl("transfer_success", lang,
                   amount=_money(result["amount"]),
                   recipient_name=result["recipient_name"],
                   transaction_id=result["transaction_id"],
                   balance=_money(result["balance"]))

    # ────────────────── Legacy ID-gathering flows ─────────────────────────────
    if pending == "skill:payment_status:await_pid":
        intent = payload.get("intent", "check_payment_status")
        session["pending_action"]  = None
        session["pending_payload"] = {}
        nlu.entities["payment_id"] = text
        return await _dispatch_skill(intent, nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:payment_status:await_rid":
        session["pending_action"]  = None
        session["pending_payload"] = {}
        nlu.entities["refund_id"]  = text
        return await _dispatch_skill("check_refund_status", nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:payment_status:await_oid":
        session["pending_action"]  = None
        session["pending_payload"] = {}
        nlu.entities["order_id"]   = text
        return await _dispatch_skill("check_order_details", nlu, session, user_id, lang, emit, sim_mode)

    if pending == "skill:payment_status:await_fraud_pid":
        session["pending_action"]   = None
        session["pending_payload"]  = {}
        nlu.entities["payment_id"]  = text
        return await _dispatch_skill("check_fraud_risk", nlu, session, user_id, lang, emit, sim_mode)

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
