
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import asyncio


def test_fraud_low_for_zero_history_small_amount(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    db_file = tmp_path / "test.db"
    from app import db as appdb
    monkeypatch.setattr(appdb, "DB_PATH", db_file)
    appdb.init_db(seed_if_empty=False)

    from app.fraud import analyse
    conn = appdb.get_connection()
    now = "2025-01-01T10:00:00+00:00"
    conn.execute("INSERT INTO users (id,name,email,password_hash,language,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                 ("u1","Test","t@t.com","x","en",now,now))
    conn.execute("INSERT INTO payment_accounts (user_id,payment_id,account_number,ifsc,balance,currency,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                 ("u1","PAY1","123456789012","VPAY0000001",5000,"INR","active",now))
    conn.commit()

    result = analyse("u1", 100.0, "999999999999", "VPAY0000001")
    assert result["risk_level"] == "LOW"
    assert result["risk_score"] < 0.35
    assert result["block"] is False


def test_fraud_high_for_large_velocity(tmp_path, monkeypatch):
    import sqlite3
    from app import db as appdb
    db_file = tmp_path / "test2.db"
    monkeypatch.setattr(appdb, "DB_PATH", db_file)
    appdb.init_db(seed_if_empty=False)

    from app.fraud import analyse
    conn = appdb.get_connection()
    now = "2025-01-01T10:00:00+00:00"
    conn.execute("INSERT INTO users (id,name,email,password_hash,language,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                 ("u2","Test2","t2@t.com","x","en",now,now))
    conn.execute("INSERT INTO payment_accounts (user_id,payment_id,account_number,ifsc,balance,currency,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                 ("u2","PAY2","111111111111","VPAY0000001",200000,"INR","active",now))
    acc_id = conn.execute("SELECT id FROM payment_accounts WHERE user_id='u2'").fetchone()["id"]
    from datetime import datetime, timedelta, timezone
    for i in range(4):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=i*5)).isoformat()
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id,sender_account_id,amount,transaction_type,status,sender_name,receiver_name,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"TXN{i}", acc_id, 50000, "TRANSFER_OUT", "SUCCESS", "You", "Recipient", ts, ts)
        )
    conn.commit()

    result = analyse("u2", 100000.0, "999999999998", "VPAY0000001")
    assert result["risk_level"] in ("MEDIUM", "HIGH")
    assert result["risk_score"] >= 0.35


def test_skill_registry_covers_all_key_intents():
    from app.skills import select_skill
    for intent in ["check_balance", "add_money", "send_money",
                   "view_wallet_transactions", "spending_summary",
                   "check_payment_status", "payment_statistics"]:
        assert select_skill(intent) is not None, f"No skill for intent: {intent}"


def test_skill_registry_no_skill_for_unknown():
    from app.skills import select_skill
    assert select_skill("do_something_evil") is None


def test_check_balance_allowed_tools():
    from app.skills import CheckBalanceSkill
    s = CheckBalanceSkill()
    assert "get_balance" in s.ALLOWED_TOOLS


def test_send_money_allowed_tools():
    from app.skills import SendMoneySkill
    s = SendMoneySkill()
    assert "create_transfer" in s.ALLOWED_TOOLS
    assert "confirm_transfer" in s.ALLOWED_TOOLS
    assert "add_money" not in s.ALLOWED_TOOLS


@pytest.mark.asyncio
async def test_mcp_gateway_blocks_unlisted_tool():
    from app.agent import _make_mcp_gateway
    gateway = _make_mcp_gateway({"get_balance"})
    with pytest.raises(PermissionError):
        await gateway("add_money", {"requesting_user_id": "u1", "amount": 100})


@pytest.mark.asyncio
async def test_mcp_gateway_allows_listed_tool(monkeypatch):
    from app.agent import _make_mcp_gateway
    calls = []
    async def fake_mcp_call(name, args):
        calls.append((name, args))
        return {"balance": 1000.0}

    import app.mcp_client as mc
    monkeypatch.setattr(mc.mcp_client, "call_tool", fake_mcp_call)

    gateway = _make_mcp_gateway({"get_balance"})
    result  = await gateway("get_balance", {"requesting_user_id": "u1"})
    assert result["balance"] == 1000.0
    assert calls[0][0] == "get_balance"


@pytest.mark.asyncio
async def test_simulation_mode_does_not_call_execute_tools(monkeypatch):
    from app.skills import AddMoneySkill
    called_tools = []

    async def fake_call(name, args):
        called_tools.append(name)
        return {}

    async def fake_emit(et, pl):
        pass

    skill = AddMoneySkill()
    session = {"pending_action": None, "pending_payload": {},
               "language": "en", "simulation_mode": True}
    result = await skill.execute(
        intent="add_money",
        entities={"amount": 500},
        session=session,
        user_id="u1",
        lang="en",
        mcp_call=fake_call,
        emit=fake_emit,
        sim_mode=True,
    )
    assert "SIMULATION" in result.reply.upper()
    assert "add_money" not in called_tools


def test_nlu_result_has_no_pin_field():
    from app.nlu import NLUResult
    result = NLUResult(english_translation="test", intent="add_money",
                       entities={"amount": 500}, confidence=0.9)
    assert "pin" not in str(result.entities).lower()
    assert "upi_pin" not in result.entities
    assert "mpin" not in result.entities


@pytest.mark.asyncio
async def test_hinglish_response_language_is_used_for_replies():
    from app.agent import handle_message
    from app.nlu import NLUResult

    session = {"user_id": "u1", "language": "en", "simulation_mode": False}
    result = await handle_message(
        NLUResult("mera balance", "general_question", {}, 0.9, "hi"),
        session,
    )

    assert session["language"] == "hi"
    assert "मैं" in result


@pytest.mark.asyncio
async def test_send_money_pending_confirmation_rehydrates_serialized_steps():
    from app.skills.send_money import SendMoneySkill

    class DummyNLU:
        entities = {}

    async def fake_emit(event, payload):
        return None

    async def fake_gateway(name, args):
        if name == "create_transfer":
            return {"transaction_id": "TXN-1001", "currency": "INR"}
        if name == "confirm_transfer":
            return {"amount": 100.0, "recipient_name": "Alice", "transaction_id": "TXN-1001", "balance": 1900.0}
        raise AssertionError(f"Unexpected tool call: {name}")

    skill = SendMoneySkill()
    session = {
        "pending_action": "skill:send_money:await_confirm",
        "pending_payload": {
            "recipient_name": "Alice",
            "account_number": "123456789012",
            "ifsc": "VPAY0000001",
            "amount": 100.0,
            "currency": "INR",
            "note": "",
            "steps": [
                {"label": "Validate recipient", "tool": "validate_recipient", "status": "done",
                 "params": {"requesting_user_id": "u1", "recipient_name": "Alice", "account_number": "123456789012", "ifsc": "VPAY0000001"}},
                {"label": "Fraud risk check", "tool": None, "status": "done", "params": {"amount": 100.0}},
                {"label": "Generate action preview", "tool": None, "status": "done", "params": {}},
                {"label": "⏸ User confirmation", "tool": None, "status": "done", "params": {}},
                {"label": "Initiate transfer", "tool": "create_transfer", "status": "pending",
                 "params": {"requesting_user_id": "u1", "recipient_name": "Alice", "account_number": "123456789012", "ifsc": "VPAY0000001", "amount": 100.0, "currency": "INR", "note": ""}},
            ],
        },
    }

    result = await skill.handle_pending(
        "skill:send_money:await_confirm",
        "yes",
        DummyNLU(),
        session,
        "u1",
        "en",
        fake_emit,
        False,
        lambda *args, **kwargs: None,
        lambda allowed_tools: fake_gateway,
    )

    assert "TXN-1001" in result
    assert session["pending_action"] is None
    assert session["pending_payload"] == {}


def test_usd_transfer_keeps_currency_through_confirmation(tmp_path, monkeypatch):
    from app import db, wallet
    from app.services.wallet_transfer_service import initiate_transfer, confirm_transfer

    db_file = tmp_path / "usd_transfer.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()

    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO users (id,name,email,password_hash,language,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("u1", "Test User", "u1@test.com", "x", "en", "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
    )
    conn.commit()

    wallet.insert_account_row(conn, "u1")
    conn.execute("UPDATE payment_accounts SET balance = 1000 WHERE user_id = ?", ("u1",))
    conn.commit()

    init = initiate_transfer("u1", "Ram", "123456789012", "VPAY0000001", 3, "note", "USD")
    result = confirm_transfer("u1", init["transaction_id"])

    assert init["currency"] == "INR"
    assert init["original_currency"] == "USD"
    assert init["exchange_rate"] == 91.0
    assert init["inr_amount"] == 273.0
    assert result["currency"] == "INR"
    assert result["amount"] == 273.0

    txn = conn.execute(
        "SELECT original_amount, original_currency, exchange_rate, inr_amount, amount, currency, transaction_type, status FROM wallet_transactions WHERE transaction_id = ?",
        (init["transaction_id"],),
    ).fetchone()
    assert txn["original_amount"] == 3.0
    assert txn["original_currency"] == "USD"
    assert txn["exchange_rate"] == 91.0
    assert txn["inr_amount"] == 273.0
    assert txn["amount"] == 273.0
    assert txn["currency"] == "INR"


def test_no_payment_secret_fields_in_skill_params():
    from app.skills import SKILL_REGISTRY
    from app.security import FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS
    for skill in SKILL_REGISTRY:
        for tool in skill.ALLOWED_TOOLS:
            for pattern in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS:
                assert pattern not in tool.lower(), (
                    f"Skill {skill.NAME} allows tool '{tool}' which looks like a payment secret."
                )
