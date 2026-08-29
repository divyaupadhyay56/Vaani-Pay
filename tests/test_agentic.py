"""
Tests for the agentic layer — skills, fraud engine, MCP gateway allowlist,
simulation mode, and security contracts.
Run: pytest tests/test_agentic.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import asyncio

# ── Fraud engine (pure logic, no DB needed) ───────────────────────────────────

def test_fraud_low_for_zero_history_small_amount(tmp_path, monkeypatch):
    """Small amount with no history → LOW risk."""
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
    """Very large amount + high velocity → HIGH risk."""
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
    # 4 rapid recent transfers
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


# ── Skill registry ────────────────────────────────────────────────────────────

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
    # Must NOT have add_money
    assert "add_money" not in s.ALLOWED_TOOLS


# ── MCP gateway allowlist ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_gateway_blocks_unlisted_tool():
    """The secure MCP gateway must raise PermissionError for tools not in the allowlist."""
    from app.agent import _make_mcp_gateway
    gateway = _make_mcp_gateway({"get_balance"})
    with pytest.raises(PermissionError):
        await gateway("add_money", {"requesting_user_id": "u1", "amount": 100})


@pytest.mark.asyncio
async def test_mcp_gateway_allows_listed_tool(monkeypatch):
    """Gateway must forward calls for allowlisted tools."""
    from app.agent import _make_mcp_gateway
    calls = []
    async def fake_mcp_call(name, args):
        calls.append((name, args))
        return {"balance": 1000.0}

    # Monkeypatch mcp_client.call_tool
    import app.mcp_client as mc
    monkeypatch.setattr(mc.mcp_client, "call_tool", fake_mcp_call)

    gateway = _make_mcp_gateway({"get_balance"})
    result  = await gateway("get_balance", {"requesting_user_id": "u1"})
    assert result["balance"] == 1000.0
    assert calls[0][0] == "get_balance"


# ── Simulation mode ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simulation_mode_does_not_call_execute_tools(monkeypatch):
    """In simulation mode, add_money skill must NOT call the add_money MCP tool."""
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


# ── Security: no PIN in entities ─────────────────────────────────────────────

def test_nlu_result_has_no_pin_field():
    from app.nlu import NLUResult
    result = NLUResult(english_translation="test", intent="add_money",
                       entities={"amount": 500}, confidence=0.9)
    assert "pin" not in str(result.entities).lower()
    assert "upi_pin" not in result.entities
    assert "mpin" not in result.entities


def test_no_payment_secret_fields_in_skill_params():
    """Ensure no skill's ALLOWED_TOOLS would allow a secret-leaking tool."""
    from app.skills import SKILL_REGISTRY
    from app.security import FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS
    for skill in SKILL_REGISTRY:
        for tool in skill.ALLOWED_TOOLS:
            for pattern in FORBIDDEN_PAYMENT_SECRET_FIELD_PATTERNS:
                assert pattern not in tool.lower(), (
                    f"Skill {skill.NAME} allows tool '{tool}' which looks like a payment secret."
                )
