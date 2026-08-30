
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.6")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")


def check_grok() -> bool:
    print("=== 1. Grok API ===")
    if not GROK_API_KEY:
        print("❌ GROK_API_KEY is not set in .env")
        print("   Fix: get a key at https://console.x.ai")
        print("        then add GROK_API_KEY=... to your .env file")
        return False

    print(f"✅ GROK_API_KEY found (length: {len(GROK_API_KEY)} chars)")

    try:
        from openai import OpenAI
    except ImportError:
        print("❌ openai package not installed. Run: pip install -r requirements.txt")
        return False

    try:
        client = OpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)
        response = client.chat.completions.create(
            model=GROK_MODEL,
            messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
            max_tokens=5,
        )
        text = response.choices[0].message.content.strip()
        print(f"✅ Test call to model '{GROK_MODEL}' succeeded: {text!r}")
    except Exception as e:
        print(f"❌ Grok API call failed: {e}")
        print("   Check that the key is valid and the model name is correct")
        print("   (see https://docs.x.ai for current model names).")
        return False

    return True


def check_database() -> bool:
    print("\n=== 2. Database ===")
    try:
        from app import db
        db.init_db()
        conn = db.get_connection()
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        print(f"✅ Database ready at {db.DB_PATH} — {count} user(s) on record.")
        return True
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False


def check_wallet() -> bool:
    print("\n=== 3. Wallet (payment accounts, Add Money, Send Money) ===")
    try:
        from app import db, wallet
        db.init_db()
        conn = db.get_connection()
        count = conn.execute("SELECT COUNT(*) AS c FROM payment_accounts").fetchone()["c"]
        print(f"✅ {count} payment account(s) on record.")

        u1 = conn.execute("SELECT id FROM users WHERE email = 'ramesh@example.com'").fetchone()
        if u1 is None:
            print("⚠️  Demo user 'ramesh@example.com' not found — skipping the live wallet checks (this is fine on an existing, non-fresh database).")
            return True
        u1 = u1["id"]

        account = wallet.get_account(u1)
        print(f"✅ Demo user's wallet: payment_id={account['payment_id']}, balance=₹{account['balance']:.2f}")

        result = wallet.add_money(u1, 1, "diagnose_setup.py test top-up")
        print(f"✅ Add Money test succeeded: transaction {result['transaction_id']}, new balance ₹{result['balance']:.2f}")

        u2 = conn.execute("SELECT id FROM users WHERE email = 'priya@example.com'").fetchone()
        if u2 is not None:
            try:
                wallet.initiate_transfer(u1, "Self", account["account_number"], account["ifsc"], 1)
                print("❌ SECURITY ISSUE: self-transfer was not blocked!")
                return False
            except wallet.WalletError:
                print("✅ Self-transfer correctly blocked.")

            acc2 = wallet.get_account(u2["id"])
            pending = wallet.initiate_transfer(u1, "Priya Stores", acc2["account_number"], acc2["ifsc"], 1)
            try:
                wallet.confirm_transfer(u2["id"], pending["transaction_id"])
                print("❌ SECURITY ISSUE: a different user was able to confirm this transfer!")
                return False
            except wallet.WalletError:
                print("✅ Cross-user transfer confirmation correctly blocked.")
            wallet.cancel_transfer(u1, pending["transaction_id"])

        return True
    except Exception as e:
        print(f"❌ Wallet check failed: {e}")
        return False


async def check_mcp_server() -> bool:
    print("\n=== 4. MCP Server ===")
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print("❌ mcp package not installed. Run: pip install -r requirements.txt")
        return False

    try:
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"✅ MCP server started and connected — {len(tools.tools)} tools registered:")
                for t in tools.tools:
                    print(f"   - {t.name}")

                result = await session.call_tool(
                    "get_payment_status", {"payment_id": "pay_1001", "requesting_user_id": "user_1"}
                )
                print(f"✅ Test tool call succeeded: {result.content[0].text[:120]}...")

                denied = await session.call_tool(
                    "get_payment_status", {"payment_id": "pay_1003", "requesting_user_id": "user_1"}
                )
                if "access_denied" in denied.content[0].text:
                    print("✅ Cross-user access control verified: unauthorized access correctly denied.")
                else:
                    print("❌ SECURITY ISSUE: cross-user access was not denied as expected!")
                    return False

                balance = await session.call_tool("get_balance", {"requesting_user_id": "user_1"})
                print(f"✅ Wallet MCP tool call succeeded: {balance.content[0].text[:120]}...")
        return True
    except Exception as e:
        print(f"❌ MCP server failed to start or respond: {e}")
        print("   Try running it standalone to see the full error:")
        print("     python3 -m mcp_server.server")
        return False


def main():
    grok_ok = check_grok()
    db_ok = check_database()
    wallet_ok = check_wallet()
    mcp_ok = asyncio.run(check_mcp_server())

    print("\n=== Summary ===")
    if grok_ok and db_ok and wallet_ok and mcp_ok:
        print("✅ Everything checks out. If the web UI still fails, restart uvicorn")
        print("   (make sure you run it from THIS SAME folder) and check its terminal output.")
    else:
        print("❌ Fix the ❌ items above, then re-run this script.")
        sys.exit(1)


if __name__ == "__main__":
    main()
