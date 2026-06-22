from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ledger.enums import (
    AccountStatus,
    AccountType,
    EntrySide,
    NormalBalance,
    TransactionStatus,
    TransactionType,
)


def normalize_currency(value: str) -> str:
    currency = value.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter ISO-style uppercase code")
    return currency


class AccountCreateRequest(BaseModel):
    account_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    account_type: AccountType
    normal_balance: NormalBalance
    currency: str = Field(min_length=3, max_length=3)
    allow_negative: bool = False
    status: AccountStatus = AccountStatus.ACTIVE
    metadata: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_code: str
    name: str
    account_type: AccountType
    normal_balance: NormalBalance
    currency: str
    allow_negative: bool
    status: AccountStatus
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class AccountBalanceResponse(BaseModel):
    account_id: UUID
    currency: str
    debit_posted_minor: int
    credit_posted_minor: int
    balance_minor: int
    version: int
    updated_at: datetime


class TransferRequest(BaseModel):
    source_account_id: UUID
    destination_account_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=500)
    external_ref: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)


class LedgerEntryResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    account_id: UUID
    side: EntrySide
    amount_minor: int
    currency: str
    entry_sequence: int
    description: str | None
    created_at: datetime


class TransactionResponse(BaseModel):
    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    currency: str
    amount_minor: int
    source_account_id: UUID | None
    destination_account_id: UUID | None
    description: str | None
    external_ref: str | None
    idempotency_key: str | None
    posted_at: datetime | None
    created_at: datetime
    ledger_entries: list[LedgerEntryResponse] = Field(default_factory=list)


class LedgerEntriesResponse(BaseModel):
    ledger_entries: list[LedgerEntryResponse]
    limit: int
    offset: int
