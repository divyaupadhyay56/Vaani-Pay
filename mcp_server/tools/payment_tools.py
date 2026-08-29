"""
Payment MCP tools.

SECURITY: every tool requires requesting_user_id — the caller's
authenticated identity — and passes it straight into data_layer, which
enforces ownership before returning anything. The MCP tool layer itself
adds no logic beyond this pass-through; the point is that a permission
check happens on every single call, not just at the app's edge.
"""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_payment_status(payment_id: str, requesting_user_id: str) -> dict:
        """Get the status, amount, method, and failure reason (if any) for a payment. Only returns data if the payment belongs to requesting_user_id."""
        return data_layer.get_payment_status(payment_id, requesting_user_id)

    @mcp.tool()
    def check_fraud_risk(payment_id: str, requesting_user_id: str) -> dict:
        """Rule-based fraud risk check for a payment. Only returns data if the payment belongs to requesting_user_id."""
        return data_layer.check_fraud_risk(payment_id, requesting_user_id)
