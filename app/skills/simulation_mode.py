from __future__ import annotations

from app.i18n import t
from app.skills.base import BaseSkill, SkillResult


class SimulationModeSkill(BaseSkill):
    NAME = "simulation_mode"
    ALLOWED_TOOLS = set()

    def can_handle(self, intent: str) -> bool:
        return intent == "set_simulation_mode"

    async def execute(self, intent, entities, session, user_id, lang, mcp_call, emit, sim_mode):
        enabled = entities.get("simulation_enabled")
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in {"false", "off", "disable", "disabled", "0", "no"}
        else:
            enabled = bool(enabled)
        session["simulation_mode"] = enabled
        return SkillResult(success=True, reply=t("simulation_on" if enabled else "simulation_off", lang))