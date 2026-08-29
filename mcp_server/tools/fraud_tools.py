"""
Fraud risk MCP tools — real-time and historical risk analysis.

Security: requesting_user_id is always the authenticated sender.
The LLM may only narrate results; it never calculates risk itself.
"""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def analyse_transfer_risk(
        requesting_user_id: str,
        amount: float,
        recipient_account_number: str,
        recipient_ifsc: str,
    ) -> dict:
        """
        Analyse fraud/anomaly risk for a proposed transfer using the
        statistical risk engine. Returns risk_level (LOW/MEDIUM/HIGH),
        risk_score (0–1), reasons, and a block flag. The LLM must not
        invent or modify these values.
        """
        return data_layer.analyse_transfer_risk(
            requesting_user_id, amount, recipient_account_number, recipient_ifsc
        )
