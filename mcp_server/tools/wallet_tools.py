"""
Wallet MCP tools — balance, Add Money, and Send Money (as a two-step
initiate/confirm flow), plus recipient validation and transaction history.

SECURITY: every tool takes requesting_user_id (the caller's authenticated
identity) and passes it straight to app/wallet.py via
mcp_server/data_layer.py, which enforces that a user can only ever read or
move money for their OWN account — never anyone else's, regardless of
what account/transaction identifiers appear elsewhere in the call. See
app/wallet.py's module docstring for the full ownership-enforcement design.

The AI must never move money in a single step: create_transfer only
creates a PENDING transaction (no balance change) and returns a
confirmation preview; only a subsequent, explicit confirm_transfer call
(after the user has been shown that preview and has agreed) actually
debits/credits anything. This mirrors the same two-step confirmation the
web UI's own Send Money screen uses, so the AI assistant can never
transfer money the user hasn't explicitly confirmed.

UPI PIN POLICY: none of these tools accept, and the AI must never ask
for, a UPI PIN, card PIN, or any other payment-method authentication
secret — for either add_money or the transfer tools. If a real
UPI-capable gateway is wired in later, that authentication happens
entirely inside the gateway's own hosted UI; the AI's role stops at
"here's the amount/recipient, would you like to proceed" and resumes
only after the provider returns a verified result.
"""

from mcp_server import data_layer


def register(mcp):
    @mcp.tool()
    def get_balance(requesting_user_id: str) -> dict:
        """Get the authenticated user's own wallet balance and currency."""
        return data_layer.get_balance(requesting_user_id)

    @mcp.tool()
    def add_money(requesting_user_id: str, amount: float, description: str = "") -> dict:
        """Add money to the authenticated user's own wallet. Validates the amount server-side (must be > 0 and within the per-transaction limit). Only ever affects the caller's own account."""
        return data_layer.add_money(requesting_user_id, amount, description or None)

    @mcp.tool()
    def get_transactions(requesting_user_id: str, filter: str = "all") -> dict:
        """Get the authenticated user's own wallet transaction history. filter can be: all, add_money, sent, received, failed, pending."""
        return data_layer.get_wallet_transactions(requesting_user_id, filter)

    @mcp.tool()
    def validate_recipient(requesting_user_id: str, recipient_name: str, account_number: str = "", ifsc: str = "") -> dict:
        """Resolve/validate a transfer recipient before sending money. If account_number is omitted, looks the name up in the caller's OWN saved beneficiaries. Never returns or searches another user's beneficiaries."""
        return data_layer.validate_recipient(requesting_user_id, recipient_name, account_number or None, ifsc or None)

    @mcp.tool()
    def create_transfer(requesting_user_id: str, recipient_name: str, account_number: str, ifsc: str, amount: float, note: str = "") -> dict:
        """Initiate a money transfer FROM the authenticated user's own wallet — creates a PENDING transaction and returns a confirmation preview (recipient, amount, fee, total debit). Does NOT move any money yet; the user must confirm via confirm_transfer before anything is debited."""
        return data_layer.create_transfer(requesting_user_id, recipient_name, account_number, ifsc, amount, note or None)

    @mcp.tool()
    def confirm_transfer(requesting_user_id: str, transaction_id: str) -> dict:
        """Confirm and execute a previously-initiated PENDING transfer, after the user has explicitly agreed to the confirmation preview. Only succeeds if the PENDING transaction belongs to the authenticated user as the sender. Actually moves the money, atomically."""
        return data_layer.confirm_transfer(requesting_user_id, transaction_id)

    @mcp.tool()
    def cancel_transfer(requesting_user_id: str, transaction_id: str) -> dict:
        """Cancel a previously-initiated PENDING transfer without moving any money. Only succeeds if the PENDING transaction belongs to the authenticated user as the sender."""
        return data_layer.cancel_transfer(requesting_user_id, transaction_id)

    @mcp.tool()
    def get_spending_summary(requesting_user_id: str, period: str = "month") -> dict:
        """Get a read-only summary (total spent, transaction count) of the authenticated user's own outgoing transfers for the given period. Currently only 'month' (the current calendar month) is supported."""
        return data_layer.get_spending_summary(requesting_user_id, period)
