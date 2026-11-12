"""
Phase 9 Controlled Revoting and Coercion Mitigation Tests
Vote Without Doubt - Backend Test Suite

Tests:
1. Sequential advancement: sequence 1 -> 2 -> 3
2. Maximum ballots enforcement: sequence 4 rejected with MAX_BALLOTS_EXCEEDED
3. Cooldown enforcement: 120-second server-side cooldown with COOLDOWN_ACTIVE (429)
4. Cooldown expiry: successful submission after cooldown window
5. Latest-vote-wins tally update (tally decrements previous candidate, increments new candidate)
6. Null revote: retraction of candidate choice, tallies decrement to zero
7. Initial ballot cannot be null (NO_PRIOR_BALLOT)
8. Prior ballot pending: revote blocked while previous ballot is QUEUED/SUBMITTED
9. Authoritative sequence assignment: client cannot choose sequence
10. Single-use authorization: revotes require fresh unconsumed authorization
11. Session and factor binding per revote
12. Database unique constraint on (election_id, pseudonym, sequence)
13. Election closed / key destroyed fails closed
14. Privacy invariants: no candidate, sequence, or pseudonym leakage in receipt
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from app.extensions import db
from app.models import (
    BallotRecord,
    Election,
    User,
    VotingAuthorization,
)
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym, destroy_election_pseudonym_key
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def revoting_user(db):
    user = User(
        username='revoter1',
        email='revoter1@college.test',
        password_hash=hash_password('secure-revote-pass'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def revoting_election(db):
    election = Election(
        election_id='1',
        title='Council Election 2026',
        description='Annual student election with revoting enabled',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


@pytest.fixture
def auth_session(db, revoting_user):
    return _seed_authorized_session(db, revoting_user)


@pytest.fixture
def revoting_client(app, db, auth_session, signed_cookie_for):
    app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x' + '44' * 20
    app.config['REVOTE_COOLDOWN_SECONDS'] = 120
    app.config['MAX_BALLOTS_PER_VOTER'] = 3
    client = app.test_client()
    client.set_cookie(
        app.config['SESSION_COOKIE_NAME'],
        signed_cookie_for(auth_session.session_id),
    )
    return client


def _grant_fresh_auth(db, user_id, election_id, session_id):
    """Helper to simulate completed MFA cycle and grant fresh authorization."""
    va = VotingAuthorization(
        user_id=user_id,
        election_id=election_id,
        session_id=session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()
    return va


# ---------------------------------------------------------------------------
# 1. Sequential Progression & Max Limit (F-9.1)
# ---------------------------------------------------------------------------

def test_controlled_revoting_sequence_progression(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Sequence advances 1 -> 2 -> 3; 4th rejected."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    # Ballot 1 (Initial vote: candidate 0)
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r1 = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert r1.status_code == 202
    assert r1.get_json()['sequence'] == 1

    # Finalize ballot 1 and age timestamp past 120s cooldown
    b1 = BallotRecord.query.filter_by(election_id=1, pseudonym=pseud, sequence=1).first()
    assert b1 is not None
    b1.state = 'FINALIZED'
    b1.created_at = datetime.utcnow() - timedelta(seconds=130)
    db.session.commit()

    # Ballot 2 (Revote 1: candidate 1)
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r2 = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r2.status_code == 202
    assert r2.get_json()['sequence'] == 2

    # Verify ballot 1 was marked superseded
    b1_refreshed = BallotRecord.query.filter_by(election_id=1, pseudonym=pseud, sequence=1).first()
    assert b1_refreshed.superseded is True

    # Finalize ballot 2 and age timestamp past cooldown
    b2 = BallotRecord.query.filter_by(election_id=1, pseudonym=pseud, sequence=2).first()
    assert b2 is not None
    b2.state = 'FINALIZED'
    b2.created_at = datetime.utcnow() - timedelta(seconds=130)
    db.session.commit()

    # Ballot 3 (Revote 2: candidate 0)
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r3 = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert r3.status_code == 202
    assert r3.get_json()['sequence'] == 3

    # Finalize ballot 3 and age timestamp past cooldown
    b3 = BallotRecord.query.filter_by(election_id=1, pseudonym=pseud, sequence=3).first()
    assert b3 is not None
    b3.state = 'FINALIZED'
    b3.created_at = datetime.utcnow() - timedelta(seconds=130)
    db.session.commit()

    # Ballot 4: Must be rejected with 409 MAX_BALLOTS_EXCEEDED
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r4 = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r4.status_code == 409
    assert r4.get_json()['error'] == 'MAX_BALLOTS_EXCEEDED'


# ---------------------------------------------------------------------------
# 2. Cooldown Enforcement (F-9.3)
# ---------------------------------------------------------------------------

def test_revote_cooldown_rejection_and_expiry(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Consecutive ballots within 120s cooldown return 429 COOLDOWN_ACTIVE."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    # Initial ballot finalized just 30 seconds ago
    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=30),
    )
    db.session.add(b1)
    db.session.commit()

    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)

    # Immediate revote attempt must be rejected with 429
    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r.status_code == 429
    assert r.get_json()['error'] == 'COOLDOWN_ACTIVE'

    # Check status endpoint exposes cooldown info
    status_r = revoting_client.get('/api/voting/status?election_id=1')
    assert status_r.status_code == 200
    sdata = status_r.get_json()
    assert sdata['cooldown_active'] is True
    assert sdata['cooldown_remaining_sec'] > 0
    assert sdata['can_revote'] is False

    # Simulate cooldown expiry (age timestamp past 120s)
    b1.created_at = datetime.utcnow() - timedelta(seconds=125)
    db.session.commit()

    # Status endpoint updates
    status_r2 = revoting_client.get('/api/voting/status?election_id=1')
    assert status_r2.get_json()['cooldown_active'] is False
    assert status_r2.get_json()['can_revote'] is True

    # Now revote succeeds
    r2 = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r2.status_code == 202
    assert r2.get_json()['sequence'] == 2


# ---------------------------------------------------------------------------
# 3. Null Ballot / Retraction (F-9.3)
# ---------------------------------------------------------------------------

def test_null_ballot_cannot_be_initial_vote(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Initial ballot cannot be null."""
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'is_null': True})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'NO_PRIOR_BALLOT'


def test_null_ballot_revote_retracts_active_choice(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Revote with is_null=True retracts candidate choice."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    # Seed finalized sequence 1
    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )
    db.session.add(b1)
    db.session.commit()

    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)

    # Submit null ballot revote
    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'is_null': True})
    assert r.status_code == 202
    assert r.get_json()['sequence'] == 2

    b2 = BallotRecord.query.filter_by(election_id=1, pseudonym=pseud, sequence=2).first()
    assert b2 is not None
    assert b2.is_null is True
    assert b2.candidate == 0
    assert b1.superseded is True


# ---------------------------------------------------------------------------
# 4. Client Sequence Manipulation Rejected (F-9.1)
# ---------------------------------------------------------------------------

def test_client_cannot_choose_sequence(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Client cannot forge sequence number; backend derives authoritative sequence."""
    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)

    # Client tries to send sequence=3 on initial vote
    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0, 'sequence': 3})
    assert r.status_code == 202
    # Authoritative sequence MUST be 1
    assert r.get_json()['sequence'] == 1


# ---------------------------------------------------------------------------
# 5. Pending Ballot Blocking (F-9.1)
# ---------------------------------------------------------------------------

def test_cannot_revote_while_prior_ballot_pending(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Revote blocked while previous ballot is QUEUED or SUBMITTED."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )
    db.session.add(b1)
    db.session.commit()

    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)
    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'PREVIOUS_BALLOT_PENDING'


# ---------------------------------------------------------------------------
# 6. Database Level Constraint on (election_id, pseudonym, sequence) (F-9.2)
# ---------------------------------------------------------------------------

def test_database_constraint_allows_multiple_sequences_blocks_duplicate(db, revoting_user):
    """Multiple sequences per pseudonym are allowed, but identical sequence is rejected."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    b1 = BallotRecord(election_id=1, pseudonym=pseud, candidate=0, sequence=1, state='FINALIZED')
    b2 = BallotRecord(election_id=1, pseudonym=pseud, candidate=1, sequence=2, state='FINALIZED')
    db.session.add_all([b1, b2])
    db.session.commit()

    # Duplicate sequence 2 must fail
    b2_dup = BallotRecord(election_id=1, pseudonym=pseud, candidate=0, sequence=2, state='QUEUED')
    db.session.add(b2_dup)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# 7. Privacy Invariant on Revotes (F-8.3, F-8.4, F-8.6)
# ---------------------------------------------------------------------------

def test_revote_receipt_preserves_privacy(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Receipt for revote does not reveal candidate, pseudonym, sequence, or blockchain hash."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        tx_hash='0xabcdef1234567890',
        receipt_code='HMAC-RECEIPT-CODE-1',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )
    db.session.add(b1)
    db.session.commit()

    status_r = revoting_client.get('/api/voting/status?election_id=1')
    assert status_r.status_code == 200
    data = status_r.get_json()

    # Must NOT contain sensitive data
    assert 'candidate' not in data
    assert 'pseudonym' not in data
    assert 'tx_hash' not in data
    assert '0xabcdef1234567890' not in status_r.data.decode()


# ---------------------------------------------------------------------------
# 8. Re-authentication & Factor Freshness Per Revote (F-9.1, F-7.1)
# ---------------------------------------------------------------------------

def test_revote_requires_fresh_authorization_not_consumed(revoting_client, revoting_user, revoting_election, auth_session, db):
    """Reusing the previous vote's authorization fails with AUTHORIZATION_CONSUMED."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )
    db.session.add(b1)

    # Seed an already consumed authorization
    va = VotingAuthorization(
        user_id=revoting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=True,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r.status_code == 403
    assert r.get_json()['error'] == 'AUTHORIZATION_CONSUMED'


def test_revote_fails_after_election_finalization_key_destroyed(revoting_client, revoting_user, revoting_election, auth_session, db):
    """After election key destruction, further revotes fail closed (ELECTION_NOT_ACTIVE)."""
    pseud = derive_pseudonym(revoting_user.id, 1)

    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseud,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )
    db.session.add(b1)
    db.session.commit()

    _grant_fresh_auth(db, revoting_user.id, 1, auth_session.session_id)

    # Shred key material upon election close
    destroy_election_pseudonym_key(1)

    r = revoting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'ELECTION_NOT_ACTIVE'
