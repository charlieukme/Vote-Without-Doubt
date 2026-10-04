"""
Test authentication core - Phase 2
"""

import pytest
from app import create_app
from app.extensions import db
from app.security.password import hash_password, verify_password
from app.security.otp import generate_otp, hash_otp, verify_otp


def test_password_hash_not_plaintext():
    password = 'testpass123'
    hashed = hash_password(password)
    assert hashed != password
    assert len(hashed) > 20


def test_password_verify_correct():
    password = 'testpass123'
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_password_verify_incorrect():
    password = 'testpass123'
    hashed = hash_password(password)
    assert verify_password('wrong', hashed) is False


def test_password_hash_not_reversible_as_plaintext():
    password = 'testpass123'
    hashed = hash_password(password)
    assert verify_password(hashed, hashed) is False


def test_otp_generation_six_digits():
    otp = generate_otp()
    assert len(otp) == 6
    assert otp.isdigit()


def test_otp_hash_not_raw():
    otp = '123456'
    hashed = hash_otp(otp)
    assert hashed != otp


def test_otp_verify_correct():
    otp = '123456'
    hashed = hash_otp(otp)
    assert verify_otp(otp, hashed) is True


def test_otp_verify_incorrect():
    otp = '123456'
    hashed = hash_otp(otp)
    assert verify_otp('654321', hashed) is False


def test_auth_status_unauthenticated():
    app = create_app('testing')
    client = app.test_client()
    response = client.get('/api/auth/status')
    assert response.status_code == 200
    data = response.get_json()
    assert data['authenticated'] is False
