"""Health endpoint tests."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    """Liveness probe returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_ok(client: TestClient) -> None:
    """Readiness returns ok when rules file exists."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_rate_limit_not_exceeded(client: TestClient) -> None:
    """Health endpoint accepts multiple requests within limit."""
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200
