"""Pytest Konfigürasyonu"""
import pytest
from src.app import create_app, db

@pytest.fixture
def app():
    """Test uygulaması"""
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """Test istemcisi"""
    return app.test_client()

@pytest.fixture
def runner(app):
    """CLI test çalıştırıcısı"""
    return app.test_cli_runner()
