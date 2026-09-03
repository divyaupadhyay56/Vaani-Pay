from __future__ import annotations

from app.skills.base import BaseSkill
from app.skills.check_balance import CheckBalanceSkill
from app.skills.add_money import AddMoneySkill
from app.skills.send_money import SendMoneySkill
from app.skills.transaction_memory import TransactionMemorySkill
from app.skills.payment_status import PaymentStatusSkill
from app.skills.beneficiaries import BeneficiariesSkill
from app.skills.simulation_mode import SimulationModeSkill
import re

SKILL_REGISTRY: list[BaseSkill] = [
    CheckBalanceSkill(),
    AddMoneySkill(),
    SendMoneySkill(),
    TransactionMemorySkill(),
    PaymentStatusSkill(),
    BeneficiariesSkill(),
    SimulationModeSkill(),
]


def select_skill(intent: str, text: str = "") -> BaseSkill | None:
    if intent == "general_question":
        normalized = text.lower()
        if re.search(r"\bsaved recipients?\b|\bbeneficiar(?:y|ies)\b", normalized):
            intent = "view_beneficiaries"
        elif re.search(r"\b(simulation mode|dry[- ]run)\b", normalized):
            intent = "set_simulation_mode"
    for skill in SKILL_REGISTRY:
        if skill.can_handle(intent):
            return skill
    return None
