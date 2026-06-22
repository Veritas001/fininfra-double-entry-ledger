import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ledger.enums import AccountStatus, AccountType, NormalBalance
from app.ledger.schemas import AccountCreateRequest, TransferRequest
from app.ledger.service import LedgerService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed local P1 demo balance through the existing ledger service."
    )
    parser.add_argument("--source-account-id", required=True, type=UUID)
    parser.add_argument("--amount-minor", type=int, default=50_000)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--run-label", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.amount_minor <= 0:
        print("amount_minor must be positive", file=sys.stderr)
        return 2

    run_label = args.run_label or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    unique_suffix = f"{run_label}-{uuid4().hex[:8]}"
    service = LedgerService()

    funding_account = service.create_account(
        AccountCreateRequest(
            account_code=f"demo-funding-{unique_suffix}",
            name="Local Demo Funding Account",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
            currency=args.currency,
            allow_negative=True,
            status=AccountStatus.ACTIVE,
            metadata={
                "demo_only": True,
                "purpose": "Local demo opening balance source",
            },
        )
    )

    idempotency_key = f"demo-seed-{unique_suffix}"
    seed_result = service.post_transfer(
        TransferRequest(
            source_account_id=funding_account.id,
            destination_account_id=args.source_account_id,
            amount_minor=args.amount_minor,
            currency=args.currency,
            description="Local demo opening balance seed",
            external_ref=f"demo-seed-{unique_suffix}",
        ),
        idempotency_key,
    )

    output = {
        "demo_only": True,
        "funding_account_id": str(funding_account.id),
        "source_account_id": str(args.source_account_id),
        "amount_minor": args.amount_minor,
        "currency": args.currency,
        "idempotency_key": idempotency_key,
        "seed_status_code": seed_result.status_code,
        "seed_response": seed_result.body,
    }
    print(json.dumps(output, indent=2, sort_keys=True))

    return 0 if seed_result.status_code == 201 else 1


if __name__ == "__main__":
    raise SystemExit(main())
