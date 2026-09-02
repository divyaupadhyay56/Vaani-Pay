from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_balance(requesting_user_id: str) -> dict:
        return data_layer.get_balance(requesting_user_id)

    @mcp.tool()
    def add_money(requesting_user_id: str, amount: float, description: str = "") -> dict:
        return data_layer.add_money(requesting_user_id, amount, description or None)

    @mcp.tool()
    def get_transactions(requesting_user_id: str, filter: str = "all") -> dict:
        return data_layer.get_wallet_transactions(requesting_user_id, filter)

    @mcp.tool()
    def validate_recipient(requesting_user_id: str, recipient_name: str, account_number: str = "", ifsc: str = "") -> dict:
        return data_layer.validate_recipient(requesting_user_id, recipient_name, account_number or None, ifsc or None)

    @mcp.tool()
    def create_transfer(requesting_user_id: str, recipient_name: str, account_number: str, ifsc: str, amount: float, note: str = "", currency: str = "INR") -> dict:
        return data_layer.create_transfer(requesting_user_id, recipient_name, account_number, ifsc, amount, note or None, currency)

    @mcp.tool()
    def confirm_transfer(requesting_user_id: str, transaction_id: str) -> dict:
        return data_layer.confirm_transfer(requesting_user_id, transaction_id)

    @mcp.tool()
    def cancel_transfer(requesting_user_id: str, transaction_id: str) -> dict:
        return data_layer.cancel_transfer(requesting_user_id, transaction_id)

    @mcp.tool()
    def get_spending_summary(requesting_user_id: str, period: str = "month") -> dict:
        return data_layer.get_spending_summary(requesting_user_id, period)
