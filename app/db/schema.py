SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    password_hash   TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'en',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS chat_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    message         TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id, conversation_id);

CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    amount          REAL NOT NULL,
    method          TEXT,
    failure_reason  TEXT,
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);

CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    total           REAL NOT NULL,
    items           TEXT NOT NULL,  -- JSON-encoded list of strings
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payment_id      TEXT,
    amount          REAL NOT NULL,
    status          TEXT NOT NULL,
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_refunds_user ON refunds(user_id);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id          TEXT NOT NULL,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    amount          REAL NOT NULL,
    status          TEXT NOT NULL,
    date            TEXT,
    PRIMARY KEY (txn_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);

-- ================== Wallet: real money-movement system ==================
-- (payment_accounts / wallet_transactions / beneficiaries)
-- Separate from the legacy payments/orders/refunds/transactions tables
-- above, which remain untouched (existing mock "payment gateway" demo
-- data + tools). This is the new, real ledger: every rupee added or
-- transferred through Add Money / Send Money goes through here, and the
-- balance is always DERIVED from this ledger by the backend — never
-- written directly by the frontend or the AI.

CREATE TABLE IF NOT EXISTS payment_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    payment_id      TEXT NOT NULL UNIQUE,
    account_number  TEXT NOT NULL UNIQUE,
    ifsc            TEXT NOT NULL,
    balance         REAL NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'INR',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payment_accounts_number ON payment_accounts(account_number);

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id              TEXT NOT NULL UNIQUE,
    sender_account_id           INTEGER REFERENCES payment_accounts(id) ON DELETE SET NULL,
    receiver_account_id         INTEGER REFERENCES payment_accounts(id) ON DELETE SET NULL,
    amount                      REAL NOT NULL,
    currency                    TEXT NOT NULL DEFAULT 'INR',
    original_amount             REAL,
    original_currency           TEXT,
    exchange_rate               REAL,
    inr_amount                  REAL,
    transaction_type            TEXT NOT NULL,  -- CREDIT | TRANSFER_OUT | TRANSFER_IN
    status                      TEXT NOT NULL,  -- PENDING | SUCCESS | FAILED | CANCELLED
    description                 TEXT,
    -- Snapshots taken at transaction time, so a party's transaction
    -- history stays meaningful even if the other account is later
    -- deleted (see ON DELETE SET NULL above), and so external/simulated
    -- recipients (not in our system) still show a clear name/number.
    sender_name                 TEXT,
    receiver_name                TEXT,
    recipient_account_number    TEXT,
    recipient_ifsc               TEXT,
    failure_reason               TEXT,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallet_txn_sender ON wallet_transactions(sender_account_id);
CREATE INDEX IF NOT EXISTS idx_wallet_txn_receiver ON wallet_transactions(receiver_account_id);

CREATE TABLE IF NOT EXISTS beneficiaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_name  TEXT NOT NULL,
    account_number  TEXT NOT NULL,
    ifsc            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(user_id, account_number)
);
CREATE INDEX IF NOT EXISTS idx_beneficiaries_user ON beneficiaries(user_id);
"""
