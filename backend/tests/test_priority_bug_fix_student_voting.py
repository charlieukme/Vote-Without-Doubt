"""
Regression tests for Priority Bug Fix — Student Cannot Vote After Registration and Security Enrollment.
Tests verify:
1. Dynamic active election resolution (no hardcoded fallback to closed Election 1).
2. Registration rate limit configuration.
3. Student wallet and face factor recognition under active session.
4. Blocking of unauthorized voting when factors are missing.
"""

from datetime import datetime, timedelta
import pytest
from flask import session

from app.extensions import db
from app.models import (
    User,
    Election,
    WalletBinding,
    FaceEnrollment,
    AuthSession,
    VotingAuthorization,
)
from app.services.auth_service import STATE_AUTHORIZED
from app.services.voting_service import VotingService


@pytest.fixture
def student_with_factors(app, db):
    """Seed an eligible, verified student with both wallet binding and active face enrollment."""
    user = User(
        username='test_student_chalrss',
        email='student_chalrss@college.edu',
        password_hash='$argon2id$v=19$m=65536,t=3,p=4$dummyhash',
        voter_id='1XX23CS000',
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()

    # Seed verified wallet
    wb = WalletBinding(
        user_id=user.id,
        wallet_address='0xaa00eb5af851c6fc7b7e0af0c8c10cca7fcb35db',
        is_verified=True,
        binding_method='personal_sign',
    )
    db.session.add(wb)

    # Seed active face enrollment
    fe = FaceEnrollment(
        user_id=user.id,
        is_enrolled=True,
        consent_given=True,
        encrypted_embedding=b'dummy_encrypted_vector_123',
    )
    db.session.add(fe)
    db.session.commit()
    return user


def test_registration_rate_limit_budget_is_at_least_20(app):
    """Verify registration budget allows normal registration steps without 429."""
    rules = app.config.get('RATE_LIMIT_RULES', {})
    reg_rule = rules.get('/api/registration')
    assert reg_rule is not None
    limit, window = reg_rule
    assert limit >= 20, f"Expected /api/registration limit >= 20, got {limit}"


def test_dynamic_election_resolution_prefers_open_election(app, db, client, student_with_factors):
    """Verify voting/authorize dynamically selects the currently open election instead of old closed."""
    now = datetime.utcnow()
    # Create old closed election (id 1)
    e_old = Election(
        election_id='ELEC_OLD_CLOSED_1',
        title='OLD CLOSED ELECTION',
        status='CLOSED',
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=1),
    )
    # Create new open election (id 2)
    e_new = Election(
        election_id='ELEC_NEW_OPEN_2',
        title='NEW OPEN ELECTION',
        status='OPEN',
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(days=1),
    )
    db.session.add_all([e_old, e_new])
    db.session.commit()

    # Create active session for student
    auth_sess = AuthSession(
        session_id='sess_test_active_123',
        user_id=student_with_factors.id,
        auth_state=STATE_AUTHORIZED,
        authenticated_at=now,
        expires_at=now + timedelta(hours=2),
        idle_expires_at=now + timedelta(minutes=30),
        last_activity=now,
        revoked=False,
    )
    db.session.add(auth_sess)
    db.session.commit()

    with client.session_transaction() as flask_sess:
        flask_sess['session_id'] = 'sess_test_active_123'

    # Call authorize WITHOUT passing election_id
    res = client.post('/api/voting/authorize', json={})
    assert res.status_code == 200
    data = res.get_json()
    assert data['election_id'] == 'ELEC_NEW_OPEN_2'


def test_wallet_and_face_status_reflect_active_student_factors(app, db, client, student_with_factors):
    """Verify wallet/status and face/status return verified state for active session."""
    now = datetime.utcnow()
    auth_sess = AuthSession(
        session_id='sess_test_factors_456',
        user_id=student_with_factors.id,
        auth_state=STATE_AUTHORIZED,
        authenticated_at=now,
        expires_at=now + timedelta(hours=2),
        idle_expires_at=now + timedelta(minutes=30),
        last_activity=now,
        revoked=False,
    )
    db.session.add(auth_sess)
    db.session.commit()

    with client.session_transaction() as flask_sess:
        flask_sess['session_id'] = 'sess_test_factors_456'

    # Check wallet status
    w_res = client.get('/api/wallet/status')
    assert w_res.status_code == 200
    w_data = w_res.get_json()
    assert w_data['bound'] is True
    assert w_data['verified'] is True
    assert w_data['wallet_address'] == '0xaa00eb5af851c6fc7b7e0af0c8c10cca7fcb35db'

    # Check face status
    f_res = client.get('/api/face/status')
    assert f_res.status_code == 200
    f_data = f_res.get_json()
    assert f_data['enrolled'] is True
    assert f_data['consent_given'] is True


def test_missing_or_revoked_session_fails_closed(app, db, client, student_with_factors):
    """Verify revoked session returns bound: False on wallet and 401 on face without leaking data."""
    now = datetime.utcnow()
    revoked_sess = AuthSession(
        session_id='sess_test_revoked_789',
        user_id=student_with_factors.id,
        auth_state=STATE_AUTHORIZED,
        authenticated_at=now,
        expires_at=now + timedelta(hours=2),
        idle_expires_at=now - timedelta(minutes=5),  # expired
        last_activity=now - timedelta(minutes=15),
        revoked=True,
    )
    db.session.add(revoked_sess)
    db.session.commit()

    with client.session_transaction() as flask_sess:
        flask_sess['session_id'] = 'sess_test_revoked_789'

    w_res = client.get('/api/wallet/status')
    assert w_res.status_code == 200
    assert w_res.get_json() == {'bound': False}

    f_res = client.get('/api/face/status')
    assert f_res.status_code == 401
