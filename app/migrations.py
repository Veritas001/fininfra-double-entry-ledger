from pathlib import Path
from threading import Lock

from app.db import get_connection


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
_schema_lock = Lock()
_schema_ready = False


def run_migrations() -> list[str]:
    applied_versions: list[str] = []

    with get_connection() as conn:
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )

        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_path.stem

            with conn.transaction():
                existing = conn.execute(
                    "SELECT version FROM schema_migrations WHERE version = %s;",
                    (version,),
                ).fetchone()
                if existing is not None:
                    continue

                conn.execute(migration_path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s);",
                    (version,),
                )
                applied_versions.append(version)

    return applied_versions


def ensure_schema() -> None:
    global _schema_ready

    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return
        run_migrations()
        _schema_ready = True
