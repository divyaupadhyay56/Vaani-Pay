from __future__ import annotations

from app.core.formatting import format_money
from app.skills.base import BaseSkill, SkillResult, WorkflowStep, err, serialize_steps


class TransactionMemorySkill(BaseSkill):
    NAME          = "transaction_memory"
    ALLOWED_TOOLS = {"get_transactions", "get_spending_summary"}

    def can_handle(self, intent: str) -> bool:
        return intent in ("view_wallet_transactions", "spending_summary", "payment_statistics")

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        if intent == "spending_summary":
            steps = [WorkflowStep("Fetch spending summary", "get_spending_summary",
                                  {"requesting_user_id": user_id, "period": "month"})]
            await emit("timeline", {"steps": serialize_steps(steps)})
            steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
            result = await mcp_call("get_spending_summary", steps[0].params)
            steps[0].status = "done" if not result.get("error") else "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            if result.get("error"):
                return SkillResult(success=False, reply=err(result), timeline=steps)
            reply = (
                f"This month you've sent **{format_money(result['total_spent'])}** across "
                f"**{result['transaction_count']}** transfers."
                if lang == "en" else
                f"इस महीने आपने **{result['transaction_count']}** ट्रांसफर में कुल **{format_money(result['total_spent'])}** भेजे।"
            )
            return SkillResult(success=True, reply=reply, data=result, timeline=steps)

        steps = [WorkflowStep("Fetch transactions", "get_transactions",
                              {"requesting_user_id": user_id, "filter": "all"})]
        await emit("timeline", {"steps": serialize_steps(steps)})
        steps[0].status = "running"; await emit("timeline", {"steps": serialize_steps(steps)})
        result = await mcp_call("get_transactions", steps[0].params)
        steps[0].status = "done" if not result.get("error") else "failed"
        await emit("timeline", {"steps": serialize_steps(steps)})
        if result.get("error"):
            return SkillResult(success=False, reply=err(result), timeline=steps)

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
