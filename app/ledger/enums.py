from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class NormalBalance(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class TransactionType(StrEnum):
    TRANSFER = "TRANSFER"


class TransactionStatus(StrEnum):
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class EntrySide(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
