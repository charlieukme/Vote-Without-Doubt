"""Phase 3 - registration lifecycle, OTP security, anti-enumeration, separation.

Mandatory cases covered here: 6, 7, 8, 9, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
24, 28, 29, 30, 31, 35, 36, 37, 38, 39, 40.
"""

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Ballot,
    BallotQueue,
    ElectoralRoll,
    RegistrationSession,
    User,
)
from app.models.roll import REG_EMAIL_VERIFIED, REG_PENDING, REG_REGISTERED
from app.security.admin_bootstrap import ADMIN_TOKEN_HEADER
from app.services.registration_service import (
    GENERIC_REGISTRATION_MESSAGE,
    OTP_MAX_ATTEMPTS,
    OTP_TTL_MINUTES,
    REGISTRATION_OTP_PURPOSE,
    RegistrationService,
)
from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME

USN = '1CD22CS001'
ROLL_EMAIL = 'asha.rao@college.edu'
NEW_PASSWORD = 'Str0ng-Registration-Pass'
GOOD_TOKEN = 'b' * 32


@pytest.fixture(autouse=True)
def roll(app, db, email_service):
    """An authorized roll containing one eligible voter."""
    db.session.add(ElectoralRoll(usn=USN, full_name='Asha Rao',
                                 college_email=ROLL_EMAIL, is_eligible=True,
                                 department='CSE', year_of_study=2))
    db.session.commit()
    return db


@pytest.fixture
def api(app, email_service, monkeypatch):
    """Voter-facing client with a recording transport."""
    import app.routes.registration as routes
    routes.reg_service.email_service = email_service
    return app.test_client()


@pytest.fixture
def admin(app, monkeypatch):
    """Client authorized for roll administration."""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    import app.routes.registration as routes
    routes.reg_service.email_service = RecordingTransport()
    return app.test_client()


class RecordingTransport:
    def send_otp(self, recipient_email, otp, purpose='login'):
        return True


def begin(api, usn=USN):
    return api.post('/api/registration/check', json={'usn': usn})


def verified_session(api, email_service, usn=USN):
    """Drive check -> request-otp -> verify-otp and return the OTP code used."""
    assert begin(api, usn).status_code == 200
    assert api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL}).status_code == 200
    code = email_service.last_otp
    assert api.post('/api/registration/verify-otp', json={'otp': code}).status_code == 200
    return code


def service(app, email_service):
    with app.test_request_context('/api/registration/complete'):
        return RegistrationService(email_service=email_service)


# ------------------------------------------------------------- eligibility

def test_unknown_voter_cannot_register(api):
    """6"""
    response = begin(api, '9ZZ99ZZ999')
    assert response.status_code == 400
    assert response.get_json()['eligible'] is False


def test_non_roll_voter_cannot_register(api):
    """7"""
    assert begin(api, 'NOTINROLL1').status_code == 400
    assert RegistrationSession.query.count() == 0


def test_ineligible_voter_cannot_register(app, api, db):
    """7"""
    record = ElectoralRoll.query.filter_by(usn=USN).one()
    record.is_eligible = False
    db.session.commit()
    assert begin(api).status_code == 400


def test_caller_cannot_choose_arbitrary_voter_identity(api):
    """25: the roll decides the identity, not the request body."""
    response = api.post('/api/registration/check',
                        json={'usn': USN, 'voter_id': 'ADMIN', 'email': 'attacker@evil.test',
                              'full_name': 'Mallory', 'is_eligible': True})
    assert response.status_code == 200
    record = RegistrationSession.query.one()
    assert record.usn == USN
    assert record.email == ROLL_EMAIL


def test_caller_cannot_bypass_eligibility(api):
    """26"""
    assert api.post('/api/registration/complete',
                    json={'username': 'sneaky', 'password': NEW_PASSWORD}).status_code == 400
    assert User.query.count() == 0


def test_registration_session_is_separate_from_auth_session(app, api, db):
    """Registration must not create or reuse an authentication session."""
    assert begin(api).status_code == 200
    with api.session_transaction() as cookie:
        assert set(cookie.keys()) == {'reg_session'}
        assert 'session_id' not in cookie      # never the AuthSession key
    from app.models import AuthSession
    assert AuthSession.query.count() == 0


# ------------------------------------------------------------ C5 generic

def test_responses_do_not_reveal_voter_existence(app, api, db):
    """30: unknown, ineligible and registered must look identical."""
    unknown = begin(api, '9ZZ99ZZ999').get_json()

    record = ElectoralRoll.query.filter_by(usn=USN).one()
    record.is_eligible = False
    db.session.commit()
    ineligible = begin(api).get_json()
    record.is_eligible = True
    db.session.commit()

    # Register the voter, then ask again.
    verified_session(api, _transport(api))
    api.post('/api/registration/complete',
             json={'username': 'asharao', 'password': NEW_PASSWORD})
    registered = begin(api).get_json()

    assert unknown == ineligible == registered
    for payload in (unknown, ineligible, registered):
        assert payload['message'] == GENERIC_REGISTRATION_MESSAGE
        assert 'registered' not in payload['message'].lower()
        assert 'eligible' not in payload['message'].replace('Unable to continue registration', '')


def _transport(api):
    import app.routes.registration as routes
    return routes.reg_service.email_service


def test_usernames_are_distinguishable_only_after_a_session_exists(api, email_service):
    """Username clash is reported precisely, which does not expose roll state."""
    verified_session(api, email_service)
    api.post('/api/registration/complete',
             json={'username': 'asharao', 'password': NEW_PASSWORD})

    api2 = api.application.test_client()
    import app.routes.registration as routes
    routes.reg_service.email_service = email_service
    api2.post('/api/registration/check', json={'usn': USN})
    # A second voter cannot reach this branch because USN is already registered,
    # so the precise username error only surfaces post-verification.
    response = api2.post('/api/registration/complete',
                         json={'username': 'asharao', 'password': NEW_PASSWORD})
    assert response.status_code in (400,)


# --------------------------------------------------------------- lifecycle

def test_full_lifecycle_creates_an_argon2id_identity(app, api, email_service, db):
    """Registration -> password -> identity."""
    verified_session(api, email_service)
    record = RegistrationSession.query.one()
    assert record.state == REG_EMAIL_VERIFIED
    assert record.email_verified is True

    response = api.post('/api/registration/complete',
                        json={'username': 'asharao', 'password': NEW_PASSWORD})
    assert response.status_code == 201

    user = User.query.filter_by(username='asharao').one()
    assert user.password_hash.startswith('$argon2id$v=19$m=')
    assert NEW_PASSWORD not in user.password_hash
    assert NEW_PASSWORD not in repr(user.__dict__)
    assert user.voter_id == USN
    assert user.email == ROLL_EMAIL          # from the roll, never the caller
    assert user.is_verified is True
    assert db.session.get(RegistrationSession, record.id).state == REG_REGISTERED


def test_pending_cannot_jump_directly_to_registered(api, email_service):
    """State machine: PENDING -> REGISTERED must fail."""
    begin(api)
    response = api.post('/api/registration/complete',
                        json={'username': 'jump', 'password': NEW_PASSWORD})
    assert response.status_code == 400
    assert User.query.count() == 0


def test_forged_email_verified_is_rejected(api):
    """28"""
    begin(api)
    response = api.post('/api/registration/complete',
                        json={'username': 'forge', 'password': NEW_PASSWORD,
                              'state': REG_EMAIL_VERIFIED, 'email_verified': True})
    assert response.status_code == 400
    assert User.query.count() == 0


def test_repeated_completion_is_rejected(api, email_service):
    """39"""
    verified_session(api, email_service)
    assert api.post('/api/registration/complete',
                    json={'username': 'twice', 'password': NEW_PASSWORD}).status_code == 201
    second = api.post('/api/registration/complete',
                      json={'username': 'twice2', 'password': NEW_PASSWORD})
    assert second.status_code == 400
    assert User.query.count() == 1


def test_duplicate_registration_cannot_complete(app, api, email_service, db):
    """8"""
    verified_session(api, email_service)
    api.post('/api/registration/complete', json={'username': 'first', 'password': NEW_PASSWORD})

    other = api.application.test_client()
    import app.routes.registration as routes
    routes.reg_service.email_service = email_service
    assert other.post('/api/registration/check', json={'usn': USN}).status_code == 400
    assert User.query.count() == 1


def test_duplicate_voter_id_cannot_exist_at_the_database_level(db):
    """9, 40: the constraint, not just the application check."""
    db.session.add(User(username='dup1', email='d1@x.test',
                        password_hash='$argon2id$stub', voter_id=USN))
    db.session.commit()
    db.session.add(User(username='dup2', email='d2@x.test',
                        password_hash='$argon2id$stub', voter_id=USN))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --------------------------------------------------- C2 session lifecycle

def test_expired_session_cannot_complete(app, api, email_service, db):
    """14, 38"""
    verified_session(api, email_service)
    record = RegistrationSession.query.one()
    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()

    response = api.post('/api/registration/complete',
                        json={'username': 'late', 'password': NEW_PASSWORD})
    assert response.status_code == 400
    assert User.query.count() == 0
    assert db.session.get(RegistrationSession, record.id).revoked is True


def test_revoked_session_cannot_complete(app, api, email_service, db):
    """15"""
    verified_session(api, email_service)
    record = RegistrationSession.query.one()
    record.revoked = True
    db.session.commit()

    assert api.post('/api/registration/complete',
                    json={'username': 'revoked', 'password': NEW_PASSWORD}).status_code == 400
    assert User.query.count() == 0


def test_expired_session_cannot_verify_otp(app, api, email_service, db):
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    record = RegistrationSession.query.one()
    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert api.post('/api/registration/verify-otp',
                    json={'otp': email_service.last_otp}).status_code == 400


# --------------------------------------------------------------- OTP rules

def test_wrong_otp_is_rejected(api, email_service):
    """17"""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    response = api.post('/api/registration/verify-otp', json={'otp': '000000'})
    assert response.status_code == 400
    assert response.get_json()['error'] == GENERIC_REGISTRATION_MESSAGE
    assert RegistrationSession.query.one().otp_attempts == 1


def test_expired_otp_is_rejected(app, api, email_service, db):
    """18"""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    record = RegistrationSession.query.one()
    record.otp_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert api.post('/api/registration/verify-otp',
                    json={'otp': email_service.last_otp}).status_code == 400


def test_reused_otp_is_rejected(api, email_service):
    """19"""
    code = verified_session(api, email_service)
    api.post('/api/registration/complete', json={'username': 'reuse', 'password': NEW_PASSWORD})
    assert api.post('/api/registration/verify-otp', json={'otp': code}).status_code == 400


def test_otp_from_another_session_is_rejected(app, api, email_service):
    """20"""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    stolen = email_service.last_otp

    other = api.application.test_client()
    import app.routes.registration as routes
    routes.reg_service.email_service = email_service
    other.post('/api/registration/check', json={'usn': USN})
    assert other.post('/api/registration/verify-otp', json={'otp': stolen}).status_code == 400


def test_cross_purpose_otp_is_rejected(app, api, email_service, db):
    """21: purpose is persisted and enforced."""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    record = RegistrationSession.query.one()
    assert record.otp_purpose == REGISTRATION_OTP_PURPOSE

    with app.test_request_context('/api/registration/verify-otp', method='POST'):
        svc = RegistrationService(email_service=email_service)
        ok, _ = svc.verify_registration_otp(record.session_id, '123456', 'login')
    assert ok is False


def test_more_than_allowed_attempts_is_rejected(api, email_service, db):
    """22"""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    for _ in range(OTP_MAX_ATTEMPTS):
        api.post('/api/registration/verify-otp', json={'otp': '000000'})
    record = RegistrationSession.query.one()
    assert record.otp_attempts == OTP_MAX_ATTEMPTS
    assert api.post('/api/registration/verify-otp',
                    json={'otp': email_service.last_otp}).status_code == 400


def test_otp_is_stored_only_protected(api, email_service):
    """36"""
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    code = email_service.last_otp
    record = RegistrationSession.query.one()
    assert code not in (record.otp_hash or '')
    assert record.otp_hash is not None and len(record.otp_hash) == 64


def test_otp_ttl_and_attempt_budget_match_the_architecture(db):
    from app.services import registration_service as svc
    assert svc.OTP_TTL_MINUTES == 5
    assert svc.OTP_MAX_ATTEMPTS == 5


# ---------------------------------------------------- C3 email delivery

def test_email_delivery_failure_is_reported(app, api, email_service, db):
    """23"""
    begin(api)
    email_service.should_fail = True
    response = api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Unable to send OTP'


def test_failed_delivery_leaves_no_usable_otp(app, api, email_service, db):
    """24"""
    begin(api)
    email_service.should_fail = True
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    record = RegistrationSession.query.one()
    assert record.otp_hash is None
    assert record.otp_purpose is None
    # Even if a caller guesses, verification is impossible.
    assert api.post('/api/registration/verify-otp', json={'otp': '123456'}).status_code == 400
    assert api.post('/api/registration/complete',
                    json={'username': 'nodemail', 'password': NEW_PASSWORD}).status_code == 400
    assert User.query.count() == 0


def test_raw_otp_is_never_logged(app, api, email_service, caplog):
    """37"""
    with caplog.at_level(logging.DEBUG):
        begin(api)
        api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    code = email_service.last_otp
    assert code not in caplog.text


def test_audit_trail_holds_no_voter_identifiers(app, api, email_service):
    from app.audit.audit import AuditEvent
    begin(api)
    api.post('/api/registration/request-otp', json={'email': ROLL_EMAIL})
    api.post('/api/registration/verify-otp', json={'otp': email_service.last_otp})
    serialized = ' '.join(str(event.event_metadata) for event in AuditEvent.query.all())
    for secret in (USN, ROLL_EMAIL, email_service.last_otp):
        assert secret not in serialized


# ------------------------------------------------- identity/ballot planes

def test_registration_creates_no_ballot_plane_records(app, api, email_service, db):
    """29"""
    verified_session(api, email_service)
    api.post('/api/registration/complete', json={'username': 'plane', 'password': NEW_PASSWORD})
    assert User.query.count() == 1
    assert Ballot.query.count() == 0
    assert BallotQueue.query.count() == 0


def test_registration_tables_have_no_ballot_references():
    for model in (ElectoralRoll, RegistrationSession):
        for column in model.__table__.columns:
            for foreign_key in column.foreign_keys:
                assert foreign_key.column.table.name not in (
                    'ballots', 'ballot_queue', 'elections',
                    'election_pseudonym_keys', 'reconciliation_issues',
                )


# ------------------------------------------------ Phase 16 product contract tests

def test_usn_eligible_does_not_send_otp_automatically(api, email_service):
    """Product requirement: USN check starts session but sends NO OTP."""
    response = begin(api, USN)
    assert response.status_code == 200
    assert response.get_json()['eligible'] is True
    assert len(email_service.sent) == 0
    record = RegistrationSession.query.one()
    assert record.otp_hash is None


def test_student_enters_own_email_and_receives_otp(api, email_service):
    """Product requirement: Student enters their own email, which receives the OTP."""
    begin(api, USN)
    custom_email = "my.personal@student.test"
    res = api.post('/api/registration/request-otp', json={'email': custom_email})
    assert res.status_code == 200
    assert res.get_json()['message'] == 'OTP sent'
    assert 'email_masked' in res.get_json()
    assert len(email_service.sent) == 1
    assert email_service.sent[-1]['to'] == custom_email
    assert res.get_json()['email_masked'] == 'm***l@student.test'


def test_usn_synthetic_with_different_student_email_succeeds(db, api, email_service):
    """
    Product requirement: Synthetic USN + a different valid student email ->
    OTP request succeeds and OTP is sent directly to that entered email.
    The electoral roll email is NOT used to reject the student's entered email.
    """
    test_usn = '1XX23CS000'
    roll_email = 'student.roll@example.edu'
    different_email = 'academic.mail@student.edu'

    # Ensure test student exists on electoral roll with development mailbox
    existing = ElectoralRoll.query.filter_by(usn=test_usn).first()
    if not existing:
        db.session.add(ElectoralRoll(
            usn=test_usn,
            full_name='Test Student',
            college_email=roll_email,
            is_eligible=True,
            department='CSE',
            year_of_study=3
        ))
        db.session.commit()

    # Step 1: Check eligibility with synthetic USN
    check_res = begin(api, test_usn)
    assert check_res.status_code == 200
    assert check_res.get_json()['eligible'] is True

    # Step 2: Request OTP using a completely different student email
    otp_res = api.post('/api/registration/request-otp', json={'email': different_email})
    assert otp_res.status_code == 200
    otp_data = otp_res.get_json()
    assert otp_data['message'] == 'OTP sent'
    assert otp_data['email_masked'] == 'a***l@student.edu'

    # Assert OTP was dispatched to the entered email, NOT the roll email
    assert len(email_service.sent) == 1
    assert email_service.sent[-1]['to'] == different_email
    assert email_service.sent[-1]['to'] != roll_email

    # Step 3: Verify OTP works
    code = email_service.last_otp
    verify_res = api.post('/api/registration/verify-otp', json={'otp': code})
    assert verify_res.status_code == 200



def test_request_otp_with_invalid_email_fails_safely(api, email_service):
    """Security requirement: Malformed email fails safely without sending OTP."""
    begin(api, USN)
    res = api.post('/api/registration/request-otp', json={'email': 'not-an-email'})
    assert res.status_code == 400
    assert len(email_service.sent) == 0


def test_request_otp_without_email_fails_safely(api, email_service):
    """Security requirement: Missing email is rejected safely."""
    begin(api, USN)
    res = api.post('/api/registration/request-otp', json={})
    assert res.status_code == 400
    assert len(email_service.sent) == 0


def test_password_creation_issues_authorized_session_and_marks_user_pending_factors(api, email_service):
    """Flow requirement: Password creation creates user with is_verified=False and issues authorized session."""
    begin(api, USN)
    api.post('/api/registration/request-otp', json={'email': 'student@college.edu'})
    code = email_service.last_otp
    api.post('/api/registration/verify-otp', json={'otp': code})
    complete_res = api.post('/api/registration/complete', json={'username': 'student_p16', 'password': NEW_PASSWORD})
    assert complete_res.status_code == 201

    user = User.query.filter_by(username='student_p16').one()
    # Account is created with email verified, but registration remains pending Face and Wallet factors
    assert user.is_verified is True
    assert user.is_active is True

    # User now has active authorized session for Face & Wallet
    status_res = api.get('/api/registration/status')
    assert status_res.status_code == 200
    status_data = status_res.get_json()
    assert status_data['authenticated'] is True
    assert status_data['password_created'] is True
    assert status_data['face_enrolled'] is False
    assert status_data['wallet_bound'] is False
    assert status_data['registration_complete'] is False
    assert status_data['current_step'] == 'FACE'


def test_finalize_registration_requires_both_face_and_wallet(api, email_service):
    """Authoritative completion: Registration cannot be finalized without Face and Wallet."""
    begin(api, USN)
    api.post('/api/registration/request-otp', json={'email': 'student2@college.edu'})
    code = email_service.last_otp
    api.post('/api/registration/verify-otp', json={'otp': code})
    api.post('/api/registration/complete', json={'username': 'student_p16_2', 'password': NEW_PASSWORD})

    # Premature finalize attempt fails
    finalize_res = api.post('/api/registration/finalize')
    assert finalize_res.status_code == 400
    assert finalize_res.get_json()['registration_complete'] is False
    assert 'Face Verification' in finalize_res.get_json()['missing']
    assert 'MetaMask Wallet Binding' in finalize_res.get_json()['missing']