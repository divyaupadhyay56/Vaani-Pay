from __future__ import annotations

from app.skills.base import BaseSkill, SkillResult, WorkflowStep, err, serialize_steps


class CheckBalanceSkill(BaseSkill):
    NAME          = "check_balance"
    ALLOWED_TOOLS = {"get_balance"}

    def can_handle(self, intent: str) -> bool:
        return intent == "check_balance"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        steps = [WorkflowStep("Retrieve wallet balance", "get_balance", {"requesting_user_id": user_id})]
        await emit("timeline", {"steps": serialize_steps(steps)})
        steps[0].status = "running"
        await emit("timeline", {"steps": serialize_steps(steps)})

        result = await mcp_call("get_balance", {"requesting_user_id": user_id})
        if result.get("error"):
            steps[0].status = "failed"
            await emit("timeline", {"steps": serialize_steps(steps)})
            return SkillResult(success=False, reply=err(result), timeline=steps)

        steps[0].status = "done"
        steps[0].result = result
        await emit("timeline", {"steps": serialize_steps(steps)})
        bal = result["balance"]
        reply = (
            f"Your current wallet balance is **₹{bal:,.2f}**."
            if lang == "en" else
            f"आपका वर्तमान वॉलेट बैलेंस **₹{bal:,.2f}** है।"
        )
        return SkillResult(success=True, reply=reply, data=result, timeline=steps)
