
from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_payment_statistics(requesting_user_id: str) -> dict:
        return data_layer.get_payment_statistics(requesting_user_id)
