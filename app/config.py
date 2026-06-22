import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "fininfra-double-entry-ledger")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://fininfra:fininfra@localhost:55432/fininfra"
)
