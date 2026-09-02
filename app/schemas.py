from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None
    language: str = "en"


class LoginRequest(BaseModel):
    email: str
    password: str

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class UpdatePreferencesRequest(BaseModel):
    language: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: bool = Field(..., description="Must be true to confirm permanent account deletion.")


class AddMoneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float
    description: Optional[str] = None
    currency: Optional[str] = None


class ValidateRecipientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: Optional[str] = None
    ifsc: Optional[str] = None


class InitiateTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: str
    ifsc: str
    amount: float
    note: Optional[str] = None
    currency: Optional[str] = None

class SaveBeneficiaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: str
    ifsc: str