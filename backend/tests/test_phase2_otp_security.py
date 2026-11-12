"""Phase 2 - OTP security: protection, expiry, attempts, binding and delivery.

Mandatory cases covered here: 8, 9, 10, 11, 12, 13, 29, 31, 32, 33, 34.
"""

import re
from datetime import datetime, timedelta

from app.extensions import db
from app.models import OTP
from app.security.otp import generate_otp, hash_otp
from app.services.auth_service import (
    GENERIC_OTP_FAILURE,
    OTP_MAX_ATTEMPTS,
    OTP_TTL_MINUTES,
    VALID_OTP_PURPOSES,
)
from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME


def start_login(auth_api):
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})


def request_otp(auth_api):
    assert auth_api.post('/api/auth/request-otp', json={}).status_code == 200


def latest_otp():
    return OTP.query.order_by(OTP.id.desc()).one()


def test_otp_is_six_digits_and_uses_the_secrets_module():
    """E: CSPRNG, six digits, no predictable sequence."""
    import secrets as stdlib_secrets
    from app.security import otp as otp_module

    assert otp_module.secrets is stdlib_secrets

    codes = {generate_otp() for _ in range(200)}
    for code in codes:
        assert re.fullmatch(r'[0-9]{6}', code)
    assert len(codes) > 150


def test_otp_is_stored_only_as_a_peppered_hmac(auth_api, email_service, phase2_user):
    """F, 29"""
    start_login(auth_api)
    request_otp(auth_api)
    raw = email_service.last_otp

    record = latest_otp()
    assert record.otp_hash == hash_otp(raw)
    assert len(record.otp_hash) == 64
    assert raw not in record.otp_hash
    assert re.fullmatch(r'[0-9a-f]{64}', record.otp_hash)


def test_otp_ttl_is_five_minutes_with_five_attempts(auth_api, email_service, phase2_user):
    """G"""
    start_login(auth_api)
    request_otp(auth_api)

    record = latest_otp()
    remaining = record.expires_at - datetime.utcnow()
    assert timedelta(minutes=OTP_TTL_MINUTES - 1) < remaining <= timedelta(
        minutes=OTP_TTL_MINUTES)
    assert record.max_attempts == OTP_MAX_ATTEMPTS == 5
    assert record.attempts == 0


def test_wrong_otp_is_rejected_and_counted(auth_api, email_service, phase2_user):
    """8"""
    start_login(auth_api)
    request_otp(auth_api)

    response = auth_api.post('/api/auth/verify-otp', json={'otp': '000000'})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_OTP_FAILURE
    assert latest_otp().attempts == 1
    assert auth_api.get('/api/auth/session').status_code == 401


def test_expired_otp_is_rejected(auth_api, email_service, phase2_user):
    """9"""
    start_login(auth_api)
    request_otp(auth_api)

    record = latest_otp()
    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()

    response = auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_OTP_FAILURE
    assert db.session.get(OTP, record.id).used is True
    assert auth_api.get('/api/auth/session').status_code == 401


def test_more_than_five_attempts_is_rejected(auth_api, email_service, phase2_user):
    """13"""
    start_login(auth_api)
    request_otp(auth_api)
    correct = email_service.last_otp

    for _ in range(OTP_MAX_ATTEMPTS):
        assert auth_api.post('/api/auth/verify-otp',
                             json={'otp': '000000'}).status_code == 400

    assert latest_otp().attempts == OTP_MAX_ATTEMPTS

    response = auth_api.post('/api/auth/verify-otp', json={'otp': correct})
    assert response.status_code == 400
    assert auth_api.get('/api/auth/session').status_code == 401


def test_used_otp_cannot_be_replayed(auth_api, email_service, phase2_user, cookie_of,
                                     client_for):
    """10, 32"""
    pre_cookie = cookie_of(auth_api.post('/api/auth/login',
                                         json={'username': PHASE2_USERNAME,
                                               'password': PHASE2_PASSWORD}))
    auth_api.post('/api/auth/request-otp', json={})
    code = email_service.last_otp
    assert auth_api.post('/api/auth/verify-otp', json={'otp': code}).status_code == 200

    replay = client_for(pre_cookie)
    response = replay.post('/api/auth/verify-otp', json={'otp': code})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_OTP_FAILURE


def test_otp_from_another_session_is_rejected(app, auth_api, email_service, phase2_user):
    """11, 32: an OTP is bound to the session that requested it."""
    start_login(auth_api)
    request_otp(auth_api)
    stolen = email_service.last_otp

    other = app.test_client()
    import app.routes.auth as auth_routes
    auth_routes.auth_service.email_service = email_service
    other.post('/api/auth/login',
               json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    other.post('/api/auth/request-otp', json={})

    response = other.post('/api/auth/verify-otp', json={'otp': stolen})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_OTP_FAILURE
    assert other.get('/api/auth/session').status_code == 401


def test_otp_for_another_purpose_is_rejected(auth_service, phase2_user):
    """12, 31: purpose binding is enforced at the service layer."""
    ok, session_obj, _msg = auth_service.authenticate(PHASE2_USERNAME, PHASE2_PASSWORD)
    assert ok is True
    sid = session_obj.session_id

    assert auth_service.request_otp(sid, 'login')[0] is True
    login_record = OTP.query.filter_by(session_id=sid, purpose='login').one()

    for other_purpose in ('password_reset', 'registration', 'wallet_auth'):
        allowed, message = auth_service.verify_otp(sid, '000000', other_purpose)
        assert allowed is False
        assert message == GENERIC_OTP_FAILURE

    assert db.session.get(OTP, login_record.id).used is False


def test_invalid_purpose_cannot_request_an_otp(auth_service, phase2_user):
    """12, 31"""
    _ok, session_obj, _msg = auth_service.authenticate(PHASE2_USERNAME, PHASE2_PASSWORD)
    allowed, message = auth_service.request_otp(session_obj.session_id, 'not_a_purpose')

    assert allowed is False
    assert message == 'Invalid OTP purpose'
    assert OTP.query.count() == 0
    assert VALID_OTP_PURPOSES == {'login'}


def test_repeated_request_supersedes_the_previous_code(auth_api, email_service, phase2_user):
    """33: only one live code exists at a time."""
    start_login(auth_api)
    request_otp(auth_api)
    first = email_service.last_otp

    request_otp(auth_api)
    second = email_service.last_otp
    assert first != second

    assert auth_api.post('/api/auth/verify-otp', json={'otp': first}).status_code == 400
    assert OTP.query.filter_by(used=False).count() == 1

    assert auth_api.post('/api/auth/verify-otp',
                         json={'otp': second}).status_code == 200
    assert OTP.query.filter_by(used=False).count() == 0


def test_email_failure_is_reported_and_leaves_no_usable_otp(app, db, email_service,
                                                             phase2_user):
    """34: a failed delivery is never reported as a success."""
    email_service.should_fail = True
    import app.routes.auth as auth_routes
    auth_routes.auth_service.email_service = email_service
    api = app.test_client()

    api.post('/api/auth/login',
             json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    response = api.post('/api/auth/request-otp', json={})

    assert response.status_code == 400
    assert response.get_json() == {'error': 'Unable to send OTP'}
    assert OTP.query.filter_by(used=False).count() == 0


def test_email_failure_never_authenticates_the_user(app, db, email_service, phase2_user):
    """34"""
    email_service.should_fail = True
    import app.routes.auth as auth_routes
    auth_routes.auth_service.email_service = email_service
    api = app.test_client()

    api.post('/api/auth/login',
             json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    api.post('/api/auth/request-otp', json={})

    assert api.get('/api/auth/status').get_json() == {
        'authenticated': False, 'state': 'PENDING_FACTORS'}
    assert api.get('/api/auth/session').status_code == 401
    assert api.post('/api/wallet/challenge', json={}).status_code == 401


def test_email_receives_the_generated_code(auth_api, email_service, phase2_user):
    """O: the delivery carries exactly the code that was stored."""
    start_login(auth_api)
    request_otp(auth_api)

    delivery = email_service.sent[-1]
    assert delivery['to'] == phase2_user.email
    assert delivery['purpose'] == 'login'
    assert delivery['otp'] == email_service.last_otp
    assert latest_otp().otp_hash == hash_otp(delivery['otp'])
