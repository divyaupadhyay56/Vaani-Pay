"""Refund MCP tools. See payment_tools.py for the ownership-check pattern used throughout."""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_refund_status(refund_id: str, requesting_user_id: str) -> dict:
        """Get refund amount and status. Only returns data if the refund belongs to requesting_user_id."""
        return data_layer.get_refund_status(refund_id, requesting_user_id)
