from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from app.ledger.schemas import (
    AccountBalanceResponse,
    AccountCreateRequest,
    AccountResponse,
    LedgerEntriesResponse,
    TransactionResponse,
    TransferRequest,
)
from app.ledger.service import LedgerBusinessError, LedgerService


router = APIRouter(prefix="/api/v1", tags=["ledger"])
service = LedgerService()


@router.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(request: AccountCreateRequest) -> AccountResponse | JSONResponse:
    try:
        return service.create_account(request)
    except LedgerBusinessError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.body)


@router.get("/accounts/{account_id}", response_model=AccountResponse)
def get_account(account_id: UUID) -> AccountResponse | JSONResponse:
    account = service.get_account(account_id)
    if account is None:
        return JSONResponse(
            status_code=404,
            content={"error_code": "account_not_found", "message": "Account not found."},
        )
    return account


@router.get("/accounts/{account_id}/balance", response_model=AccountBalanceResponse)
def get_account_balance(account_id: UUID) -> AccountBalanceResponse | JSONResponse:
    balance = service.get_account_balance(account_id)
    if balance is None:
        return JSONResponse(
            status_code=404,
            content={"error_code": "account_not_found", "message": "Account not found."},
        )
    return balance


@router.post("/transfers", response_model=TransactionResponse)
def post_transfer(
    request: TransferRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    result = service.post_transfer(request, idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body)


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: UUID) -> TransactionResponse | JSONResponse:
    transaction = service.get_transaction(transaction_id)
    if transaction is None:
        return JSONResponse(
            status_code=404,
            content={"error_code": "transaction_not_found", "message": "Transaction not found."},
        )
    return transaction


@router.get("/ledger-entries", response_model=LedgerEntriesResponse)
def list_ledger_entries(
    account_id: UUID | None = None,
    transaction_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LedgerEntriesResponse:
    return service.list_ledger_entries(
        account_id=account_id,
        transaction_id=transaction_id,
        limit=limit,
        offset=offset,
    )
