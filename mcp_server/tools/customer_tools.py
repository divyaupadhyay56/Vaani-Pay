from mcp_server import data_layer
def register(mcp):
    @mcp.tool()
    def get_customer_details(requesting_user_id: str) -> dict:
        return data_layer.get_customer_details(requesting_user_id)

    @mcp.tool()
    def get_transaction_history(requesting_user_id: str) -> dict:
        return data_layer.get_transaction_history(requesting_user_id)
