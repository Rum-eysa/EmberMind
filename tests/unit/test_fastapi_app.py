"""FastAPI adapter tests."""
from fastapi.testclient import TestClient

from src.fastapi_app import create_fastapi_app


def test_fastapi_health_and_openapi(client):
    health = client.get("/health")
    openapi = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "Wildfire Monitoring API"


def test_fastapi_fires_endpoint(client):
    response = client.get("/api/v1/fires?limit=10")

    assert response.status_code == 200
    assert response.json()["source"] == "NASA FIRMS"
    assert response.json()["count"] == 0


def test_fastapi_rejects_invalid_limit(client):
    response = client.get("/api/v1/fires?limit=0")

    assert response.status_code == 422
