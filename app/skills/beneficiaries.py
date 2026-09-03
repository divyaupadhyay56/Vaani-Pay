from __future__ import annotations

from app.skills.base import BaseSkill, SkillResult
from app.i18n import t


class BeneficiariesSkill(BaseSkill):
    NAME = "beneficiaries"
    ALLOWED_TOOLS = {"list_beneficiaries"}

    def can_handle(self, intent: str) -> bool:
        return intent == "view_beneficiaries"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        result = await mcp_call("list_beneficiaries", {"requesting_user_id": user_id})
        if result.get("error"):
            return SkillResult(success=False, reply=t("wallet_error_generic", lang))

        beneficiaries = result.get("beneficiaries", [])
        if not beneficiaries:
            return SkillResult(success=True, reply=t("no_beneficiaries", lang))

        lines = [
            f"• {item['recipient_name']} — {item['account_number']} ({item['ifsc']})"
            for item in beneficiaries
        ]
        return SkillResult(
            success=True,
            reply=f"{t('saved_beneficiaries_header', lang)}\n" + "\n".join(lines),
        )