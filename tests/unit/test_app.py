"""Uygulama Testleri"""

def test_health_check(client):
    """Sağlık kontrolü testi"""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'healthy'

def test_api_root(client):
    """API kök endpoint'i testi"""
    response = client.get('/api/v1')
    assert response.status_code == 200
    assert 'version' in response.json
