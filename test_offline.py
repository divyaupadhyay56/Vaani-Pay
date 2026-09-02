
import asyncio
import re

from app import db, wallet
from app.nlu import NLUResult
from app.agent import handle_message, ACCESS_DENIED_MESSAGE
from app.mcp_client import mcp_client

db.init_db() 
_AMOUNT_RE = re.compile(r"₹?([\d,]+(?:\.\d+)?)")


def _amount(message: str):
    match = _AMOUNT_RE.search(message.replace(",", ""))
    return match.group(1) if match else None


def fake_understand(message, conversation_context=""):
    m = message.lower()
    if "fraud" in m:
        pid = [w for w in message.split() if w.startswith("pay_")]
        return NLUResult(message, "check_fraud_risk", {"payment_id": pid[0] if pid else None}, 0.9)
    if "pay_" in m and "fail" in m:
        pid = [w for w in message.split() if w.startswith("pay_")]
        return NLUResult(message, "check_payment_failure", {"payment_id": pid[0] if pid else None}, 0.9)
    if "pay_" in m:
        pid = [w for w in message.split() if w.startswith("pay_")]
        return NLUResult(message, "check_payment_status", {"payment_id": pid[0] if pid else None}, 0.9)
    if "check payment status" in m:
        return NLUResult(message, "check_payment_status", {}, 0.9)
    if "why did my payment fail" in m:
        return NLUResult(message, "check_payment_failure", {}, 0.9)
    if "refund" in m:
        rid = [w for w in message.split() if w.startswith("rfnd_")]
        return NLUResult(message, "check_refund_status", {"refund_id": rid[0] if rid else None}, 0.9)
    if "order" in m:
        oid = [w for w in message.split() if w.startswith("ord_")]
        return NLUResult(message, "check_order_details", {"order_id": oid[0] if oid else None}, 0.9)
    if "wallet" in m or "wallet transactions" in m:
        return NLUResult(message, "view_wallet_transactions", {}, 0.9)
    if "spend" in m or "spent" in m:
        return NLUResult(message, "spending_summary", {}, 0.9)
    if "transaction" in m:
        return NLUResult(message, "view_transactions", {}, 0.9)
    if "statistics" in m:
        return NLUResult(message, "payment_statistics", {}, 0.9)
    if m.strip() in ("balance", "what's my balance", "check balance", "my balance"):
        return NLUResult(message, "check_balance", {}, 0.9)
    if m.startswith("add ") and ("money" in m or "₹" in message or _amount(message)):
        return NLUResult(message, "add_money", {"amount": _amount(message)}, 0.9)
    if m.startswith("send ") or "send money" in m:
        amt = _amount(message)
        name_match = re.search(r"\bto\s+([A-Za-z ]+)", message)
        return NLUResult(message, "send_money", {
            "amount": amt, "recipient_name": name_match.group(1).strip() if name_match else None,
        }, 0.9)
    if "hello" in m or "hi" == m.strip():
        return NLUResult(message, "greeting", {}, 0.95)
    return NLUResult(message, "fallback_human_handoff", {}, 0.2)


async def run():
    user1_session = {"authenticated": True, "user_id": "user_1", "user_name": "Ramesh Traders", "language": "en",
                      "pending_action": None, "pending_payload": {}, "history": []}
    user2_session = {"authenticated": True, "user_id": "user_2", "user_name": "Priya Stores", "language": "en",
                      "pending_action": None, "pending_payload": {}, "history": []}
    user1_session_hi = {"authenticated": True, "user_id": "user_1", "user_name": "Ramesh Traders", "language": "hi",
                         "pending_action": None, "pending_payload": {}, "history": []}

    async def turn(session, message, label):
        nlu = fake_understand(message)
        reply = await handle_message(nlu, session)
        print(f"{label}: {message!r} -> {reply}")
        return reply

    print("=== Basic tool calls (each user, own data) ===")
    await turn(user1_session, "check payment status pay_1001", "user_1")
    await turn(user1_session, "why did payment pay_1002 fail", "user_1")
    await turn(user1_session, "check refund status rfnd_3001", "user_1")
    await turn(user1_session, "check order details ord_2001", "user_1")
    r_fraud = await turn(user1_session, "check fraud risk for pay_1002", "user_1")
    assert "risk" in r_fraud.lower(), f"Fraud tool didn't run as expected: {r_fraud}"
    await turn(user1_session, "view my transactions", "user_1")
    await turn(user1_session, "show my payment statistics", "user_1")

    print("\n=== CRITICAL: user_1 attempting to access user_2's data ===")
    r1 = await turn(user1_session, "check payment status pay_1003", "user_1 (user_2's payment)")
    assert r1 == ACCESS_DENIED_MESSAGE, f"SECURITY FAILURE: expected access denied, got: {r1}"
    r2 = await turn(user1_session, "check refund status rfnd_3002", "user_1 (user_2's refund)")
    assert r2 == ACCESS_DENIED_MESSAGE, f"SECURITY FAILURE: expected access denied, got: {r2}"
    r3 = await turn(user1_session, "check order details ord_2002", "user_1 (user_2's order)")
    assert r3 == ACCESS_DENIED_MESSAGE, f"SECURITY FAILURE: expected access denied, got: {r3}"
    print("✅ All cross-user access attempts correctly denied.")

    print("\n=== user_2 confirms they see ONLY their own data ===")
    r4 = await turn(user2_session, "view my transactions", "user_2")
    assert "pay_1003" in r4 and "pay_1001" not in r4, "SECURITY FAILURE: user_2 saw user_1's data"
    print("✅ user_2's transaction history contains only user_2's transactions.")

    print("\n=== Missing ID -> asks for it, then continues correctly ===")
    r5 = await turn(user1_session, "check payment status", "user_1 (no ID given)")
    assert r5 == "Sure! Please enter your payment ID."
    r6 = await turn(user1_session, "pay_1001", "user_1 (providing the ID)")
    assert "success" in r6
    print("✅ Pending-ID follow-up flow works correctly.")

    print("\n=== Bilingual replies (same data, Hindi language preference) ===")
    r_hi = await turn(user1_session_hi, "check payment status pay_1001", "user_1 (hi)")
    assert "भुगतान" in r_hi, f"Expected a Hindi reply, got: {r_hi}"
    print("✅ Hindi-language reply rendered correctly.")

    print("\n=== Wallet: balance, Add Money (ask -> confirm -> execute) ===")
    balance_before = wallet.get_balance("user_1")
    r7 = await turn(user1_session, "balance", "user_1")
    assert "₹" in r7

    r8 = await turn(user1_session, "add money", "user_1 (no amount)")
    assert "how much" in r8.lower()
    r9 = await turn(user1_session, "500", "user_1 (giving amount)")
    assert "confirm" in r9.lower()
    r10 = await turn(user1_session, "yes", "user_1 (confirming)")
    assert "added" in r10.lower() or "✅" in r10
    assert wallet.get_balance("user_1") == balance_before + 500, "Add Money didn't update the balance correctly"
    print("✅ Add Money ask->confirm->execute flow works and balance updated correctly.")

    print("\n=== Wallet: Add Money cancellation doesn't touch the balance ===")
    balance_before_cancel = wallet.get_balance("user_1")
    await turn(user1_session, "add 200", "user_1")
    await turn(user1_session, "no", "user_1 (cancelling)")
    assert wallet.get_balance("user_1") == balance_before_cancel, "Cancelled Add Money should not change the balance"
    print("✅ Cancelling Add Money leaves the balance untouched.")

    print("\n=== Wallet: Send Money (initiate -> confirm), atomic balance update ===")
    acc1_before = wallet.get_balance("user_1")
    acc2_before = wallet.get_balance("user_2")
    acc2 = wallet.get_account("user_2")
    r11 = await turn(user1_session, f"send 300 to Priya Stores", "user_1")
    assert "account number" in r11.lower()  # asked for account details since name-only isn't a saved beneficiary yet
    r12 = await turn(user1_session, f"{acc2['account_number']} {acc2['ifsc']}", "user_1 (account details)")
    assert "confirm" in r12.lower() and "300" in r12
    r13 = await turn(user1_session, "yes", "user_1 (confirming transfer)")
    assert "successful" in r13.lower() or "✅" in r13
    assert wallet.get_balance("user_1") == acc1_before - 300, "Sender balance not debited correctly"
    assert wallet.get_balance("user_2") == acc2_before + 300, "Receiver balance not credited correctly"
    print("✅ Send Money transferred exactly ₹300 atomically between the two accounts.")

    print("\n=== SECURITY: user_2 cannot confirm a transfer user_1 initiated ===")
    acc2_for_test = wallet.get_account("user_2")
    initiated = wallet.initiate_transfer("user_1", "Priya Stores", acc2_for_test["account_number"], acc2_for_test["ifsc"], 10)
    try:
        wallet.confirm_transfer("user_2", initiated["transaction_id"])
        raise AssertionError("SECURITY FAILURE: user_2 was able to confirm user_1's pending transfer!")
    except wallet.WalletError as e:
        assert e.code == "not_found"
    wallet.cancel_transfer("user_1", initiated["transaction_id"])
    print("✅ Cross-user transfer confirmation correctly blocked.")

    print("\n=== SECURITY: self-transfer is blocked ===")
    acc1_for_test = wallet.get_account("user_1")
    try:
        wallet.initiate_transfer("user_1", "Myself", acc1_for_test["account_number"], acc1_for_test["ifsc"], 10)
        raise AssertionError("SECURITY FAILURE: self-transfer was allowed!")
    except wallet.WalletError:
        pass
    print("✅ Self-transfer correctly blocked.")

    print("\n=== Wallet: transaction history + spending summary ===")
    r14 = await turn(user1_session, "show my wallet transactions", "user_1")
    assert "Priya Stores" in r14
    r15 = await turn(user1_session, "how much have I spent this month", "user_1")
    assert "₹" in r15
    print("✅ Wallet transaction history and spending summary render correctly.")

    await mcp_client.close()
    print("\nAll turns completed. Security checks passed.")


asyncio.run(run())
