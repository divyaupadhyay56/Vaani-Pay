"""
MCP server for Vaani Pay — Agentic Payment Platform.

Tools:
  Legacy (mock gateway demo): get_payment_status, get_order_details,
    get_refund_status, get_customer_details, get_transaction_history,
    check_fraud_risk, get_payment_statistics

  Wallet (real money-movement): get_balance, add_money, get_transactions,
    validate_recipient, create_transfer, confirm_transfer, cancel_transfer,
    get_spending_summary

  Fraud/Risk Engine: analyse_transfer_risk

Every tool requires requesting_user_id and enforces ownership at
mcp_server/data_layer.py and app/wallet.py.
"""

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import (
    analytics_tools,
    customer_tools,
    fraud_tools,
    order_tools,
    payment_tools,
    refund_tools,
    wallet_tools,
)

mcp = FastMCP("vaani-pay")

payment_tools.register(mcp)
order_tools.register(mcp)
refund_tools.register(mcp)
customer_tools.register(mcp)
analytics_tools.register(mcp)
wallet_tools.register(mcp)
fraud_tools.register(mcp)

if __name__ == "__main__":
    mcp.run(transport="stdio")
