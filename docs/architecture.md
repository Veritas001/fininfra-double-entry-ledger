# P1 Architecture Notes

## Purpose

P1 Double-Entry Ledger is the accounting foundation prototype for the FMI Lab. It inherits the FastAPI, PostgreSQL, Docker, readiness, and pytest foundation from P0, then adds ledger-specific domain behavior.

## Current Scope

This repository implements:

1. Account APIs
2. Balance projection
3. Cash-style transfer posting between `ASSET` accounts with `DEBIT` normal balance
4. Immutable ledger entries
5. Idempotency records
6. PostgreSQL transactional consistency

Generic multi-account journal posting is not implemented in the P1 MVP. It is a possible future extension once the transfer ledger invariants are stable.

## Future Extensions

P1 is intended to support later FMI Lab modules such as payment posting, clearing and settlement simulations, risk workflows, and quantitative accounting. Those modules are not implemented here.

## Design Principles

- Keep services testable
- Keep APIs explicit
- Keep infrastructure reproducible
- Use Docker for local development
- Use PostgreSQL as the default financial data store
- Use integer minor units for money amounts
- Preserve double-entry invariants
