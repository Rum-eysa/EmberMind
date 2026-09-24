"""Pytest fixtures for the FastAPI application."""
import pytest
from fastapi.testclient import TestClient

from src.fastapi_app import create_fastapi_app


@pytest.fixture
def api():
    """Return a testing FastAPI application."""
    return create_fastapi_app("testing")


@pytest.fixture
def client(api):
    """Return a client with the application lifespan enabled."""
    with TestClient(api) as test_client:
        yield test_client
