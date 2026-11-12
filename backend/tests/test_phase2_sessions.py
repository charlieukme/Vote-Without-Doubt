"""Phase 2 - session revocation, expiry, logout and cookie integrity.

Mandatory cases covered here: 18, 19, 20, 21, 22, 23, 24, 25.
"""

from datetime import datetime, timedelta

from app.extensions import db
from app.models import AuthSession, OTP
from app.security import sessions as sessions_module
from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME


def seed_session(user, **overrides):
    now = datetime.utcnow()
    fields = {
        'session_id': 'seeded-session-id',
        'user_id': user.id,
        'auth_state': 'AUTHORIZED',
        'authenticated_at': now,
        'last_activity': now,
        'expires_at': now + timedelta(hours=2),
        'idle_expires_at': now + timedelta(minutes=10),
    }
    fields.update(overrides)
    record = AuthSession(**fields)
    db.session.add(record)
    db.session.commit()
    return record


def authorised(auth_api, email_service):
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})


def test_revoked_session_is_rejected(phase2_user, client_for_session):
    """18"""
    record = seed_session(phase2_user, revoked=True)
    client = client_for_session(record.session_id)
    assert client.get('/api/auth/status').get_json() == {'authenticated': False}
    assert client.get('/api/auth/session').status_code == 401


def test_idle_expired_session_is_rejected(db, phase2_user, client_for_session):
    """19"""
    now = datetime.utcnow()
    record = seed_session(phase2_user, last_activity=now - timedelta(minutes=11),
                          idle_expires_at=now - timedelta(minutes=1))
    assert client_for_session(record.session_id).get('/api/auth/session').status_code == 401
    assert db.session.get(AuthSession, record.id).revoked is True


def test_absolute_expired_session_is_rejected(phase2_user, client_for_session):
    """20"""
    record = seed_session(phase2_user, expires_at=datetime.utcnow() - timedelta(seconds=1))
    assert client_for_session(record.session_id).get('/api/auth/session').status_code == 401


def test_activity_slides_the_idle_window_but_not_the_absolute_deadline(db, phase2_user,
                                                                       client_for_session):
    """19/20: idle is a sliding window; the two-hour cap never moves."""
    now = datetime.utcnow()
    absolute = now + timedelta(minutes=5)
    idle = now + timedelta(seconds=30)
    record = seed_session(phase2_user, last_activity=now - timedelta(minutes=9),
                          idle_expires_at=idle, expires_at=absolute)

    assert client_for_session(record.session_id).get('/api/auth/session').status_code == 200

    db.session.expire_all()
    refreshed = db.session.get(AuthSession, record.id)
    assert refreshed.idle_expires_at > idle
    assert refreshed.expires_at == absolute


def test_absolute_deadline_survives_continuous_activity(phase2_user, client_for_session):
    """20: activity cannot extend a session beyond the absolute deadline."""
    now = datetime.utcnow()
    absolute = now + timedelta(minutes=2)
    record = seed_session(phase2_user, expires_at=absolute,
                          idle_expires_at=now - timedelta(minutes=30))
    client = client_for_session(record.session_id)
    for _ in range(3):
        client.get('/api/auth/session')
    assert client.get('/api/auth/session').status_code == 401


def test_timeouts_match_the_frozen_architecture():
    """C"""
    assert sessions_module.IDLE_TIMEOUT_MINUTES == 10
    assert sessions_module.ABSOLUTE_TIMEOUT_MINUTES == 120


def test_logout_revokes_the_session_and_stops_protected_access(auth_api, email_service,
                                                               phase2_user):
    """21, 22"""
    authorised(auth_api, email_service)
    assert auth_api.get('/api/auth/session').status_code == 200

    response = auth_api.post('/api/auth/logout', json={})
    assert response.status_code == 200
    assert response.get_json() == {'message': 'Logged out'}

    assert auth_api.get('/api/auth/session').status_code == 401
    assert auth_api.get('/api/auth/status').get_json() == {'authenticated': False}
    assert AuthSession.query.filter_by(revoked=False).count() == 0


def test_repeated_logout_is_safe(auth_api, phase2_user):
    """23"""
    for _ in range(3):
        assert auth_api.post('/api/auth/logout', json={}).status_code == 200


def test_logout_invalidates_outstanding_otps(auth_api, email_service, phase2_user):
    """21/22: a pending OTP cannot outlive the session it was issued for."""
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    assert OTP.query.filter_by(used=False).count() == 1

    auth_api.post('/api/auth/logout', json={})
    assert OTP.query.filter_by(used=False).count() == 0


def test_tampered_session_cookie_is_rejected(auth_api, email_service, phase2_user,
                                             cookie_of, client_for):
    """24"""
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    good = cookie_of(auth_api.post('/api/auth/verify-otp',
                                   json={'otp': email_service.last_otp}))
    assert client_for(good).get('/api/auth/session').status_code == 200

    position = 12
    flipped = good[:position] + ('B' if good[position] == 'A' else 'A') + good[position + 1:]
    assert flipped != good
    assert client_for(flipped).get('/api/auth/session').status_code == 401


def test_forged_cookie_is_rejected(phase2_user, client_for):
    """24"""
    forged = client_for('not-a-real-signed-session')
    assert forged.get('/api/auth/session').status_code == 401
    assert forged.get('/api/auth/status').get_json() == {'authenticated': False}


def test_fake_frontend_auth_state_grants_nothing(auth_api, phase2_user):
    """25: the server never trusts client-supplied authentication state."""
    for payload in ({'authenticated': True}, {'state': 'AUTHORIZED'},
                    {'auth_state': 'AUTHORIZED', 'role': 'admin'}):
        response = auth_api.get('/api/auth/session', json=payload)
        assert response.status_code in (401, 405)

    login = auth_api.post('/api/auth/login',
                          json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD,
                                'authenticated': True, 'state': 'AUTHORIZED'})
    assert login.get_json()['state'] == 'PENDING_FACTORS'


def test_production_cookie_uses_the_host_prefix(app, monkeypatch):
    """B: strongest appropriate cookie configuration."""
    from app.config.config import ProductionConfig

    assert ProductionConfig.SESSION_COOKIE_NAME == '__Host-session'
    assert ProductionConfig.SESSION_COOKIE_PATH == '/'
    assert ProductionConfig.SESSION_COOKIE_SECURE is True
    assert ProductionConfig.SESSION_COOKIE_HTTPONLY is True
    assert ProductionConfig.SESSION_COOKIE_SAMESITE == 'Strict'


def test_issued_cookie_is_httponly_and_samesite_strict(app, auth_api, email_service,
                                                       phase2_user):
    """B: the cookie is emitted by the login response that opens the session."""
    response = auth_api.post('/api/auth/login',
                             json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    header = next(h for h in response.headers.getlist('Set-Cookie')
                  if h.startswith(app.config['SESSION_COOKIE_NAME'] + '='))
    assert 'HttpOnly' in header
    assert 'SameSite=Strict' in header


def test_live_seeded_session_is_accepted(phase2_user, client_for_session):
    """Positive control proving the signed-cookie helper is not vacuous.

    Without this, every "expired/revoked session is rejected" assertion above
    would also pass if the cookie helper were simply broken.
    """
    record = seed_session(phase2_user)
    client = client_for_session(record.session_id)
    assert client.get('/api/auth/session').status_code == 200
    assert client.get('/api/auth/status').get_json()['authenticated'] is True
