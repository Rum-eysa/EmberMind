"""Pytest fixtures for the FastAPI application."""
import pytest
from fastapi.testclient import TestClient

from src.fastapi_app import create_fastapi_app


@pytest.fixture(scope="function")
def api():
    """Return a testing FastAPI application."""
    app = create_fastapi_app("testing")
    app.state.database.create_all()  # Ensure tables are created
    yield app


@pytest.fixture(scope="function")
def client(api):
    """Return a client with the application lifespan enabled."""
    with TestClient(api) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def session(api):
    """Return a database session for testing."""
    api.state.database.create_all()  # Ensure tables are created
    with api.state.database.session() as db_session:
        yield db_session
