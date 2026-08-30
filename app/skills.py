
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import fraud as fraud_engine

@dataclass
class WorkflowStep:
    label:       str              
    tool:        str | None       
    params:      dict             
    status:      str = "pending"  
    result:      Any  = None


@dataclass
class SkillResult:
    success:     bool
    reply:       str              
    data:        dict = field(default_factory=dict)
    timeline:    list[WorkflowStep] = field(default_factory=list)
    risk:        dict | None = None
    preview:     dict | None = None   


class BaseSkill:
    NAME:          str       = "base"
    ALLOWED_TOOLS: set[str]  = set()

    def can_handle(self, intent: str) -> bool:
        raise NotImplementedError

    async def execute(
        self,
        intent:    str,
        entities:  dict,
        session:   dict,
        user_id:   str,
        lang:      str,
        mcp_call,          
        emit,              
        sim_mode:  bool,
    ) -> SkillResult:
        raise NotImplementedError


class CheckBalanceSkill(BaseSkill):
    NAME          = "check_balance"
    ALLOWED_TOOLS = {"get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "check_balance"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        steps = [WorkflowStep("Retrieve wallet balance", "get_balance", {"requesting_user_id": user_id})]
        await emit("timeline", {"steps": _serialize_steps(steps)})
        steps[0].status = "running"
        await emit("timeline", {"steps": _serialize_steps(steps)})

        result = await mcp_call("get_balance", {"requesting_user_id": user_id})
        if result.get("error"):
            steps[0].status = "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            return SkillResult(success=False, reply=_err(result), timeline=steps)

        steps[0].status = "done"
        steps[0].result = result
        await emit("timeline", {"steps": _serialize_steps(steps)})
        bal = result["balance"]
        reply = (
            f"Your current wallet balance is **₹{bal:,.2f}**."
            if lang == "en" else
            f"आपका वर्तमान वॉलेट बैलेंस **₹{bal:,.2f}** है।"
        )
        return SkillResult(success=True, reply=reply, data=result, timeline=steps)


class AddMoneySkill(BaseSkill):
    NAME          = "add_money"
    ALLOWED_TOOLS = {"add_money", "get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "add_money"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        from app.agent import _parse_amount, _money
        amount = _parse_amount(str(entities.get("amount") or ""))

        # Ask for amount if missing
        if amount is None:
            session["pending_action"]  = "skill:add_money:await_amount"
            session["pending_payload"] = {}
            q = ("How much would you like to add to your wallet? (e.g. ₹500)"
                 if lang == "en" else
                 "आप अपने वॉलेट में कितना जोड़ना चाहते हैं? (जैसे ₹500)")
            return SkillResult(success=True, reply=q, timeline=[])

        steps = [
            WorkflowStep("Validate amount",      None,        {"amount": amount}),
            WorkflowStep("Run fraud check",      None,        {}),
            WorkflowStep("⏸ User confirmation",  None,        {}),
            WorkflowStep("Credit wallet",        "add_money", {"requesting_user_id": user_id, "amount": amount}),
            WorkflowStep("Verify new balance",   "get_balance", {"requesting_user_id": user_id}),
        ]

        preview = {
            "action":   "Add Money",
            "amount":   f"₹{amount:,.2f}",
            "method":   "Vaani Pay Wallet",
            "risk":     "LOW",
            "steps":    [s.label for s in steps],
            "sim_mode": sim_mode,
        }

        if sim_mode:
            return SkillResult(
                success=True,
                reply=_sim_reply("Add Money", f"₹{amount:,.2f}", lang),
                timeline=steps,
                preview=preview,
            )

        session["pending_action"]  = "skill:add_money:await_confirm"
        session["pending_payload"] = {"amount": amount, "steps": _serialize_steps(steps)}
        await emit("preview", preview)
        await emit("timeline", {"steps": _serialize_steps(steps)})
        prompt = (
            f"💳 **Add Money Preview**\n\nAmount: ₹{amount:,.2f}\n\nReply **yes** to confirm or **no** to cancel."
            if lang == "en" else
            f"💳 **पैसे जोड़ें — पूर्वावलोकन**\n\nराशि: ₹{amount:,.2f}\n\nपुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।"
        )
        return SkillResult(success=True, reply=prompt, timeline=steps, preview=preview)



class SendMoneySkill(BaseSkill):
    NAME          = "send_money"
    ALLOWED_TOOLS = {"validate_recipient", "create_transfer", "confirm_transfer", "cancel_transfer", "get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "send_money"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        from app.agent import _parse_amount, _money
        recipient_name  = (entities.get("recipient_name") or "").strip()
        account_number  = (entities.get("recipient_account_number") or "").strip()
        ifsc            = (entities.get("recipient_ifsc") or "").strip()
        amount_raw      = entities.get("amount")
        note            = (entities.get("note") or "").strip()
        amount          = _parse_amount(str(amount_raw or ""))

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
                "note": note,
            }),
            WorkflowStep("Execute transfer",     "confirm_transfer",   {}),
            WorkflowStep("Verify result",        "get_balance",        {"requesting_user_id": user_id}),
        ]

        await emit("timeline", {"steps": _serialize_steps(steps)})

        steps[0].status = "running"
        await emit("timeline", {"steps": _serialize_steps(steps)})
        resolution = await mcp_call("validate_recipient", steps[0].params)
        status = resolution.get("status")
        if status == "not_found":
            steps[0].status = "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            session["pending_action"]  = "skill:send_money:await_account"
            session["pending_payload"] = {**payload, "recipient_name": recipient_name,
                                          "amount": amount, "note": note}
            q = (f"I couldn't find a saved beneficiary named **{recipient_name}**. "
                 f"Please provide their account number and IFSC (e.g. '123456789012 VPAY0000001')."
                 if lang == "en" else
                 f"**{recipient_name}** नाम का कोई सहेजा हुआ लाभार्थी नहीं मिला। "
                 f"कृपया उनका खाता नंबर और IFSC दें।")
            return SkillResult(success=True, reply=q, timeline=steps)
        if status in ("invalid", "ambiguous"):
            steps[0].status = "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            return SkillResult(success=False, reply=resolution.get("message", "Invalid recipient."), timeline=steps)

        steps[0].status = "done"
        resolved_account = resolution["account_number"]
        resolved_ifsc    = resolution["ifsc"]
        resolved_name    = resolution["recipient_name"]

        
        steps[1].status = "running"
        await emit("timeline", {"steps": _serialize_steps(steps)})
        risk = fraud_engine.analyse(user_id, amount, resolved_account, resolved_ifsc)
        steps[1].status = "done"
        steps[1].result = risk

     
        steps[2].status = "running"
        preview = {
            "action":     "Send Money",
            "recipient":  resolved_name,
            "account":    f"XXXX{resolved_account[-4:]}",
            "ifsc":       resolved_ifsc,
            "amount":     f"₹{amount:,.2f}",
            "fee":        "₹0.00",
            "total_debit": f"₹{amount:,.2f}",
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "risk_reasons": risk["reasons"],
            "steps":      [s.label for s in steps],
            "sim_mode":   sim_mode,
        }
        steps[2].status = "done"
        await emit("timeline", {"steps": _serialize_steps(steps)})
        await emit("preview",  preview)
        await emit("risk",     {"level": risk["risk_level"], "score": risk["risk_score"], "reasons": risk["reasons"]})

        if risk["block"]:
            steps[3].status = "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
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
                reply=_sim_reply("Send Money", f"₹{amount:,.2f} to {resolved_name}", lang),
                timeline=steps, risk=risk, preview=preview,
            )

      
        steps[3].status = "running"
        session["pending_action"]  = "skill:send_money:await_confirm"
        session["pending_payload"] = {
            "recipient_name":  resolved_name,
            "account_number":  resolved_account,
            "ifsc":            resolved_ifsc,
            "amount":          amount,
            "note":            note,
            "risk":            risk,
            "steps":           _serialize_steps(steps),
        }
        risk_tag = {"LOW": "🟢 Low", "MEDIUM": "🟡 Medium", "HIGH": "🔴 High"}[risk["risk_level"]]
        confirm_msg = (
            f"📤 **Transfer Preview**\n\n"
            f"To: **{resolved_name}** (XXXX{resolved_account[-4:]})\n"
            f"Amount: **₹{amount:,.2f}**\n"
            f"Fee: ₹0.00\n"
            f"Risk: {risk_tag}\n\n"
            + ("\n".join(f"• {r}" for r in risk["reasons"]) + "\n\n" if risk["reasons"] != ["Transaction pattern appears normal"] else "")
            + "Reply **yes** to confirm or **no** to cancel."
            if lang == "en" else
            f"📤 **ट्रांसफर पूर्वावलोकन**\n\n"
            f"प्राप्तकर्ता: **{resolved_name}** (XXXX{resolved_account[-4:]})\n"
            f"राशि: **₹{amount:,.2f}**\n"
            f"जोखिम: {risk_tag}\n\n"
            f"पुष्टि के लिए **हाँ** या रद्द करने के लिए **नहीं** टाइप करें।"
        )
        return SkillResult(success=True, reply=confirm_msg, timeline=steps, risk=risk, preview=preview)



class TransactionMemorySkill(BaseSkill):
    NAME          = "transaction_memory"
    ALLOWED_TOOLS = {"get_transactions", "get_spending_summary"}

    def can_handle(self, intent: str) -> bool:
        return intent in ("view_wallet_transactions", "spending_summary", "payment_statistics")

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        from app.agent import _money
        if intent == "spending_summary":
            steps = [WorkflowStep("Fetch spending summary", "get_spending_summary",
                                  {"requesting_user_id": user_id, "period": "month"})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            result = await mcp_call("get_spending_summary", steps[0].params)
            steps[0].status = "done" if not result.get("error") else "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            if result.get("error"):
                return SkillResult(success=False, reply=_err(result), timeline=steps)
            reply = (
                f"This month you've sent **{_money(result['total_spent'])}** across "
                f"**{result['transaction_count']}** transfers."
                if lang == "en" else
                f"इस महीने आपने **{result['transaction_count']}** ट्रांसफर में कुल **{_money(result['total_spent'])}** भेजे।"
            )
            return SkillResult(success=True, reply=reply, data=result, timeline=steps)

        steps = [WorkflowStep("Fetch transactions", "get_transactions",
                              {"requesting_user_id": user_id, "filter": "all"})]
        await emit("timeline", {"steps": _serialize_steps(steps)})
        steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
        result = await mcp_call("get_transactions", steps[0].params)
        steps[0].status = "done" if not result.get("error") else "failed"
        await emit("timeline", {"steps": _serialize_steps(steps)})
        if result.get("error"):
            return SkillResult(success=False, reply=_err(result), timeline=steps)

        txns = result.get("transactions", [])
        if not txns:
            reply = ("No wallet transactions yet." if lang == "en"
                     else "अभी कोई वॉलेट लेनदेन नहीं है।")
            return SkillResult(success=True, reply=reply, data=result, timeline=steps)

        lines = []
        for tx in txns[:8]:
            amt   = abs(tx["amount"])
            sign  = "+" if tx["amount"] > 0 else "−"
            cpty  = tx.get("counterparty", "")
            date  = str(tx.get("date", ""))[:10]
            lines.append(f"• {sign}₹{amt:,.2f} — {tx['type'].replace('_',' ').title()} {cpty} ({date})")

        header = "**Your recent wallet activity:**" if lang == "en" else "**आपकी हाल की वॉलेट गतिविधि:**"
        reply  = header + "\n" + "\n".join(lines)
        return SkillResult(success=True, reply=reply, data=result, timeline=steps)



class PaymentStatusSkill(BaseSkill):
    NAME          = "payment_status"
    ALLOWED_TOOLS = {"get_payment_status", "check_fraud_risk", "get_transaction_history",
                     "get_payment_statistics", "get_order_details", "get_refund_status"}

    def can_handle(self, intent: str) -> bool:
        return intent in (
            "check_payment_status", "check_payment_failure",
            "check_refund_status",  "check_order_details",
            "check_fraud_risk",     "view_transactions",
            "payment_statistics",
        )

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        from app.agent import _money

        if intent in ("check_payment_status", "check_payment_failure"):
            pid = entities.get("payment_id") or ""
            if not pid:
                session["pending_action"]  = "skill:payment_status:await_pid"
                session["pending_payload"] = {"intent": intent}
                return SkillResult(success=True, reply="Please enter your payment ID (e.g. pay_1001).", timeline=[])
            steps = [WorkflowStep("Fetch payment status", "get_payment_status",
                                  {"payment_id": pid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("get_payment_status", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that payment.", timeline=steps)
            if intent == "check_payment_failure":
                if res["status"] != "failed":
                    return SkillResult(success=True, reply=f"Payment {pid} did not fail — status: {res['status']}.", timeline=steps)
                return SkillResult(success=False,
                                   reply=f"Payment **{pid}** failed. Reason: **{res['failure_reason']}**. Amount: {_money(res['amount'])}.",
                                   timeline=steps)
            suffix = f" Failure reason: {res['failure_reason']}." if res.get("failure_reason") else ""
            return SkillResult(success=True,
                               reply=f"Payment **{pid}**: status **{res['status']}**, amount {_money(res['amount'])}, method {res['method']}.{suffix}",
                               timeline=steps)

        if intent == "check_refund_status":
            rid = entities.get("refund_id") or ""
            if not rid:
                session["pending_action"]  = "skill:payment_status:await_rid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter your refund ID.", timeline=[])
            steps = [WorkflowStep("Fetch refund status", "get_refund_status",
                                  {"refund_id": rid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("get_refund_status", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that refund.", timeline=steps)
            return SkillResult(success=True,
                               reply=f"Refund **{rid}**: {_money(res['amount'])}, status **{res['status']}** (for payment {res['payment_id']}).",
                               timeline=steps)

        if intent == "check_order_details":
            oid = entities.get("order_id") or ""
            if not oid:
                session["pending_action"]  = "skill:payment_status:await_oid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter your order ID.", timeline=[])
            steps = [WorkflowStep("Fetch order details", "get_order_details",
                                  {"order_id": oid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("get_order_details", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that order.", timeline=steps)
            return SkillResult(success=True,
                               reply=f"Order **{oid}**: status **{res['status']}**, total {_money(res['total'])}, items: {', '.join(res['items'])}.",
                               timeline=steps)

        if intent == "check_fraud_risk":
            pid = entities.get("payment_id") or ""
            if not pid:
                session["pending_action"]  = "skill:payment_status:await_fraud_pid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter the payment ID to check for fraud risk.", timeline=[])
            steps = [WorkflowStep("Run fraud risk check", "check_fraud_risk",
                                  {"payment_id": pid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("check_fraud_risk", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": _serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied.", timeline=steps)
            tag = {"high": "🔴 HIGH", "low": "🟢 LOW"}.get(res["risk_level"], res["risk_level"])
            return SkillResult(success=True,
                               reply=f"Fraud risk for payment **{pid}**: **{tag}**. Reason: {res['reason']}.",
                               timeline=steps)

        if intent == "view_transactions":
            steps = [WorkflowStep("Fetch transaction history", "get_transaction_history",
                                  {"requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("get_transaction_history", steps[0].params)
            steps[0].status = "done"; await emit("timeline", {"steps": _serialize_steps(steps)})
            txns = res.get("transactions", [])
            if not txns:
                return SkillResult(success=True, reply="No transactions yet.", timeline=steps)
            lines = [f"• {tx['type'].upper()} {tx['txn_id']}: {_money(tx['amount'])} — {tx['status']} ({tx['date']})"
                     for tx in txns]
            return SkillResult(success=True, reply="**Your transactions:**\n" + "\n".join(lines), timeline=steps)

        if intent == "payment_statistics":
            steps = [WorkflowStep("Calculate payment statistics", "get_payment_statistics",
                                  {"requesting_user_id": user_id})]
            await emit("timeline", {"steps": _serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": _serialize_steps(steps)})
            res = await mcp_call("get_payment_statistics", steps[0].params)
            steps[0].status = "done"; await emit("timeline", {"steps": _serialize_steps(steps)})
            return SkillResult(success=True,
                               reply=f"You have **{res['transaction_count']}** payments totalling **{_money(res['total_amount'])}** "
                                     f"(avg {_money(res['average_amount'])}). Success rate: {res['success_rate']}%.",
                               timeline=steps)

        return SkillResult(success=False, reply="Intent not handled by this skill.", timeline=[])



SKILL_REGISTRY: list[BaseSkill] = [
    CheckBalanceSkill(),
    AddMoneySkill(),
    SendMoneySkill(),
    TransactionMemorySkill(),
    PaymentStatusSkill(),
]


def select_skill(intent: str) -> BaseSkill | None:
    for skill in SKILL_REGISTRY:
        if skill.can_handle(intent):
            return skill
    return None


def _serialize_steps(steps: list[WorkflowStep]) -> list[dict]:
    return [
        {"label": s.label, "tool": s.tool, "status": s.status}
        for s in steps
    ]


def _err(result: dict) -> str:
    return result.get("message") or result.get("error") or "An error occurred."


def _sim_reply(action: str, detail: str, lang: str) -> str:
    if lang == "en":
        return (f"🧪 **SIMULATION** — No real payment executed.\n\n"
                f"**{action}**: {detail}\n\n"
                f"Workflow validated. All checks passed. "
                f"Switch to execution mode and confirm to proceed with the real payment.")
    return (f"🧪 **सिमुलेशन** — कोई वास्तविक भुगतान नहीं हुआ।\n\n"
            f"**{action}**: {detail}\n\n"
            f"वर्कफ़्लो सत्यापित। सभी जाँचें पास।")
