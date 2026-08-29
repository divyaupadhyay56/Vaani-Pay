"""Analytics MCP tools. Self-only, same reasoning as customer_tools.py."""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_payment_statistics(requesting_user_id: str) -> dict:
        """Get summary payment statistics (count, total, average, success rate) for the authenticated user's own account."""
        return data_layer.get_payment_statistics(requesting_user_id)
