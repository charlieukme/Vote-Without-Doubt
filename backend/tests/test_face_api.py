"""
Phase 5 - Face API
"""

from app import create_app


def test_face_status_unauth(client):
    resp = client.get('/api/face/status')
    assert resp.status_code == 401


def test_face_consent_requires_auth(client):
    resp = client.post('/api/face/consent')
    assert resp.status_code == 401


def test_enroll_challenge_auth(client):
    resp = client.post('/api/face/challenge/enroll')
    assert resp.status_code == 401


def test_verify_challenge_auth(client):
    resp = client.post('/api/face/challenge/verify')
    assert resp.status_code == 401


def test_face_enroll_requires_auth(client):
    resp = client.post('/api/face/enroll', json={})
    assert resp.status_code == 401


def test_face_verify_requires_auth(client):
    resp = client.post('/api/face/verify', json={})
    assert resp.status_code == 401
