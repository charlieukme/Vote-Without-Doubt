"""
Authorization Security & Biometric Challenge Binding Regression Tests - Phase B.1
Vote Without Doubt - Backend

Mandatory Security Invariants Tested:
1. Expired face challenge is rejected.
2. One-time challenge consumption: a consumed challenge cannot be replayed for subsequent authorizations.
3. Consumption is tracked via consumed=True/consumed_at; success=True is strictly preserved.
4. Cross-election rejection: a challenge issued for Election A cannot satisfy Election B.
5. Cross-user rejection: a challenge issued for User A cannot satisfy User B.
6. Cross-session rejection: a challenge issued for Session A cannot satisfy Session B.
7. Registration challenge (authorization_id=None, election_id=None) cannot satisfy voting.
8. Challenge freshness: challenges completed beyond the max freshness window (300s) are rejected.
9. Direct ballot submission without all verified factors is rejected (403 FACTORS_INCOMPLETE).
10. Concurrency safety: simultaneous requests racing to consume the same challenge result in
    exactly one consumer succeeding and the other being rejected.
11. Legitimate retry: after a failed or expired challenge, a fresh challenge succeeds.
12. Legitimate revote: after casting sequence 1, revoting (sequence 2) requires a fresh face challenge.
13. Reversible Alembic migration: upgrade and downgrade cleanly add and remove columns on a disposable DB.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import subprocess
import sys
import tempfile
import pytest
from sqlalchemy import inspect

from app.extensions import db
from app.models import (
    BallotRecord,
    Election,
    FaceChallenge,
    FaceEnrollment,
    User,
    VotingAuthorization,
    WalletBinding,
)
from app.security.password import hash_password
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def voter_user(db):
    user = User(
        username='b1_voter',
        email='b1_voter@college.test',
        password_hash=hash_password('correct-password'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def other_user(db):
    user = User(
        username='other_voter',
        email='other_voter@college.test',
        password_hash=hash_password('correct-password'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def election_alpha(db):
    election = Election(
        election_id='101',
        title='Alpha Election 2026',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


@pytest.fixture
def election_beta(db):
    election = Election(
        election_id='102',
        title='Beta Election 2026',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


@pytest.fixture
def voter_session(db, voter_user):
    return _seed_authorized_session(db, voter_user)


@pytest.fixture
def setup_factors(db, voter_user):
    """Enroll face and bind wallet for voter."""
    fe = FaceEnrollment(
        user_id=voter_user.id,
        is_enrolled=True,
        consent_given=True,
        encrypted_embedding=b'\x02' * 512,
    )
    wb = WalletBinding(
        user_id=voter_user.id,
        wallet_address='0x' + '22' * 20,
        is_verified=True,
        binding_method='signature',
    )
    db.session.add(fe)
    db.session.add(wb)
    db.session.commit()
    return fe, wb


@pytest.fixture
def voter_client(app, db, voter_session, signed_cookie_for):
    app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x' + '33' * 20
    client = app.test_client()
    client.set_cookie(
        app.config['SESSION_COOKIE_NAME'],
        signed_cookie_for(voter_session.session_id),
    )
    return client


# ---------------------------------------------------------------------------
# Invariant 1: Expired challenge rejection
# ---------------------------------------------------------------------------
def test_expired_face_challenge_rejected(db, voter_client, voter_user, voter_session, election_alpha, setup_factors):
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200
    va_id = auth_res.get_json()['authorization_id']

    # Seed expired challenge
    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-expired-01',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-exp',
        integrity_mac='mac-exp',
        completed=True,
        success=True,
        completed_at=now - timedelta(seconds=60),
        expires_at=now - timedelta(seconds=10),  # EXPIRED
        authorization_id=va_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    data = mf_res.get_json()
    assert data['wallet_ok'] is True
    assert data['face_ok'] is False  # MUST be rejected
    assert data['authorized'] is False


# ---------------------------------------------------------------------------
# Invariant 2 & 3: One-time consumption & replay prevention (success=True preserved)
# ---------------------------------------------------------------------------
def test_face_challenge_single_use_consumed_and_replay_rejected(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    # 1. Authorize Election Alpha
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200
    va_id = auth_res.get_json()['authorization_id']

    # Seed valid challenge bound to this authorization
    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-valid-01',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-valid',
        integrity_mac='mac-valid',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    # Mark factors -> Should consume challenge and authorize
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    data = mf_res.get_json()
    assert data['face_ok'] is True
    assert data['wallet_ok'] is True
    assert data['authorized'] is True

    # Verify consumption state in DB
    consumed_row = db.session.get(FaceChallenge, fc.id)
    assert consumed_row.consumed is True
    assert consumed_row.consumed_at is not None
    assert consumed_row.success is True  # Invariant: success=True must NOT be flipped to False

    # 2. Attempt replay on a fresh authorization
    auth2_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth2_res.status_code == 200

    mf2_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf2_res.status_code == 200
    data2 = mf2_res.get_json()
    assert data2['face_ok'] is False  # Stale consumed challenge must NOT authorize again
    assert data2['authorized'] is False


# ---------------------------------------------------------------------------
# Invariant 4: Cross-election rejection
# ---------------------------------------------------------------------------
def test_cross_election_challenge_rejected(
    db, voter_client, voter_user, voter_session, election_alpha, election_beta, setup_factors
):
    # Challenge issued for Election Beta (102)
    auth_beta = voter_client.post('/api/voting/authorize', json={'election_id': 102})
    assert auth_beta.status_code == 200
    va_beta_id = auth_beta.get_json()['authorization_id']

    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-beta-01',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-beta',
        integrity_mac='mac-beta',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va_beta_id,
        election_id=election_beta.id,  # Bound to Beta
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    # Voter authorizes Election Alpha (101)
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200

    # Mark factors for Election Alpha
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    data = mf_res.get_json()
    assert data['face_ok'] is False  # Must be rejected because challenge belongs to Beta
    assert data['authorized'] is False


# ---------------------------------------------------------------------------
# Invariant 5: Cross-user rejection
# ---------------------------------------------------------------------------
def test_cross_user_challenge_rejected(
    db, voter_client, voter_user, other_user, voter_session, election_alpha, setup_factors
):
    now = datetime.utcnow()
    # Challenge belongs to other_user
    fc = FaceChallenge(
        challenge_id='ch-other-user',
        user_id=other_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-other',
        integrity_mac='mac-other',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    voter_client.post('/api/voting/authorize', json={'election_id': 101})
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    assert mf_res.get_json()['face_ok'] is False


# ---------------------------------------------------------------------------
# Invariant 6: Cross-session rejection
# ---------------------------------------------------------------------------
def test_cross_session_challenge_rejected(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    now = datetime.utcnow()
    # Challenge belongs to another session
    fc = FaceChallenge(
        challenge_id='ch-diff-session',
        user_id=voter_user.id,
        session_id='completely-different-session-id',
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-diff-s',
        integrity_mac='mac-diff-s',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    voter_client.post('/api/voting/authorize', json={'election_id': 101})
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    assert mf_res.get_json()['face_ok'] is False


# ---------------------------------------------------------------------------
# Invariant 7: Registration challenge cannot authorize voting
# ---------------------------------------------------------------------------
def test_registration_challenge_cannot_authorize_voting(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    now = datetime.utcnow()
    # Registration challenge has authorization_id=None and election_id=None
    fc = FaceChallenge(
        challenge_id='ch-reg-enrollment',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-reg',
        integrity_mac='mac-reg',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=None,
        election_id=None,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    voter_client.post('/api/voting/authorize', json={'election_id': 101})
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    # Must be rejected because an un-bound registration challenge cannot authorize a ballot
    assert mf_res.get_json()['face_ok'] is False


# ---------------------------------------------------------------------------
# Invariant 7b: Unbound challenge with valid election_id cannot authorize voting (Strict binding)
# ---------------------------------------------------------------------------
def test_unbound_challenge_with_valid_election_cannot_authorize_voting(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    """
    Hardening regression: even if election_id matches the target election,
    a challenge with authorization_id=None MUST NOT authorize voting.
    """
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200

    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-unbound-valid-election',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-unbound-e',
        integrity_mac='mac-unbound-e',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=None,  # STRICT: Unbound to authorization
        election_id=election_alpha.id,  # Valid election ID
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    data = mf_res.get_json()
    assert data['face_ok'] is False
    assert data['authorized'] is False


# ---------------------------------------------------------------------------
# Invariant 7c: Same election but different authorization challenge cannot be reused
# ---------------------------------------------------------------------------
def test_same_election_different_authorization_challenge_rejected(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    """
    Hardening regression: a challenge bound to authorization A for Election Alpha
    cannot authorize authorization B for the same Election Alpha.
    """
    # 1. Authorize Election Alpha (Attempt 1)
    auth1 = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth1.status_code == 200
    va1_id = auth1.get_json()['authorization_id']

    # 2. Challenge is minted and bound strictly to Attempt 1
    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-attempt-1',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-att-1',
        integrity_mac='mac-att-1',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va1_id,  # Bound strictly to Attempt 1
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    # 3. Voter creates a NEW authorization cycle (Attempt 2) for the SAME election
    auth2 = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth2.status_code == 200
    va2_id = auth2.get_json()['authorization_id']
    assert va2_id != va1_id

    # 4. Attempt to mark factors for Attempt 2 using Attempt 1's challenge
    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    data = mf_res.get_json()
    assert data['face_ok'] is False  # Must be rejected because challenge belongs to va1_id, not va2_id
    assert data['authorized'] is False


# ---------------------------------------------------------------------------
# Invariant 8: Challenge freshness window enforcement
# ---------------------------------------------------------------------------
def test_stale_completed_challenge_rejected(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200
    va_id = auth_res.get_json()['authorization_id']

    now = datetime.utcnow()
    # Challenge completed 10 minutes ago (beyond max 300s window)
    fc = FaceChallenge(
        challenge_id='ch-stale-completed',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-stale',
        integrity_mac='mac-stale',
        completed=True,
        success=True,
        completed_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(hours=1),  # unexpired TTL, but stale completion
        authorization_id=va_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()

    mf_res = voter_client.post('/api/voting/mark-factors', json={'election_id': 101})
    assert mf_res.status_code == 200
    assert mf_res.get_json()['face_ok'] is False


# ---------------------------------------------------------------------------
# Invariant 9: Direct ballot submission without all required factors rejected
# ---------------------------------------------------------------------------
def test_direct_ballot_submission_without_factors_rejected(
    voter_client, voter_user, election_alpha
):
    # Case A: Direct submit without authorization -> rejected
    sub_res = voter_client.post('/api/voting/submit', json={'election_id': 101, 'candidate': 0})
    assert sub_res.status_code in (400, 403)

    # Case B: Direct submit with authorization initiated but factors incomplete -> 403 FACTORS_INCOMPLETE
    voter_client.post('/api/voting/authorize', json={'election_id': 101})
    sub_res2 = voter_client.post('/api/voting/submit', json={'election_id': 101, 'candidate': 0})
    assert sub_res2.status_code == 403
    assert 'FACTORS_INCOMPLETE' in sub_res2.get_json().get('error', '')


# ---------------------------------------------------------------------------
# Invariant 10: Concurrency safety — two simultaneous requests to consume challenge
# ---------------------------------------------------------------------------
def test_concurrent_attempts_to_consume_same_challenge(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    auth = VotingService.create_authorization(
        user_id=uid,
        election_id=eid,
        session_id=sid,
    )

    now = datetime.utcnow()
    fc = FaceChallenge(
        challenge_id='ch-race-01',
        user_id=uid,
        session_id=sid,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-race',
        integrity_mac='mac-race',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=auth.id,
        election_id=eid,
        consumed=False,
    )
    db.session.add(fc)
    db.session.commit()
    cid = fc.id

    def _mark_factors_task():
        with app.app_context():
            res = VotingService.mark_factors(
                user_id=uid,
                election_id=eid,
                session_id=sid,
            )
            return bool(res and res.face_verified and res.authorized)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_mark_factors_task)
        f2 = executor.submit(_mark_factors_task)
        results = [f1.result(), f2.result()]

    # Exactly one consumer must succeed; the second must be rejected (face_ok=False)
    assert results.count(True) == 1
    assert results.count(False) == 1

    # Verify the challenge is consumed exactly once
    with app.app_context():
        challenge = db.session.get(FaceChallenge, cid)
        assert challenge.consumed is True


# ---------------------------------------------------------------------------
# Invariant 11: Legitimate retry behavior after expired/failed challenge
# ---------------------------------------------------------------------------
def test_legitimate_retry_after_failed_challenge(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    auth_res = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth_res.status_code == 200
    va_id = auth_res.get_json()['authorization_id']

    # First challenge expired
    now = datetime.utcnow()
    fc1 = FaceChallenge(
        challenge_id='ch-retry-fail-01',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-r1',
        integrity_mac='mac-r1',
        completed=True,
        success=False,
        completed_at=now,
        expires_at=now - timedelta(seconds=5),
        authorization_id=va_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc1)
    db.session.commit()

    # Factors check fails
    mf1 = voter_client.post('/api/voting/mark-factors', json={'election_id': 101}).get_json()
    assert mf1['face_ok'] is False

    # Legitimate retry: voter completes a second fresh challenge
    fc2 = FaceChallenge(
        challenge_id='ch-retry-succ-02',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-r2',
        integrity_mac='mac-r2',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc2)
    db.session.commit()

    # Factors check now succeeds
    mf2 = voter_client.post('/api/voting/mark-factors', json={'election_id': 101}).get_json()
    assert mf2['face_ok'] is True
    assert mf2['authorized'] is True


# ---------------------------------------------------------------------------
# Invariant 12: Legitimate revoting requires fresh biometric verification
# ---------------------------------------------------------------------------
def test_revoting_requires_fresh_face_challenge(
    db, voter_client, voter_user, voter_session, election_alpha, setup_factors
):
    from unittest.mock import patch

    # 1. First vote authorization
    auth1 = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth1.status_code == 200
    va1_id = auth1.get_json()['authorization_id']

    now = datetime.utcnow()
    fc1 = FaceChallenge(
        challenge_id='ch-revote-01',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-rv1',
        integrity_mac='mac-rv1',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va1_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc1)
    db.session.commit()

    # Mark factors -> Authorized
    mf1 = voter_client.post('/api/voting/mark-factors', json={'election_id': 101}).get_json()
    assert mf1['authorized'] is True

    # Submit first vote (sequence 1)
    with patch('app.relayer.trigger_async_relayer'):
        sub1 = voter_client.post('/api/voting/submit', json={'election_id': 101, 'candidate': 0})
        assert sub1.status_code == 202

    # Verify ballot is queued and first challenge consumed
    assert fc1.consumed is True

    # 2. Start revote authorization cycle
    auth2 = voter_client.post('/api/voting/authorize', json={'election_id': 101})
    assert auth2.status_code == 200
    va2_id = auth2.get_json()['authorization_id']

    # Without fresh biometric challenge, revote authorization MUST NOT succeed
    mf2 = voter_client.post('/api/voting/mark-factors', json={'election_id': 101}).get_json()
    assert mf2['face_ok'] is False
    assert mf2['authorized'] is False

    # Issue and complete fresh challenge for revote
    fc2 = FaceChallenge(
        challenge_id='ch-revote-02',
        user_id=voter_user.id,
        session_id=voter_session.session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce='nonce-rv2',
        integrity_mac='mac-rv2',
        completed=True,
        success=True,
        completed_at=now,
        expires_at=now + timedelta(seconds=300),
        authorization_id=va2_id,
        election_id=election_alpha.id,
        consumed=False,
    )
    db.session.add(fc2)
    db.session.commit()

    # Revote factors now authorized
    mf3 = voter_client.post('/api/voting/mark-factors', json={'election_id': 101}).get_json()
    assert mf3['face_ok'] is True
    assert mf3['authorized'] is True

# ---------------------------------------------------------------------------
# SEC-D0-01 Regression Tests: Atomic Ballot Authorization Consumption
# ---------------------------------------------------------------------------
def test_sec_d0_01_already_consumed_authorization_rejected(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    # Create authorization and mark it as consumed
    auth = VotingService.create_authorization(uid, eid, session_id=sid)
    auth.wallet_verified = True
    auth.face_verified = True
    auth.authorized = True
    auth.consumed = True
    auth.consumed_at = datetime.utcnow()
    db.session.commit()

    ballots_before = BallotRecord.query.filter_by(election_id=eid).count()

    ballot, err = VotingService.submit_ballot(uid, eid, candidate=0, session_id=sid)
    assert ballot is None
    assert err == "AUTHORIZATION_CONSUMED"

    ballots_after = BallotRecord.query.filter_by(election_id=eid).count()
    assert ballots_after == ballots_before


def test_sec_d0_01_two_competing_claims_cannot_both_succeed(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    # Pre-derive pseudonyms for all candidate election ID formats to avoid concurrent key inserts
    from app.security.pseudonym import derive_pseudonym
    for val in (eid, election_alpha.election_id, str(election_alpha.election_id), int(election_alpha.election_id)):
        try:
            derive_pseudonym(uid, val)
        except Exception:
            pass
    db.session.commit()

    auth = VotingService.create_authorization(uid, eid, session_id=sid)
    auth.wallet_verified = True
    auth.face_verified = True
    auth.authorized = True
    auth.consumed = False
    db.session.commit()

    def _competing_submit(candidate_choice):
        with app.app_context():
            ballot, err = VotingService.submit_ballot(uid, eid, candidate=candidate_choice, session_id=sid)
            return ballot, err

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_competing_submit, 0)
        f2 = executor.submit(_competing_submit, 1)
        results = [f1.result(), f2.result()]

    successes = [r for r in results if r[1] == "OK"]
    failures = [r for r in results if r[1] != "OK"]

    # At most one submission succeeds
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0][1] in ("AUTHORIZATION_CONSUMED", "BALLOT_ALREADY_CAST")

    # Verify only 1 ballot exists in queue
    ballots = BallotRecord.query.filter_by(election_id=eid).all()
    assert len(ballots) == 1
    assert ballots[0].sequence == 1


def test_sec_d0_01_failed_claim_does_not_create_ballot(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    auth = VotingService.create_authorization(uid, eid, session_id=sid)
    auth.wallet_verified = True
    auth.face_verified = True
    auth.authorized = True
    auth.consumed = True  # Already claimed
    db.session.commit()

    ballots_before = BallotRecord.query.filter_by(election_id=eid).count()

    ballot, err = VotingService.submit_ballot(uid, eid, candidate=0, session_id=sid)
    assert ballot is None
    assert err == "AUTHORIZATION_CONSUMED"

    ballots_after = BallotRecord.query.filter_by(election_id=eid).count()
    assert ballots_after == ballots_before


def test_sec_d0_01_ballot_insertion_failure_rolls_back_authorization_claim(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    # Pre-derive pseudonyms for all representations before patching commit
    from app.security.pseudonym import derive_pseudonym
    for val in (eid, election_alpha.election_id, str(election_alpha.election_id), int(election_alpha.election_id)):
        try:
            derive_pseudonym(uid, val)
        except Exception:
            pass
    db.session.commit()

    auth = VotingService.create_authorization(uid, eid, session_id=sid)
    auth.wallet_verified = True
    auth.face_verified = True
    auth.authorized = True
    auth.consumed = False
    db.session.commit()
    auth_id = auth.id

    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError

    # Simulate an IntegrityError on commit during ballot insertion
    with patch.object(db.session, 'commit', side_effect=IntegrityError("mock duplicate sequence", params=None, orig=Exception())):
        ballot, err = VotingService.submit_ballot(uid, eid, candidate=0, session_id=sid)
        assert ballot is None
        assert err == "BALLOT_ALREADY_CAST"

    # Verify that the authorization claim was rolled back
    reloaded_auth = db.session.get(VotingAuthorization, auth_id)
    assert reloaded_auth.consumed is False


def test_sec_d0_01_legitimate_voting_and_permitted_revoting(
    app, db, voter_user, voter_session, election_alpha, setup_factors
):
    uid = voter_user.id
    eid = election_alpha.id
    sid = voter_session.session_id

    # 1. First legitimate vote
    auth1 = VotingService.create_authorization(uid, eid, session_id=sid)
    auth1.wallet_verified = True
    auth1.face_verified = True
    auth1.authorized = True
    db.session.commit()

    b1, err1 = VotingService.submit_ballot(uid, eid, candidate=0, session_id=sid)
    assert err1 == "OK"
    assert b1.sequence == 1

    # Simulate relayer confirmation & backdate to satisfy revote cooldown
    b1.state = 'CONFIRMED'
    b1.created_at = datetime.utcnow() - timedelta(minutes=5)
    db.session.commit()

    # 2. Second legitimate vote with fresh authorization
    auth2 = VotingService.create_authorization(uid, eid, session_id=sid)
    auth2.wallet_verified = True
    auth2.face_verified = True
    auth2.authorized = True
    db.session.commit()

    b2, err2 = VotingService.submit_ballot(uid, eid, candidate=1, session_id=sid)
    assert err2 == "OK"
    assert b2.sequence == 2

    # Check both authorizations are consumed and both ballots exist
    assert db.session.get(VotingAuthorization, auth1.id).consumed is True
    assert db.session.get(VotingAuthorization, auth2.id).consumed is True
    all_ballots = BallotRecord.query.filter_by(election_id=eid).order_by(BallotRecord.sequence.asc()).all()
    assert len(all_ballots) == 2


# ---------------------------------------------------------------------------
# Invariant 13: Alembic migration upgrade and downgrade on disposable database
# ---------------------------------------------------------------------------
def test_alembic_migration_upgrade_and_downgrade_disposable_db(tmp_path):
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    db_path = tmp_path / 'disposable_migration.sqlite3'
    url = f'sqlite:///{db_path.as_posix()}'

    env = dict(os.environ)
    env.update({
        'DATABASE_URL': url,
        'FLASK_ENV': 'testing',
        'TESTING_SECRET_KEY': 'testing-only-secret-not-for-production',
    })
    env.pop('FLASK_DEBUG', None)

    # 1. Upgrade to head
    upgrade = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade'],
        cwd=backend_dir, capture_output=True, text=True, env=env, timeout=120,
    )
    assert upgrade.returncode == 0, upgrade.stderr or upgrade.stdout

    # Inspect columns in upgraded database
    from sqlalchemy import create_engine
    engine = create_engine(url)
    with engine.connect() as conn:
        cols = {col['name'] for col in inspect(conn).get_columns('face_challenges')}
    assert 'authorization_id' in cols
    assert 'election_id' in cols
    assert 'consumed' in cols
    assert 'consumed_at' in cols

    # 2. Downgrade by 1 revision back to previous head
    downgrade = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'downgrade', 'a1e2d3c4b5a6'],
        cwd=backend_dir, capture_output=True, text=True, env=env, timeout=120,
    )
    assert downgrade.returncode == 0, downgrade.stderr or downgrade.stdout

    # Inspect columns in downgraded database
    engine.dispose()
    engine = create_engine(url)
    with engine.connect() as conn:
        downgraded_cols = {col['name'] for col in inspect(conn).get_columns('face_challenges')}
    assert 'authorization_id' not in downgraded_cols
    assert 'election_id' not in downgraded_cols
    assert 'consumed' not in downgraded_cols
    assert 'consumed_at' not in downgraded_cols

    # 3. Upgrade back to head to verify re-apply
    re_upgrade = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade'],
        cwd=backend_dir, capture_output=True, text=True, env=env, timeout=120,
    )
    assert re_upgrade.returncode == 0, re_upgrade.stderr or re_upgrade.stdout
    engine.dispose()
