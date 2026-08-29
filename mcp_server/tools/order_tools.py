"""Order MCP tools. See payment_tools.py for the ownership-check pattern used throughout."""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_order_details(order_id: str, requesting_user_id: str) -> dict:
        """Get order status, items, and total. Only returns data if the order belongs to requesting_user_id."""
        return data_layer.get_order_details(order_id, requesting_user_id)
