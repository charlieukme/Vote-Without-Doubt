"""Phase 2 - password security, lockout, anti-enumeration and secret hygiene.

Mandatory cases covered here: 4, 5, 6, 27, 28, 30, 35.
"""

import logging
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import AuthSession, User
from app.services.auth_service import LOCKOUT_MINUTES, MAX_FAILED_LOGINS
from tests.conftest import (
    PHASE2_EMAIL,
    PHASE2_PASSWORD,
    PHASE2_USERNAME,
    RecordingEmailService,
)


def login(auth_api, username=PHASE2_USERNAME, password=PHASE2_PASSWORD):
    return auth_api.post('/api/auth/login', json={'username': username, 'password': password})


def test_password_hash_is_argon2id(phase2_user):
    """A"""
    assert phase2_user.password_hash.startswith('$argon2id$v=19$m=')
    assert PHASE2_PASSWORD not in phase2_user.password_hash


def test_raw_password_is_never_persisted(phase2_user):
    """28"""
    row = db.session.execute(
        db.select(User).where(User.username == PHASE2_USERNAME)
    ).scalars().one()
    assert PHASE2_PASSWORD not in repr(row.__dict__)


def test_correct_password_is_accepted(auth_api, phase2_user):
    assert login(auth_api).status_code == 200


def test_wrong_password_returns_generic_failure(auth_api, phase2_user):
    """4"""
    response = login(auth_api, password='wrong-password')
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Invalid credentials'}


def test_errors_do_not_reveal_whether_an_account_exists(auth_api, phase2_user):
    """27: identical status and body for unknown account and wrong password."""
    missing = login(auth_api, username='no-such-account')
    wrong = login(auth_api, password='wrong-password')

    assert missing.status_code == wrong.status_code == 401
    assert missing.get_json() == wrong.get_json() == {'error': 'Invalid credentials'}
    assert b'no-such-account' not in missing.data
    assert PHASE2_USERNAME.encode() not in wrong.data
    assert PHASE2_EMAIL.encode() not in wrong.data


def test_repeated_wrong_passwords_lock_the_account(auth_api, phase2_user):
    """5"""
    for _ in range(MAX_FAILED_LOGINS):
        assert login(auth_api, password='wrong-password').status_code == 401

    assert phase2_user.failed_login_attempts == MAX_FAILED_LOGINS
    assert phase2_user.locked_until is not None
    remaining = phase2_user.locked_until - datetime.utcnow()
    assert timedelta(minutes=LOCKOUT_MINUTES - 1) < remaining <= timedelta(
        minutes=LOCKOUT_MINUTES)


def test_correct_password_while_locked_is_rejected(auth_api, phase2_user):
    """6"""
    for _ in range(MAX_FAILED_LOGINS):
        login(auth_api, password='wrong-password')

    response = login(auth_api)
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Invalid credentials'}


def test_lockout_expires_and_login_succeeds_again(auth_api, phase2_user):
    """K"""
    for _ in range(MAX_FAILED_LOGINS):
        login(auth_api, password='wrong-password')

    phase2_user.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()

    assert login(auth_api).status_code == 200


def test_successful_login_clears_the_failure_counter(auth_api, phase2_user):
    """K"""
    login(auth_api, password='wrong-password')
    login(auth_api, password='wrong-password')
    assert phase2_user.failed_login_attempts == 2

    assert login(auth_api).status_code == 200
    assert phase2_user.failed_login_attempts == 0
    assert phase2_user.locked_until is None


def test_raw_otp_and_session_ids_are_never_logged(auth_api, email_service, phase2_user,
                                                 caplog):
    """30"""
    with caplog.at_level(logging.DEBUG):
        auth_api.post('/api/auth/login',
                      json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
        auth_api.post('/api/auth/request-otp', json={})
        auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})

    code = email_service.last_otp
    assert code not in caplog.text

    for record in AuthSession.query.all():
        assert record.session_id not in caplog.text

    for entry in caplog.records:
        message = entry.getMessage()
        assert code not in message
        assert PHASE2_PASSWORD not in message


def test_audit_events_contain_no_authentication_identifiers(auth_api, email_service,
                                                            phase2_user):
    """P/30: the audit trail records that events happened, never who or which session."""
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})

    from app.audit.audit import AuditEvent
    serialized = ' '.join(str(event.event_metadata) for event in AuditEvent.query.all())

    for secret in (PHASE2_USERNAME, PHASE2_EMAIL, PHASE2_PASSWORD, email_service.last_otp):
        assert secret not in serialized
    for record in AuthSession.query.all():
        assert record.session_id not in serialized


def test_audit_chain_stays_valid_across_the_login_lifecycle(auth_api, email_service,
                                                             phase2_user):
    """Audit integrity is preserved while authentication runs."""
    from app.audit.audit import AuditLogger

    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    auth_api.post('/api/auth/logout', json={})

    assert AuditLogger().verify_chain() is True


def test_missing_pepper_fails_closed_for_production(monkeypatch):
    """35"""
    from app.security import otp as otp_module

    monkeypatch.delenv('OTP_PEPPER', raising=False)

    class ProductionApp:
        config = {'APP_ENV': 'production'}

    with pytest.raises(RuntimeError, match='OTP_PEPPER'):
        otp_module.get_otp_pepper(app=ProductionApp())


def test_production_app_refuses_to_boot_without_pepper(monkeypatch):
    """35"""
    from app.config.config import ProductionConfig

    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'k' * 48, raising=False)
    monkeypatch.setattr(ProductionConfig, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:',
                        raising=False)
    monkeypatch.delenv('OTP_PEPPER', raising=False)
    monkeypatch.setattr('app.load_dotenv', lambda *a, **kw: None)

    with pytest.raises(RuntimeError, match='OTP_PEPPER'):
        create_app('production')


def test_non_production_environments_use_the_explicit_test_pepper(monkeypatch):
    """35: the fallback exists, is named as non-production, and is test-only."""
    from app.security import otp as otp_module

    monkeypatch.delenv('OTP_PEPPER', raising=False)

    class TestingApp:
        config = {'APP_ENV': 'testing'}

    pepper = otp_module.get_otp_pepper(app=TestingApp())
    assert pepper == otp_module.NON_PRODUCTION_PEPPER.encode()
    assert 'not-for-production' in otp_module.NON_PRODUCTION_PEPPER


def test_configured_pepper_is_used_when_present(monkeypatch):
    """F"""
    from app.security import otp as otp_module

    monkeypatch.setenv('OTP_PEPPER', 'a-unique-pepper-for-this-test')

    class ProductionApp:
        config = {'APP_ENV': 'production'}

    assert otp_module.get_otp_pepper(app=ProductionApp()) == b'a-unique-pepper-for-this-test'


def test_different_peppers_produce_different_otp_hashes(monkeypatch):
    """F: the pepper is genuinely part of the protection."""
    from app.security import otp as otp_module

    monkeypatch.setenv('OTP_PEPPER', 'pepper-one')
    first = otp_module.hash_otp('123456')

    monkeypatch.setenv('OTP_PEPPER', 'pepper-two')
    second = otp_module.hash_otp('123456')

    assert first != second


def test_real_email_service_contract_is_used_by_the_service(app, db, phase2_user):
    """O: AuthService depends on the documented EmailService interface."""
    from app.email.service import EmailService
    from app.services.auth_service import AuthService

    service = AuthService()
    assert isinstance(service.email_service, EmailService)
    assert callable(service.email_service.send_otp)

    recorder = RecordingEmailService()
    assert AuthService(email_service=recorder).email_service is recorder


def test_email_service_reads_smtp_configuration_from_the_environment(monkeypatch):
    """O: no hard-coded SMTP credentials."""
    from app.email import service as email_module

    source = open(email_module.__file__, encoding='utf-8-sig').read()
    for variable in ('MAIL_SERVER', 'MAIL_PORT', 'MAIL_USE_TLS', 'MAIL_USE_SSL',
                     'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER'):
        assert f"os.getenv('{variable}'" in source
