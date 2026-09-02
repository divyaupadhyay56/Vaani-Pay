

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_payment_status(payment_id: str, requesting_user_id: str) -> dict:
        return data_layer.get_payment_status(payment_id, requesting_user_id)

    @mcp.tool()
    def check_fraud_risk(payment_id: str, requesting_user_id: str) -> dict:
        return data_layer.check_fraud_risk(payment_id, requesting_user_id)
