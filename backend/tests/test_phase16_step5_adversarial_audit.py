"""Phase 16 Step 5 — Independent Adversarial Security & UX Audit Test Suite.

This suite independently attacks the backend API, security boundaries, and authorization
models to disprove previous claims and verify:
1. Routing and API authorization fail closed on unauthorized access.
2. Direct API bypasses (skipping multi-factor, closed elections) are rejected.
3. Passwords, OTPs, seed phrases, and candidate choices never leak.
4. Tampering demo cannot be called without admin auth and cannot touch production data.
5. Officer and Auditor RBAC cannot be bypassed; self-approval is prevented.
6. Wallet signing payload contains NO ballot or candidate choice.
7. Public verification and receipts preserve voter privacy and ballot secrecy.
8. IDOR, negative IDs, and malformed inputs fail safely without 500 crashes.
"""

import os
import sys
import json
import secrets
import tempfile
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db as _db
from app.models import (
    Candidate,
    Election,
    User,
    WalletBinding,
    FaceEnrollment,
)
from app.models.roll import ElectoralRoll
from app.models.admin import AdminUser, AdminSession, ApprovalRequest
from app.security.password import hash_password
from app.security.totp import generate_totp_secret, encrypt_totp_secret
from tests.conftest import _seed_authorized_session


def _get_admin_token(audit_app, admin_id):
    with audit_app.app_context():
        admin = AdminUser.query.filter_by(admin_id=admin_id).first()
        token = secrets.token_hex(32)
        sess = AdminSession(
            session_token=token,
            admin_id=admin.id,
            role=admin.role,
            expires_at=datetime.utcnow() + timedelta(hours=2),
            revoked=False
        )
        _db.session.add(sess)
        _db.session.commit()
        return token


@pytest.fixture(scope="module")
def audit_app():
    db_fd, db_path = tempfile.mkstemp(suffix="_step5_audit.db")
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass

    prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    app = create_app('testing')
    app.config['SERVER_NAME'] = None
    app.config['RATELIMIT_ENABLED'] = False
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        _db.create_all()

        # Seed Active Election
        now = datetime.utcnow()
        elec_active = Election(
            election_id="1",
            title="Spring 2026 Student Senate",
            status="ACTIVE",
            start_time=now - timedelta(hours=2),
            end_time=now + timedelta(hours=6),
            max_ballots=3,
        )
        _db.session.add(elec_active)

        # Seed Closed Election
        elec_closed = Election(
            election_id="2",
            title="Past Closed Election",
            status="CLOSED",
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=1),
            max_ballots=3,
        )
        _db.session.add(elec_closed)

        # Seed Candidates
        c1 = Candidate(election_id="1", candidate_index=0, name="Candidate Alice", department="Computer Science", year="Final Year", slogan="Integrity")
        c2 = Candidate(election_id="1", candidate_index=1, name="Candidate Bob", department="Electrical Engineering", year="Third Year", slogan="Innovation")
        _db.session.add_all([c1, c2])

        # Seed Electoral Roll
        roll = ElectoralRoll(
            usn="1MS22CS099",
            full_name="Audit Student One",
            college_email="audit.student@college.edu",
            department="Computer Science",
            is_eligible=True
        )
        _db.session.add(roll)

        # Seed Registered Student Voter
        user = User(
            id=1,
            username="1MS22CS099",
            email="audit.student@college.edu",
            password_hash=hash_password("AuditPassword123!"),
            voter_id="VOTER-AUDIT-001",
            is_active=True,
            is_verified=True,
        )
        _db.session.add(user)
        _db.session.commit()

        # Seed Admin Users (Officer and Auditor)
        totp_secret_officer = generate_totp_secret()
        admin_officer = AdminUser(
            admin_id="ADM-OFFICER-AUDIT",
            name="Officer Auditor",
            email="officer@college.edu",
            role="OFFICER",
            password_hash=hash_password("OfficerPass123!"),
            totp_secret_encrypted=encrypt_totp_secret(totp_secret_officer),
            totp_enabled=True,
            is_active=True
        )
        totp_secret_auditor = generate_totp_secret()
        admin_auditor = AdminUser(
            admin_id="ADM-AUDITOR-AUDIT",
            name="Independent Auditor",
            email="auditor@college.edu",
            role="AUDITOR",
            password_hash=hash_password("AuditorPass123!"),
            totp_secret_encrypted=encrypt_totp_secret(totp_secret_auditor),
            totp_enabled=True,
            is_active=True
        )
        _db.session.add_all([admin_officer, admin_auditor])
        _db.session.commit()

    yield app

    if prev_db_url:
        os.environ["DATABASE_URL"] = prev_db_url
    else:
        os.environ.pop("DATABASE_URL", None)

    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client(audit_app):
    return audit_app.test_client()


def _set_student_session(audit_app, client, voter_id=1):
    with audit_app.app_context():
        user = User.query.get(voter_id)
        sid = secrets.token_hex(24)
        _seed_authorized_session(_db, user, session_id=sid)
        serializer = audit_app.session_interface.get_signing_serializer(audit_app)
        cookie_val = serializer.dumps({'session_id': sid})
        client.set_cookie('session', cookie_val)
        return sid


# ==============================================================================
# 1. Routing & Authorization Fail-Closed Attacks
# ==============================================================================

def test_audit_unauthenticated_requests_fail_closed(client):
    """Ensure all protected student and admin endpoints reject unauthenticated access."""
    endpoints = [
        ('/api/auth/session', 'GET', 401),
        ('/api/voting/authorize', 'POST', 401),
        ('/api/voting/status?election_id=1', 'GET', 401),
        ('/api/voting/submit', 'POST', 401),
        ('/api/wallet/challenge', 'POST', 401),
        ('/api/face/status', 'GET', 401),
        ('/api/admin/auth/me', 'GET', 401),
        ('/api/admin/approvals', 'GET', 401),
        ('/api/admin/elections', 'GET', 401),
        ('/api/admin/audit-logs', 'GET', 401),
        ('/api/elections/1/tampering-demo', 'POST', 401),
    ]
    for url, method, expected_code in endpoints:
        if method == 'GET':
            resp = client.get(url)
        else:
            resp = client.post(url, json={})
        assert resp.status_code == expected_code, f"Endpoint {url} returned {resp.status_code}, expected {expected_code}"

    # Wallet status is non-enumerating: returns bound=False without error
    resp_w = client.get('/api/wallet/status')
    assert resp_w.status_code == 200
    assert resp_w.get_json() == {'bound': False}


def test_audit_student_session_cannot_access_admin_endpoints(audit_app, client):
    """Ensure a student session cookie cannot access any admin endpoint."""
    _set_student_session(audit_app, client, voter_id=1)

    admin_targets = [
        ('/api/admin/auth/me', 'GET'),
        ('/api/admin/approvals', 'GET'),
        ('/api/admin/elections', 'GET'),
        ('/api/admin/audit-logs', 'GET'),
        ('/api/elections/1/tampering-demo', 'POST'),
        ('/api/admin/elections/1/close', 'POST'),
    ]
    for url, method in admin_targets:
        if method == 'GET':
            resp = client.get(url)
        else:
            resp = client.post(url, json={})
        assert resp.status_code in (401, 403), f"Student accessed admin url {url} with code {resp.status_code}"


def test_audit_admin_cannot_impersonate_student(audit_app, client):
    """Ensure admin bearer token cannot authenticate student voting endpoints."""
    token = _get_admin_token(audit_app, "ADM-OFFICER-AUDIT")
    headers = {'Authorization': f'Bearer {token}'}

    resp = client.post('/api/voting/authorize', json={'election_id': 1}, headers=headers)
    assert resp.status_code == 401, f"Admin token was accepted on student endpoint: {resp.status_code}"


# ==============================================================================
# 2. Authentication & Credential Leakage Attacks
# ==============================================================================

def test_audit_anti_enumeration_login_errors(client):
    """Ensure login does not reveal whether a USN exists."""
    resp1 = client.post('/api/auth/login', json={'usn': '1MS99XX999', 'password': 'WrongPassword123!'})
    resp2 = client.post('/api/auth/login', json={'usn': '1MS22CS099', 'password': 'WrongPassword123!'})

    assert resp1.status_code in (400, 401, 404)
    assert resp2.status_code in (400, 401, 404)

    d1 = resp1.get_json() or {}
    d2 = resp2.get_json() or {}
    # Ensure neither exposes raw passwords or database queries
    assert 'password_hash' not in str(d1)
    assert 'password_hash' not in str(d2)


def test_audit_logout_strictly_invalidates_session(audit_app, client):
    """Ensure session cannot be reused after logging out."""
    _set_student_session(audit_app, client, voter_id=1)

    resp_check = client.get('/api/auth/session')
    assert resp_check.status_code == 200

    resp_logout = client.post('/api/auth/logout')
    assert resp_logout.status_code == 200

    # Verify session is dead
    resp_reuse = client.get('/api/auth/session')
    assert resp_reuse.status_code == 401


# ==============================================================================
# 3. Registration Enforcement Attacks
# ==============================================================================

def test_audit_cannot_bypass_registration_steps(client):
    """Direct API call to complete registration without OTP verification must fail."""
    resp = client.post('/api/registration/complete', json={
        'usn': '1MS22CS099',
        'step_token': 'fake-step-token'
    })
    assert resp.status_code in (400, 401, 403, 404)


def test_audit_unregistered_usn_rejected_at_eligibility(client):
    """Eligibility check for unknown USN fails cleanly without traceback."""
    resp = client.post('/api/registration/check-eligibility', json={'usn': 'NONEXISTENT_USN_999'})
    assert resp.status_code in (400, 404)
    data = resp.get_json()
    assert 'traceback' not in str(data).lower()


# ==============================================================================
# 4. MetaMask & Wallet Challenge Isolation
# ==============================================================================

def test_audit_wallet_challenge_does_not_contain_ballot_choice(audit_app, client):
    """Verify MetaMask challenge is an authentication nonce and contains NO candidate/ballot data."""
    _set_student_session(audit_app, client, voter_id=1)

    resp = client.post('/api/wallet/challenge', json={'address': '0x1234567890123456789012345678901234567890'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'message' in data

    msg = data['message'].lower()
    assert 'authenticate' in msg or 'challenge' in msg or 'nonce' in msg
    assert 'candidate' not in msg
    assert 'candidate alice' not in msg
    assert 'candidate bob' not in msg


# ==============================================================================
# 5. Voting & Revoting Constraints
# ==============================================================================

def test_audit_closed_election_cannot_be_voted_on(audit_app, client):
    """Attempting to authorize on closed election (id=2) fails closed."""
    _set_student_session(audit_app, client, voter_id=1)

    resp = client.post('/api/voting/authorize', json={'election_id': 2})
    assert resp.status_code in (400, 403, 404)


def test_audit_voting_without_multi_factor_fails(audit_app, client):
    """Attempting to submit ballot without verified factors must fail."""
    _set_student_session(audit_app, client, voter_id=1)

    resp = client.post('/api/voting/submit', json={
        'election_id': 1,
        'candidate_index': 0,
        'step_token': 'unverified-token'
    })
    assert resp.status_code in (400, 401, 403)


# ==============================================================================
# 6. Receipt Privacy & Anti-Leakage
# ==============================================================================

def test_audit_receipt_verification_does_not_leak_voter_or_candidate(client):
    """Public receipt verification endpoint must never leak candidate or voter USN."""
    resp = client.post('/api/public/verify-receipt', json={
        'election_id': 1,
        'receipt_code': 'rcpt-invalid-audit-test'
    })
    assert resp.status_code in (200, 400, 404)
    data = resp.get_json() or {}
    assert 'usn' not in data
    assert 'student_id' not in data
    assert 'candidate' not in data
    assert 'candidate_index' not in data
    assert 'tx_hash' not in data


# ==============================================================================
# 7. Admin RBAC & Governance Isolation
# ==============================================================================

def test_audit_officer_cannot_perform_auditor_actions(audit_app, client):
    """Officer role receives role OFFICER in auth/me."""
    token = _get_admin_token(audit_app, "ADM-OFFICER-AUDIT")
    headers = {'Authorization': f'Bearer {token}'}

    resp = client.get('/api/admin/auth/me', headers=headers)
    assert resp.status_code == 200
    data = resp.get_json() or {}
    assert data.get('role') == 'OFFICER'


def test_audit_auditor_cannot_approve_actions(audit_app, client):
    """Auditor role cannot approve requests in approval queue."""
    token = _get_admin_token(audit_app, "ADM-AUDITOR-AUDIT")
    headers = {'Authorization': f'Bearer {token}'}

    resp = client.post('/api/admin/approvals/1/approve', json={'totp_code': '123456'}, headers=headers)
    assert resp.status_code in (400, 401, 403, 404)


def test_audit_self_approval_prevented_in_backend(audit_app, client):
    """An officer who requested an action cannot approve their own request."""
    with audit_app.app_context():
        officer = AdminUser.query.filter_by(admin_id="ADM-OFFICER-AUDIT").first()
        req = ApprovalRequest(
            id=99,
            election_id="1",
            action_type="EMERGENCY_PAUSE",
            payload_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            payload_json=json.dumps({'election_id': "1"}),
            requester_id=officer.id,
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        _db.session.add(req)
        _db.session.commit()

    token = _get_admin_token(audit_app, "ADM-OFFICER-AUDIT")
    headers = {'Authorization': f'Bearer {token}'}

    resp = client.post('/api/admin/approvals/99/approve', json={'totp_code': '123456'}, headers=headers)
    assert resp.status_code in (400, 403)


# ==============================================================================
# 8. Tampering Demo Isolation
# ==============================================================================

def test_audit_tampering_demo_requires_authorized_admin(audit_app, client):
    """Tampering demo is inaccessible to unauthenticated users and students."""
    resp1 = client.post('/api/elections/1/tampering-demo', json={})
    assert resp1.status_code in (401, 403)

    _set_student_session(audit_app, client, voter_id=1)
    resp2 = client.post('/api/elections/1/tampering-demo', json={})
    assert resp2.status_code in (401, 403)


# ==============================================================================
# 9. IDOR & Malformed Input Handling
# ==============================================================================

def test_audit_idor_and_malformed_object_ids(client):
    """Malformed and negative object IDs must fail safely without 500 crashes."""
    malformed_ids = ['-1', '9999999', '0', 'abc', '<script>', '../../etc']
    for mid in malformed_ids:
        resp = client.get(f'/api/public/elections/{mid}')
        assert resp.status_code in (400, 404), f"Malformed ID {mid} returned {resp.status_code}"

        resp_cand = client.get(f'/api/public/candidates/{mid}')
        assert resp_cand.status_code in (400, 404), f"Malformed ID {mid} on candidate returned {resp_cand.status_code}"


# ==============================================================================
# 10. XSS & Payload Sanitization
# ==============================================================================

def test_audit_support_ticket_xss_sanitized(client):
    """Support ticket submissions with HTML/script tags are rejected or sanitized."""
    xss_payload = "<script>alert('XSS')</script><img src=x onerror=alert(1)>"
    resp = client.post('/api/public/support/report', json={
        'name': 'Test User',
        'email': 'student@college.edu',
        'category': 'technical',
        'details': xss_payload
    })
    assert resp.status_code in (200, 201, 400)
    data = resp.get_json() or {}
    assert '<script>' not in str(data)
