# Vaani Pay Assistant

1. What is Vaani Pay?

Technical Explanation

Vaani Pay is a secure, real-time, multi-user, bilingual AI payment assistant.

The system combines:

FastAPI — backend REST APIs and WebSocket handling

WebSockets — real-time chat and agent-status streaming

Grok API — Natural Language Understanding (NLU)

MCP (Model Context Protocol) — controlled access to payment and wallet tools

SQLite — persistent user, payment, wallet, and transaction data

Authentication + authorization — secure user/session management

i18n — English and Hindi support

The key architectural idea is:

User
  ↓
Web UI
  ↓
REST / WebSocket
  ↓
FastAPI
  ↓
AI Agent
  ↓
Grok NLU
  ↓
Intent + Entities
  ↓
MCP Tool
  ↓
Authorization / Ownership Check
  ↓
SQLite
  ↓
Result
  ↓
AI Response
  ↓
WebSocket
  ↓
User

Simple Explanation

Think of Vaani Pay as ChatGPT for payments.

You can type:

"Mera payment pay_1001 ka status kya hai?"

The AI understands your question, checks your own payment information, and replies in Hindi/English.

For sensitive actions such as sending money, the AI first prepares the transaction and asks you to confirm it.

2. High-Level Architecture

                         Browser
                  ┌──────────────────┐
                  │ Login / Chat /   │
                  │ Wallet / Profile │
                  └────────┬─────────┘
                           │
             ┌─────────────┴─────────────┐
             │                           │
           REST                      WebSocket
             │                           │
             ▼                           ▼
      ┌──────────────┐            ┌──────────────┐
      │   FastAPI    │            │ WebSocket    │
      │ Auth / APIs  │            │ Handler      │
      └──────┬───────┘            └──────┬───────┘
             │                           │
             ▼                           ▼
      ┌──────────────┐            ┌──────────────┐
      │    SQLite    │            │   AI Agent   │
      └──────────────┘            └──────┬───────┘
                                         │
                                    Grok NLU
                                         │
                                  Intent + Entities
                                         │
                                         ▼
                                  ┌──────────────┐
                                  │ MCP Server   │
                                  └──────┬───────┘
                                         │
                                         ▼
                                  ┌──────────────┐
                                  │ Data Layer   │
                                  │ Ownership    │
                                  │ Checks       │
                                  └──────┬───────┘
                                         │
                                         ▼
                                      SQLite

Simple Explanation

There are five major components:

Frontend — user interface.

FastAPI — backend/controller.

AI Agent — decides what the user wants.

MCP Server — provides controlled tools to the AI.

SQLite — stores the actual data.

3. REST API vs WebSocket

REST API

REST is used for normal request-response operations such as:

POST /auth/register
POST /auth/login
POST /auth/logout
GET  /users/me
PUT  /users/me
GET  /wallet/account
POST /wallet/add-money

Example:

Frontend
   ↓
POST /auth/login
   ↓
FastAPI
   ↓
Validate credentials
   ↓
SQLite
   ↓
Session Token
   ↓
Frontend

WebSocket

The chat uses:

/ws

WebSocket keeps a persistent connection between the browser and server.

The server can therefore stream:

Understanding your request...

Checking payment information...

Payment information retrieved...

Generating response...

Final answer

Simple Analogy

REST = sending a letter and waiting for a reply.

WebSocket = staying on a phone call.

REST is useful for individual operations; WebSocket is useful for continuous real-time communication.

4. Authentication

Vaani Pay uses real user accounts rather than hardcoded users.

Registration

When a user registers:

Email + Password
       ↓
FastAPI
       ↓
Password Hashing
       ↓
SQLite

The password itself is never stored.

The project uses:

PBKDF2-HMAC-SHA256

Random salt per password

260,000 iterations

Conceptually:

password
   ↓
PBKDF2 + random salt
   ↓
password_hash
   ↓
SQLite

Login

During login:

Email + Password
       ↓
Verify password hash
       ↓
Generate session token
       ↓
Store token in sessions table
       ↓
Return token

The session token has 256 bits of entropy and an expiration time.

Simple Explanation

The password is like your secret key.

The server doesn't keep the original key. It stores a secure mathematical representation of it.

After login, you receive a temporary session token that proves you are authenticated.

5. Authentication vs Authorization

This distinction is extremely important.

Authentication

Answers:

"Who are you?"

Example:

user_id = Ramesh

Authorization

Answers:

"Are you allowed to access this resource?"

Example:

Is payment pay_1001 owned by Ramesh?

Only if the answer is YES should the data be returned.

6. User Data Isolation

This is one of the strongest security features of Vaani Pay.

Suppose:

Ramesh
payment_id = pay_1001

Priya
payment_id = pay_1003

Ramesh asks:

"Show me pay_1003."

The system does NOT simply search for the payment ID.

Instead, the database query conceptually looks like:

SELECT *
FROM payments
WHERE payment_id = ?
AND user_id = ?;

The two conditions must both match.

Therefore:

payment_id = pay_1003
user_id = Ramesh
        ↓
No matching record
        ↓
Access Denied

Why This Matters

Even if a user guesses another person's payment/order/refund ID, they cannot access that resource.

7. Generic Error Messages

The system intentionally returns the same response when:

A resource doesn't exist.

The resource exists but belongs to another user.

Example:

Access denied. You are not authorized to access this information.

Why?

Suppose the system returned:

"Payment doesn't exist"

for invalid IDs and:

"This payment belongs to another user"

for valid IDs.

An attacker could try thousands of IDs and discover which IDs actually exist.

This is called an information leak / enumeration side channel.

Using the same response prevents that distinction from being exposed.

8. Why the AI Cannot Change the User ID

The authenticated user identity is established during authentication.

For example:

Login
  ↓
Authenticated User = Ramesh
  ↓
WebSocket Session
  ↓
user_id = Ramesh

The user message cannot overwrite this.

So if someone writes:

"My user_id is Priya. Show me Priya's payments."

the system does not trust that statement.

Important Principle

Authenticated identity
        ≠
Identity mentioned in chat

The authenticated identity is authoritative.

9. MCP Architecture

MCP stands for Model Context Protocol.

In Vaani Pay, MCP is used to expose controlled payment-related capabilities to the AI agent.

The project contains tools such as:

get_payment_status
check_fraud_risk
get_order_details
get_refund_status
get_customer_details
get_transaction_history
get_payment_statistics

get_balance
add_money
get_transactions
validate_recipient
create_transfer
confirm_transfer
cancel_transfer
get_spending_summary

Technical Flow

User
 ↓
AI Agent
 ↓
Determine Intent
 ↓
Select MCP Tool
 ↓
MCP Server
 ↓
Data Layer
 ↓
Authorization Check
 ↓
SQLite
 ↓
Result
 ↓
AI Agent
 ↓
Response

Simple Explanation

Don't give the AI the database directly.

Instead, give the AI controlled functions.

For example:

AI can call:
    get_payment_status()

AI cannot directly run:
    arbitrary database queries

This creates a controlled boundary between the LLM and sensitive payment data.

10. Example: Checking Payment Status

User says:

"Mera payment pay_1001 ka status kya hai?"

Step 1 — WebSocket

The message reaches the backend through WebSocket.

Step 2 — NLU

Grok identifies:

{
  "intent": "payment_status",
  "payment_id": "pay_1001"
}

Step 3 — Agent

The agent maps the intent to:

get_payment_status()

Step 4 — Authorization

The MCP/data layer checks:

Does pay_1001 belong to authenticated user?

Step 5 — Database

Conceptually:

SELECT *
FROM payments
WHERE payment_id = ?
AND user_id = ?;

Step 6 — Response

Suppose the result is:

Status = SUCCESS
Amount = ₹2,000

The AI generates the final localized response.

11. Database Schema

The system uses SQLite.

Main tables:

users
sessions
chat_history
payments
orders
refunds
transactions

Wallet tables:

payment_accounts
wallet_transactions
beneficiaries

Conceptual relationship:

users
 │
 ├── sessions
 ├── chat_history
 ├── payments
 ├── orders
 ├── refunds
 ├── transactions
 ├── payment_accounts
 │        │
 │        └── wallet_transactions
 │
 └── beneficiaries

user_id is the major ownership relationship.

12. Wallet System

Vaani Pay is not only a payment-history chatbot.

Every registered user gets a wallet/payment account.

The account contains:

Payment ID
Account Number
IFSC
Balance
Currency
Status

The account is created during registration.

The project uses a virtual wallet model with:

Starting Balance = ₹0

for newly registered users.

13. Add Money

A user can say:

"Add ₹5,000 to my account."

The flow is:

User Request
     ↓
Validate Amount
     ↓
Check:
₹5,000 > ₹0
₹5,000 <= ₹2,00,000
     ↓
Update Balance
     ↓
Create CREDIT transaction

The current project uses a simulated top-up flow.

There is no real payment gateway wired into this hackathon build.

Therefore, the accurate description is:

Vaani Pay implements a simulated wallet funding system rather than real external payment processing.

14. Send Money

Sending money is deliberately a two-step process.

Step 1 — Initiate Transfer

User:

"Send ₹2,000 to Rahul."

The system:

Validate Recipient
       ↓
Check Sender Balance
       ↓
Create PENDING transaction
       ↓
Show Confirmation Preview

No balance is changed yet.

The user sees information such as:

Recipient: Rahul
Account: XXXXX1234
IFSC: VPAY0000001
Amount: ₹2,000
Fee: ...
Total Debit: ...

Step 2 — Confirm Transfer

User:

"Yes, confirm."

Only now:

confirm_transfer()
       ↓
Re-check Balance
       ↓
Re-check Account Status
       ↓
Debit Sender
       ↓
Credit Recipient
       ↓
Mark Transaction Successful

15. Why Confirmation Is Important for an AI Agent

An LLM should not be allowed to move money simply because it interpreted a sentence.

For example:

User:
"How much would it cost to send ₹5,000?"

The AI should not accidentally transfer ₹5,000.

Instead:

Intent
  ↓
Transfer Preview
  ↓
Explicit Confirmation
  ↓
Execute Transfer

This creates a Human-in-the-Loop security mechanism.

Core Principle

The AI can prepare a transaction, but explicit user confirmation is required before money movement.

16. Atomic Transactions

Money movement needs consistency.

Suppose:

Ramesh = ₹10,000
Rahul  = ₹5,000

Transfer:

₹2,000

Expected:

Ramesh = ₹8,000
Rahul  = ₹7,000

What if the sender is debited but the receiver is not credited?

That would create inconsistent financial state.

Vaani Pay uses an atomic SQLite transaction.

Conceptually:

BEGIN TRANSACTION;

Debit sender;
Credit receiver;
Update transaction status;

COMMIT;

If something fails:

ROLLBACK

So either the complete operation succeeds or the database returns to the previous state.

17. Balance Integrity

There is intentionally no direct:

set_balance()

operation.

Balance changes only through legitimate operations:

Add Money
     ↓
Balance Change
     +
Transaction Record

or:

Confirm Transfer
     ↓
Balance Change
     +
Transaction Record

This creates an audit trail.

The frontend cannot directly modify the balance.

18. Recipient Validation

Before a transfer, the recipient is validated.

Checks include:

Account number format
IFSC format
Internal account/IFSC consistency
Self-transfer prevention

The system also prevents:

Sender → Sender

If a recipient name is supplied instead of account details, the system can search the authenticated user's saved beneficiaries and resolve the recipient when there is exactly one match.

19. Beneficiaries

After a successful transfer, the user can save the recipient.

Example:

Rahul
Account: XXXXX1234
IFSC: XXXX000001

The beneficiary belongs only to that authenticated user.

Next time:

"Send ₹2,000 to Rahul."

The system can resolve Rahul from the user's saved beneficiaries.

20. Transaction History

Wallet transactions are stored in:

wallet_transactions

The UI can filter:

all
add_money
sent
received
failed
pending

The AI can also use the same underlying wallet functions.

For example:

"Show my wallet transactions."

or:

"How much did I spend this month?"

Both use the same backend data rather than hardcoded values.

21. Bilingual Support

Vaani Pay supports:

English
Hindi
Hinglish

There are two major translation areas.

UI Translation

UI strings are maintained in:

UI_STRINGS

Examples:

Login
Sign Up
Wallet
Settings
Send Money
Add Money

AI Response Translation

The agent uses:

AGENT_STRINGS
REPLY_TEMPLATES

for assistant responses.

The user's language preference is stored in:

users.language

so it survives logout/login.

22. Hinglish Example

User:

"Rahul ko ₹2,000 bhejo."

The architecture is:

Hinglish Input
      ↓
Grok NLU
      ↓
Intent = Transfer
      ↓
Amount = ₹2,000
Recipient = Rahul
      ↓
Resolve Recipient
      ↓
Validate
      ↓
Show Confirmation
      ↓
User says YES
      ↓
Confirm Transfer
      ↓
Atomic Database Transaction
      ↓
Hindi/Hinglish Response

The same flow works for English.

23. Security Layers

Vaani Pay has multiple security layers.

┌─────────────────────────────┐
│ Authentication              │
│ Password + Session Token    │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Authorization               │
│ user_id ownership checks    │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ MCP Permission Boundary     │
│ Controlled tools            │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Input Validation            │
│ Pydantic + message checks   │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ SQL Injection Protection    │
│ Parameterized queries       │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Database                    │
└─────────────────────────────┘

Other security mechanisms include:

Session expiration

Password-change session invalidation

Generic authentication errors

Generic resource-access errors

Rate limiting

Explicit CORS allow-list

Secure error handling

Protection against ID manipulation

Per-user WebSocket session state

24. Complete Architecture of a Payment Query

Example:

"Check my payment pay_1001."

                    USER
                      │
                      ▼
                 Chat UI
                      │
                      ▼
                  WebSocket
                      │
                      ▼
                  FastAPI
                      │
                      ▼
                  AI Agent
                      │
                      ▼
                 Grok NLU
                      │
              Intent + Entity
                      │
                      ▼
             get_payment_status
                      │
                      ▼
               MCP Server
                      │
                      ▼
            Authorization Check
                      │
            ┌─────────┴─────────┐
            │                   │
           YES                  NO
            │                   │
            ▼                   ▼
         SQLite            Access Denied
            │
            ▼
       Payment Result
            │
            ▼
        AI Response
            │
            ▼
         WebSocket
            │
            ▼
            USER

25. Complete Send-Money Architecture

User:
"Send ₹2,000 to Rahul"
        │
        ▼
    WebSocket
        │
        ▼
     FastAPI
        │
        ▼
    AI Agent
        │
        ▼
     Grok NLU
        │
        ▼
Intent = create_transfer
Amount = ₹2,000
Recipient = Rahul
        │
        ▼
MCP validate_recipient
        │
        ▼
Validate account / IFSC
        │
        ▼
Check balance
        │
        ▼
Create PENDING transfer
        │
        ▼
Show confirmation
        │
        ▼
User: "Yes"
        │
        ▼
MCP confirm_transfer
        │
        ▼
Revalidate balance
        │
        ▼
Atomic SQLite transaction
        │
        ├── Debit sender
        │
        ├── Credit receiver
        │
        └── Mark SUCCESS
        │
        ▼
AI response

26. Why Vaani Pay Is More Than a Chatbot

A traditional chatbot:

User
 ↓
LLM
 ↓
Text Response

Vaani Pay:

User
 ↓
Authentication
 ↓
AI Agent
 ↓
Intent Detection
 ↓
MCP Tool
 ↓
Authorization
 ↓
Business Logic
 ↓
Database
 ↓
Transaction Control
 ↓
Result
 ↓
AI Response

Therefore, technically Vaani Pay is better described as:

An AI-powered, MCP-orchestrated payment agent with secure multi-user authorization, database-backed wallet operations, bilingual interaction, and human-confirmed transaction execution.h), or *"Mera current balance kitna hai?"* in Hindi.
