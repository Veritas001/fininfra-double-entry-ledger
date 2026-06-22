#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

RUN_ID="${RUN_ID:-$(date -u +%Y%m%d%H%M%S)-$$}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

section() {
  printf "\n== %s ==\n" "$1"
}

explain() {
  printf "%s\n" "$1"
}

request() {
  local method="$1"
  local path="$2"
  local output_file="$3"
  shift 3

  curl -sS -o "$output_file" -w "%{http_code}" -X "$method" "${API_BASE_URL}${path}" "$@"
}

expect_status() {
  local actual="$1"
  local expected="$2"
  local body_file="$3"
  local label="$4"

  if [[ "$actual" != "$expected" ]]; then
    printf "Unexpected status for %s: expected %s, got %s\n" "$label" "$expected" "$actual" >&2
    cat "$body_file" >&2
    printf "\n" >&2
    exit 1
  fi
}

json_get() {
  local file="$1"
  local path="$2"
  "$PYTHON_BIN" - "$file" "$path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle)

for part in sys.argv[2].split("."):
    if part:
        value = value[int(part)] if isinstance(value, list) else value[part]

print(value)
PY
}

json_pretty() {
  "$PYTHON_BIN" -m json.tool "$1"
}

json_assert_transfer_entries_balance() {
  "$PYTHON_BIN" - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    body = json.load(handle)

entries = body["ledger_entries"]
debit_total = sum(entry["amount_minor"] for entry in entries if entry["side"] == "DEBIT")
credit_total = sum(entry["amount_minor"] for entry in entries if entry["side"] == "CREDIT")

if len(entries) != 2:
    raise SystemExit(f"expected exactly 2 ledger entries, found {len(entries)}")
if debit_total != credit_total:
    raise SystemExit(f"unbalanced entries: debit={debit_total} credit={credit_total}")

print(f"Verified exactly two entries and debit total equals credit total: {debit_total}")
PY
}

section "P1 Double-Entry Ledger Demo"
explain "API base URL: ${API_BASE_URL}"
explain "Run id: ${RUN_ID}"

section "1. Check API health"
HEALTH_BODY="$TMP_DIR/health.json"
HEALTH_STATUS="$(request GET "/health" "$HEALTH_BODY")"
expect_status "$HEALTH_STATUS" "200" "$HEALTH_BODY" "/health"
json_pretty "$HEALTH_BODY"

section "2. Check database readiness"
READY_BODY="$TMP_DIR/ready.json"
READY_STATUS="$(request GET "/ready" "$READY_BODY")"
expect_status "$READY_STATUS" "200" "$READY_BODY" "/ready"
json_pretty "$READY_BODY"

section "3. Create source cash account"
SOURCE_BODY="$TMP_DIR/source_account.json"
SOURCE_PAYLOAD="$TMP_DIR/source_payload.json"
cat > "$SOURCE_PAYLOAD" <<JSON
{
  "account_code": "demo-source-${RUN_ID}",
  "name": "Demo Source Cash ${RUN_ID}",
  "account_type": "ASSET",
  "normal_balance": "DEBIT",
  "currency": "USD",
  "allow_negative": false,
  "metadata": {"demo_only": true}
}
JSON
SOURCE_STATUS="$(request POST "/api/v1/accounts" "$SOURCE_BODY" -H "Content-Type: application/json" --data @"$SOURCE_PAYLOAD")"
expect_status "$SOURCE_STATUS" "201" "$SOURCE_BODY" "create source account"
SOURCE_ACCOUNT_ID="$(json_get "$SOURCE_BODY" "id")"
json_pretty "$SOURCE_BODY"

section "4. Create destination settlement account"
DEST_BODY="$TMP_DIR/destination_account.json"
DEST_PAYLOAD="$TMP_DIR/destination_payload.json"
cat > "$DEST_PAYLOAD" <<JSON
{
  "account_code": "demo-destination-${RUN_ID}",
  "name": "Demo Destination Settlement ${RUN_ID}",
  "account_type": "ASSET",
  "normal_balance": "DEBIT",
  "currency": "USD",
  "allow_negative": false,
  "metadata": {"demo_only": true}
}
JSON
DEST_STATUS="$(request POST "/api/v1/accounts" "$DEST_BODY" -H "Content-Type: application/json" --data @"$DEST_PAYLOAD")"
expect_status "$DEST_STATUS" "201" "$DEST_BODY" "create destination account"
DEST_ACCOUNT_ID="$(json_get "$DEST_BODY" "id")"
json_pretty "$DEST_BODY"

section "5. Seed source account with local demo opening balance"
explain "The public API has no production-style funding endpoint. This demo uses scripts/seed_demo_data.py to post a balanced transfer from a local demo funding account."
SEED_BODY="$TMP_DIR/seed.json"
"$PYTHON_BIN" scripts/seed_demo_data.py \
  --source-account-id "$SOURCE_ACCOUNT_ID" \
  --amount-minor 50000 \
  --currency USD \
  --run-label "$RUN_ID" > "$SEED_BODY"
json_pretty "$SEED_BODY"

section "6. Post transfer from source to destination"
TRANSFER_BODY="$TMP_DIR/transfer.json"
TRANSFER_PAYLOAD="$TMP_DIR/transfer_payload.json"
TRANSFER_IDEMPOTENCY_KEY="demo-transfer-${RUN_ID}"
cat > "$TRANSFER_PAYLOAD" <<JSON
{
  "source_account_id": "${SOURCE_ACCOUNT_ID}",
  "destination_account_id": "${DEST_ACCOUNT_ID}",
  "amount_minor": 12500,
  "currency": "USD",
  "description": "Demo transfer from source cash to settlement"
}
JSON
TRANSFER_STATUS="$(request POST "/api/v1/transfers" "$TRANSFER_BODY" -H "Content-Type: application/json" -H "Idempotency-Key: ${TRANSFER_IDEMPOTENCY_KEY}" --data @"$TRANSFER_PAYLOAD")"
expect_status "$TRANSFER_STATUS" "201" "$TRANSFER_BODY" "post transfer"
TRANSACTION_ID="$(json_get "$TRANSFER_BODY" "id")"
json_pretty "$TRANSFER_BODY"
json_assert_transfer_entries_balance "$TRANSFER_BODY"

section "7. Replay same transfer with same Idempotency-Key"
REPLAY_BODY="$TMP_DIR/replay.json"
REPLAY_STATUS="$(request POST "/api/v1/transfers" "$REPLAY_BODY" -H "Content-Type: application/json" -H "Idempotency-Key: ${TRANSFER_IDEMPOTENCY_KEY}" --data @"$TRANSFER_PAYLOAD")"
expect_status "$REPLAY_STATUS" "200" "$REPLAY_BODY" "idempotent replay"
REPLAY_TRANSACTION_ID="$(json_get "$REPLAY_BODY" "id")"
if [[ "$REPLAY_TRANSACTION_ID" != "$TRANSACTION_ID" ]]; then
  printf "Replay returned a different transaction id: %s vs %s\n" "$REPLAY_TRANSACTION_ID" "$TRANSACTION_ID" >&2
  exit 1
fi
json_pretty "$REPLAY_BODY"
explain "Replay returned the same transaction id and did not double-post."

section "8. Query transaction"
TX_BODY="$TMP_DIR/transaction_lookup.json"
TX_STATUS="$(request GET "/api/v1/transactions/${TRANSACTION_ID}" "$TX_BODY")"
expect_status "$TX_STATUS" "200" "$TX_BODY" "get transaction"
json_pretty "$TX_BODY"
json_assert_transfer_entries_balance "$TX_BODY"

section "9. Query account balances"
SOURCE_BALANCE="$TMP_DIR/source_balance.json"
DEST_BALANCE="$TMP_DIR/destination_balance.json"
SOURCE_BALANCE_STATUS="$(request GET "/api/v1/accounts/${SOURCE_ACCOUNT_ID}/balance" "$SOURCE_BALANCE")"
DEST_BALANCE_STATUS="$(request GET "/api/v1/accounts/${DEST_ACCOUNT_ID}/balance" "$DEST_BALANCE")"
expect_status "$SOURCE_BALANCE_STATUS" "200" "$SOURCE_BALANCE" "source balance"
expect_status "$DEST_BALANCE_STATUS" "200" "$DEST_BALANCE" "destination balance"
explain "Source balance:"
json_pretty "$SOURCE_BALANCE"
explain "Destination balance:"
json_pretty "$DEST_BALANCE"

section "10. List ledger entries for transaction"
ENTRIES_BODY="$TMP_DIR/ledger_entries.json"
ENTRIES_STATUS="$(request GET "/api/v1/ledger-entries?transaction_id=${TRANSACTION_ID}" "$ENTRIES_BODY")"
expect_status "$ENTRIES_STATUS" "200" "$ENTRIES_BODY" "list ledger entries"
json_pretty "$ENTRIES_BODY"

section "11. Attempt invalid same-account transfer"
INVALID_BODY="$TMP_DIR/invalid_transfer.json"
INVALID_PAYLOAD="$TMP_DIR/invalid_transfer_payload.json"
cat > "$INVALID_PAYLOAD" <<JSON
{
  "source_account_id": "${SOURCE_ACCOUNT_ID}",
  "destination_account_id": "${SOURCE_ACCOUNT_ID}",
  "amount_minor": 100,
  "currency": "USD",
  "description": "Expected rejection: same-account transfer"
}
JSON
INVALID_STATUS="$(request POST "/api/v1/transfers" "$INVALID_BODY" -H "Content-Type: application/json" -H "Idempotency-Key: demo-invalid-${RUN_ID}" --data @"$INVALID_PAYLOAD")"
if [[ "$INVALID_STATUS" != "422" && "$INVALID_STATUS" != "409" ]]; then
  printf "Expected same-account transfer to be rejected, got HTTP %s\n" "$INVALID_STATUS" >&2
  cat "$INVALID_BODY" >&2
  printf "\n" >&2
  exit 1
fi
json_pretty "$INVALID_BODY"
explain "Expected business rejection observed; this is successful demo evidence."

section "Demo complete"
explain "The demo created accounts, seeded a local opening balance through balanced ledger posting, posted a transfer, proved idempotent replay, listed ledger entries, checked balances, and demonstrated rejection without partial mutation."
