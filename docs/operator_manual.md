# P1 Operator Manual

This manual explains how to run the P1 Double-Entry Ledger locally, execute the demo flow, and troubleshoot common setup issues.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop or another Docker Compose-compatible runtime
- `curl`
- PostgreSQL container started through this repository's `docker-compose.yml`

The demo script uses only `curl`, shell, and Python standard library parsing. `jq` is not required.

## Create and Activate a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Requirements

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Start PostgreSQL

```bash
docker compose up -d db
```

The default host database URL is:

```text
postgresql://fininfra:fininfra@localhost:55432/fininfra
```

## Run Migrations

```bash
python scripts/run_migrations.py
```

## Start the FastAPI App

```bash
uvicorn app.main:app --reload
```

By default, the service is available at:

```text
http://localhost:8000
```

## Open Health, Readiness, and API Docs

```text
http://localhost:8000/health
http://localhost:8000/ready
http://localhost:8000/docs
```

`/health` checks the API process. `/ready` checks database connectivity and returns HTTP 503 when PostgreSQL is unavailable.

## Run Tests

```bash
pytest
```

or, without relying on shell activation:

```bash
.venv/bin/python -m pytest
```

## Run the Demo Script

Start PostgreSQL, run migrations, and start the FastAPI app first. In another terminal:

```bash
bash scripts/demo_p1_flow.sh
```

To point the script at a different local API URL:

```bash
API_BASE_URL=http://localhost:8001 bash scripts/demo_p1_flow.sh
```

The demo creates accounts, seeds a local source balance through the ledger service, posts a transfer, replays the same transfer idempotently, lists ledger entries, checks balances, and demonstrates a rejected same-account transfer.

## Demo Seed Tool

`scripts/seed_demo_data.py` is local demo tooling. It does not run automatically and does not add a public API endpoint.

The seed helper creates a demo funding account and posts a balanced transfer into the demo source account. This preserves the double-entry invariant while making the walkthrough runnable without adding a production-style funding endpoint.

Example direct use:

```bash
.venv/bin/python scripts/seed_demo_data.py \
  --source-account-id <source-account-uuid> \
  --amount-minor 50000 \
  --currency USD
```

## Troubleshooting

### Database Not Ready

If `/ready` returns HTTP 503, confirm the database container is running:

```bash
docker compose ps
docker compose up -d db
```

Then rerun migrations:

```bash
python scripts/run_migrations.py
```

### Port Already in Use

If port `8000` is already in use, run the API on another port:

```bash
uvicorn app.main:app --reload --port 8001
```

Then run the demo with:

```bash
API_BASE_URL=http://localhost:8001 bash scripts/demo_p1_flow.sh
```

If PostgreSQL host port `55432` is already in use, update `docker-compose.yml` and `.env.example` consistently.

### Missing Virtual Environment

If `.venv/bin/python` is missing:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Failed Migrations

Confirm `DATABASE_URL` points to the running local PostgreSQL container. Then run:

```bash
python scripts/run_migrations.py
```

If the database is in an unexpected local demo state, inspect the current Docker volume before deleting anything. Do not delete data unless you intend to reset the local demo database.

### Pytest Import or Dependency Errors

Activate the virtual environment and reinstall dependencies:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```

### Demo Script Fails During Seeding

The seed helper imports the app and uses the configured database. Make sure dependencies are installed and `DATABASE_URL` matches the database used by the running API.

## Non-Production Warning

P1 is a local FMI Lab prototype. It is not for real money, real securities, custody, production settlement, production payments, trading, regulated workflows, or operational financial infrastructure.
