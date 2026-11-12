"""Phase 2 - authentication lifecycle and session rotation.

Mandatory cases covered here: 1, 2, 3, 7, 14, 15, 16, 17, 26, 36.
"""

from app.extensions import db
from app.models import AuthSession, OTP
from app.services.auth_service import GENERIC_OTP_FAILURE
from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME


def login(auth_api, password=PHASE2_PASSWORD):
    return auth_api.post('/api/auth/login',
                         json={'username': PHASE2_USERNAME, 'password': password})


def test_password_plus_correct_otp_authorises(auth_api, email_service, phase2_user):
    """1, 7, 14: the full two-factor flow authorises and consumes the OTP."""
    assert login(auth_api).status_code == 200
    assert auth_api.post('/api/auth/request-otp', json={}).status_code == 200

    verified = auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    assert verified.status_code == 200
    assert verified.get_json()['state'] == 'AUTHORIZED'

    assert auth_api.get('/api/auth/status').get_json() == {
        'authenticated': True, 'state': 'AUTHORIZED'}
    assert auth_api.get('/api/auth/session').status_code == 200

    record = OTP.query.order_by(OTP.id.desc()).one()
    assert record.used is True
    assert record.consumed_at is not None
    assert record.purpose == 'login'


def test_correct_password_without_otp_is_not_authorized(auth_api, phase2_user):
    """2: a valid password alone never authorises."""
    assert login(auth_api).status_code == 200
    assert auth_api.get('/api/auth/status').get_json() == {
        'authenticated': False, 'state': 'PENDING_FACTORS'}
    assert auth_api.get('/api/auth/session').status_code == 401


def test_otp_without_password_authentication_is_rejected(auth_api, email_service, phase2_user):
    """3: an OTP cannot be used without a preceding password step."""
    assert auth_api.post('/api/auth/request-otp', json={}).status_code == 401

    response = auth_api.post('/api/auth/verify-otp', json={'otp': '123456'})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_OTP_FAILURE
    assert email_service.sent == []


def test_protected_endpoints_reject_a_pending_session(auth_api, phase2_user):
    """26: nothing protected is reachable before the second factor completes."""
    assert login(auth_api).status_code == 200
    assert auth_api.get('/api/auth/session').status_code == 401
    # /api/wallet/challenge is a later-phase endpoint that also demands an
    # AUTHORIZED session; a pending Phase 2 session must not satisfy it.
    assert auth_api.post('/api/wallet/challenge', json={}).status_code == 401


def test_successful_otp_rotates_the_session_identifier(auth_api, email_service, phase2_user,
                                                       cookie_of):
    """15: the session identifier changes when the second factor completes."""
    pre_cookie = cookie_of(login(auth_api))
    auth_api.post('/api/auth/request-otp', json={})
    post_cookie = cookie_of(auth_api.post('/api/auth/verify-otp',
                                          json={'otp': email_service.last_otp}))

    assert pre_cookie is not None and post_cookie is not None
    assert pre_cookie != post_cookie

    old = AuthSession.query.filter_by(auth_state='PENDING_FACTORS').one()
    new = AuthSession.query.filter_by(auth_state='AUTHORIZED').one()
    assert old.session_id != new.session_id
    assert old.revoked is True
    assert new.revoked is False
    assert new.authenticated_at is not None


def test_old_session_cannot_authenticate_after_rotation(auth_api, email_service, phase2_user,
                                                        cookie_of, client_for):
    """16, 17: the stale cookie is dead; the rotated cookie works."""
    pre_cookie = cookie_of(login(auth_api))
    auth_api.post('/api/auth/request-otp', json={})
    post_cookie = cookie_of(auth_api.post('/api/auth/verify-otp',
                                          json={'otp': email_service.last_otp}))

    stale = client_for(pre_cookie)
    assert stale.get('/api/auth/status').get_json() == {'authenticated': False}
    assert stale.get('/api/auth/session').status_code == 401

    fresh = client_for(post_cookie)
    assert fresh.get('/api/auth/session').status_code == 200


def test_session_fixation_cannot_promote_a_pending_session(auth_api, email_service, phase2_user,
                                                           cookie_of, client_for):
    """36: replaying the pre-authentication cookie grants nothing."""
    pre_cookie = cookie_of(login(auth_api))
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})

    pending = AuthSession.query.filter_by(auth_state='PENDING_FACTORS').one()
    assert pending.revoked is True

    attacker = client_for(pre_cookie)
    assert attacker.get('/api/auth/session').status_code == 401
    assert attacker.get('/api/auth/status').get_json() == {'authenticated': False}


def test_session_identifiers_are_opaque_and_unique(auth_api, phase2_user):
    import re
    seen = set()
    for _ in range(3):
        assert login(auth_api).status_code == 200
        record = AuthSession.query.order_by(AuthSession.id.desc()).first()
        seen.add(record.session_id)

    assert len(seen) == 3
    for value in seen:
        assert re.fullmatch(r'[0-9a-f]{64}', value)
