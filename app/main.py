from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATABASE_URL, SERVICE_NAME
from app.health import basic_health_check, project_identity
from app.ledger.routes import router as ledger_router

app = FastAPI(
    title="P1 Double-Entry Ledger",
    description="A prototype double-entry ledger service for the FMI Lab.",
    version="0.2.0",
)

app.include_router(ledger_router)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/")
def root() -> dict:
    return project_identity()


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return basic_health_check()


@app.get("/ready")
def readiness() -> dict:
    try:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()

        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "database": "connected",
            "database_check": result[0],
        }
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "service": SERVICE_NAME,
                "status": "not_ready",
                "database": "not_connected",
                "error": str(exc),
            },
        )
