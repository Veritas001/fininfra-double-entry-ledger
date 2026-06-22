from fastapi.testclient import TestClient

from app.health import basic_health_check, project_identity
from app.main import app

client = TestClient(app)


def test_basic_health_check_status_ok():
    result = basic_health_check()

    assert result["service"] == "fininfra-double-entry-ledger"
    assert result["status"] == "ok"
    assert result["component"] == "api"


def test_project_identity_contains_three_narratives():
    result = project_identity()

    assert "Software Engineering" in result["narratives"]
    assert "Financial Infrastructure" in result["narratives"]
    assert "Quantitative Finance" in result["narratives"]


def test_health_endpoint_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_endpoint_describes_project():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["project"] == "P1 Double-Entry Ledger"


def test_ready_endpoint_returns_not_ready_when_database_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.main.DATABASE_URL",
        "postgresql://fininfra:fininfra@127.0.0.1:1/fininfra",
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["database"] == "not_connected"


def test_env_example_uses_p1_service_name():
    content = open(".env.example", encoding="utf-8").read()

    assert "SERVICE_NAME=fininfra-double-entry-ledger" in content
