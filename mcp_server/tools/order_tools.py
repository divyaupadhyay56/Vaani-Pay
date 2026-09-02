
from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_order_details(order_id: str, requesting_user_id: str) -> dict:
        return data_layer.get_order_details(order_id, requesting_user_id)
