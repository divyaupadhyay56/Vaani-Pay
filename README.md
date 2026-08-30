# Vaani Pay Assistant

A secure, real-time, **multi-user**, **bilingual (English + Hindi)** payments
support chatbot: users register/log in with their own account, then ask
about their own payments, orders, refunds, transactions, fraud risk, and
statistics — with strict per-user data isolation enforced at the MCP tool
layer, a real SQLite database, and a live WebSocket status stream showing
what the agent is doing.

This started as a static-demo hackathon build (hardcoded users, fixed
tokens, English-only) and has been upgraded to a database-driven,
multi-user, secure, bilingual platform **without changing the working
parts that already worked**: the WebSocket protocol, the MCP tool
architecture, and the core agent logic are the same shape as before —
only the data source and auth model underneath changed.

## Architecture

```
Browser (chat UI + login/signup/profile)
      │ REST (/auth, /users/me, /transactions)      │ WebSocket (/ws)
      ▼                                              ▼
FastAPI — auth endpoints, profile endpoints    FastAPI — WebSocket handler
      │                                              │
      ▼                                              ▼
app/auth.py  (register / login / sessions)     AI Agent (app/agent.py)
      │                                           NLU (Grok API) → intent + entities
      │                                           Tool selection → MCP tool
      ▼                                              │
app/db.py — SQLite                                   │ MCP (stdio transport)
  users, sessions, chat_history,                      ▼
  payments, orders, refunds, transactions        MCP Server (mcp_server/server.py)
      ▲                                           get_payment_status │ get_order_details
      │                                           get_refund_status │ get_customer_details
      └───────────── same DB, same ownership ──── get_transaction_history │ check_fraud_risk
                      checks on every query        get_payment_statistics
                                                        │
                                                        ▼
                                              mcp_server/data_layer.py
                                              — ownership check on every lookup,
                                                now backed by SQLite instead of JSON
```

## 1. Accounts & data privacy

- **Real accounts.** `POST /auth/register` creates a user row in SQLite
  with a securely hashed password (PBKDF2-HMAC-SHA256, per-password random
  salt, 260k iterations — see `app/security.py`). Plain-text passwords are
  never stored or logged anywhere.
- **Real login sessions.** `POST /auth/login` verifies credentials and
  issues an opaque, unguessable session token (`app/security.py`'s
  `generate_token()`, 256 bits of entropy) stored in the `sessions` table
  with an expiry (`SESSION_TTL_HOURS` in `.env`, default 24h). Expired or
  unknown tokens are rejected everywhere they're checked.
- **Every MCP tool that looks up a specific resource** (`get_payment_status`,
  `get_order_details`, `get_refund_status`, `check_fraud_risk`) requires a
  `requesting_user_id` parameter and verifies, in
  `mcp_server/data_layer.py`, that the resource actually belongs to that
  user — now via a parameterized SQL `WHERE ... AND user_id = ?` clause —
  before returning anything.
- If the resource belongs to someone else, or doesn't exist at all, the
  **same** generic response is returned in both cases:
  `"Access denied. You are not authorized to access this information."`
  Returning different messages for "not found" vs "someone else's data"
  would let a user enumerate valid IDs by observing which error they get —
  this closes that side channel.
- `requesting_user_id` is always the caller's **authenticated** identity
  (resolved once at WebSocket auth time / REST request time — see
  `app/auth.py`), never a value parsed from a chat message, URL parameter,
  or request body. `app/nlu.py`'s extraction schema has no `user_id`
  field at all, so there's no way for a message (even an adversarial one)
  to smuggle a different identity into a tool call.
- `get_customer_details`, `get_transaction_history`, and
  `get_payment_statistics` take **no resource ID at all** — they always
  return the caller's own data, so there's no ID-manipulation surface for
  these three tools whatsoever.
- **Account deletion** (`DELETE /users/me`) requires re-entering the
  current password as confirmation, then deletes the user row — `ON
  DELETE CASCADE` foreign keys remove all of that user's sessions, chat
  history, payments, orders, refunds, and transactions along with it.

Verify data isolation directly:
```bash
python3 test_offline.py
```
This runs real tool calls (against the actual MCP server, reading from
the real SQLite database) as two different demo users and asserts that
cross-user access attempts are denied, that each user's transaction
history contains only their own data, and that bilingual replies render
correctly.

## 2. Registration, login & account management

- `POST /auth/register` — name, email, password, optional phone, and a
  language preference. Passwords must be at least 8 characters and
  contain a mix of letters and numbers (`app/security.py`).
- `POST /auth/login` — returns a session token + user profile.
- `POST /auth/logout` — revokes the current session token server-side.
- `GET /users/me` / `PUT /users/me` — view/update profile (name, phone).
- `POST /users/me/change-password` — requires the current password;
  changing it invalidates all existing sessions (forces re-login
  everywhere) so a leaked old token stops working.
- `GET /users/me/preferences` / `PUT /users/me/preferences` — read/update
  the language preference (`en`/`hi`), persisted in the database so it
  survives logout/login.
- `DELETE /users/me` — permanent account deletion (password + explicit
  `confirm: true` required).

All of this is also reachable from the chat UI itself via the ⚙️ button
in the header (profile view/edit, language switcher, change password,
logout, delete account).

## 3. Chat UI

`static/index.html` — a single-page app:
- Login / Sign Up tabs shown before any chat is possible.
- Profile & Settings panel (name/phone editing, password change, language
  switcher, logout, account deletion with a confirmation step).
- Collapsible suggestion menu above the input, rendered from the same
  translated string dictionary as the rest of the UI.
- Chat bubbles, live status line, and header status indicator — unchanged
  from the original design.

## 4. Real-time communication

Chat still happens over a single WebSocket (`/ws`) — the protocol shape
is unchanged, only the auth token is now a real DB-backed session token
instead of a static value:
```
{"type": "auth", "token": "<session token from /auth/login>"}
      ↓
{"type": "auth_success", "user_id": "...", "name": "...", "language": "en"}
```
For every chat message, the server streams status events in this order,
then the final (localized) answer:
```
🔍 Understanding your request...
🔧 Checking payment information...
✓ Payment information retrieved
🤖 Generating response...
<final answer, in the user's selected language>
```
Every chat turn (both user and assistant messages) is also persisted to
the `chat_history` table (`app/main.py`'s `_persist_chat_turn`), scoped to
the authenticated user.

## 5. MCP-based architecture

`mcp_server/server.py` exposes exactly these 7 tools, split into domain
modules under `mcp_server/tools/`:

| Tool | File |
|---|---|
| `get_payment_status` | `payment_tools.py` |
| `check_fraud_risk` | `payment_tools.py` |
| `get_order_details` | `order_tools.py` |
| `get_refund_status` | `refund_tools.py` |
| `get_customer_details` | `customer_tools.py` |
| `get_transaction_history` | `customer_tools.py` |
| `get_payment_statistics` | `analytics_tools.py` |
| `get_balance` | `wallet_tools.py` |
| `add_money` | `wallet_tools.py` |
| `get_transactions` | `wallet_tools.py` |
| `validate_recipient` | `wallet_tools.py` |
| `create_transfer` | `wallet_tools.py` |
| `confirm_transfer` | `wallet_tools.py` |
| `cancel_transfer` | `wallet_tools.py` |
| `get_spending_summary` | `wallet_tools.py` |

All backed by the SQLite database (`mcp_server/data_layer.py` →
`app/db.py`) instead of static JSON. Tool signatures, the agent, and the
frontend are unchanged from the original design — only the data source
underneath `data_layer.py` changed, exactly as the original architecture
was designed to allow.

## 6. Bilingual support (English + Hindi)

- **UI strings**: `app/i18n.py`'s `UI_STRINGS` dictionary, served via
  `GET /i18n/{lang}`. The frontend fetches this once at load and on every
  language change, and applies it via `data-i18n`/`data-i18n-placeholder`
  attributes — no translated string is hardcoded in the HTML/JS.
- **AI assistant replies**: `app/i18n.py`'s `AGENT_STRINGS` (fixed
  messages like greetings) and `REPLY_TEMPLATES` (interpolated messages
  like payment status). `app/agent.py` renders every reply through these
  — nothing in the agent hardcodes English text directly.
- **NLU**: `app/nlu.py`'s prompt explicitly asks the Grok model to handle
  Hindi/English/mixed input and always translate to English internally
  for intent/entity extraction, so the assistant understands a question
  either way and replies in the user's preferred language.
- **Persistence**: the language preference lives on `users.language` in
  the database (set at signup, changeable any time via
  `PUT /users/me/preferences`), so it survives logout/login.
- **Dynamic switching**: changing language in Settings updates the UI
  immediately and reconnects the WebSocket so the very next chat reply
  comes back in the new language — no page reload needed.

## 7. Security requirements

| Requirement | Where it's implemented |
|---|---|
| Authentication | `app/auth.py` — password hashing, session tokens with expiry. WebSocket won't process any chat message, and no REST endpoint returns data, until a token verifies. |
| Authorization | `mcp_server/data_layer.py` — every resource lookup filters by `user_id` in the SQL itself. |
| User/session isolation | `app/session_store.py` — each WebSocket connection gets its own in-memory conversation state; `user_id`/`language` are set once at auth and never overwritten from chat text. |
| MCP-level permission checks | Enforced inside the MCP tools themselves (`mcp_server/tools/*.py` → `data_layer.py`), not just at the app's edge — see `diagnose_setup.py` and `test_offline.py`, which call the MCP server directly and confirm denial. |
| Input validation | `app/main.py` (Pydantic models on every REST body; message type/length checks on WebSocket) and `app/auth.py` (email format, password policy). |
| SQL injection protection | Every query in `app/db.py` / `mcp_server/data_layer.py` uses parameterized `?` placeholders — no string-built SQL anywhere. |
| Rate limiting | `app/main.py` — a per-IP rolling-window limiter on `/auth/register` and `/auth/login`. |
| Secure CORS | `app/main.py` — explicit allow-list (`CORS_ALLOWED_ORIGINS` in `.env`), defaults to localhost only; never `*` with credentials. |
| Secure password hashing | `app/security.py` — PBKDF2-HMAC-SHA256, random salt per password, 260k iterations. |
| Token expiration | `app/auth.py` — sessions expire after `SESSION_TTL_HOURS`; changing password invalidates all existing sessions. |
| Generic auth error messages | `app/auth.py` — identical error for "no such email" and "wrong password"; identical error for "not found" and "someone else's resource". |
| Secure error handling | `app/main.py`'s `_safe_error_message()` / global exception handler — unexpected errors are logged server-side in full, the client only ever receives a generic message. |
| Protection against ID manipulation | A user can type any `payment_id`/`order_id`/`refund_id` — the tool only ever returns data if it belongs to their authenticated account (SQL-enforced). |

## 8. Database schema

```
users            id, name, email, phone, password_hash, language, created_at, updated_at, last_login
sessions         token, user_id, created_at, expires_at
chat_history     id, user_id, conversation_id, role, message, timestamp
payments         payment_id, user_id, status, amount, method, failure_reason, date
orders           order_id, user_id, status, total, items (JSON), date
refunds          refund_id, user_id, payment_id, amount, status, date
transactions     txn_id, user_id, type, amount, status, date

-- Wallet: the real money-movement system (see section 9 below)
payment_accounts     id, user_id, payment_id, account_number, ifsc, balance, currency, status, created_at
wallet_transactions  id, transaction_id, sender_account_id, receiver_account_id, amount, transaction_type,
                     status, description, sender_name, receiver_name, recipient_account_number,
                     recipient_ifsc, failure_reason, created_at, updated_at
beneficiaries        id, user_id, recipient_name, account_number, ifsc, created_at
```
See `app/db.py`'s `SCHEMA` for the full DDL with foreign keys and indexes.

## 9. Wallet: Payment Accounts, Add Money & Send Money

Every registered user gets a real, usable wallet — not just a payment
history viewer. This is the single biggest addition on top of the
database/auth upgrade, and it's built as its own module
(`app/wallet.py`) that both the REST API and the AI/MCP tools call into,
so there is exactly one place that enforces the money-movement rules.

**Automatic account creation.** `POST /auth/register` creates the user
row AND a `payment_accounts` row in the *same* database transaction (see
`app/auth.py`'s `register()` calling `app/wallet.py`'s
`insert_account_row()`) — a user can never exist without a wallet, and a
wallet is never created as a separate, independently-failable step. Each
account gets:
- a unique **Payment ID** (`PAY...`, internal identifier),
- a unique 12-digit **account number**,
- a fixed **IFSC** (`VPAY0000001` — Vaani Pay is a single-branch virtual
  wallet, so every account shares one IFSC, the same way a real neobank's
  virtual accounts often do),
- a starting balance of **₹0**.

The registration response includes a `message: "Your payment account has
been successfully created."` confirmation plus the new account details,
shown to the user immediately (both in the API response and in the
sign-up screen's confirmation message).

**Add Money.** `POST /wallet/add-money` (or the "Add Money" button in the
Wallet screen, or asking the AI assistant "add ₹5,000 to my account") —
validates the amount (`> ₹0`, ≤ ₹2,00,000 per transaction —
`MAX_ADD_MONEY` in `app/wallet.py`), then atomically updates the balance
and appends a `CREDIT` row to `wallet_transactions`. There is no real
payment gateway wired in for the hackathon build — this is an explicitly
simulated top-up, matching the brief's "safe simulated funding flow"
requirement.

**Send Money — always a two-step confirm.** Neither the REST API nor the
AI assistant ever moves money in one call:
1. `POST /wallet/transfers` (`initiate_transfer` in `app/wallet.py`)
   validates the recipient and the sender's balance, and creates a
   `PENDING` `wallet_transactions` row — **no balance changes yet**. It
   returns a confirmation preview (recipient, masked account number,
   IFSC, amount, fee, total debit) — this is what renders the "Confirm
   Transfer" screen.
2. `POST /wallet/transfers/{id}/confirm` (`confirm_transfer`) is the
   *only* call that actually moves money. It re-validates the sender's
   balance and account status **at confirm time** (not just at initiate
   time, in case something changed in between — e.g. two transfers
   initiated back-to-back), then debits the sender and, if the recipient
   is a real Vaani Pay account, credits them, inside one atomic SQLite
   transaction guarded by a process-wide lock. If anything fails partway
   through, the whole thing rolls back — a transfer can never end up
   debited-but-not-credited.
3. `POST /wallet/transfers/{id}/cancel` cancels a still-`PENDING`
   transfer without touching any balance.

Sending to an account number that isn't in our system still succeeds (as
a simulated external transfer — the sender is debited, there's just no
Vaani Pay account to credit), matching the brief's "credit the
recipient's balance if the recipient exists in the simulated system"
requirement.

**Recipient validation.** `POST /wallet/validate-recipient`
(`validate_recipient`) checks: account number format (9–18 digits), IFSC
format (`^[A-Z]{4}0[A-Z0-9]{6}$`), that the IFSC matches the account
number if it's an internal account, and — critically — that the sender
isn't sending to their own account number. If only a recipient *name* is
given (no account number), it looks the name up in the caller's own
saved beneficiaries and resolves automatically if there's exactly one
match.

**Saved beneficiaries.** After a successful transfer, the UI offers "Save
this recipient?" — `POST /beneficiaries` stores it for the *authenticated
user only* (never global/shared), so next time the user (or the AI
assistant, when asked to "send ₹2,000 to Rahul") can resolve a transfer
by name alone.

**Transaction history & filters.** `GET /wallet/transactions?filter=...`
(`all` / `add_money` / `sent` / `received` / `failed` / `pending`) — all
computed live from `wallet_transactions`, never hardcoded. The Wallet
screen's History tab and the AI's "show my wallet transactions" /
"how much did I spend this month" both read from the exact same function
(`get_wallet_transactions` / `get_spending_summary` in `app/wallet.py`).

**Balance is always derived, never set directly.** There is intentionally
no `set_balance()` function anywhere in the codebase — the only ways a
balance changes are as a side effect of `add_money()` or
`confirm_transfer()`, both of which also append an immutable
`wallet_transactions` row in the same atomic step. The frontend only ever
displays whatever `GET /wallet/account` returns; it cannot influence it.

### Wallet security specifically

| Rule | How it's enforced |
|---|---|
| A user can never modify their own balance directly | No public function sets balance except as a side effect of Add Money / confirm_transfer, both of which are amount-validated and produce an audit row |
| A user can never modify another user's balance | Every wallet function takes the caller's authenticated `user_id` and looks up `payment_accounts` via `WHERE user_id = ?` — never via a client-supplied account id |
| A user can never confirm/cancel someone else's transfer | `confirm_transfer`/`cancel_transfer` verify the `PENDING` transaction's sender account belongs to the calling user, using the same generic "not found" response whether the transaction doesn't exist or belongs to someone else (verified in `test_offline.py` and `diagnose_setup.py`) |
| Self-transfers are blocked | `validate_recipient` compares the recipient account number against the sender's own before allowing a transfer to proceed |
| Amounts can't be manipulated in-flight | The amount used to actually debit/credit at `confirm_transfer` time is the one stored on the `PENDING` row created at `initiate_transfer` time — never re-read from the confirm request |
| The AI can't move money without explicit confirmation | `create_transfer`/`add_money` MCP tools never debit/credit by themselves; `app/agent.py`'s conversation state machine requires an explicit "yes" reply to a shown confirmation before calling `confirm_transfer` |
| Atomicity | `confirm_transfer` runs the balance check + both balance updates + status update inside one SQLite transaction (`app/db.py`'s `tx()`), plus a process-wide lock — see `app/wallet.py`'s module docstring |

## 10. Bilingual payment flow

The wallet is fully bilingual, using the same `app/i18n.py` mechanism as
the rest of the app — Add Money, Send Money (all three steps), the
confirmation screen, transaction statuses, and every AI response about
balance/transfers are all rendered through `t()`/`tpl()` with no
hardcoded English anywhere in `app/wallet.py`, `app/agent.py`, or
`static/index.html`'s wallet UI. For example, asking the AI *"Rahul ko
₹2,000 bhejo"* (Hindi/Hinglish) walks through the exact same
resolve → confirm → execute flow as the English version, with every
message — including the confirmation screen — rendered in Hindi.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your Grok API key (get one at https://console.x.ai)
```

The database is created (and, only if empty, seeded with two demo users —
see below) automatically on first run; no separate migration step is
required for local development. To create it explicitly ahead of time:
```bash
python3 -m app.db
```

Verify before touching the browser:
```bash
python3 diagnose_setup.py
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000**. Sign up for a new account, or log in with
one of the seeded demo accounts:

| Email | Password |
|---|---|
| `ramesh@example.com` | `Demo@1234` |
| `priya@example.com` | `Demo@1234` |

Then try the suggestion menu, ask questions like *"check payment status
pay_1001"* or *"मेरा भुगतान pay_1001 का स्टेटस क्या है?"*, switch
languages from Settings, or try signing in as one user and asking about
the other user's payment/order/refund IDs (`pay_1003`, `ord_2002`,
`rfnd_3002` belong to Priya) to see the access-denied response.

To try the wallet: open the 💰 Wallet button in the header. Both demo
accounts start with a balance (₹8,500 for Ramesh, ₹8,000 for Priya) and
one demo transfer already in their history. Try "Add Money", or "Send
Money" to the other demo account's account number (visible in their own
Wallet screen), or ask the AI assistant directly: *"what's my balance?"*,
*"add ₹5,000 to my account"*, *"send ₹2,000 to Priya Stores"* (it will
ask for her account number + IFSC the first time, then offer to save her
as a beneficiary after a successful transfer — after that, just her name
is enough), or *"Mera current balance kitna hai?"* in Hindi.


<img width="544" height="880" alt="image" src="https://github.com/user-attachments/assets/194e82d5-b20b-4027-8a58-f4bcaab5a18a" />

