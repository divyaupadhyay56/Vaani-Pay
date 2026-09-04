Vaani Pay --- How the Project Works

1. What is Vaani Pay?

Vaani Pay is a secure, bilingual AI payment assistant. Users can
interact with the system in English, Hindi, or Hinglish using a chat
interface.

The main idea is:

AI understands the request, but deterministic backend services
control the money.

The AI does not directly access the database or freely execute payment
operations.

2. High-Level Flow

User
  ↓
Web App
  ↓
FastAPI + WebSocket
  ↓
Grok NLU
  ↓
Agent Orchestrator
  ↓
Skill
  ↓
MCP Tool Layer
  ↓
Business / Wallet Services
  ↓
SQLite Database

The WebSocket also sends live workflow updates back to the user.

3. User and Authentication

A user first creates an account and logs in.

Registration creates a user in SQLite.

Passwords are securely hashed.

Login creates an opaque session token.

The authenticated user identity is stored on the server.

The AI cannot choose or change the user's user_id.

Users can update their profile, language preference, password, or
delete their account.

This server-side identity is important because payment and data-access
decisions must not depend on information supplied by the AI or by the
chat message.

4. Conversational AI / NLU

The user can type requests such as:

"Ramesh ko ₹500 bhejo"
"Show my balance"
"Show my transaction history"
"Add ₹1000"

Grok is used for Natural Language Understanding (NLU).

It converts the message into structured information such as:

Intent: send_money
Recipient: Ramesh
Amount: ₹500
Confidence: high

The NLU handles English, Hindi and mixed-language input.

It is specifically instructed not to extract or store sensitive
payment secrets such as UPI PIN, card PIN or OTP.

5. Agent Orchestrator

app/agent.py acts as the central workflow coordinator.

It:

Receives the NLU result.

Uses the authenticated server-side user identity.

Checks pending actions such as payment confirmation.

Handles simulation mode.

Selects the correct skill.

Creates a restricted MCP gateway for that skill.

Sends the result back to the WebSocket/client.

The agent therefore coordinates the workflow instead of containing all
business logic itself.

6. Skills

Vaani Pay separates actions into reusable skills.

Examples include:

Send Money

Add Money

Check Balance

Transaction Memory / History

Payment Status

Beneficiary Management

Simulation Mode

Each important skill has access only to the tools it needs.

For example, the Send Money workflow uses tools such as:

validate_recipient
create_transfer
confirm_transfer
cancel_transfer
get_balance

This tool allowlist prevents an AI workflow from freely calling
unrelated operations.

7. MCP Tool Layer

Vaani Pay uses Model Context Protocol (MCP) as the tool boundary
between the agent and backend capabilities.

The MCP server exposes domain tools for:

Wallet

Payments

Fraud

Orders

Refunds

Customers

Analytics

The important security principle is:

MCP provides the tool interface; authorization is enforced by the
application, skills and data layer.

8. Send Money --- Main Secure Flow

When a user asks to send money, Vaani Pay follows a controlled workflow:

User Request
    ↓
Understand Intent
    ↓
Identify Recipient
    ↓
Validate Recipient
    ↓
Fraud Risk Check
    ↓
Action Preview
    ↓
User Confirmation
    ↓
Create Pending Transfer
    ↓
Confirm / Execute Transfer
    ↓
Verify Balance & Status
    ↓
Success Response

Recipient Validation

The system checks the recipient and validates account/IFSC information.
It also prevents invalid and self-transfer cases.

Fraud Risk Check

Before execution, the system runs a behavioral/rule-based risk
engine.

It considers signals such as:

Unusual transaction amount

Transaction velocity

New recipient

Unusual transaction time

Round-number patterns

The result is a risk level such as LOW, MEDIUM or HIGH.

A high-risk transfer can be blocked before execution.

Action Preview

Before money is moved, the user receives a preview containing
information such as:

Recipient

Masked account number

Amount

Currency

FX conversion where applicable

Fee

Risk level

Risk reasons

Human Confirmation

The transfer does not execute immediately after the AI understands the
request.

The user must explicitly confirm:

yes → continue
no  → cancel

This creates a human-in-the-loop control before the financial operation.

9. Wallet and Transactions

The wallet layer manages the local payment-account simulation.

It supports:

Balance

Add Money

Send Money

Transaction History

Spending Summary / Analytics

Multi-currency handling

Transfers use a transaction lifecycle such as:

PENDING → SUCCESS
        ↘ CANCELLED

The transfer service uses database transactions and locking around the
critical balance update.

The current project is a local/demo wallet simulation, not a live
UPI or bank settlement system.

10. Beneficiaries

Users can manage saved recipients through the beneficiary functionality.

They can:

Add a beneficiary

View beneficiaries

Edit beneficiary information

Delete a beneficiary

Saved beneficiaries can also help the Send Money workflow resolve a
recipient.

11. Simulation Mode

Simulation mode provides a safe what-if workflow.

For example:

"What would happen if I send ₹50,000 to Ramesh?"

The system can perform the validation, risk analysis and preview without
executing the actual transfer.

This is useful for testing and demonstrating payment workflows safely.

12. Live Agent Timeline

Vaani Pay uses WebSockets to stream workflow events to the frontend.

The user can see progress such as:

Request received
      ↓
Intent recognized
      ↓
Recipient validation
      ↓
Fraud risk check
      ↓
Action preview
      ↓
User confirmation
      ↓
Transfer execution
      ↓
Verification
      ↓
Success

This makes the agent's work observable instead of showing only a loading
spinner.

13. Data and Privacy

SQLite stores application data such as:

Users

Sessions

Payment accounts

Beneficiaries

Wallet transactions

Chat history

Payment/order/refund information

User-owned resources are queried using the authenticated user's
identity.

For example, the system checks both:

resource_id
+
requesting_user_id

This prevents one user from accessing another user's payment
information.

14. Security Architecture

Vaani Pay uses multiple security boundaries:

Secure password hashing

Server-side session authentication

User-scoped authorization

Parameterized SQL queries

Skill-level tool allowlists

No PIN/OTP exposure to the AI

Recipient validation

Fraud risk checks

Explain-before-execute preview

Explicit human confirmation

Simulation/dry-run mode

Safe error handling

The core security philosophy is:

AI proposes. Humans authorize. Deterministic systems execute.

15. Technology Stack

Layer                     Technology

Frontend                  HTML / CSS / JavaScript
Backend                   Python + FastAPI
Real-time communication   WebSocket
AI / NLU                  Grok API
Agent orchestration       Python skill-based architecture
Tool protocol             MCP
Database                  SQLite
Security                  PBKDF2-HMAC-SHA256 + server-side sessions
Architecture              Modular services + skills + MCP tools

16. Important Current-State Notes

The current uploaded project should be described accurately:

It is bilingual text-based, not yet voice-enabled.

Fraud detection is rule/behavior based, not an ML fraud model.

The wallet is a local/demo payment simulation.

FX rates are configured/demo values rather than a live exchange-rate
API.

Razorpay/UPI/banking integrations should be presented as future
production extensions unless separately implemented.

One-Line Project Summary

Vaani Pay is a secure, bilingual AI payment assistant that combines
NLU, agentic workflows and MCP-based tool control with recipient
validation, behavioral fraud checks, explainable payment previews and
explicit human authorization before money movement.