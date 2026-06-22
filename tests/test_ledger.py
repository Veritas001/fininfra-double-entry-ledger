from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.config import DATABASE_URL
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


def create_account(
    *,
    code: str | None = None,
    account_type: str = "ASSET",
    currency: str = "USD",
    normal_balance: str = "DEBIT",
    allow_negative: bool = False,
    status: str = "ACTIVE",
) -> dict:
    account_code = code or f"acct-{uuid4()}"
    response = client.post(
        "/api/v1/accounts",
        json={
            "account_code": account_code,
            "name": account_code,
            "account_type": account_type,
            "normal_balance": normal_balance,
            "currency": currency,
            "allow_negative": allow_negative,
            "status": status,
            "metadata": {"test": True},
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def post_transfer(
    source_account_id: str,
    destination_account_id: str,
    *,
    amount_minor: int = 100,
    currency: str = "USD",
    key: str | None = None,
    external_ref: str | None = None,
) -> Response:
    payload = {
        "source_account_id": source_account_id,
        "destination_account_id": destination_account_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "description": "test transfer",
    }
    if external_ref is not None:
        payload["external_ref"] = external_ref

    return client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": key or f"idem-{uuid4()}"},
    )


def scalar(sql: str, params: tuple = ()) -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(sql, params).fetchone()[0]


def test_create_account_happy_path() -> None:
    account = create_account(code="cash-main")

    assert account["account_code"] == "cash-main"
    assert account["currency"] == "USD"
    assert account["status"] == "ACTIVE"
    assert scalar("SELECT count(*) FROM account_balances;") == 1


def test_duplicate_account_code_returns_top_level_error() -> None:
    create_account(code="duplicate-code")

    response = client.post(
        "/api/v1/accounts",
        json={
            "account_code": "duplicate-code",
            "name": "duplicate-code-again",
            "account_type": "ASSET",
            "normal_balance": "DEBIT",
            "currency": "USD",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error_code": "duplicate_account_code",
        "message": "An account with this account_code already exists.",
    }


def test_get_account() -> None:
    account = create_account(code="receivable")

    response = client.get(f"/api/v1/accounts/{account['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == account["id"]


def test_get_account_balance() -> None:
    account = create_account(code="cash-balance")

    response = client.get(f"/api/v1/accounts/{account['id']}/balance")

    assert response.status_code == 200
    assert response.json()["balance_minor"] == 0
    assert response.json()["debit_posted_minor"] == 0
    assert response.json()["credit_posted_minor"] == 0


def test_successful_transfer_creates_one_transaction_and_two_entries() -> None:
    source = create_account(code="source", allow_negative=True)
    destination = create_account(code="destination")

    response = post_transfer(source["id"], destination["id"], amount_minor=125)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "POSTED"
    assert body["amount_minor"] == 125
    assert len(body["ledger_entries"]) == 2
    assert scalar("SELECT count(*) FROM transactions;") == 1
    assert scalar("SELECT count(*) FROM ledger_entries;") == 2


def test_successful_transfer_updates_balances_correctly() -> None:
    source = create_account(code="source-balances", allow_negative=True)
    destination = create_account(code="destination-balances")

    post_response = post_transfer(source["id"], destination["id"], amount_minor=250)
    assert post_response.status_code == 201

    source_balance = client.get(f"/api/v1/accounts/{source['id']}/balance").json()
    destination_balance = client.get(f"/api/v1/accounts/{destination['id']}/balance").json()

    assert source_balance["credit_posted_minor"] == 250
    assert source_balance["balance_minor"] == -250
    assert destination_balance["debit_posted_minor"] == 250
    assert destination_balance["balance_minor"] == 250


def test_every_posted_transaction_balances() -> None:
    source = create_account(code="source-balanced", allow_negative=True)
    destination = create_account(code="destination-balanced")
    response = post_transfer(source["id"], destination["id"], amount_minor=900)
    assert response.status_code == 201

    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """
            SELECT
                sum(CASE WHEN side = 'DEBIT' THEN amount_minor ELSE 0 END) AS debit_total,
                sum(CASE WHEN side = 'CREDIT' THEN amount_minor ELSE 0 END) AS credit_total
            FROM ledger_entries
            WHERE transaction_id = %s;
            """,
            (response.json()["id"],),
        ).fetchone()

    assert row[0] == row[1] == 900


def test_insufficient_funds_rejects_transfer_and_creates_no_ledger_entries() -> None:
    source = create_account(code="source-no-funds", allow_negative=False)
    destination = create_account(code="destination-no-funds")

    response = post_transfer(source["id"], destination["id"], amount_minor=1)

    assert response.status_code == 409
    assert response.json()["error_code"] == "insufficient_funds"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_duplicate_idempotency_key_same_request_replays_without_double_posting() -> None:
    source = create_account(code="source-idem", allow_negative=True)
    destination = create_account(code="destination-idem")
    key = f"idem-{uuid4()}"

    first = post_transfer(source["id"], destination["id"], amount_minor=77, key=key)
    second = post_transfer(source["id"], destination["id"], amount_minor=77, key=key)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert scalar("SELECT count(*) FROM transactions;") == 1
    assert scalar("SELECT count(*) FROM ledger_entries;") == 2
    assert client.get(f"/api/v1/accounts/{destination['id']}/balance").json()["balance_minor"] == 77


def test_duplicate_idempotency_key_different_request_returns_conflict() -> None:
    source = create_account(code="source-idem-conflict", allow_negative=True)
    destination = create_account(code="destination-idem-conflict")
    key = f"idem-{uuid4()}"

    first = post_transfer(source["id"], destination["id"], amount_minor=44, key=key)
    second = post_transfer(source["id"], destination["id"], amount_minor=45, key=key)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_code"] == "idempotency_conflict"
    assert scalar("SELECT count(*) FROM transactions;") == 1
    assert scalar("SELECT count(*) FROM ledger_entries;") == 2


def test_missing_idempotency_key_returns_top_level_error() -> None:
    source = create_account(code="source-missing-idempotency", allow_negative=True)
    destination = create_account(code="destination-missing-idempotency")

    response = client.post(
        "/api/v1/transfers",
        json={
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount_minor": 10,
            "currency": "USD",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "invalid_idempotency_key",
        "message": "Idempotency-Key header must not be empty.",
    }
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_blank_idempotency_key_returns_top_level_error() -> None:
    source = create_account(code="source-blank-idempotency", allow_negative=True)
    destination = create_account(code="destination-blank-idempotency")

    response = post_transfer(source["id"], destination["id"], amount_minor=10, key=" ")

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_idempotency_key"
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_same_account_transfer_is_rejected_without_mutation() -> None:
    account = create_account(code="same-account", allow_negative=True)

    response = post_transfer(account["id"], account["id"], amount_minor=10)

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "same_account_transfer_not_allowed",
        "message": "source_account_id and destination_account_id must be different.",
    }
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_invalid_source_account_returns_error_and_no_mutation() -> None:
    destination = create_account(code="valid-destination")

    response = post_transfer(str(uuid4()), destination["id"], amount_minor=10)

    assert response.status_code == 404
    assert response.json()["error_code"] == "source_account_not_found"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0
    assert client.get(f"/api/v1/accounts/{destination['id']}/balance").json()["balance_minor"] == 0


def test_invalid_destination_account_returns_error_and_no_mutation() -> None:
    source = create_account(code="valid-source", allow_negative=True)

    response = post_transfer(source["id"], str(uuid4()), amount_minor=10)

    assert response.status_code == 404
    assert response.json()["error_code"] == "destination_account_not_found"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0
    assert client.get(f"/api/v1/accounts/{source['id']}/balance").json()["balance_minor"] == 0


@pytest.mark.parametrize(
    ("source_status", "destination_status"),
    [
        ("FROZEN", "ACTIVE"),
        ("CLOSED", "ACTIVE"),
        ("ACTIVE", "FROZEN"),
        ("ACTIVE", "CLOSED"),
    ],
)
def test_frozen_or_closed_accounts_cannot_transfer(
    source_status: str,
    destination_status: str,
) -> None:
    source = create_account(code=f"source-{source_status}", allow_negative=True, status=source_status)
    destination = create_account(code=f"destination-{destination_status}", status=destination_status)

    response = post_transfer(source["id"], destination["id"], amount_minor=10)

    assert response.status_code == 409
    assert response.json()["error_code"].endswith("account_not_active")
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


@pytest.mark.parametrize("amount_minor", [0, -1])
def test_invalid_amount_zero_or_negative_fails_validation(amount_minor: int) -> None:
    source = create_account(code=f"source-invalid-amount-{amount_minor}", allow_negative=True)
    destination = create_account(code=f"destination-invalid-amount-{amount_minor}")

    response = post_transfer(source["id"], destination["id"], amount_minor=amount_minor)

    assert response.status_code == 422
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_currency_mismatch_fails() -> None:
    source = create_account(code="usd-source", currency="USD", allow_negative=True)
    destination = create_account(code="eur-destination", currency="EUR")

    response = post_transfer(source["id"], destination["id"], amount_minor=10, currency="USD")

    assert response.status_code == 409
    assert response.json()["error_code"] == "currency_mismatch"
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_credit_normal_accounts_cannot_use_transfer_api() -> None:
    source = create_account(code="source-credit-normal", normal_balance="CREDIT", allow_negative=True)
    destination = create_account(code="destination-credit-normal")

    response = post_transfer(source["id"], destination["id"], amount_minor=10)

    assert response.status_code == 409
    assert response.json()["error_code"] == "unsupported_transfer_account_type"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_non_asset_accounts_cannot_use_transfer_api() -> None:
    source = create_account(code="source-expense", account_type="EXPENSE", allow_negative=True)
    destination = create_account(code="destination-expense")

    response = post_transfer(source["id"], destination["id"], amount_minor=10)

    assert response.status_code == 409
    assert response.json()["error_code"] == "unsupported_transfer_account_type"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0


def test_duplicate_external_reference_returns_conflict_without_second_post() -> None:
    source = create_account(code="source-external-ref", allow_negative=True)
    destination = create_account(code="destination-external-ref")

    first = post_transfer(
        source["id"],
        destination["id"],
        amount_minor=10,
        external_ref="business-ref-001",
    )
    second = post_transfer(
        source["id"],
        destination["id"],
        amount_minor=20,
        external_ref="business-ref-001",
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_code"] == "duplicate_business_reference"
    assert scalar("SELECT count(*) FROM transactions;") == 1
    assert scalar("SELECT count(*) FROM ledger_entries;") == 2


def test_rollback_behavior_on_posting_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    source = create_account(code="source-rollback", allow_negative=True)
    destination = create_account(code="destination-rollback")

    from app.ledger.routes import service

    def fail_insert_ledger_entries(*args, **kwargs):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(service.repository, "insert_ledger_entries", fail_insert_ledger_entries)

    response = post_transfer(source["id"], destination["id"], amount_minor=10)

    assert response.status_code == 500
    assert response.json()["error_code"] == "posting_failed"
    assert scalar("SELECT count(*) FROM transactions;") == 0
    assert scalar("SELECT count(*) FROM ledger_entries;") == 0
    assert client.get(f"/api/v1/accounts/{source['id']}/balance").json()["balance_minor"] == 0
    assert client.get(f"/api/v1/accounts/{destination['id']}/balance").json()["balance_minor"] == 0


def test_account_balance_projection_equals_aggregate_ledger_entries() -> None:
    source = create_account(code="source-projection", allow_negative=True)
    destination = create_account(code="destination-projection")
    assert post_transfer(source["id"], destination["id"], amount_minor=10).status_code == 201
    assert post_transfer(source["id"], destination["id"], amount_minor=15).status_code == 201

    with psycopg.connect(DATABASE_URL) as conn:
        destination_projection = conn.execute(
            """
            SELECT
                sum(CASE WHEN side = 'DEBIT' THEN amount_minor ELSE 0 END)
                - sum(CASE WHEN side = 'CREDIT' THEN amount_minor ELSE 0 END)
            FROM ledger_entries
            WHERE account_id = %s;
            """,
            (destination["id"],),
        ).fetchone()[0]

    api_balance = client.get(f"/api/v1/accounts/{destination['id']}/balance").json()["balance_minor"]
    assert api_balance == destination_projection == 25


def test_ready_endpoint_still_checks_database_availability() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "connected"
    assert response.json()["database_check"] == 1


def test_api_validation_for_missing_fields_and_invalid_enums() -> None:
    missing_required = client.post(
        "/api/v1/accounts",
        json={
            "account_code": "missing-name",
            "account_type": "ASSET",
            "normal_balance": "DEBIT",
            "currency": "USD",
        },
    )
    invalid_enum = client.post(
        "/api/v1/accounts",
        json={
            "account_code": "bad-enum",
            "name": "bad enum",
            "account_type": "CASH",
            "normal_balance": "DEBIT",
            "currency": "USD",
        },
    )
    missing_transfer_field = client.post(
        "/api/v1/transfers",
        json={
            "destination_account_id": str(uuid4()),
            "amount_minor": 10,
            "currency": "USD",
        },
        headers={"Idempotency-Key": f"idem-{uuid4()}"},
    )

    assert missing_required.status_code == 422
    assert invalid_enum.status_code == 422
    assert missing_transfer_field.status_code == 422


def test_get_transaction_and_list_ledger_entries() -> None:
    source = create_account(code="source-read", allow_negative=True)
    destination = create_account(code="destination-read")
    transfer = post_transfer(source["id"], destination["id"], amount_minor=33)
    assert transfer.status_code == 201
    transaction_id = transfer.json()["id"]

    transaction_response = client.get(f"/api/v1/transactions/{transaction_id}")
    entries_response = client.get(f"/api/v1/ledger-entries?transaction_id={transaction_id}")

    assert transaction_response.status_code == 200
    assert transaction_response.json()["id"] == transaction_id
    assert entries_response.status_code == 200
    assert len(entries_response.json()["ledger_entries"]) == 2


def test_ledger_entries_are_database_immutable() -> None:
    source = create_account(code="source-immutable", allow_negative=True)
    destination = create_account(code="destination-immutable")
    transfer = post_transfer(source["id"], destination["id"], amount_minor=10)
    entry_id = transfer.json()["ledger_entries"][0]["id"]

    with psycopg.connect(DATABASE_URL) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute(
                    "UPDATE ledger_entries SET amount_minor = 11 WHERE id = %s;",
                    (entry_id,),
                )

    assert client.get(f"/api/v1/ledger-entries?transaction_id={transfer.json()['id']}").json()[
        "ledger_entries"
    ][0]["amount_minor"] == 10
