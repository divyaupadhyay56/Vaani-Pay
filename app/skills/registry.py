from __future__ import annotations

from app.skills.base import BaseSkill
from app.skills.check_balance import CheckBalanceSkill
from app.skills.add_money import AddMoneySkill
from app.skills.send_money import SendMoneySkill
from app.skills.transaction_memory import TransactionMemorySkill
from app.skills.payment_status import PaymentStatusSkill

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
