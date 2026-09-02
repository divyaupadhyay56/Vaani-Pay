from __future__ import annotations

from app.core.formatting import format_money
from app.skills.base import BaseSkill, SkillResult, WorkflowStep, serialize_steps


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
        if intent in ("check_payment_status", "check_payment_failure"):
            pid = entities.get("payment_id") or ""
            if not pid:
                session["pending_action"]  = "skill:payment_status:await_pid"
                session["pending_payload"] = {"intent": intent}
                return SkillResult(success=True, reply="Please enter your payment ID (e.g. pay_1001).", timeline=[])
            steps = [WorkflowStep("Fetch payment status", "get_payment_status",
                                  {"payment_id": pid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("get_payment_status", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that payment.", timeline=steps)
            if intent == "check_payment_failure":
                if res["status"] != "failed":
                    return SkillResult(success=True, reply=f"Payment {pid} did not fail — status: {res['status']}.", timeline=steps)
                return SkillResult(success=False,
                                   reply=f"Payment **{pid}** failed. Reason: **{res['failure_reason']}**. Amount: {format_money(res['amount'])}.",
                                   timeline=steps)
            suffix = f" Failure reason: {res['failure_reason']}." if res.get("failure_reason") else ""
            return SkillResult(success=True,
                               reply=f"Payment **{pid}**: status **{res['status']}**, amount {format_money(res['amount'])}, method {res['method']}.{suffix}",
                               timeline=steps)

        if intent == "check_refund_status":
            rid = entities.get("refund_id") or ""
            if not rid:
                session["pending_action"]  = "skill:payment_status:await_rid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter your refund ID.", timeline=[])
            steps = [WorkflowStep("Fetch refund status", "get_refund_status",
                                  {"refund_id": rid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("get_refund_status", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that refund.", timeline=steps)
            return SkillResult(success=True,
                               reply=f"Refund **{rid}**: {format_money(res['amount'])}, status **{res['status']}** (for payment {res['payment_id']}).",
                               timeline=steps)

        if intent == "check_order_details":
            oid = entities.get("order_id") or ""
            if not oid:
                session["pending_action"]  = "skill:payment_status:await_oid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter your order ID.", timeline=[])
            steps = [WorkflowStep("Fetch order details", "get_order_details",
                                  {"order_id": oid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("get_order_details", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied for that order.", timeline=steps)
            return SkillResult(success=True,
                               reply=f"Order **{oid}**: status **{res['status']}**, total {format_money(res['total'])}, items: {', '.join(res['items'])}.",
                               timeline=steps)

        if intent == "check_fraud_risk":
            pid = entities.get("payment_id") or ""
            if not pid:
                session["pending_action"]  = "skill:payment_status:await_fraud_pid"
                session["pending_payload"] = {}
                return SkillResult(success=True, reply="Please enter the payment ID to check for fraud risk.", timeline=[])
            steps = [WorkflowStep("Run fraud risk check", "check_fraud_risk",
                                  {"payment_id": pid, "requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("check_fraud_risk", steps[0].params)
            steps[0].status = "done" if not res.get("error") else "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            if res.get("error") == "access_denied":
                return SkillResult(success=False, reply="Access denied.", timeline=steps)
            tag = {"high": "🔴 HIGH", "low": "🟢 LOW"}.get(res["risk_level"], res["risk_level"])
            return SkillResult(success=True,
                               reply=f"Fraud risk for payment **{pid}**: **{tag}**. Reason: {res['reason']}.",
                               timeline=steps)

        if intent == "view_transactions":
            steps = [WorkflowStep("Fetch transaction history", "get_transaction_history",
                                  {"requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("get_transaction_history", steps[0].params)
            steps[0].status = "done"; await emit("timeline", {"steps": serialize_steps(steps)})
            txns = res.get("transactions", [])
            if not txns:
                return SkillResult(success=True, reply="No transactions yet.", timeline=steps)
            lines = [f"• {tx['type'].upper()} {tx['txn_id']}: {format_money(tx['amount'])} — {tx['status']} ({tx['date']})"
                     for tx in txns]
            return SkillResult(success=True, reply="**Your transactions:**\n" + "\n".join(lines), timeline=steps)

        if intent == "payment_statistics":
            steps = [WorkflowStep("Calculate payment statistics", "get_payment_statistics",
                                  {"requesting_user_id": user_id})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            res = await mcp_call("get_payment_statistics", steps[0].params)
            steps[0].status = "done"; await emit("timeline", {"steps": serialize_steps(steps)})
            return SkillResult(success=True,
                               reply=f"You have **{res['transaction_count']}** payments totalling **{format_money(res['total_amount'])}** "
                                     f"(avg {format_money(res['average_amount'])}). Success rate: {res['success_rate']}%.",
                               timeline=steps)

        return SkillResult(success=False, reply="Intent not handled by this skill.", timeline=[])

    async def handle_pending(self, pending_key, text, nlu, session, user_id, lang, emit, sim_mode, dispatch_skill, make_gateway):
        payload = session.get("pending_payload") or {}

        if pending_key == "skill:payment_status:await_pid":
            intent = payload.get("intent", "check_payment_status")
            session["pending_action"]  = None
            session["pending_payload"] = {}
            nlu.entities["payment_id"] = text
            return await dispatch_skill(intent, nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:payment_status:await_rid":
            session["pending_action"]  = None
            session["pending_payload"] = {}
            nlu.entities["refund_id"]  = text
            return await dispatch_skill("check_refund_status", nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:payment_status:await_oid":
            session["pending_action"]  = None
            session["pending_payload"] = {}
            nlu.entities["order_id"]   = text
            return await dispatch_skill("check_order_details", nlu, session, user_id, lang, emit, sim_mode)

        if pending_key == "skill:payment_status:await_fraud_pid":
            session["pending_action"]   = None
            session["pending_payload"]  = {}
            nlu.entities["payment_id"]  = text
            return await dispatch_skill("check_fraud_risk", nlu, session, user_id, lang, emit, sim_mode)

        return None
