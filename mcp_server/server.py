
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
