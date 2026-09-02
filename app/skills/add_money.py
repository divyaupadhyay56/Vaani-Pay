from __future__ import annotations

from app.core.formatting import format_money, is_affirmative, parse_amount
from app.i18n import t, tpl
from app.skills.base import (
    BaseSkill,
    SkillResult,
    WorkflowStep,
    serialize_steps,
    sim_reply,
    wallet_error_reply,
)


class AddMoneySkill(BaseSkill):
    NAME          = "add_money"
    ALLOWED_TOOLS = {"add_money", "get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "add_money"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        amount, currency = parse_amount(str(entities.get("amount") or ""))

        if amount is None:
            session["pending_action"]  = "skill:add_money:await_amount"
            session["pending_payload"] = {}
            q = ("How much would you like to add to your wallet? (e.g. ₹500 or $100)"
                 if lang == "en" else
                 "आप अपने वॉलेट में कितना जोड़ना चाहते हैं? (जैसे ₹500)")
            return SkillResult(success=True, reply=q, timeline=[])

        steps = [
            WorkflowStep("Validate amount",      None,        {"amount": amount}),
            WorkflowStep("Run fraud check",      None,        {}),
            WorkflowStep("⏸ User confirmation",  None,        {}),
            WorkflowStep("Credit wallet",        "add_money", {"requesting_user_id": user_id, "amount": amount, "currency": currency}),
            WorkflowStep("Verify new balance",   "get_balance", {"requesting_user_id": user_id}),
        ]

        symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "₹")
        preview = {
            "action":   "Add Money",
            "amount":   f"{symbol}{amount:,.2f}",
            "currency": currency,
            "method":   "Vaani Pay Wallet",
            "risk":     "LOW",
            "steps":    [s.label for s in steps],
            "sim_mode": sim_mode,
        }

        if sim_mode:
            return SkillResult(
                success=True,
                reply=sim_reply("Add Money", f"{symbol}{amount:,.2f}", lang),
                timeline=steps,
                preview=preview,
            )

        session["pending_action"]  = "skill:add_money:await_confirm"
        session["pending_payload"] = {"amount": amount, "currency": currency, "steps": serialize_steps(steps)}
        await emit("preview", preview)
        await emit("timeline", {"steps": serialize_steps(steps)})
        prompt = (
            f"💳 **Add Money Preview**\n\nAmount: {symbol}{amount:,.2f}\n\nReply **yes** to confirm or **no** to cancel."
            if lang == "en" else
            f"💳 **पैसे जोड़ें — पूर्वावलोकन**\n\nराशि: {symbol}{amount:,.2f}\n\nपुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।"
        )
        return SkillResult(success=True, reply=prompt, timeline=steps, preview=preview)

    async def handle_pending(self, pending_key, text, nlu, session, user_id, lang, emit, sim_mode, dispatch_skill, make_gateway):
        payload = session.get("pending_payload") or {}

        if pending_key == "skill:add_money:await_amount":
            amount, currency = parse_amount(text)
            if amount is None:
                return ("Please enter a valid amount (e.g. ₹500 or $100)." if lang == "en"
                        else "कृपया एक वैध राशि दर्ज करें।")
            session["pending_action"]  = "skill:add_money:await_confirm"
            session["pending_payload"] = {"amount": amount, "currency": currency}
            symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "₹")
            await emit("preview", {"action": "Add Money", "amount": f"{symbol}{amount:,.2f}",
                                   "currency": currency, "risk_level": "LOW", "sim_mode": sim_mode})
            return (f"💳 Add **{symbol}{amount:,.2f}** to your wallet?\n\nReply **yes** to confirm or **no** to cancel."
                    if lang == "en" else
                    f"💳 अपने वॉलेट में **{symbol}{amount:,.2f}** जोड़ें?\n\nपुष्टि के लिए **हाँ** टाइप करें।")

        if pending_key == "skill:add_money:await_confirm":
            amount = payload.get("amount")
            currency = payload.get("currency", "INR")
            session["pending_action"]  = None
            session["pending_payload"] = {}
            if not is_affirmative(text):
                return t("add_money_cancelled", lang)
            symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "₹")
            if sim_mode:
                return f"🧪 SIMULATION — Would add {symbol}{amount:,.2f} to your wallet. No real credit applied."
            gateway = make_gateway(self.ALLOWED_TOOLS)
            steps = [WorkflowStep("Credit wallet", "add_money",
                        {"requesting_user_id": user_id, "amount": amount, "currency": currency})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"
            await emit("timeline", {"steps": serialize_steps(steps)})
            result = await gateway("add_money", {"requesting_user_id": user_id, "amount": amount, "currency": currency, "description": "Wallet top-up"})
            if result.get("error"):
                steps[0].status = "failed"
                await emit("timeline", {"steps": serialize_steps(steps)})
                return wallet_error_reply(result, lang)
            steps[0].status = "done"
            await emit("timeline", {"steps": serialize_steps(steps)})
            return tpl("add_money_success", lang,
                       amount=format_money(result["amount"], currency), balance=format_money(result["balance"], currency),
                       transaction_id=result["transaction_id"])

        return None
