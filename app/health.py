from datetime import datetime, timezone

from app.config import SERVICE_NAME


def basic_health_check() -> dict:
    return {
        "service": SERVICE_NAME,
        "status": "ok",
        "component": "api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "FMI Lab P1 double-entry ledger prototype is running."
    }


def project_identity() -> dict:
    return {
        "project": "P1 Double-Entry Ledger",
        "purpose": "Accounting foundation prototype for future FMI Lab payment, clearing, settlement, risk, and quantitative workflows.",
        "narratives": [
            "Software Engineering",
            "Financial Infrastructure",
            "Quantitative Finance"
        ]
    }
