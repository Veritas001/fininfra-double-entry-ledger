from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.ledger.enums import IdempotencyStatus
from app.ledger.schemas import AccountCreateRequest


class LedgerRepository:
    def create_account(
        self,
        conn: psycopg.Connection,
        account_id: UUID,
        request: AccountCreateRequest,
    ) -> dict[str, Any]:
        account = conn.execute(
            """
            INSERT INTO accounts (
                id,
                account_code,
                name,
                account_type,
                normal_balance,
                currency,
                allow_negative,
                status,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *;
            """,
            (
                account_id,
                request.account_code,
                request.name,
                request.account_type.value,
                request.normal_balance.value,
                request.currency,
                request.allow_negative,
                request.status.value,
                Jsonb(request.metadata) if request.metadata is not None else None,
            ),
        ).fetchone()

        conn.execute(
            """
            INSERT INTO account_balances(account_id, currency)
            VALUES (%s, %s);
            """,
            (account_id, request.currency),
        )
        return account

    def get_account(self, conn: psycopg.Connection, account_id: UUID) -> dict[str, Any] | None:
        return conn.execute(
            "SELECT * FROM accounts WHERE id = %s;",
            (account_id,),
        ).fetchone()

    def get_account_balance(
        self,
        conn: psycopg.Connection,
        account_id: UUID,
    ) -> dict[str, Any] | None:
        return conn.execute(
            "SELECT * FROM account_balances WHERE account_id = %s;",
            (account_id,),
        ).fetchone()

    def fetch_accounts_for_update(
        self,
        conn: psycopg.Connection,
        account_ids: list[UUID],
    ) -> dict[UUID, dict[str, Any]]:
        placeholders = ", ".join(["%s"] * len(account_ids))
        rows = conn.execute(
            f"SELECT * FROM accounts WHERE id IN ({placeholders});",
            tuple(account_ids),
        ).fetchall()
        return {row["id"]: row for row in rows}

    def lock_balances(
        self,
        conn: psycopg.Connection,
        account_ids: list[UUID],
    ) -> dict[UUID, dict[str, Any]]:
        ordered_ids = sorted(set(account_ids), key=str)
        placeholders = ", ".join(["%s"] * len(ordered_ids))
        rows = conn.execute(
            f"""
            SELECT *
            FROM account_balances
            WHERE account_id IN ({placeholders})
            ORDER BY account_id
            FOR UPDATE;
            """,
            tuple(ordered_ids),
        ).fetchall()
        return {row["account_id"]: row for row in rows}

    def create_transaction(
        self,
        conn: psycopg.Connection,
        *,
        transaction_id: UUID,
        amount_minor: int,
        currency: str,
        source_account_id: UUID,
        destination_account_id: UUID,
        description: str | None,
        external_ref: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return conn.execute(
            """
            INSERT INTO transactions (
                id,
                transaction_type,
                status,
                currency,
                amount_minor,
                source_account_id,
                destination_account_id,
                description,
                external_ref,
                idempotency_key,
                posted_at
            )
            VALUES (%s, 'TRANSFER', 'POSTED', %s, %s, %s, %s, %s, %s, %s, now())
            RETURNING *;
            """,
            (
                transaction_id,
                currency,
                amount_minor,
                source_account_id,
                destination_account_id,
                description,
                external_ref,
                idempotency_key,
            ),
        ).fetchone()

    def create_external_reference(
        self,
        conn: psycopg.Connection,
        *,
        source_system: str,
        external_ref: str,
        transaction_id: UUID,
    ) -> bool:
        row = conn.execute(
            """
            INSERT INTO external_references(id, source_system, external_ref, transaction_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_system, external_ref) DO NOTHING
            RETURNING id;
            """,
            (uuid4(), source_system, external_ref, transaction_id),
        ).fetchone()
        return row is not None

    def insert_ledger_entries(
        self,
        conn: psycopg.Connection,
        *,
        transaction_id: UUID,
        destination_account_id: UUID,
        source_account_id: UUID,
        amount_minor: int,
        currency: str,
        description: str | None,
    ) -> list[dict[str, Any]]:
        rows = []
        entries = [
            (uuid4(), transaction_id, destination_account_id, "DEBIT", amount_minor, currency, 1, description),
            (uuid4(), transaction_id, source_account_id, "CREDIT", amount_minor, currency, 2, description),
        ]
        for entry in entries:
            rows.append(
                conn.execute(
                    """
                    INSERT INTO ledger_entries (
                        id,
                        transaction_id,
                        account_id,
                        side,
                        amount_minor,
                        currency,
                        entry_sequence,
                        description
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *;
                    """,
                    entry,
                ).fetchone()
            )
        return rows

    def update_account_balance(
        self,
        conn: psycopg.Connection,
        *,
        account_id: UUID,
        debit_posted_minor: int,
        credit_posted_minor: int,
        balance_minor: int,
    ) -> dict[str, Any]:
        return conn.execute(
            """
            UPDATE account_balances
            SET debit_posted_minor = %s,
                credit_posted_minor = %s,
                balance_minor = %s,
                version = version + 1,
                updated_at = now()
            WHERE account_id = %s
            RETURNING *;
            """,
            (debit_posted_minor, credit_posted_minor, balance_minor, account_id),
        ).fetchone()

    def get_transaction(
        self,
        conn: psycopg.Connection,
        transaction_id: UUID,
    ) -> dict[str, Any] | None:
        return conn.execute(
            "SELECT * FROM transactions WHERE id = %s;",
            (transaction_id,),
        ).fetchone()

    def get_transaction_entries(
        self,
        conn: psycopg.Connection,
        transaction_id: UUID,
    ) -> list[dict[str, Any]]:
        return conn.execute(
            """
            SELECT *
            FROM ledger_entries
            WHERE transaction_id = %s
            ORDER BY entry_sequence;
            """,
            (transaction_id,),
        ).fetchall()

    def list_ledger_entries(
        self,
        conn: psycopg.Connection,
        *,
        account_id: UUID | None,
        transaction_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        filters = []
        params: list[Any] = []

        if account_id is not None:
            filters.append("account_id = %s")
            params.append(account_id)
        if transaction_id is not None:
            filters.append("transaction_id = %s")
            params.append(transaction_id)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])

        return conn.execute(
            f"""
            SELECT *
            FROM ledger_entries
            {where_clause}
            ORDER BY created_at, transaction_id, entry_sequence
            LIMIT %s OFFSET %s;
            """,
            tuple(params),
        ).fetchall()

    def insert_idempotency_processing(
        self,
        conn: psycopg.Connection,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> bool:
        row = conn.execute(
            """
            INSERT INTO idempotency_records(idempotency_key, request_hash, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING idempotency_key;
            """,
            (idempotency_key, request_hash, IdempotencyStatus.PROCESSING.value),
        ).fetchone()
        return row is not None

    def get_idempotency_record(
        self,
        conn: psycopg.Connection,
        *,
        idempotency_key: str,
        lock: bool = False,
        nowait: bool = False,
    ) -> dict[str, Any] | None:
        lock_clause = ""
        if lock:
            lock_clause = " FOR UPDATE"
            if nowait:
                lock_clause += " NOWAIT"

        return conn.execute(
            f"""
            SELECT *
            FROM idempotency_records
            WHERE idempotency_key = %s
            {lock_clause};
            """,
            (idempotency_key,),
        ).fetchone()

    def mark_idempotency_succeeded(
        self,
        conn: psycopg.Connection,
        *,
        idempotency_key: str,
        transaction_id: UUID,
        response_code: int,
        response_body: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            UPDATE idempotency_records
            SET status = %s,
                transaction_id = %s,
                response_code = %s,
                response_body = %s,
                error_code = NULL,
                updated_at = now()
            WHERE idempotency_key = %s;
            """,
            (
                IdempotencyStatus.SUCCEEDED.value,
                transaction_id,
                response_code,
                Jsonb(response_body),
                idempotency_key,
            ),
        )

    def mark_idempotency_failed(
        self,
        conn: psycopg.Connection,
        *,
        idempotency_key: str,
        response_code: int,
        response_body: dict[str, Any],
        error_code: str,
    ) -> None:
        conn.execute(
            """
            UPDATE idempotency_records
            SET status = %s,
                response_code = %s,
                response_body = %s,
                error_code = %s,
                updated_at = now()
            WHERE idempotency_key = %s;
            """,
            (
                IdempotencyStatus.FAILED.value,
                response_code,
                Jsonb(response_body),
                error_code,
                idempotency_key,
            ),
        )

    def insert_audit_event(
        self,
        conn: psycopg.Connection,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        event_payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_events(id, event_type, entity_type, entity_id, event_payload)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (uuid4(), event_type, entity_type, entity_id, Jsonb(event_payload)),
        )
