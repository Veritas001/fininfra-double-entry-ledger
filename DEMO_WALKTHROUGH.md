# P1 Ledger Control Room Demo Walkthrough

This walkthrough demonstrates v1.1 of Project 1 - Double-Entry Ledger Control Room.

## Start Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d db
python scripts/run_migrations.py
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8011/dashboard
```

## Browser Sequence

1. Confirm service health and database readiness cards load.
2. Click `Reset Demo Ledger`.
3. Confirm the dashboard shows an understandable empty state.
4. Click `Replay Settlement Demo`.
5. Confirm `Ledger Balanced: TRUE`.
6. Confirm `Total Debits = 20005`, `Total Credits = 20005`, and `Difference = 0`.
7. Confirm accounts are visible:
   - Settlement Cash
   - Seller Payable
   - Clearing Fee Revenue
8. Confirm two journal entries are visible:
   - Collect buyer funds
   - Pay seller
9. Confirm the trial balance is visible and balanced.
10. Click `Replay Settlement Demo` again.
11. Confirm the totals remain unchanged and journal entries are not duplicated.

## What The Scenario Represents

The demo replays a settlement-style cash flow with notional `10000` and clearing fee `5`.

Entry 1 - Collect buyer funds:

- Debit Settlement Cash: `10005`
- Credit Seller Payable: `10000`
- Credit Clearing Fee Revenue: `5`

Entry 2 - Pay seller:

- Debit Seller Payable: `10000`
- Credit Settlement Cash: `10000`

Expected final state:

- Total debits = `20005`
- Total credits = `20005`
- Trial balance difference = `0`
- Settlement Cash ending debit balance = `5`
- Seller Payable ending balance = `0`
- Clearing Fee Revenue ending credit balance = `5`

## Boundary

This is a local prototype demo for ledger integrity, immutable-style postings, trial balance checks, and settlement-readiness concepts. It is not a production bank general ledger, broker system, trading system, market data pipeline, payment network, or clearing system.
