"""
Tests proving the UPI PIN / payment-authentication-secret policy is
actually enforced, not just documented — for both Add Money and Send
Money.

Three layers are tested:
1. REST-level: a request smuggling a PIN-like field is rejected with 422
   (Pydantic's extra="forbid"), never silently accepted or ignored.
2. Static/regression: no Pydantic request model, database column, or MCP
   tool parameter anywhere in the app is named like a payment secret —
   this guards against someone accidentally adding a real PIN field in
   the future, which extra="forbid" alone would not catch (it only blocks
   UNDECLARED fields, not deliberately-added ones).
3. Unit: the redaction helper actually strips secret-like keys.
"""

import asyncio
import importlib
import inspect
import os
import re
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB per test, so tests don't interfere with each other."""
    db_file = tmp_path / "test_vaani_pay.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c


def register_and_login(client, email="pintest@example.com"):
    client.post("/auth/register", json={
        "name": "PIN Test User", "email": email, "password": "TestPass123", "language": "en",
    })
    res = client.post("/auth/login", json={"email": email, "password": "TestPass123"})
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ==================== Layer 1: REST-level rejection ====================

def test_add_money_rejects_request_with_upi_pin_field(client):
    headers = register_and_login(client)
    res = client.post("/wallet/add-money", json={"amount": 500, "upi_pin": "1234"}, headers=headers)
    assert res.status_code == 422
    # Confirm the rejection happened before any wallet logic ran: balance must still be 0.
    account = client.get("/wallet/account", headers=headers).json()
    assert account["balance"] == 0


def test_add_money_rejects_mpin_field_too(client):
    headers = register_and_login(client)
    res = client.post("/wallet/add-money", json={"amount": 500, "mpin": "1234"}, headers=headers)
    assert res.status_code == 422


def test_add_money_works_normally_without_forbidden_fields(client):
    """Sanity check: the guard doesn't break the legitimate happy path."""
    headers = register_and_login(client)
    res = client.post("/wallet/add-money", json={"amount": 500}, headers=headers)
    assert res.status_code == 200


def test_wallet_history_includes_signed_amount_for_ui(client):
    """History rows must expose the signed amount that the browser renders."""
    headers = register_and_login(client, email="historyui@example.com")
    res = client.post("/wallet/add-money", json={"amount": 500}, headers=headers)
    assert res.status_code == 200

    txs = client.get("/wallet/transactions?filter=all", headers=headers).json()["transactions"]
    assert txs
    assert txs[0]["amount"] == 500
    assert txs[0]["signed_amount"] == 500


def test_saved_recipients_reply_lists_beneficiaries(client):
    """The agent should answer saved-recipient queries instead of falling back to a generic message."""
    from app import wallet
    from app.agent import handle_message
    from app.nlu import NLUResult

    headers = register_and_login(client, email="savedrecips@example.com")
    client.post("/beneficiaries", json={
        "recipient_name": "Priya Sharma",
        "account_number": "123456789012",
        "ifsc": "VPAY0000001",
    }, headers=headers)

    async def run_check():
        session = {"user_id": "user_1", "language": "en", "simulation_mode": False}
        # use a stable user_id that matches the auth-created user
        user = client.get("/users/me", headers=headers).json()
        session["user_id"] = user["id"]
        response = await handle_message(
            NLUResult(english_translation="saved recipients", intent="general_question", entities={}, confidence=0.9),
            session,
            emit=None,
        )
        assert "Priya Sharma" in response
        assert "Saved recipients" in response or "saved recipients" in response.lower()

    import asyncio
    asyncio.run(run_check())


def test_send_money_simulation_uses_empty_strings_for_missing_recipient_fields():
    """Simulation mode must not pass None into the MCP recipient validator."""
    from app.skills import SendMoneySkill

    captured = {}

    async def fake_mcp_call(name, args):
        captured["name"] = name
        captured["args"] = args
        return {
            "status": "resolved",
            "recipient_name": "Divya",
            "account_number": "123456789012",
            "ifsc": "VPAY0000001",
        }

    async def fake_emit(event_type, payload):
        return None

    skill = SendMoneySkill()
    session = {"pending_action": None, "pending_payload": {}, "language": "en", "simulation_mode": True}
    result = asyncio.run(skill.execute(
        intent="send_money",
        entities={"recipient_name": "Divya", "amount": 34},
        session=session,
        user_id="u1",
        lang="en",
        mcp_call=fake_mcp_call,
        emit=fake_emit,
        sim_mode=True,
    ))

    assert result.success is True
    assert captured["name"] == "validate_recipient"
    assert captured["args"]["account_number"] == ""
    assert captured["args"]["ifsc"] == ""
    assert "SIMULATION" in result.reply.upper()


def test_favicon_route_serves_an_icon(client):
    """Browser requests for /favicon.ico should not 404 on the app shell."""
    res = client.get("/favicon.ico")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("image/") or "svg" in res.headers.get("content-type", "")


def test_send_money_initiate_rejects_upi_pin_field(client):
    headers = register_and_login(client, email="pinsender@example.com")
    client.post("/wallet/add-money", json={"amount": 1000}, headers=headers)

    res = client.post("/wallet/transfers", json={
        "recipient_name": "Someone", "account_number": "123456789012", "ifsc": "VPAY0000001",
        "amount": 100, "upi_pin": "1234",
    }, headers=headers)
    assert res.status_code == 422


def test_send_money_initiate_rejects_transaction_password_field(client):
    headers = register_and_login(client, email="pinsender2@example.com")
    res = client.post("/wallet/transfers", json={
        "recipient_name": "Someone", "account_number": "123456789012", "ifsc": "VPAY0000001",
        "amount": 100, "transaction_password": "secret",
    }, headers=headers)
    assert res.status_code == 422


def test_validate_recipient_rejects_pin_field(client):
    headers = register_and_login(client, email="pinvalidate@example.com")
    res = client.post("/wallet/validate-recipient", json={
        "recipient_name": "Someone", "account_number": "123456789012", "ifsc": "VPAY0000001", "card_pin": "1234",
    }, headers=headers)
    assert res.status_code == 422


def test_save_beneficiary_rejects_pin_field(client):
    headers = register_and_login(client, email="pinbeneficiary@example.com")
    res = client.post("/beneficiaries", json={
        "recipient_name": "Someone", "account_number": "123456789012", "ifsc": "VPAY0000001", "atm_pin": "1234",
    }, headers=headers)
    assert res.status_code == 422


# ==================== Layer 2: static regression guards ====================

def test_no_wallet_request_model_declares_a_payment_secret_field():
    """Even if extra='forbid' were removed later, no model should ever DECLARE a PIN-like field."""
    from app import security, main

    wallet_models = [
        main.AddMoneyRequest, main.ValidateRecipientRequest,
        main.InitiateTransferRequest, main.SaveBeneficiaryRequest,
    ]
    for model in wallet_models:
        hits = security.find_forbidden_payment_secret_fields(model.model_fields.keys())
        assert hits == [], f"{model.__name__} declares forbidden field(s): {hits}"


def test_all_pydantic_models_in_main_are_free_of_payment_secret_fields():
    """Broader sweep: every BaseModel in app/main.py, not just the wallet ones."""
    from app import security, main
    from pydantic import BaseModel

    checked_any = False
    for name, obj in vars(main).items():
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            checked_any = True
            hits = security.find_forbidden_payment_secret_fields(obj.model_fields.keys())
            assert hits == [], f"{name} declares forbidden field(s): {hits}"
    assert checked_any, "sanity check: expected to find at least one BaseModel in app.main"


def test_no_database_column_is_named_like_a_payment_secret():
    from app import security

    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "db.py")
    with open(schema_path) as f:
        schema_sql = f.read()

    # Extract plausible column-name tokens from every CREATE TABLE block —
    # good enough for a regression guard without a full SQL parser.
    column_names = re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:TEXT|REAL|INTEGER|BLOB)\b", schema_sql, re.MULTILINE)
    hits = security.find_forbidden_payment_secret_fields(column_names)
    assert hits == [], f"Database schema declares forbidden column(s): {hits}"


def test_no_mcp_wallet_tool_parameter_is_named_like_a_payment_secret():
    from app import security

    tools_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "mcp_server", "tools", "wallet_tools.py"
    )
    with open(tools_path) as f:
        source = f.read()

    # Pull every parameter name out of the tool function signatures.
    param_names = re.findall(r"def \w+\(([^)]*)\)", source)
    all_params = []
    for sig in param_names:
        for part in sig.split(","):
            part = part.strip()
            if not part:
                continue
            param_name = part.split(":")[0].strip()
            all_params.append(param_name)

    hits = security.find_forbidden_payment_secret_fields(all_params)
    assert hits == [], f"MCP wallet tool declares forbidden parameter(s): {hits}"


def test_forbidden_field_matcher_catches_expected_variants():
    """Sanity check on the matcher itself, so the regression tests above are trustworthy."""
    from app import security

    hits = security.find_forbidden_payment_secret_fields([
        "upi_pin", "UPI_PIN", "upiPin".lower(), "mpin", "m_pin", "card_pin", "atm_pin",
        "transaction_password", "txn_password", "amount", "recipient_name", "ifsc",
    ])
    assert "amount" not in hits
    assert "recipient_name" not in hits
    assert "ifsc" not in hits
    assert "upi_pin" in hits
    assert "mpin" in hits
    assert "card_pin" in hits
    assert "transaction_password" in hits


# ==================== Layer 3: redaction helper ====================

def test_redact_payment_secrets_strips_matching_keys():
    from app import security

    raw = {"amount": 500, "upi_pin": "1234", "recipient_name": "Rahul", "mpin": "9999"}
    redacted = security.redact_payment_secrets(raw)

    assert redacted["amount"] == 500
    assert redacted["recipient_name"] == "Rahul"
    assert redacted["upi_pin"] == "[REDACTED]"
    assert redacted["mpin"] == "[REDACTED]"


def test_redact_payment_secrets_leaves_clean_dict_unchanged():
    from app import security

    raw = {"amount": 500, "recipient_name": "Rahul", "ifsc": "VPAY0000001"}
    assert security.redact_payment_secrets(raw) == raw
