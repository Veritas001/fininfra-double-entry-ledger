# P1 — Double-Entry Ledger

This repository implements Project 1 of the FMI Lab: a double-entry ledger prototype that provides the accounting foundation for future payment, clearing, settlement, risk, and quantitative workflow modules.

P1 inherits the engineering foundation established in P0: FastAPI, Dockerized PostgreSQL, health/readiness checks, pinned dependencies, tests, and architecture documentation. This repository is Project 1. P0 is mentioned here only as the foundation that P1 builds on.

This is a vendor-due-diligence-grade prototype lab artifact. It is not a production bank, clearing system, payment network, crypto wallet, personal finance app, trading bot, or real-money financial service.

## FMI Lab Role

P1 supplies the accounting layer that later FMI Lab modules can reuse conceptually. Payment posting, clearing and settlement simulations, cash and securities balance workflows, P&L, margin, risk, reconciliation, and quantitative research services all need ledger-grade accounting primitives before more complex workflows are added.

The repository intentionally stops at the ledger boundary. It demonstrates careful backend engineering and accounting invariants without claiming to operate real financial infrastructure.

## What P1 Implements

- Account creation and account reads
- Account balance projection in integer minor units
- Transfer posting between accounts
- Immutable ledger entries
- Posted transaction reads
- Ledger entry listing
- Idempotent transfer requests using `Idempotency-Key`
- Canonical request hashing for duplicate request detection
- PostgreSQL-backed transactional posting
- Deterministic balance-row locking during transfers
- Tests for correctness, validation, idempotency, rollback, readiness, and immutability behavior

## What P1 Does Not Implement

P1 does not implement:

- Generic multi-account journal posting
- Matching engine
- Payment network
- Clearing netting
- Securities settlement
- FIX
- ISO 20022 messaging
- Margin model
- Risk engine
- Backtesting engine
- Real-money custody, wallets, deposits, withdrawals, or banking operations

Those belong to later FMI Lab modules or are outside the prototype boundary.

## Project Structure

```text
fininfra-double-entry-ledger/
├── app/
│   ├── config.py
│   ├── db.py
│   ├── health.py
│   ├── main.py
│   ├── migrations.py
│   └── ledger/
│       ├── enums.py
│       ├── repository.py
│       ├── routes.py
│       ├── schemas.py
│       └── service.py
├── docs/
│   ├── architecture.md
│   ├── demo_playbook.md
│   ├── operator_manual.md
│   └── status/
│       └── P1_LEDGER.md
├── migrations/
│   ├── 001_p1_double_entry_ledger.sql
│   └── 002_drop_transaction_external_ref_unique.sql
├── scripts/
│   ├── demo_p1_flow.sh
│   ├── run_migrations.py
│   └── seed_demo_data.py
├── tests/
│   ├── test_demo_artifacts.py
│   ├── test_health.py
│   └── test_ledger.py
├── docker-compose.yml
├── Dockerfile
├── pytest.ini
├── README.md
└── requirements.txt
```

## API Endpoints

Foundation endpoints inherited from P0 and retained in P1:

- `GET /`
- `GET /health`
- `GET /ready`

P1 ledger endpoints are under `/api/v1`:

- `POST /api/v1/accounts`
- `GET /api/v1/accounts/{account_id}`
- `GET /api/v1/accounts/{account_id}/balance`
- `POST /api/v1/transfers`
- `GET /api/v1/transactions/{transaction_id}`
- `GET /api/v1/ledger-entries`

### Create Account

```bash
curl -X POST http://localhost:8000/api/v1/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "account_code": "cash-usd",
    "name": "Cash USD",
    "account_type": "ASSET",
    "normal_balance": "DEBIT",
    "currency": "USD",
    "allow_negative": false
  }'
```

### Post Transfer

```bash
curl -X POST http://localhost:8000/api/v1/transfers \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-transfer-001" \
  -d '{
    "source_account_id": "00000000-0000-0000-0000-000000000001",
    "destination_account_id": "00000000-0000-0000-0000-000000000002",
    "amount_minor": 1000,
    "currency": "USD",
    "description": "Prototype ledger transfer"
  }'
```

Successful transfer posting returns `201` with a posted transaction and two ledger entries. Replaying the same request with the same `Idempotency-Key` returns the stored response with `200` and does not post again.

For the P1 MVP, `POST /api/v1/transfers` is scoped to cash-style transfer accounts. Both source and destination accounts must be `ASSET` accounts with `DEBIT` normal balance. Generic multi-account journal posting is intentionally out of scope and may be added as a future ledger extension.

## Data Model Summary

P1 adds these PostgreSQL tables:

- `accounts`: account identity, type, normal balance, currency, status, metadata
- `account_balances`: projected debit, credit, and normal-balance-adjusted balances
- `transactions`: posted transfer transaction records
- `ledger_entries`: immutable debit and credit entries
- `idempotency_records`: request hash, status, response replay, and failure tracking
- `external_references`: optional uniqueness for external business references
- `audit_events`: lightweight prototype audit trail

The migrations also add PostgreSQL enum types, check constraints, foreign keys, indexes, and triggers that prevent update/delete of `ledger_entries`.

## Double-Entry Accounting Rule

Money amounts are represented only as integer minor units such as cents. Floats are not used for money.

For each transfer:

- Destination account receives one `DEBIT` ledger entry.
- Source account receives one `CREDIT` ledger entry.
- Both entries use the same positive `amount_minor` and currency.
- The transaction is posted only when total debits equal total credits.

Balance projection uses the account normal balance:

- `DEBIT` normal accounts: `balance_minor = debit_posted_minor - credit_posted_minor`
- `CREDIT` normal accounts: `balance_minor = credit_posted_minor - debit_posted_minor`

## Core Invariants

- `amount_minor` must be positive.
- Currency is normalized to a three-letter uppercase code.
- Transfers require an `Idempotency-Key` header.
- Transfer source and destination accounts must be different.
- Transfer source and destination accounts must both be `ASSET` accounts with `DEBIT` normal balance.
- Same idempotency key plus same request hash replays the stored success response.
- Same idempotency key plus a different request hash returns `409`.
- Duplicate idempotency keys never double-post.
- Frozen or closed accounts cannot transfer.
- Currency mismatches are rejected.
- Non-negative accounts cannot be posted below zero.
- Ledger entries have no update/delete API and are protected by database triggers.
- Transfer posting and balance updates happen in one database transaction.
- Failed or rejected transfer attempts create no ledger entries.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d db
python scripts/run_migrations.py
uvicorn app.main:app --reload
```

Then open:

```text
http://localhost:8000/
http://localhost:8000/health
http://localhost:8000/ready
http://localhost:8000/docs
```

## Demo / Operator Walkthrough

For reviewers who want to understand what the ledger does, see:

- `docs/demo_playbook.md`
- `docs/operator_manual.md`

After starting the service locally, run:

```bash
bash scripts/demo_p1_flow.sh
```

The demo creates ledger accounts, seeds a local demo opening balance through balanced ledger posting, posts a transfer, validates idempotency behavior, lists ledger entries, and shows how failed requests avoid partial ledger mutation.

## Run with Docker

```bash
docker compose up --build
```

The API container receives `SERVICE_NAME=fininfra-double-entry-ledger` and `DATABASE_URL=postgresql://fininfra:fininfra@db:5432/fininfra`. Local host commands use the compose-mapped PostgreSQL port `55432`.

## Run Migrations

```bash
source .venv/bin/activate
python scripts/run_migrations.py
```

Ledger API calls also ensure the schema exists before executing P1 operations, but running migrations explicitly is clearer for local setup and review.

## Run Tests

```bash
.venv/bin/python -m pytest
```

The test suite covers health/readiness behavior and P1 ledger correctness, idempotency, validation, rollback, balance projection, and immutability behavior.

## Non-Production Disclaimer

This code is a learning and portfolio prototype for financial infrastructure engineering. It is not hardened for real financial transactions, regulated operations, custody, clearing, settlement, payments, trading, risk management, or production accounting. It should not be used to move, hold, settle, or represent real money or securities.
