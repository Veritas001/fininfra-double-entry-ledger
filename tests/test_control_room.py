from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import DATABASE_URL
from app.db import get_connection
from app.ledger.control_room import ControlRoomService, Posting
from app.ledger.enums import EntrySide
from app.ledger.service import LedgerBusinessError
from app.main import app
from app.migrations import run_migrations


client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    run_migrations()


@pytest.fixture(autouse=True)
def clean_ledger_tables(migrated_database: None) -> Iterator[None]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            conn.execute(
                """
                TRUNCATE
                    audit_events,
                    external_references,
                    idempotency_records,
                    ledger_entries,
                    transactions,
                    account_balances,
                    accounts
                RESTART IDENTITY CASCADE;
                """
            )
    yield


def test_dashboard_route_loads() -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Project 1 - Double-Entry Ledger Control Room" in response.text


def test_summary_endpoint_returns_required_fields() -> None:
    response = client.get("/api/v1/ledger/summary")

    assert response.status_code == 200
    body = response.json()
    for field in [
        "account_count",
        "journal_entry_count",
        "posting_count",
        "total_debits",
        "total_credits",
        "trial_balance_difference",
        "ledger_balanced",
        "latest_journal_entry",
        "demo_state",
    ]:
        assert field in body


def test_replay_settlement_demo_creates_balanced_entries() -> None:
    response = client.post("/api/v1/ledger/demo/replay-settlement")

    assert response.status_code == 200
    summary = response.json()
    assert summary["account_count"] == 3
    assert summary["journal_entry_count"] == 2
    assert summary["posting_count"] == 5
    assert summary["total_debits"] == 20_005
    assert summary["total_credits"] == 20_005
    assert summary["trial_balance_difference"] == 0
    assert summary["ledger_balanced"] is True

    journal_entries = client.get("/api/v1/ledger/journal-entries").json()["journal_entries"]
    assert len(journal_entries) == 2
    assert sorted(len(entry["postings"]) for entry in journal_entries) == [2, 3]


def test_repeated_replay_settlement_demo_is_deterministic() -> None:
    first = client.post("/api/v1/ledger/demo/replay-settlement").json()
    second = client.post("/api/v1/ledger/demo/replay-settlement").json()

    assert second == first
    assert client.get("/api/v1/ledger/summary").json()["posting_count"] == 5


def test_trial_balance_difference_is_zero_after_replay() -> None:
    client.post("/api/v1/ledger/demo/replay-settlement")

    trial_balance = client.get("/api/v1/ledger/trial-balance").json()

    assert trial_balance["difference"] == 0
    assert trial_balance["balanced"] is True
    assert trial_balance["total_debits"] == 5
    assert trial_balance["total_credits"] == 5


def test_unbalanced_demo_journal_entry_is_rejected_and_not_persisted() -> None:
    service = ControlRoomService()

    with pytest.raises(LedgerBusinessError) as exc_info:
        with get_connection() as conn:
            with conn.transaction():
                service._post_journal_entry(
                    conn,
                    transaction_id=uuid4(),
                    external_ref="broken-unbalanced-entry",
                    description="Broken unbalanced entry",
                    postings=[
                        Posting(uuid4(), EntrySide.DEBIT, 100),
                        Posting(uuid4(), EntrySide.CREDIT, 99),
                    ],
                )

    assert exc_info.value.error_code == "unbalanced_journal_entry"
    with psycopg.connect(DATABASE_URL) as conn:
        assert conn.execute("SELECT count(*) FROM transactions;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM ledger_entries;").fetchone()[0] == 0
