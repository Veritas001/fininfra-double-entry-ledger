DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'account_type') THEN
        CREATE TYPE account_type AS ENUM ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'normal_balance') THEN
        CREATE TYPE normal_balance AS ENUM ('DEBIT', 'CREDIT');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'account_status') THEN
        CREATE TYPE account_status AS ENUM ('ACTIVE', 'FROZEN', 'CLOSED');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transaction_type') THEN
        CREATE TYPE transaction_type AS ENUM ('TRANSFER');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transaction_status') THEN
        CREATE TYPE transaction_status AS ENUM ('POSTED', 'REJECTED', 'FAILED');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entry_side') THEN
        CREATE TYPE entry_side AS ENUM ('DEBIT', 'CREDIT');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'idempotency_status') THEN
        CREATE TYPE idempotency_status AS ENUM ('PROCESSING', 'SUCCEEDED', 'FAILED');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY,
    account_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    account_type account_type NOT NULL,
    normal_balance normal_balance NOT NULL,
    currency VARCHAR(3) NOT NULL,
    allow_negative BOOLEAN NOT NULL DEFAULT FALSE,
    status account_status NOT NULL DEFAULT 'ACTIVE',
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT accounts_currency_format CHECK (currency = upper(currency) AND currency ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS account_balances (
    account_id UUID PRIMARY KEY REFERENCES accounts(id),
    currency VARCHAR(3) NOT NULL,
    debit_posted_minor BIGINT NOT NULL DEFAULT 0,
    credit_posted_minor BIGINT NOT NULL DEFAULT 0,
    balance_minor BIGINT NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_balances_currency_format CHECK (currency = upper(currency) AND currency ~ '^[A-Z]{3}$'),
    CONSTRAINT account_balances_debits_nonnegative CHECK (debit_posted_minor >= 0),
    CONSTRAINT account_balances_credits_nonnegative CHECK (credit_posted_minor >= 0),
    CONSTRAINT account_balances_version_nonnegative CHECK (version >= 0)
);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY,
    transaction_type transaction_type NOT NULL,
    status transaction_status NOT NULL,
    currency VARCHAR(3) NOT NULL,
    amount_minor BIGINT NOT NULL,
    source_account_id UUID REFERENCES accounts(id),
    destination_account_id UUID REFERENCES accounts(id),
    description TEXT,
    external_ref TEXT,
    idempotency_key TEXT,
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transactions_amount_positive CHECK (amount_minor > 0),
    CONSTRAINT transactions_currency_format CHECK (currency = upper(currency) AND currency ~ '^[A-Z]{3}$')
);

DROP INDEX IF EXISTS transactions_external_ref_unique;

CREATE TABLE IF NOT EXISTS ledger_entries (
    id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    account_id UUID NOT NULL REFERENCES accounts(id),
    side entry_side NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    entry_sequence INTEGER NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ledger_entries_amount_positive CHECK (amount_minor > 0),
    CONSTRAINT ledger_entries_currency_format CHECK (currency = upper(currency) AND currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ledger_entries_sequence_positive CHECK (entry_sequence > 0),
    CONSTRAINT ledger_entries_transaction_sequence_unique UNIQUE (transaction_id, entry_sequence)
);

CREATE INDEX IF NOT EXISTS ledger_entries_account_created_idx
    ON ledger_entries(account_id, created_at);

CREATE INDEX IF NOT EXISTS ledger_entries_transaction_idx
    ON ledger_entries(transaction_id);

CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    status idempotency_status NOT NULL,
    transaction_id UUID REFERENCES transactions(id),
    response_code INTEGER,
    response_body JSONB,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS external_references (
    id UUID PRIMARY KEY,
    source_system TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT external_references_source_ref_unique UNIQUE (source_system, external_ref)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION prevent_ledger_entry_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ledger_entries_no_update ON ledger_entries;
CREATE TRIGGER ledger_entries_no_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW
    EXECUTE FUNCTION prevent_ledger_entry_mutation();

DROP TRIGGER IF EXISTS ledger_entries_no_delete ON ledger_entries;
CREATE TRIGGER ledger_entries_no_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW
    EXECUTE FUNCTION prevent_ledger_entry_mutation();
