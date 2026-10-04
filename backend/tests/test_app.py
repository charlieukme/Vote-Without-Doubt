"""
Test application foundation
Phase 1 - Backend Foundation Tests
"""

import pytest
from app import create_app


def test_create_app():
    """Test Flask app creation"""
    app = create_app('testing')
    assert app is not None
    assert app.config['TESTING'] is True


def test_health_endpoint():
    """Test health endpoint"""
    app = create_app('testing')
    client = app.test_client()
    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    assert 'message' in data
    assert 'timestamp' in data


def test_config_loads():
    """Test configuration loads correctly"""
    app = create_app('testing')
    assert app.config['APP_NAME'] == 'Vote Without Doubt'
    assert app.config['APP_ENV'] == 'testing'


def test_404_handler():
    """Test 404 error handler"""
    app = create_app('testing')
    client = app.test_client()
    response = client.get('/api/nonexistent')
    assert response.status_code == 404
    data = response.get_json()
    assert 'error' in data
