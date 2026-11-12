"""
Shared pytest fixtures - Phase 1 (remediated)
Vote Without Doubt - Backend

Phase 1 had no ``conftest.py``: every test module built its own app, no test
touched a database, and identity/ballot separation was asserted only by
inspecting an unpersisted object.

These fixtures give every test:

* an isolated application instance;
* an isolated on-disk SQLite database, created and destroyed per test, so
  constraint behaviour and persistence are genuinely exercised rather than
  mocked away;
* a test client bound to that application and database.

Isolation note: SQLite is used so the suite runs with no external service. The
MySQL-specific behaviour that SQLite cannot express (engine/charset, InnoDB,
JSON column type, ``DATETIME`` precision, ``AUTO_INCREMENT``) is verified
separately by ``tests/test_mysql_path.py`` and by applying the Alembic
migrations; see ``docs/PHASE1_REMEDIATION_REPORT.md`` for the documented MySQL
integration path.
"""

import os
import tempfile
import time

import pytest

os.environ.setdefault('FLASK_ENV', 'testing')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('OTP_PEPPER', 'test-otp-pepper-not-for-production-use')
os.environ.setdefault('TESTING_SECRET_KEY', 'testing-only-secret-not-for-production')

# Phase 5 biometric configuration. The encryption key is fixed and explicitly
# non-production so templates written by one test can be read by another; the
# similarity threshold is the FIXTURE-DOMAIN value measured on the synthetic
# fixtures (see tests/face_fixtures.py). Production sets its own and refuses to
# boot without both.
os.environ.setdefault('FACE_ENCRYPTION_KEY', 'lnM7afwMMzvIom2qb0f13DjQZSo4pFoRS0ztukO6Ay4=')
os.environ.setdefault('FACE_SIMILARITY_THRESHOLD', '0.83')

# Phase 8 pseudonym master encryption key for test suites.
os.environ.setdefault('PSEUDONYM_MASTER_KEY', 'k8v9t6QG9_8t8S6vL5P6s1zZ-7v_8y4w2x1a0b3c4d5=')

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402


def _remove_quietly(path: str, attempts: int = 5) -> None:
    """Delete a file, tolerating a briefly-retained handle on Windows."""
    for attempt in range(attempts):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                return
            time.sleep(0.05)


@pytest.fixture
def app():
    """Application instance with a private database file, torn down afterwards."""
    handle, database_path = tempfile.mkstemp(suffix='.sqlite3', prefix='votest_')
    os.close(handle)
    os.unlink(database_path)

    previous_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = f'sqlite:///{database_path}'

    application = create_app('testing')

    yield application

    if previous_url is None:
        os.environ.pop('DATABASE_URL', None)
    else:
        os.environ['DATABASE_URL'] = previous_url

    with application.app_context():
        _db.session.remove()
        try:
            _db.drop_all()
        except Exception:
            pass
        for engine in list(_db.engines.values()):
            engine.dispose()

    _remove_quietly(database_path)


@pytest.fixture
def db(app):
    """Application context with all tables created; rolled back and dropped after."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app, db):
    """Flask test client bound to the isolated application and database."""
    return app.test_client()


@pytest.fixture
def audit_logger(app, db):
    """An AuditLogger bound to the isolated test database."""
    from app.audit.audit import AuditLogger
    return AuditLogger()


# ---------------------------------------------------------------------------
# Phase 2 Auth Core fixtures
# ---------------------------------------------------------------------------

PHASE2_USERNAME = 'phase2user'
PHASE2_PASSWORD = 'correct-horse-battery'
PHASE2_EMAIL = 'phase2user@college.test'


class RecordingEmailService:
    """Stand-in for :class:`app.email.service.EmailService`.

    Records every delivery attempt and can be told to fail, so the suite can
    prove that a delivery failure is reported honestly instead of being reported
    as a success. This exercises the same call path the real service uses.
    """

    def __init__(self, should_fail: bool = False):
        self.sent = []
        self.should_fail = should_fail

    def send_otp(self, recipient_email, otp, purpose='login'):
        if self.should_fail:
            return False
        self.sent.append({'to': recipient_email, 'otp': otp, 'purpose': purpose})
        return True

    @property
    def last_otp(self):
        return self.sent[-1]['otp'] if self.sent else None


@pytest.fixture
def email_service():
    """Recording SMTP transport used in place of a live Mailpit instance."""
    return RecordingEmailService()


@pytest.fixture
def auth_service(app, db, email_service):
    """AuthService wired to the recording transport."""
    from app.services.auth_service import AuthService
    return AuthService(email_service=email_service)


@pytest.fixture
def phase2_user(db):
    """An existing, verified, active account (Phase 2 does not create accounts)."""
    from app.models import User
    from app.security.password import hash_password
    account = User(
        username=PHASE2_USERNAME,
        email=PHASE2_EMAIL,
        password_hash=hash_password(PHASE2_PASSWORD),
        is_active=True,
        is_verified=True,
    )
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture
def auth_api(app, db, email_service):
    """Test client whose auth routes use the recording transport."""
    import app.routes.auth as auth_routes
    auth_routes.auth_service.email_service = email_service
    return app.test_client()


@pytest.fixture
def cookie_of(app):
    """Extract the raw signed session cookie value from a response."""
    def _extract(response):
        prefix = app.config['SESSION_COOKIE_NAME'] + '='
        for header in response.headers.getlist('Set-Cookie'):
            if header.startswith(prefix):
                return header.split(';')[0].split('=', 1)[1]
        return None
    return _extract


@pytest.fixture
def client_for(app):
    """Build a client presenting exactly the supplied session cookie."""
    def _build(value):
        test_client = app.test_client()
        test_client.set_cookie(app.config['SESSION_COOKIE_NAME'], value)
        return test_client
    return _build


@pytest.fixture
def signed_cookie_for(app):
    """Mint a validly signed session cookie carrying a given server-side session id.

    Flask stores session data in a signed cookie, so a raw session id is not a
    usable cookie value. Tests that seed an AuthSession row directly must present
    a properly signed cookie, otherwise every request would be rejected for the
    wrong reason and the assertion would pass vacuously.
    """
    def _mint(session_id):
        serializer = app.session_interface.get_signing_serializer(app)
        return serializer.dumps({'session_id': session_id})
    return _mint


@pytest.fixture
def client_for_session(app, signed_cookie_for):
    """Build a client presenting a signed cookie for a seeded session id."""
    def _build(session_id):
        test_client = app.test_client()
        test_client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                               signed_cookie_for(session_id))
        return test_client
    return _build


@pytest.fixture
def begin_login(auth_api):
    """Perform only the password step of the login flow."""
    def _login(username=PHASE2_USERNAME, password=PHASE2_PASSWORD):
        response = auth_api.post('/api/auth/login', json={'username': username, 'password': password})
        assert response.status_code == 200, response.get_json()
        return response
    return _login


@pytest.fixture
def full_login(auth_api, email_service, begin_login):
    """Password -> OTP -> authorized. Returns (pre_cookie, post_cookie, otp)."""
    def _login(app=None):
        begin_login()
        requested = auth_api.post('/api/auth/request-otp', json={})
        assert requested.status_code == 200, requested.get_json()
        code = email_service.last_otp
        verified = auth_api.post('/api/auth/verify-otp', json={'otp': code})
        assert verified.status_code == 200, verified.get_json()
        return verified, code
    return _login

# ---------------------------------------------------------------------------
# Phase 5 face recognition fixtures
# ---------------------------------------------------------------------------

PHASE5_USERNAME = 'phase5face'
PHASE5_PASSWORD = 'phase5-face-password'


@pytest.fixture
def face_user(db):
    """A verified, active account to attach a face template to."""
    from app.models import User
    from app.security.password import hash_password
    account = User(
        username=PHASE5_USERNAME,
        email='phase5face@college.test',
        password_hash=hash_password(PHASE5_PASSWORD),
        is_active=True,
        is_verified=True,
    )
    db.session.add(account)
    db.session.commit()
    return account


def _seed_authorized_session(db, user, session_id=None, auth_state='AUTHORIZED'):
    """Insert a live AuthSession row directly (no OTP round trip)."""
    import secrets as _secrets
    from datetime import datetime, timedelta
    from app.models import AuthSession
    now = datetime.utcnow()
    record = AuthSession(
        session_id=session_id or _secrets.token_hex(24),
        user_id=user.id,
        auth_state=auth_state,
        authenticated_at=now,
        expires_at=now + timedelta(hours=2),
        idle_expires_at=now + timedelta(minutes=10),
        last_activity=now,
        revoked=False,
    )
    db.session.add(record)
    db.session.commit()
    return record


@pytest.fixture
def face_session(db, face_user):
    """A live AUTHORIZED session for the Phase 5 user."""
    return _seed_authorized_session(db, face_user)


@pytest.fixture
def face_client(app, db, face_session, signed_cookie_for, face_rate_limits):
    """Test client presenting a signed cookie for a live authorized session.

    Depends on ``face_rate_limits`` so the shipped per-endpoint budgets do not
    fail unrelated tests that legitimately make several biometric requests.
    """
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      signed_cookie_for(face_session.session_id))
    return client


@pytest.fixture
def second_face_session(db, face_user):
    """A second, different authorized session for the same user."""
    return _seed_authorized_session(db, face_user)


@pytest.fixture
def other_face_user(db):
    """A second account, for cross-user challenge and template isolation."""
    from app.models import User
    from app.security.password import hash_password
    account = User(
        username='phase5other',
        email='phase5other@college.test',
        password_hash=hash_password(PHASE5_PASSWORD),
        is_active=True,
        is_verified=True,
    )
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture
def real_face_engine():
    """Return the real InsightFace engine, failing loudly if weights are absent.

    Deliberately NOT a skip: a missing model tree is a genuine Phase 5 failure
    and must be visible rather than silently excluded from the run.
    """
    from app.services.face_engine import get_engine
    try:
        return get_engine()
    except Exception as error:
        pytest.fail(
            'The real face engine could not be loaded, so the Phase 5 suite '
            f'cannot verify anything: {error!r}. Provision the InsightFace '
            'buffalo_l weights under backend/face_models.'
        )


@pytest.fixture
def face_rate_limits(app, db):
    """Relaxed Phase 5 rate-limit budgets plus a reset limiter.

    The shipped budgets (3 challenges/minute, 5 enrolments/5min, 10
    verifications/5min) are genuinely enforced and are asserted by
    ``test_phase5_face_security.py::test_rate_limits_actually_engage``.
    Every other test raises them so an unrelated test cannot fail merely
    because it made several biometric requests.
    """
    from app.security.rate_limit import InMemoryRateLimiter
    keys = ('FACE_RATE_LIMIT_CHALLENGE', 'FACE_RATE_LIMIT_ENROLL',
            'FACE_RATE_LIMIT_VERIFY')
    saved = {key: app.config[key] for key in keys}
    for key in keys:
        app.config[key] = (10000, 60)
    app.extensions['rate_limiter'] = InMemoryRateLimiter()
    yield app
    for key in keys:
        app.config[key] = saved[key]
    app.extensions['rate_limiter'] = InMemoryRateLimiter()



MULTIPART_BOUNDARY = '----votestphase5faceboundary'


def encode_multipart(fields, files):
    """Build a real ``multipart/form-data`` body.

    ``fields`` is a sequence of ``(name, value)`` and ``files`` a sequence of
    ``(name, filename, blob)``. Encoding the body by hand is deliberate: it lets
    one field name carry several file parts, exactly as a browser FormData built
    with repeated ``append('frames', ...)`` calls does. Werkzeug's test client
    cannot express repeated keys through its ``data=`` mapping.
    """
    parts = []
    for name, value in fields:
        parts.append(f'--{MULTIPART_BOUNDARY}'.encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b'')
        parts.append(str(value).encode())
    for name, filename, blob in files:
        parts.append(f'--{MULTIPART_BOUNDARY}'.encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode())
        parts.append(b'Content-Type: image/jpeg')
        parts.append(b'')
        parts.append(bytes(blob))
    parts.append(f'--{MULTIPART_BOUNDARY}--'.encode())
    parts.append(b'')
    return b'\r\n'.join(parts)


def post_frames(client, url, frames, challenge_id, consent=None, purpose=None):
    """POST a real multipart submission with ``frames`` as repeated JPEG parts."""
    fields = [('challenge_id', challenge_id)]
    if consent is not None:
        fields.append(('consent', 'true' if consent else 'false'))
    if purpose is not None:
        fields.append(('purpose', purpose))
    files = [('frames', f'frame_{index}.jpg', blob)
             for index, blob in enumerate(frames)]
    body = encode_multipart(fields, files)
    return client.post(
        url, data=body,
        content_type=f'multipart/form-data; boundary={MULTIPART_BOUNDARY}',
    )

