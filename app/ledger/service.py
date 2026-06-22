import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from psycopg.errors import LockNotAvailable, UniqueViolation

from app.db import get_connection
from app.ledger.enums import AccountStatus, AccountType, EntrySide, IdempotencyStatus, NormalBalance
from app.ledger.repository import LedgerRepository
from app.ledger.schemas import (
    AccountBalanceResponse,
    AccountCreateRequest,
    AccountResponse,
    LedgerEntriesResponse,
    TransactionResponse,
    TransferRequest,
)
from app.migrations import ensure_schema


@dataclass(frozen=True)
class ServiceResponse:
    status_code: int
    body: dict[str, Any]


class LedgerBusinessError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(message)

    @property
    def body(self) -> dict[str, str]:
        return {"error_code": self.error_code, "message": self.message}


class LedgerService:
    def __init__(self, repository: LedgerRepository | None = None) -> None:
        self.repository = repository or LedgerRepository()

    def create_account(self, request: AccountCreateRequest) -> AccountResponse:
        ensure_schema()
        account_id = uuid4()

        try:
            with get_connection() as conn:
                with conn.transaction():
                    account = self.repository.create_account(conn, account_id, request)
                    self.repository.insert_audit_event(
                        conn,
                        event_type="ACCOUNT_CREATED",
                        entity_type="account",
                        entity_id=str(account_id),
                        event_payload={"account_code": request.account_code},
                    )
                    return AccountResponse.model_validate(account)
        except UniqueViolation as exc:
            raise LedgerBusinessError(
                409,
                "duplicate_account_code",
                "An account with this account_code already exists.",
            ) from exc

    def get_account(self, account_id: UUID) -> AccountResponse | None:
        ensure_schema()
        with get_connection() as conn:
            account = self.repository.get_account(conn, account_id)
        if account is None:
            return None
        return AccountResponse.model_validate(account)

    def get_account_balance(self, account_id: UUID) -> AccountBalanceResponse | None:
        ensure_schema()
        with get_connection() as conn:
            balance = self.repository.get_account_balance(conn, account_id)
        if balance is None:
            return None
        return AccountBalanceResponse.model_validate(balance)

    def post_transfer(
        self,
        request: TransferRequest,
        idempotency_key: str | None,
    ) -> ServiceResponse:
        ensure_schema()

        if request.source_account_id == request.destination_account_id:
            return ServiceResponse(
                status_code=422,
                body={
                    "error_code": "same_account_transfer_not_allowed",
                    "message": "source_account_id and destination_account_id must be different.",
                },
            )

        normalized_idempotency_key = idempotency_key.strip() if idempotency_key is not None else ""
        if not normalized_idempotency_key:
            return ServiceResponse(
                status_code=422,
                body={
                    "error_code": "invalid_idempotency_key",
                    "message": "Idempotency-Key header must not be empty.",
                },
            )

        request_hash = self._request_hash(request)
        reservation = self._reserve_idempotency(normalized_idempotency_key, request_hash)
        if reservation is not None:
            return reservation

        try:
            return self._post_reserved_transfer(request, normalized_idempotency_key, request_hash)
        except LedgerBusinessError as exc:
            self._mark_idempotency_failed(normalized_idempotency_key, exc.status_code, exc.body, exc.error_code)
            return ServiceResponse(status_code=exc.status_code, body=exc.body)
        except Exception:
            body = {
                "error_code": "posting_failed",
                "message": "Transfer could not be posted.",
            }
            self._mark_idempotency_failed(normalized_idempotency_key, 500, body, "posting_failed")
            return ServiceResponse(status_code=500, body=body)

    def get_transaction(self, transaction_id: UUID) -> TransactionResponse | None:
        ensure_schema()
        with get_connection() as conn:
            return self._transaction_response(conn, transaction_id)

    def list_ledger_entries(
        self,
        *,
        account_id: UUID | None,
        transaction_id: UUID | None,
        limit: int,
        offset: int,
    ) -> LedgerEntriesResponse:
        ensure_schema()
        with get_connection() as conn:
            rows = self.repository.list_ledger_entries(
                conn,
                account_id=account_id,
                transaction_id=transaction_id,
                limit=limit,
                offset=offset,
            )
        return LedgerEntriesResponse(
            ledger_entries=rows,
            limit=limit,
            offset=offset,
        )

    def _reserve_idempotency(
        self,
        idempotency_key: str,
        request_hash: str,
    ) -> ServiceResponse | None:
        try:
            with get_connection() as conn:
                with conn.transaction():
                    inserted = self.repository.insert_idempotency_processing(
                        conn,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    )
                    if inserted:
                        return None

                    record = self.repository.get_idempotency_record(
                        conn,
                        idempotency_key=idempotency_key,
                        lock=True,
                        nowait=True,
                    )
        except LockNotAvailable:
            return ServiceResponse(
                status_code=409,
                body={
                    "error_code": "idempotency_processing",
                    "message": "A request with this Idempotency-Key is still processing.",
                },
            )

        if record is None:
            return ServiceResponse(
                status_code=409,
                body={
                    "error_code": "idempotency_unavailable",
                    "message": "Idempotency record is unavailable.",
                },
            )

        if record["request_hash"] != request_hash:
            return ServiceResponse(
                status_code=409,
                body={
                    "error_code": "idempotency_conflict",
                    "message": "Idempotency-Key was already used for a different request.",
                },
            )

        if record["status"] == IdempotencyStatus.SUCCEEDED.value:
            return ServiceResponse(
                status_code=200,
                body=jsonable_encoder(record["response_body"]),
            )

        if record["status"] == IdempotencyStatus.PROCESSING.value:
            return ServiceResponse(
                status_code=409,
                body={
                    "error_code": "idempotency_processing",
                    "message": "A request with this Idempotency-Key is still processing.",
                },
            )

        return ServiceResponse(
            status_code=record["response_code"] or 409,
            body=jsonable_encoder(
                record["response_body"]
                or {
                    "error_code": record["error_code"] or "idempotency_failed",
                    "message": "A prior request with this Idempotency-Key failed.",
                }
            ),
        )

    def _post_reserved_transfer(
        self,
        request: TransferRequest,
        idempotency_key: str,
        request_hash: str,
    ) -> ServiceResponse:
        transaction_id = uuid4()

        with get_connection() as conn:
            with conn.transaction():
                record = self.repository.get_idempotency_record(
                    conn,
                    idempotency_key=idempotency_key,
                    lock=True,
                    nowait=False,
                )
                if record is None or record["request_hash"] != request_hash:
                    raise LedgerBusinessError(
                        409,
                        "idempotency_conflict",
                        "Idempotency reservation changed before posting.",
                    )
                if record["status"] != IdempotencyStatus.PROCESSING.value:
                    raise LedgerBusinessError(
                        409,
                        "idempotency_conflict",
                        "Idempotency-Key is not available for posting.",
                    )

                accounts = self.repository.fetch_accounts_for_update(
                    conn,
                    [request.source_account_id, request.destination_account_id],
                )
                source = accounts.get(request.source_account_id)
                destination = accounts.get(request.destination_account_id)
                if source is None:
                    raise LedgerBusinessError(404, "source_account_not_found", "Source account was not found.")
                if destination is None:
                    raise LedgerBusinessError(
                        404,
                        "destination_account_not_found",
                        "Destination account was not found.",
                    )

                balances = self.repository.lock_balances(
                    conn,
                    [request.source_account_id, request.destination_account_id],
                )
                if request.source_account_id not in balances or request.destination_account_id not in balances:
                    raise LedgerBusinessError(
                        409,
                        "balance_missing",
                        "One or more account balance rows are missing.",
                    )

                self._validate_account_for_transfer(source, "source")
                self._validate_account_for_transfer(destination, "destination")
                self._validate_transfer_account_scope(source)
                self._validate_transfer_account_scope(destination)
                self._validate_currency(source, destination, request.currency)

                transaction = self.repository.create_transaction(
                    conn,
                    transaction_id=transaction_id,
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                    source_account_id=request.source_account_id,
                    destination_account_id=request.destination_account_id,
                    description=request.description,
                    external_ref=request.external_ref,
                    idempotency_key=idempotency_key,
                )

                if request.external_ref is not None:
                    inserted = self.repository.create_external_reference(
                        conn,
                        source_system="P1_TRANSFER_API",
                        external_ref=request.external_ref,
                        transaction_id=transaction_id,
                    )
                    if not inserted:
                        raise LedgerBusinessError(
                            409,
                            "duplicate_business_reference",
                            "external_ref has already been posted.",
                        )

                entries = self.repository.insert_ledger_entries(
                    conn,
                    transaction_id=transaction_id,
                    destination_account_id=request.destination_account_id,
                    source_account_id=request.source_account_id,
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                    description=request.description,
                )
                self._assert_entries_balance(entries)

                projected = self._project_balances(
                    accounts=accounts,
                    balances=balances,
                    entries=entries,
                )
                for account_id, projected_balance in projected.items():
                    self.repository.update_account_balance(
                        conn,
                        account_id=account_id,
                        debit_posted_minor=projected_balance["debit_posted_minor"],
                        credit_posted_minor=projected_balance["credit_posted_minor"],
                        balance_minor=projected_balance["balance_minor"],
                    )

                self.repository.insert_audit_event(
                    conn,
                    event_type="TRANSFER_POSTED",
                    entity_type="transaction",
                    entity_id=str(transaction_id),
                    event_payload={
                        "amount_minor": request.amount_minor,
                        "currency": request.currency,
                        "source_account_id": str(request.source_account_id),
                        "destination_account_id": str(request.destination_account_id),
                    },
                )

                transaction["ledger_entries"] = entries
                body = TransactionResponse.model_validate(transaction).model_dump(mode="json")
                self.repository.mark_idempotency_succeeded(
                    conn,
                    idempotency_key=idempotency_key,
                    transaction_id=transaction_id,
                    response_code=201,
                    response_body=body,
                )

        return ServiceResponse(status_code=201, body=body)

    def _mark_idempotency_failed(
        self,
        idempotency_key: str,
        status_code: int,
        body: dict[str, Any],
        error_code: str,
    ) -> None:
        with get_connection() as conn:
            with conn.transaction():
                self.repository.mark_idempotency_failed(
                    conn,
                    idempotency_key=idempotency_key,
                    response_code=status_code,
                    response_body=body,
                    error_code=error_code,
                )

    def _transaction_response(
        self,
        conn,
        transaction_id: UUID,
    ) -> TransactionResponse | None:
        transaction = self.repository.get_transaction(conn, transaction_id)
        if transaction is None:
            return None

        transaction["ledger_entries"] = self.repository.get_transaction_entries(conn, transaction_id)
        return TransactionResponse.model_validate(transaction)

    def _request_hash(self, request: TransferRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _validate_account_for_transfer(self, account: dict[str, Any], role: str) -> None:
        if account["status"] != AccountStatus.ACTIVE.value:
            raise LedgerBusinessError(
                409,
                f"{role}_account_not_active",
                f"{role.capitalize()} account is {account['status']}.",
            )

    def _validate_transfer_account_scope(self, account: dict[str, Any]) -> None:
        if (
            account["account_type"] != AccountType.ASSET.value
            or account["normal_balance"] != NormalBalance.DEBIT.value
        ):
            raise LedgerBusinessError(
                409,
                "unsupported_transfer_account_type",
                "P1 transfers require ASSET accounts with DEBIT normal balance.",
            )

    def _validate_currency(
        self,
        source: dict[str, Any],
        destination: dict[str, Any],
        request_currency: str,
    ) -> None:
        if source["currency"] != request_currency or destination["currency"] != request_currency:
            raise LedgerBusinessError(
                409,
                "currency_mismatch",
                "Source account, destination account, and transfer currency must match.",
            )

    def _assert_entries_balance(self, entries: list[dict[str, Any]]) -> None:
        debit_total = sum(
            entry["amount_minor"] for entry in entries if entry["side"] == EntrySide.DEBIT.value
        )
        credit_total = sum(
            entry["amount_minor"] for entry in entries if entry["side"] == EntrySide.CREDIT.value
        )
        if debit_total != credit_total:
            raise LedgerBusinessError(
                409,
                "unbalanced_transaction",
                "Total debit entries must equal total credit entries.",
            )

    def _project_balances(
        self,
        *,
        accounts: dict[UUID, dict[str, Any]],
        balances: dict[UUID, dict[str, Any]],
        entries: list[dict[str, Any]],
    ) -> dict[UUID, dict[str, int]]:
        projected = {
            account_id: {
                "debit_posted_minor": int(balance["debit_posted_minor"]),
                "credit_posted_minor": int(balance["credit_posted_minor"]),
            }
            for account_id, balance in balances.items()
        }

        for entry in entries:
            account_projection = projected[entry["account_id"]]
            if entry["side"] == EntrySide.DEBIT.value:
                account_projection["debit_posted_minor"] += entry["amount_minor"]
            else:
                account_projection["credit_posted_minor"] += entry["amount_minor"]

        for account_id, account_projection in projected.items():
            account = accounts[account_id]
            debit_posted = account_projection["debit_posted_minor"]
            credit_posted = account_projection["credit_posted_minor"]
            if account["normal_balance"] == NormalBalance.DEBIT.value:
                balance_minor = debit_posted - credit_posted
            else:
                balance_minor = credit_posted - debit_posted

            if not account["allow_negative"] and balance_minor < 0:
                raise LedgerBusinessError(
                    409,
                    "insufficient_funds",
                    "Transfer would make an account balance negative.",
                )

            account_projection["balance_minor"] = balance_minor

        return projected
