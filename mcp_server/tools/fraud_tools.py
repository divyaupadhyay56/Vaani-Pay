from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def analyse_transfer_risk(
        requesting_user_id: str,
        amount: float,
        recipient_account_number: str,
        recipient_ifsc: str,
    ) -> dict:
        return data_layer.analyse_transfer_risk(
            requesting_user_id, amount, recipient_account_number, recipient_ifsc
        )
