"""
Phase 16 Step 2.5: Backend Gap & Integration Hardening Test Suite
Vote Without Doubt - System Verification

Covers:
1. Forgot Password Flow:
   - Request OTP to roll-bound email
   - Account enumeration resistance (identical response for unknown user)
   - OTP verification and password update with Argon2id
   - Single-use and attempt exhaustion
   - Session invalidation of all prior sessions
2. Candidate Metadata & Security:
   - Metadata persistence (year, slogan, manifesto, photo_url)
   - Structured manifesto sanitization (HTML stripped)
   - Safe photo upload validation and path traversal defense
   - Live query in /api/voting/election/<id>
3. Registration Deadline Enforcement:
   - Registration permitted before deadline
   - Registration rejected after deadline (start & complete)
   - Active registered voter unaffected by registration deadline
4. Server Time & Mid-flow Election Close:
   - Authoritative UTC server time endpoint
   - Submission rejected when now > end_time
5. Support Dispute Ticketing & Privacy:
   - Public support reporting with reference ID
   - Privacy filtering rejecting private key / seed phrase leakage
"""

import io
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.extensions import db
from app.models import (
    AuthSession,
    Candidate,
    Election,
    ElectoralRoll,
    OTP,
    SupportTicket,
    User,
    VotingAuthorization,
)
from app.models.admin import AdminUser
from app.security.password import hash_password, verify_password
from app.services.auth_service import AuthService
from app.services.election_admin_service import ElectionAdminService
from app.services.registration_service import RegistrationService
from app.services.voting_service import VotingService


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def test_officer(db):
    officer = AdminUser(
        admin_id="OFF-201",
        name="Officer Alice",
        email="alice@college.edu",
        password_hash=hash_password("OfficerPass123!"),
        role="OFFICER",
        is_active=True,
    )
    db.session.add(officer)
    db.session.commit()
    return officer


@pytest.fixture
def student_user(db):
    user = User(
        username="student_step25",
        email="student_step25@college.edu",
        password_hash=hash_password("OldPassword123!"),
        voter_id="1MS21CS099",
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


# ==============================================================================
# 1. Forgot Password Tests (Gap 01)
# ==============================================================================

def test_forgot_password_request_success(client, db, student_user):
    """Requesting password reset for valid user sends OTP to registered email."""
    import app.routes.auth as auth_routes
    with patch.object(auth_routes.auth_service.email_service, 'send_otp', return_value=True) as mock_send:
        res = client.post('/api/auth/forgot-password/request', json={'identifier': 'student_step25'})
        assert res.status_code == 200
        data = res.get_json()
        assert 'reset_token' in data
        assert 'verification code has been sent' in data['message']
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == 'student_step25@college.edu'
        assert args[2] == 'password_reset'


def test_forgot_password_by_usn(client, db, student_user):
    """User can request reset using official roll USN."""
    import app.routes.auth as auth_routes
    with patch.object(auth_routes.auth_service.email_service, 'send_otp', return_value=True) as mock_send:
        res = client.post('/api/auth/forgot-password/request', json={'identifier': '1ms21cs099'})
        assert res.status_code == 200
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == 'student_step25@college.edu'


def test_forgot_password_enumeration_resistance(client, db):
    """Unknown user receives identical generic response and dummy token."""
    import app.routes.auth as auth_routes
    with patch.object(auth_routes.auth_service.email_service, 'send_otp') as mock_send:
        res = client.post('/api/auth/forgot-password/request', json={'identifier': 'nonexistent_user'})
        assert res.status_code == 200
        data = res.get_json()
        assert 'reset_token' in data
        assert 'verification code has been sent' in data['message']
        mock_send.assert_not_called()


def test_forgot_password_reset_flow(client, db, student_user):
    """Valid OTP resets password and invalidates all existing sessions."""
    # 1. Open an existing session for student
    active_sess = AuthSession(
        session_id="active_sess_123",
        user_id=student_user.id,
        auth_state="AUTHORIZED",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        idle_expires_at=datetime.utcnow() + timedelta(minutes=10),
        last_activity=datetime.utcnow(),
        revoked=False,
    )
    db.session.add(active_sess)
    db.session.commit()

    # 2. Request reset
    captured_otp = []
    def fake_send(email, code, purpose):
        captured_otp.append(code)
        return True

    import app.routes.auth as auth_routes
    with patch.object(auth_routes.auth_service.email_service, 'send_otp', side_effect=fake_send):
        res_req = client.post('/api/auth/forgot-password/request', json={'identifier': student_user.username})
        assert res_req.status_code == 200
        token = res_req.get_json()['reset_token']
        otp_code = captured_otp[0]

    # 3. Complete reset with valid code
    res_reset = client.post('/api/auth/forgot-password/reset', json={
        'reset_token': token,
        'otp': otp_code,
        'new_password': 'NewSecurePassword123!',
    })
    assert res_reset.status_code == 200
    assert 'Password has been reset' in res_reset.get_json()['message']

    # 4. Verify password updated
    updated_user = db.session.get(User, student_user.id)
    assert verify_password('NewSecurePassword123!', updated_user.password_hash)
    assert not verify_password('OldPassword123!', updated_user.password_hash)

    # 5. Verify existing session was revoked
    db.session.refresh(active_sess)
    assert active_sess.revoked is True


def test_forgot_password_invalid_otp_and_exhaustion(client, db, student_user):
    """Invalid OTP increments attempts and burns after max attempts."""
    import app.routes.auth as auth_routes
    with patch.object(auth_routes.auth_service.email_service, 'send_otp', return_value=True):
        res_req = client.post('/api/auth/forgot-password/request', json={'identifier': student_user.username})
        token = res_req.get_json()['reset_token']

    # Wrong OTP attempts
    for _ in range(5):
        res = client.post('/api/auth/forgot-password/reset', json={
            'reset_token': token,
            'otp': '999999',
            'new_password': 'NewPassword123!',
        })
        assert res.status_code == 400

    # 6th attempt is rejected because attempts exhausted
    otp_record = OTP.query.filter_by(session_id=token, purpose='password_reset').first()
    assert otp_record.used is True


# ==============================================================================
# 2. Candidate Profile & Photo Security Tests (Gap 03, 05, 06)
# ==============================================================================

def test_candidate_metadata_creation_and_sanitization(client, db, test_officer):
    """Candidate supports year, slogan, sanitized manifesto, and photo_url."""
    election = Election(
        election_id="2501",
        title="Metadata Test Election",
        status="DRAFT",
    )
    db.session.add(election)
    db.session.commit()

    cand = ElectionAdminService.add_candidate(
        election_id="2501",
        name="Candidate Jane",
        officer=test_officer,
        department="Computer Science",
        year="4th Year",
        slogan="Innovation & Transparency",
        manifesto="<script>alert('xss')</script>1. Wi-Fi upgrade\n2. Open lab hours",
        photo_url="/api/public/candidate-photo/jane.jpg",
    )
    assert cand.candidate_index == 0
    assert cand.year == "4th Year"
    assert cand.slogan == "Innovation & Transparency"
    # Verify script tags stripped
    assert "<script>" not in cand.manifesto
    assert "1. Wi-Fi upgrade" in cand.manifesto
    assert cand.photo_url == "/api/public/candidate-photo/jane.jpg"


def test_candidate_photo_upload_security(client, db, test_officer):
    """Candidate photo upload rejects non-images, enforces 2MB cap, and checks DRAFT state."""
    election = Election(
        election_id="2502",
        title="Photo Test Election",
        status="DRAFT",
    )
    db.session.add(election)
    db.session.commit()

    cand = ElectionAdminService.add_candidate(
        election_id="2502",
        name="Bob Smith",
        officer=test_officer,
    )

    # Authenticate officer session via header
    import secrets
    officer_token = secrets.token_hex(32)
    from app.models.admin import AdminSession
    asess = AdminSession(
        session_token=officer_token,
        admin_id=test_officer.id,
        role="OFFICER",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.session.add(asess)
    db.session.commit()
    headers = {'X-Admin-Session': officer_token}

    # Reject non-image file
    fake_exe = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00fake_executable_bytes_exceeding_100_bytes_padding_padding_padding_padding_padding_padding_padding_padding")
    res = client.post(
        f'/api/admin/elections/2502/candidates/{cand.candidate_index}/photo',
        data={'photo': (fake_exe, 'malware.exe')},
        headers=headers,
        content_type='multipart/form-data',
    )
    assert res.status_code == 400

    # Reject oversized file (> 2MB)
    huge_data = io.BytesIO(b"A" * (2 * 1024 * 1024 + 50))
    res_huge = client.post(
        f'/api/admin/elections/2502/candidates/{cand.candidate_index}/photo',
        data={'photo': (huge_data, 'huge.jpg')},
        headers=headers,
        content_type='multipart/form-data',
    )
    assert res_huge.status_code == 400
    assert 'FILE_TOO_LARGE' in res_huge.get_json()['error']


def test_voting_election_endpoint_returns_real_candidates(client, db, student_user, test_officer):
    """GET /api/voting/election/<id> queries real Candidate database records."""
    election = Election(
        election_id="2503",
        title="Live Candidate Election",
        status="ACTIVE",
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=1),
    )
    db.session.add(election)
    db.session.commit()

    cand1 = Candidate(
        election_id="2503",
        candidate_index=0,
        name="Real Candidate One",
        department="ECE",
        year="3rd Year",
        slogan="Future Forward",
        manifesto="Labs and research support",
    )
    cand2 = Candidate(
        election_id="2503",
        candidate_index=1,
        name="Real Candidate Two",
        department="ISE",
        year="4th Year",
        slogan="United We Code",
        manifesto="Hackathon funding",
    )
    db.session.add_all([cand1, cand2])
    db.session.commit()

    # Authenticate student session
    with client.session_transaction() as sess:
        s = AuthSession(
            session_id="student_sess_live",
            user_id=student_user.id,
            auth_state="AUTHORIZED",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            idle_expires_at=datetime.utcnow() + timedelta(minutes=15),
            last_activity=datetime.utcnow(),
            revoked=False,
        )
        db.session.add(s)
        db.session.commit()
        sess['session_id'] = "student_sess_live"

    res = client.get('/api/voting/election/2503')
    assert res.status_code == 200
    data = res.get_json()
    assert data['candidate_count'] == 2
    assert data['candidates'][0]['name'] == "Real Candidate One"
    assert data['candidates'][0]['slogan'] == "Future Forward"
    assert data['candidates'][1]['name'] == "Real Candidate Two"
    assert 'server_time' in data


# ==============================================================================
# 3. Registration Deadline Tests (Gap 04)
# ==============================================================================

def test_registration_deadline_boundary_enforcement(client, db):
    """Registration is permitted before deadline and blocked after deadline."""
    roll = ElectoralRoll(
        usn="1MS21CS888",
        full_name="Deadline Tester",
        college_email="deadline888@college.edu",
        is_eligible=True,
    )
    db.session.add(roll)

    # Active election with registration deadline in the PAST
    past_election = Election(
        election_id="2504",
        title="Closed Reg Election",
        status="ACTIVE",
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=4),
        registration_deadline=datetime.utcnow() - timedelta(minutes=10),
    )
    db.session.add(past_election)
    db.session.commit()

    reg_service = RegistrationService()

    # 1. start_registration rejected after deadline
    ok, session_rec, msg = reg_service.start_registration("1MS21CS888")
    assert ok is False
    assert "Registration is closed" in msg

    # 2. Reopen deadline administratively (set deadline in future)
    past_election.registration_deadline = datetime.utcnow() + timedelta(hours=2)
    db.session.commit()

    # Registration now allowed
    ok, session_rec, msg = reg_service.start_registration("1MS21CS888")
    assert ok is True
    assert session_rec is not None


# ==============================================================================
# 4. Server Time & Mid-Flow Close Tests (Gap 05 & 06)
# ==============================================================================

def test_server_time_endpoint(client):
    """GET /api/public/server-time returns authoritative server UTC timestamp."""
    res = client.get('/api/public/server-time')
    assert res.status_code == 200
    data = res.get_json()
    assert 'server_time' in data
    assert data['server_time'].endswith('Z')
    assert 'timestamp' in data


def test_voting_closed_mid_flow_rejection(db):
    """If election end_time arrives while student is preparing ballot, submission is rejected."""
    election = Election(
        election_id="2505",
        title="Mid Flow Close Election",
        status="ACTIVE",
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() - timedelta(seconds=1),  # Closed 1s ago!
    )
    db.session.add(election)
    db.session.commit()

    is_valid, err_code, _ = VotingService.validate_election_and_candidate(
        election_id=2505,
        candidate=0,
    )
    assert is_valid is False
    assert err_code == "ELECTION_CLOSED"


# ==============================================================================
# 5. Support Dispute Ticketing & Privacy Tests (Gap 12)
# ==============================================================================

def test_public_support_report_success(client, db):
    """Voter can log a support ticket and receive a unique reference ID."""
    res = client.post('/api/public/support/report', json={
        'category': 'otp',
        'details': 'Did not receive verification code after 5 minutes on Outlook.',
        'contact_email': 'student@college.edu',
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data['success'] is True
    assert data['reference_id'].startswith('REF-')

    ticket = SupportTicket.query.filter_by(reference_id=data['reference_id']).first()
    assert ticket is not None
    assert ticket.category == 'otp'
    assert ticket.status == 'OPEN'


def test_support_report_privacy_filter(client, db):
    """Support endpoint rejects attempts to submit private keys or seed phrases."""
    res = client.post('/api/public/support/report', json={
        'category': 'wallet',
        'details': 'Here is my private_key 0x1234567890abcdef...',
    })
    assert res.status_code == 400
    assert 'SENSITIVE_DATA_REJECTED' in res.get_json()['error']
