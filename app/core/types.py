from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserIdentity:
    user_id: str
    name: str
    email: str
    language: str
