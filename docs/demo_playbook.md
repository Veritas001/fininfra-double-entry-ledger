# P1 Demo Playbook

## What P1 Is

P1 is a double-entry ledger prototype for the FMI Lab. It provides the accounting foundation that future payment, clearing, settlement, risk, and quantitative workflow modules can build on.

It is not a production financial system, personal finance app, trading bot, crypto wallet, production bank ledger, payment network, or clearing system. It is a serious engineering prototype focused on ledger correctness, transactional consistency, idempotency, and failure behavior.

## Problem It Solves

Financial infrastructure systems need a trustworthy way to represent value movement. Before a payment rail can settle cash, a clearing simulator can post settlement legs, or a risk module can inspect balances, the system needs accounting primitives that are explicit, auditable, and resistant to partial failure.

P1 solves that foundation problem by modeling:

- Accounts with type, currency, status, and normal balance
- Transactions that represent posted transfer requests
- Immutable debit and credit ledger entries
- Projected account balances
- Idempotency records that prevent duplicate posting
- Transactional rollback when posting fails

## Why Double-Entry Matters

Double-entry accounting is the core invariant behind the ledger. Every posted transfer creates two entries:

- A debit entry to the destination account
- A credit entry to the source account

The posted transaction is valid only when total debits equal total credits. That invariant makes the ledger reviewable: a reviewer can inspect the transaction entries and confirm the accounting equation for that event.

## Demo Storyline

The demo simulates a local cash-style transfer flow:

1. Check that the API is running with `/health`.
2. Check that PostgreSQL is reachable with `/ready`.
3. Create a source cash account.
4. Create a destination settlement account.
5. Seed the source account with a local demo opening balance using a balanced ledger transfer from a demo funding account.
6. Post a transfer from source to destination.
7. Verify the transaction has exactly two ledger entries.
8. Verify total debit equals total credit.
9. Replay the same request with the same `Idempotency-Key`.
10. Verify the replay does not double-post.
11. Query the transaction, balances, and ledger entries.
12. Attempt an invalid same-account transfer.
13. Verify the rejected request does not create ledger entries.

## What Each Step Proves

`/health` proves the FastAPI service process is alive.

`/ready` proves the service can connect to PostgreSQL. If the database is unavailable, `/ready` returns HTTP 503 with `status = not_ready` and `database = not_connected`.

Account creation proves the ledger can create cash-style accounts with unique account codes, active status, and USD currency.

Demo seeding proves a source account can receive an opening balance through the same double-entry posting path used by the service. The seed helper creates a demo funding account with negative balances allowed, then posts a balanced transfer to the source account. This is local demo tooling, not a production funding model.

Transfer posting proves the service can create one transaction and two immutable ledger entries in one database transaction.

Transaction lookup proves the reviewer can retrieve a posted transaction and inspect its entries.

Balance lookup proves projected balances are updated from posted debit and credit totals.

Ledger entry listing proves the immutable accounting record can be reviewed separately from the transaction envelope.

Idempotency replay proves duplicate client retries do not double-post. The same key and same request hash return the original transaction response.

Invalid transfer rejection proves business-rule failures are returned cleanly and do not partially mutate ledger state.

## Interpreting Ledger Objects

An account is the ledger container being debited or credited. In the P1 MVP transfer API, both source and destination accounts must be `ASSET` accounts with `DEBIT` normal balance. Generic multi-account journal posting is intentionally out of scope for this MVP.

A transaction is the business event envelope. For P1, the supported transaction type is `TRANSFER`.

A ledger entry is the immutable accounting line. P1 transfer posting creates exactly two entries: one `DEBIT` and one `CREDIT`.

An account balance is a projection derived from posted debit and credit totals:

- For `DEBIT` normal accounts: `balance_minor = debit_posted_minor - credit_posted_minor`
- For `CREDIT` normal accounts: `balance_minor = credit_posted_minor - debit_posted_minor`

An idempotency record stores a canonical request hash and response replay data so that client retries are safe.

## Why Failed Transfers Must Not Partially Mutate Balances

Ledger posting must be atomic. A failed transfer must not create only one ledger entry, update only one balance, or leave a transaction half-posted. Partial mutation would make the accounting record unreliable and would break future modules that depend on ledger balances.

P1 posts the transaction, entries, and balance updates in one PostgreSQL transaction. Business rejections and unexpected failures roll back the posting path, so failed requests do not create ledger entries.

## Future FMI Lab Support

P1 is designed as a foundation for later prototypes:

- Payment rail: posting cash movement and reconciliation events
- Clearing and settlement: representing cash and securities settlement legs
- Risk: inspecting balances and exposures
- Backtesting: reconciling fills, cash, and portfolio accounting
- Hermes capstone: integrating ledger behavior with other FMI Lab modules

Those systems are not implemented in P1. The demo shows only the ledger foundation they can build on.

## Non-Production Boundary

P1 is not hardened for real money, real securities, regulated workflows, custody, settlement, payments, or trading. The demo uses local accounts and local PostgreSQL state only. It should be reviewed as a prototype engineering artifact, not as production financial infrastructure.
