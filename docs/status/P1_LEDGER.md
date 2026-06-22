# P1 — Double-Entry Ledger

## Status

Implemented prototype. The test suite passes for the current ledger scope.

## Role in FMI Lab

P1 is the accounting foundation for the entire FMI Lab.

It will support future modules involving:
- payment posting
- clearing and settlement
- cash balances
- securities balances
- P&L
- margin
- portfolio accounting
- reconciliation

## Project Goal

Build a double-entry ledger service that supports accounts, transactions, immutable ledger entries, idempotent transfer requests, and transactional consistency.

The P1 MVP transfer API is scoped to cash-style transfers between `ASSET` accounts with `DEBIT` normal balance. Generic multi-account journal posting is out of scope for this gate.

## Must Not Do Yet

Do not implement:
- generic multi-account journal posting
- exchange matching
- payment networks
- clearing and settlement
- backtesting
- trading strategies
- market surveillance

Those belong to later projects.

## Implemented Evidence

- PostgreSQL-backed accounts, balances, transactions, ledger entries, idempotency records, external references, and audit events
- `/api/v1/accounts`
- `/api/v1/accounts/{account_id}`
- `/api/v1/accounts/{account_id}/balance`
- `/api/v1/transfers`
- `/api/v1/transactions/{transaction_id}`
- `/api/v1/ledger-entries`
- Double-entry transfer posting with one debit and one credit entry
- Idempotency-key replay and conflict handling
- Database trigger protection against ledger entry update/delete
- Tests for success, rejection, validation, idempotency, rollback, balance projection, immutability, and readiness

## Prototype Boundary

P1 is not a production bank ledger, payment network, wallet, clearing system, or trading system. It is the accounting foundation for later FMI Lab prototypes.
