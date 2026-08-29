"""
Customer MCP tools.

Both tools here are self-only: they take requesting_user_id and nothing
else, always returning that user's own data. There is no resource ID
parameter at all, so there is no ID-manipulation surface for these two
tools — a user cannot pass someone else's identifier because none is accepted.
"""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_customer_details(requesting_user_id: str) -> dict:
        """Get the authenticated user's own profile (name, email)."""
        return data_layer.get_customer_details(requesting_user_id)

    @mcp.tool()
    def get_transaction_history(requesting_user_id: str) -> dict:
        """Get the authenticated user's own recent transactions."""
        return data_layer.get_transaction_history(requesting_user_id)
