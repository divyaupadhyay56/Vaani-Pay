from __future__ import annotations

import re

from app import fraud as fraud_engine
from app.core.formatting import format_money, is_affirmative, is_negative, parse_amount
from app.i18n import t, tpl
from app.skills.base import (
    BaseSkill,
    SkillResult,
    WorkflowStep,
    serialize_steps,
    sim_reply,
    wallet_error_reply,
)


class SendMoneySkill(BaseSkill):
    NAME          = "send_money"
    ALLOWED_TOOLS = {"validate_recipient", "create_transfer", "confirm_transfer", "cancel_transfer", "get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "send_money"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        recipient_name  = (entities.get("recipient_name") or "").strip()
        account_number  = (entities.get("recipient_account_number") or "").strip()
        ifsc            = (entities.get("recipient_ifsc") or "").strip()
        amount_raw      = entities.get("amount")
        note            = (entities.get("note") or "").strip()
        
        # Check if currency was already determined (e.g., from previous interaction)
        currency_override = entities.get("currency")
        
        if currency_override:
            # Currency already determined, amount is already a number
            try:
                amount = float(amount_raw) if amount_raw else None
            except (TypeError, ValueError):
                amount = None
            currency = currency_override
        else:
            # Parse both amount and currency from text
            amount, currency = parse_amount(str(amount_raw or ""))

        payload = session.get("pending_payload") or {}

        if not recipient_name:
            session["pending_action"]  = "skill:send_money:await_recipient"
            session["pending_payload"] = payload
            q = ("Who would you like to send money to?" if lang == "en"
                 else "आप किसे पैसे भेजना चाहते हैं?")
            return SkillResult(success=True, reply=q, timeline=[])

        if not amount:
            session["pending_action"]  = "skill:send_money:await_amount"
            session["pending_payload"] = {**payload, "recipient_name": recipient_name,
                                          "account_number": account_number, "ifsc": ifsc, "note": note}
            q = (f"How much would you like to send to {recipient_name}?" if lang == "en"
                 else f"आप {recipient_name} को कितना भेजना चाहते हैं?")
            return SkillResult(success=True, reply=q, timeline=[])

        steps = [
            WorkflowStep("Validate recipient",   "validate_recipient", {
                "requesting_user_id": user_id,
                "recipient_name": recipient_name,
                "account_number": account_number or "",
                "ifsc": ifsc or "",
            }),
            WorkflowStep("Fraud risk check",     None,                 {"amount": amount}),
            WorkflowStep("Generate action preview", None,              {}),
            WorkflowStep("⏸ User confirmation",  None,                 {}),
            WorkflowStep("Initiate transfer",    "create_transfer",    {
                "requesting_user_id": user_id,
                "recipient_name": recipient_name,
                "account_number": account_number or "TBD",
                "ifsc": ifsc or "TBD",
                "amount": amount,
                "currency": currency,
                "note": note,
            }),
            WorkflowStep("Execute transfer",     "confirm_transfer",   {}),
            WorkflowStep("Verify result",        "get_balance",        {"requesting_user_id": user_id}),
        ]

        await emit("timeline", {"steps": serialize_steps(steps)})

        steps[0].status = "running"
        await emit("timeline", {"steps": serialize_steps(steps)})
        resolution = await mcp_call("validate_recipient", steps[0].params)
        status = resolution.get("status")
        if status == "not_found":
            steps[0].status = "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            session["pending_action"]  = "skill:send_money:await_account"
            session["pending_payload"] = {**payload, "recipient_name": recipient_name,
                                          "amount": amount, "currency": currency, "note": note}
            q = (f"I couldn't find a saved beneficiary named **{recipient_name}**. "
                 f"Please provide their account number and IFSC (e.g. '123456789012 VPAY0000001')."
                 if lang == "en" else
                 f"**{recipient_name}** नाम का कोई सहेजा हुआ लाभार्थी नहीं मिला। "
                 f"कृपया उनका खाता नंबर और IFSC दें।")
            return SkillResult(success=True, reply=q, timeline=steps)
        if status in ("invalid", "ambiguous"):
            steps[0].status = "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            return SkillResult(success=False, reply=resolution.get("message", "Invalid recipient."), timeline=steps)

        steps[0].status = "done"
        resolved_account = resolution["account_number"]
        resolved_ifsc    = resolution["ifsc"]
        resolved_name    = resolution["recipient_name"]

        steps[1].status = "running"
        await emit("timeline", {"steps": serialize_steps(steps)})
        risk = fraud_engine.analyse(user_id, amount, resolved_account, resolved_ifsc)
        steps[1].status = "done"
        steps[1].result = risk

        steps[2].status = "running"
        symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "₹")
        inr_amount = amount * {"INR": 1.0, "USD": 91.0, "EUR": 109.91, "GBP": 128.01}.get(currency, 1.0)
        preview = {
            "action":     "Send Money",
            "recipient":  resolved_name,
            "account":    f"XXXX{resolved_account[-4:]}",
            "ifsc":       resolved_ifsc,
            "amount":     f"{symbol}{amount:,.2f}",
            "currency":   currency,
            "fx_rate":    {"INR": 1.0, "USD": 91.0, "EUR": 109.91, "GBP": 128.01}.get(currency, 1.0),
            "inr_amount": f"₹{inr_amount:,.2f}",
            "fee":        "₹0.00",
            "total_debit": f"₹{inr_amount:,.2f}",
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "risk_reasons": risk["reasons"],
            "steps":      [s.label for s in steps],
            "sim_mode":   sim_mode,
        }
        steps[2].status = "done"
        await emit("timeline", {"steps": serialize_steps(steps)})
        await emit("preview",  preview)
        await emit("risk",     {"level": risk["risk_level"], "score": risk["risk_score"], "reasons": risk["reasons"]})

        if risk["block"]:
            steps[3].status = "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            block_msg = (
                f"⛔ **High Risk Detected** — this transfer has been blocked.\n\n"
                f"Reasons:\n" + "\n".join(f"• {r}" for r in risk["reasons"])
                if lang == "en" else
                f"⛔ **उच्च जोखिम** — यह ट्रांसफर ब्लॉक कर दिया गया है।"
            )
            return SkillResult(success=False, reply=block_msg, timeline=steps, risk=risk, preview=preview)

        if sim_mode:
            return SkillResult(
                success=True,
                reply=sim_reply("Send Money", f"{symbol}{amount:,.2f} to {resolved_name}", lang),
                timeline=steps, risk=risk, preview=preview,
            )

        steps[3].status = "running"
        session["pending_action"]  = "skill:send_money:await_confirm"
        session["pending_payload"] = {
            "recipient_name":  resolved_name,
            "account_number":  resolved_account,
            "ifsc":            resolved_ifsc,
            "amount":          amount,
            "currency":        currency,
            "note":            note,
            "risk":            risk,
            "steps":           serialize_steps(steps),
        }
        risk_tag = {"LOW": "🟢 Low", "MEDIUM": "🟡 Medium", "HIGH": "🔴 High"}[risk["risk_level"]]
        fx_rate = {"INR": 1.0, "USD": 91.0, "EUR": 109.91, "GBP": 128.01}.get(currency, 1.0)
        inr_amount = amount * fx_rate
        confirm_msg = (
            f"📤 **Transfer Preview**\n\n"
            f"To: **{resolved_name}** (XXXX{resolved_account[-4:]})\n"
            f"Amount: **{symbol}{amount:,.2f}**\n"
            f"FX: 1 {currency} = ₹{fx_rate:,.2f}\n"
            f"Converted to INR: **₹{inr_amount:,.2f}**\n"
            f"Fee: ₹0.00\n"
            f"Risk: {risk_tag}\n\n"
            + ("\n".join(f"• {r}" for r in risk["reasons"]) + "\n\n" if risk["reasons"] != ["Transaction pattern appears normal"] else "")
            + "Reply **yes** to confirm or **no** to cancel."
            if lang == "en" else
            f"📤 **ट्रांसफर पूर्वावलोकन**\n\n"
            f"प्राप्तकर्ता: **{resolved_name}** (XXXX{resolved_account[-4:]})\n"
            f"राशि: **{symbol}{amount:,.2f}**\n"
            f"FX: 1 {currency} = ₹{fx_rate:,.2f}\n"
            f"INR में बदला: **₹{inr_amount:,.2f}**\n"
            f"जोखिम: {risk_tag}\n\n"
            f"पुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।"
        )
        return SkillResult(success=True, reply=confirm_msg, timeline=steps, risk=risk, preview=preview)

    async def handle_pending(self, pending_key, text, nlu, session, user_id, lang, emit, sim_mode, dispatch_skill, make_gateway):
        payload = session.get("pending_payload") or {}

        if pending_key == "skill:send_money:await_recipient":
            session["pending_action"]  = None
            session["pending_payload"] = {**payload, "recipient_name": text}
            nlu.entities["recipient_name"] = text
            return await dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:send_money:await_amount":
            amount, amt_currency = parse_amount(text)
            if amount is None:
                return ("Please enter a valid amount." if lang == "en" else "कृपया वैध राशि दर्ज करें।")
            session["pending_action"]  = None
            merged = {**payload, "amount": amount, "currency": amt_currency}
            session["pending_payload"] = merged
            nlu.entities = {**nlu.entities, "recipient_name": merged.get("recipient_name"),
                            "recipient_account_number": merged.get("account_number"),
                            "recipient_ifsc": merged.get("ifsc"), "amount": amount,
                            "currency": amt_currency, "note": merged.get("note")}
            return await dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:send_money:await_account":
            parts = [p.strip() for p in re.split(r"[\s,]+", text) if p.strip()]
            if len(parts) < 2:
                return ("Please provide account number and IFSC separated by space (e.g. 123456789012 VPAY0000001)."
                        if lang == "en" else "कृपया खाता नंबर और IFSC दें।")
            session["pending_action"]  = None
            merged = {**payload, "account_number": parts[0], "ifsc": parts[1]}
            session["pending_payload"] = merged
            nlu.entities = {**nlu.entities, "recipient_name": merged.get("recipient_name"),
                            "recipient_account_number": parts[0], "recipient_ifsc": parts[1],
                            "amount": merged.get("amount"), "currency": merged.get("currency"), "note": merged.get("note")}
            return await dispatch_skill("send_money", nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:send_money:await_confirm":
            session["pending_action"]  = None
            session["pending_payload"] = {}
            if is_negative(text):
                return t("transfer_cancelled", lang)
            if not is_affirmative(text):
                return ("Please reply **yes** to confirm or **no** to cancel."
                        if lang == "en" else "पुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।")

            gateway = make_gateway(self.ALLOWED_TOOLS)
            old_steps = [WorkflowStep(
                label=s.get("label", "Unknown step"),
                tool=s.get("tool"),
                params=s.get("params") or {},
                status=s.get("status", "pending"),
                result=s.get("result"),
            ) for s in (payload.get("steps") or [])]

            await emit("timeline", {"steps": payload.get("steps", [])})

            init_step = WorkflowStep("Initiate transfer", "create_transfer", {
                "requesting_user_id": user_id,
                "recipient_name":     payload["recipient_name"],
                "account_number":     payload["account_number"],
                "ifsc":               payload["ifsc"],
                "amount":             payload["amount"],
                "currency":           payload.get("currency") or "INR",
                "note":               payload.get("note") or "",
            })
            init_step.status = "running"
            await emit("timeline", {"steps": serialize_steps(old_steps) +
                                             [{"label": init_step.label, "tool": init_step.tool, "status": init_step.status}]})
            transfer = await gateway("create_transfer", init_step.params)
            if transfer.get("error"):
                return wallet_error_reply(transfer, lang)

            confirm_step = WorkflowStep("Execute transfer", "confirm_transfer",
                                {"requesting_user_id": user_id, "transaction_id": transfer["transaction_id"]})
            confirm_step.status = "running"
            await emit("timeline", {"steps": [{"label": confirm_step.label, "tool": confirm_step.tool,
                                                "status": confirm_step.status}]})
            result = await gateway("confirm_transfer", confirm_step.params)
            if result.get("error"):
                return wallet_error_reply(result, lang)

            confirm_step.status = "done"
            await emit("timeline", {"steps": [{"label": confirm_step.label, "tool": confirm_step.tool,
                                                "status": confirm_step.status}]})
            currency_code = transfer.get("currency", "INR")
            return tpl("transfer_success", lang,
                       amount=format_money(result["amount"], currency_code),
                       recipient_name=result["recipient_name"],
                       transaction_id=result["transaction_id"],
                       balance=format_money(result["balance"], currency_code))

        return None
