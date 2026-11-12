"""
Regression tests for Student Login Redirect Bug and Session Persistence.

Verifies:
1. Rate limit configuration reserves independent, dedicated budgets for read-only
   status (/api/auth/status) and session (/api/auth/session) queries separate from
   the core authentication action endpoints (/api/auth).
2. _scope_for_request() prioritizes specific prefix rules over broader prefixes.
3. Normal login and navigation flow (including repeated status queries) does not
   exhaust rate limits or trigger 429 errors.
4. Active student session persists across consecutive status checks and protected route queries.
"""

from datetime import datetime, timedelta
import secrets
import pytest
from flask import session

from app.extensions import db
from app.models import User, AuthSession, Election, WalletBinding, FaceEnrollment
from app.security.password import hash_password
from app.security.rate_limit import _scope_for_request, get_limiter
from tests.conftest import _seed_authorized_session


def test_auth_rate_limit_rules_have_dedicated_status_budgets(app):
    """Verify rate limit rules provide dedicated budgets for auth status and session polling."""
    rules = app.config.get('RATE_LIMIT_RULES', {})
    
    assert '/api/auth/status' in rules, "Expected dedicated rule for /api/auth/status"
    assert rules['/api/auth/status'][0] >= 60, f"Expected /api/auth/status budget >= 60, got {rules['/api/auth/status'][0]}"
    
    assert '/api/auth/session' in rules, "Expected dedicated rule for /api/auth/session"
    assert rules['/api/auth/session'][0] >= 60, f"Expected /api/auth/session budget >= 60, got {rules['/api/auth/session'][0]}"
    
    assert '/api/auth' in rules, "Expected rule for /api/auth"
    assert rules['/api/auth'][0] >= 30, f"Expected /api/auth budget >= 30, got {rules['/api/auth'][0]}"


def test_scope_for_request_prioritizes_specific_auth_status_rule(app):
    """Verify _scope_for_request evaluates specific prefixes before broad ones."""
    with app.test_request_context('/api/auth/status'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/auth/status', f"Expected scope '/api/auth/status', got '{scope}'"
        assert limit >= 60

    with app.test_request_context('/api/auth/session'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/auth/session', f"Expected scope '/api/auth/session', got '{scope}'"
        assert limit >= 60

    with app.test_request_context('/api/auth/login'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/auth', f"Expected scope '/api/auth', got '{scope}'"


def test_repeated_auth_status_polling_does_not_exhaust_budget(app, client):
    """Verify 15 consecutive requests to /api/auth/status succeed and do not return 429."""
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    get_limiter().reset()

    try:
        for i in range(15):
            res = client.get('/api/auth/status')
            assert res.status_code == 200, f"Request {i+1} failed with status {res.status_code}: {res.get_data(as_text=True)}"
            data = res.get_json()
            assert 'authenticated' in data
    finally:
        app.config['RATE_LIMIT_TESTING_ENABLED'] = False
        get_limiter().reset()


def test_student_session_persists_across_navigation_queries(app, db, client, signed_cookie_for):
    """Verify an authorized session remains recognized across status, session, and student endpoints."""
    # Seed test student
    user = User(
        username='test_student_persists',
        email='persists@college.edu',
        password_hash=hash_password('Password123!'),
        voter_id='1EW23CS999',
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()

    sid = secrets.token_hex(32)
    _seed_authorized_session(db, user, session_id=sid)

    cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    client.set_cookie(cookie_name, signed_cookie_for(sid))

    # 1. /api/auth/status returns authenticated: True
    res_status = client.get('/api/auth/status')
    assert res_status.status_code == 200
    assert res_status.get_json().get('authenticated') is True
    assert res_status.get_json().get('state') == 'AUTHORIZED'

    # 2. /api/auth/session returns AUTHORIZED session details
    res_session = client.get('/api/auth/session')
    assert res_session.status_code == 200
    assert res_session.get_json().get('state') == 'AUTHORIZED'

    # 3. Simulate multiple navigations and refreshes
    for _ in range(5):
        s_res = client.get('/api/auth/status')
        assert s_res.status_code == 200
        assert s_res.get_json().get('authenticated') is True

    # 4. Final check that session remains valid
    final_res = client.get('/api/auth/session')
    assert final_res.status_code == 200
    assert final_res.get_json().get('state') == 'AUTHORIZED'
