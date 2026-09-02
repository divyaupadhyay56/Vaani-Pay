from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.i18n import t


@dataclass
class WorkflowStep:
    label:       str
    tool:        str | None
    params:      dict
    status:      str = "pending"
    result:      Any = None


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

    async def handle_pending(
        self,
        pending_key: str,
        text: str,
        nlu,
        session: dict,
        user_id: str,
        lang: str,
        emit,
        sim_mode: bool,
        dispatch_skill,
        make_gateway,
    ) -> str | None:
        """Handle a pending-action follow-up. Return reply string, or None if unhandled."""
        return None


def serialize_steps(steps: list[WorkflowStep]) -> list[dict]:
    return [
        {
            "label": s.label,
            "tool": s.tool,
            "status": s.status,
            "params": s.params,
        }
        for s in steps
    ]


def err(result: dict) -> str:
    return result.get("message") or result.get("error") or "An error occurred."


def sim_reply(action: str, detail: str, lang: str) -> str:
    if lang == "en":
        return (f"🧪 **SIMULATION** — No real payment executed.\n\n"
                f"**{action}**: {detail}\n\n"
                f"Workflow validated. All checks passed. "
                f"Switch to execution mode and confirm to proceed with the real payment.")
    return (f"🧪 **सिमुलेशन** — कोई वास्तविक भुगतान नहीं हुआ।\n\n"
            f"**{action}**: {detail}\n\n"
            f"वर्कफ़्लो सत्यापित। सभी जाँचें पास।")


def wallet_error_reply(result: dict, lang: str) -> str:
    code = result.get("error")
    key_map = {"insufficient_balance": "error_insufficient_balance"}
    if code in key_map:
        return t(key_map[code], lang)
    return f"{t('wallet_error_generic', lang)} ({result.get('message', code)})"
