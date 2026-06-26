from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import get_connection
from app.ledger.enums import EntrySide, NormalBalance
from app.ledger.service import LedgerBusinessError
from app.migrations import ensure_schema


DEMO_TIMESTAMP = datetime(2026, 6, 23, 0, 0, 0, tzinfo=timezone.utc)
DEMO_SOURCE_SYSTEM = "P1_LEDGER_CONTROL_ROOM"

SETTLEMENT_CASH_ID = UUID("11111111-1111-4111-8111-111111111111")
SELLER_PAYABLE_ID = UUID("22222222-2222-4222-8222-222222222222")
CLEARING_FEE_REVENUE_ID = UUID("33333333-3333-4333-8333-333333333333")
COLLECT_BUYER_FUNDS_ID = UUID("44444444-4444-4444-8444-444444444444")
PAY_SELLER_ID = UUID("55555555-5555-4555-8555-555555555555")


@dataclass(frozen=True)
class Posting:
    account_id: UUID
    side: EntrySide
    amount_minor: int


class ControlRoomService:
    def summary(self) -> dict[str, Any]:
        ensure_schema()
        with get_connection() as conn:
            summary = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM accounts) AS account_count,
                    (SELECT count(*) FROM transactions) AS journal_entry_count,
                    (SELECT count(*) FROM ledger_entries) AS posting_count,
                    COALESCE(sum(CASE WHEN side = 'DEBIT' THEN amount_minor ELSE 0 END), 0) AS total_debits,
                    COALESCE(sum(CASE WHEN side = 'CREDIT' THEN amount_minor ELSE 0 END), 0) AS total_credits
                FROM ledger_entries;
                """
            ).fetchone()

            latest = self._latest_journal_entry(conn)

        total_debits = int(summary["total_debits"])
        total_credits = int(summary["total_credits"])
        return {
            "account_count": int(summary["account_count"]),
            "journal_entry_count": int(summary["journal_entry_count"]),
            "posting_count": int(summary["posting_count"]),
            "total_debits": total_debits,
            "total_credits": total_credits,
            "trial_balance_difference": total_debits - total_credits,
            "ledger_balanced": total_debits == total_credits,
            "latest_journal_entry": latest,
            "demo_state": {
                "scenario": "settlement_demo",
                "replayed": self._demo_has_been_replayed(total_debits, total_credits, latest),
                "currency": "USD",
            },
        }

    def accounts(self) -> list[dict[str, Any]]:
        ensure_schema()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.id AS account_id,
                    a.account_code,
                    a.name,
                    a.account_type,
                    a.normal_balance,
                    a.currency,
                    COALESCE(b.debit_posted_minor, 0) AS debit_total,
                    COALESCE(b.credit_posted_minor, 0) AS credit_total,
                    COALESCE(b.balance_minor, 0) AS ending_balance
                FROM accounts a
                LEFT JOIN account_balances b ON b.account_id = a.id
                ORDER BY a.account_code;
                """
            ).fetchall()

        return [self._account_row(row) for row in rows]

    def journal_entries(self, limit: int = 25) -> list[dict[str, Any]]:
        ensure_schema()
        with get_connection() as conn:
            transactions = conn.execute(
                """
                SELECT *
                FROM transactions
                ORDER BY COALESCE(posted_at, created_at) DESC, id
                LIMIT %s;
                """,
                (limit,),
            ).fetchall()

            entries = []
            for transaction in transactions:
                postings = conn.execute(
                    """
                    SELECT
                        le.account_id,
                        a.account_code,
                        a.name,
                        le.side,
                        le.amount_minor,
                        le.currency
                    FROM ledger_entries le
                    JOIN accounts a ON a.id = le.account_id
                    WHERE le.transaction_id = %s
                    ORDER BY le.entry_sequence;
                    """,
                    (transaction["id"],),
                ).fetchall()
                entries.append(self._journal_entry_row(transaction, postings))

        return entries

    def trial_balance(self) -> dict[str, Any]:
        rows = []
        total_debits = 0
        total_credits = 0

        for account in self.accounts():
            ending_balance = int(account["ending_balance"])
            debit_balance = 0
            credit_balance = 0
            if account["normal_side"] == NormalBalance.DEBIT.value:
                debit_balance = max(ending_balance, 0)
                credit_balance = abs(min(ending_balance, 0))
            else:
                credit_balance = max(ending_balance, 0)
                debit_balance = abs(min(ending_balance, 0))

            total_debits += debit_balance
            total_credits += credit_balance
            rows.append(
                {
                    **account,
                    "trial_debit_balance": debit_balance,
                    "trial_credit_balance": credit_balance,
                }
            )

        return {
            "rows": rows,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "difference": total_debits - total_credits,
            "balanced": total_debits == total_credits,
        }

    def reset_demo(self) -> dict[str, Any]:
        ensure_schema()
        with get_connection() as conn:
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
        return self.summary()

    def replay_settlement_demo(self) -> dict[str, Any]:
        self.reset_demo()
        ensure_schema()
        with get_connection() as conn:
            with conn.transaction():
                self._create_demo_accounts(conn)
                self._post_journal_entry(
                    conn,
                    transaction_id=COLLECT_BUYER_FUNDS_ID,
                    external_ref="control-room-demo-collect-buyer-funds",
                    description="Collect buyer funds for settlement",
                    postings=[
                        Posting(SETTLEMENT_CASH_ID, EntrySide.DEBIT, 10_005),
                        Posting(SELLER_PAYABLE_ID, EntrySide.CREDIT, 10_000),
                        Posting(CLEARING_FEE_REVENUE_ID, EntrySide.CREDIT, 5),
                    ],
                )
                self._post_journal_entry(
                    conn,
                    transaction_id=PAY_SELLER_ID,
                    external_ref="control-room-demo-pay-seller",
                    description="Pay seller from settlement cash",
                    postings=[
                        Posting(SELLER_PAYABLE_ID, EntrySide.DEBIT, 10_000),
                        Posting(SETTLEMENT_CASH_ID, EntrySide.CREDIT, 10_000),
                    ],
                )
                self._refresh_balances(conn)

        return self.summary()

    def _create_demo_accounts(self, conn) -> None:
        accounts = [
            (
                SETTLEMENT_CASH_ID,
                "demo-settlement-cash",
                "Settlement Cash",
                "ASSET",
                "DEBIT",
                "USD",
                False,
            ),
            (
                SELLER_PAYABLE_ID,
                "demo-seller-payable",
                "Seller Payable",
                "LIABILITY",
                "CREDIT",
                "USD",
                False,
            ),
            (
                CLEARING_FEE_REVENUE_ID,
                "demo-clearing-fee-revenue",
                "Clearing Fee Revenue",
                "REVENUE",
                "CREDIT",
                "USD",
                False,
            ),
        ]

        for account in accounts:
            conn.execute(
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
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s, %s);
                """,
                (*account, Jsonb({"demo_only": True, "scenario": "settlement_demo"}), DEMO_TIMESTAMP, DEMO_TIMESTAMP),
            )
            conn.execute(
                """
                INSERT INTO account_balances(account_id, currency, updated_at)
                VALUES (%s, %s, %s);
                """,
                (account[0], "USD", DEMO_TIMESTAMP),
            )

    def _post_journal_entry(
        self,
        conn,
        *,
        transaction_id: UUID,
        external_ref: str,
        description: str,
        postings: list[Posting],
    ) -> None:
        debit_total = sum(posting.amount_minor for posting in postings if posting.side == EntrySide.DEBIT)
        credit_total = sum(posting.amount_minor for posting in postings if posting.side == EntrySide.CREDIT)
        if debit_total <= 0 or debit_total != credit_total:
            raise LedgerBusinessError(
                409,
                "unbalanced_journal_entry",
                "Journal entry debits must equal credits and be positive.",
            )

        conn.execute(
            """
            INSERT INTO transactions (
                id,
                transaction_type,
                status,
                currency,
                amount_minor,
                description,
                external_ref,
                posted_at,
                created_at
            )
            VALUES (%s, 'JOURNAL_ENTRY', 'POSTED', 'USD', %s, %s, %s, %s, %s);
            """,
            (transaction_id, debit_total, description, external_ref, DEMO_TIMESTAMP, DEMO_TIMESTAMP),
        )
        conn.execute(
            """
            INSERT INTO external_references(id, source_system, external_ref, transaction_id, created_at)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (
                UUID(int=transaction_id.int + 10),
                DEMO_SOURCE_SYSTEM,
                external_ref,
                transaction_id,
                DEMO_TIMESTAMP,
            ),
        )

        for sequence, posting in enumerate(postings, start=1):
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
                    description,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, 'USD', %s, %s, %s);
                """,
                (
                    UUID(int=transaction_id.int + sequence),
                    transaction_id,
                    posting.account_id,
                    posting.side.value,
                    posting.amount_minor,
                    sequence,
                    description,
                    DEMO_TIMESTAMP,
                ),
            )

    def _refresh_balances(self, conn) -> None:
        conn.execute(
            """
            WITH posting_totals AS (
                SELECT
                    account_id,
                    COALESCE(sum(CASE WHEN side = 'DEBIT' THEN amount_minor ELSE 0 END), 0) AS debit_total,
                    COALESCE(sum(CASE WHEN side = 'CREDIT' THEN amount_minor ELSE 0 END), 0) AS credit_total
                FROM ledger_entries
                GROUP BY account_id
            )
            UPDATE account_balances b
            SET debit_posted_minor = COALESCE(t.debit_total, 0),
                credit_posted_minor = COALESCE(t.credit_total, 0),
                balance_minor = CASE
                    WHEN a.normal_balance = 'DEBIT'
                        THEN COALESCE(t.debit_total, 0) - COALESCE(t.credit_total, 0)
                    ELSE COALESCE(t.credit_total, 0) - COALESCE(t.debit_total, 0)
                END,
                version = version + 1,
                updated_at = %s
            FROM accounts a
            LEFT JOIN posting_totals t ON t.account_id = a.id
            WHERE b.account_id = a.id;
            """,
            (DEMO_TIMESTAMP,),
        )

    def _latest_journal_entry(self, conn) -> dict[str, Any] | None:
        latest = conn.execute(
            """
            SELECT *
            FROM transactions
            ORDER BY COALESCE(posted_at, created_at) DESC, id DESC
            LIMIT 1;
            """
        ).fetchone()
        if latest is None:
            return None
        postings = conn.execute(
            """
            SELECT
                le.account_id,
                a.account_code,
                a.name,
                le.side,
                le.amount_minor,
                le.currency
            FROM ledger_entries le
            JOIN accounts a ON a.id = le.account_id
            WHERE le.transaction_id = %s
            ORDER BY le.entry_sequence;
            """,
            (latest["id"],),
        ).fetchall()
        return self._journal_entry_row(latest, postings)

    def _journal_entry_row(self, transaction: dict[str, Any], postings: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "journal_entry_id": str(transaction["id"]),
            "transaction_reference": transaction["id"],
            "external_reference": transaction["external_ref"],
            "description": transaction["description"],
            "status": transaction["status"],
            "transaction_type": transaction["transaction_type"],
            "created_at": transaction["created_at"],
            "posted_at": transaction["posted_at"],
            "postings": [
                {
                    "account": f"{posting['account_code']} - {posting['name']}",
                    "account_id": str(posting["account_id"]),
                    "debit_amount": posting["amount_minor"] if posting["side"] == EntrySide.DEBIT.value else 0,
                    "credit_amount": posting["amount_minor"] if posting["side"] == EntrySide.CREDIT.value else 0,
                    "currency": posting["currency"],
                }
                for posting in postings
            ],
        }

    def _account_row(self, row: dict[str, Any]) -> dict[str, Any]:
        ending_balance = int(row["ending_balance"])
        normal_side = row["normal_balance"]
        side_label = normal_side if ending_balance >= 0 else self._opposite_side(normal_side)
        return {
            "account_id": str(row["account_id"]),
            "code": row["account_code"],
            "name": row["name"],
            "account_type": row["account_type"],
            "normal_side": normal_side,
            "currency": row["currency"],
            "debit_total": int(row["debit_total"]),
            "credit_total": int(row["credit_total"]),
            "ending_balance": ending_balance,
            "display_balance": f"{abs(ending_balance)} {row['currency']} {side_label}",
        }

    def _opposite_side(self, side: str) -> str:
        return EntrySide.CREDIT.value if side == EntrySide.DEBIT.value else EntrySide.DEBIT.value

    def _demo_has_been_replayed(
        self,
        total_debits: int,
        total_credits: int,
        latest: dict[str, Any] | None,
    ) -> bool:
        return (
            total_debits == 20_005
            and total_credits == 20_005
            and latest is not None
            and latest["external_reference"] in {"control-room-demo-collect-buyer-funds", "control-room-demo-pay-seller"}
        )
