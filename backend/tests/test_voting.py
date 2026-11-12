"""
Phase 7 Core Voting Pipeline Integration & Security Tests
Vote Without Doubt - Backend

Requirements tested:
1. Multi-factor voting authorization (session, wallet verified, face verified).
2. Client cannot forge or assert factor verification (server-authoritative).
3. Session binding: authorization is bound to the authenticated session.
4. Revoting prohibition (Phase 6 boundary): sequence=1 strictly, rejects duplicates.
5. Election and candidate validation (active, time window, candidate index range).
6. Real relayer pipeline integration (QUEUED -> SUBMITTED -> CONFIRMED -> FINALIZED/FAILED).
7. Status endpoint correctness (model column fix, authoritative state).
8. Privacy: strict identity/ballot separation, Section 8.6 receipt without sensitive data.
9. Database-level unique constraint preventing concurrent duplicates.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

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
from app.security.pseudonym import derive_pseudonym
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def voting_user(db):
    user = User(
        username='voter1',
        email='voter1@college.test',
        password_hash=hash_password('correct-password'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def active_election(db):
    election = Election(
        election_id='1',
        title='College Council 2026',
        description='Annual student council general election',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


@pytest.fixture
def auth_session(db, voting_user):
    return _seed_authorized_session(db, voting_user)


@pytest.fixture
def voting_client(app, db, auth_session, signed_cookie_for):
    app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x' + '33' * 20
    client = app.test_client()
    client.set_cookie(
        app.config['SESSION_COOKIE_NAME'],
        signed_cookie_for(auth_session.session_id),
    )
    return client


# ---------------------------------------------------------------------------
# 1. Unauthenticated & Basic Cryptographic Isolation
# ---------------------------------------------------------------------------

def test_voting_authorize_unauth(client):
    r = client.post('/api/voting/authorize', json={'election_id': 1})
    assert r.status_code == 401


def test_voting_submit_unauth(client):
    r = client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert r.status_code == 401


def test_voting_status_unauth(client):
    r = client.get('/api/voting/status?election_id=1')
    assert r.status_code == 401


def test_pseudonym_deterministic(db):
    p1 = derive_pseudonym(1, 1)
    p2 = derive_pseudonym(1, 1)
    assert p1 == p2


def test_pseudonym_diff_election(db):
    assert derive_pseudonym(1, 1) != derive_pseudonym(1, 2)


def test_pseudonym_diff_user(db):
    assert derive_pseudonym(1, 1) != derive_pseudonym(2, 1)


# ---------------------------------------------------------------------------
# 2. Authorization Lifecycle & Session Binding
# ---------------------------------------------------------------------------

def test_authorization_flow_authenticated(voting_client, active_election):
    res = voting_client.post('/api/voting/authorize', json={'election_id': 1})
    assert res.status_code == 200
    data = res.get_json()
    assert 'authorization_id' in data
    assert 'expires_at' in data
    assert 'factors_required' in data
    assert set(data['factors_required']) == {'wallet', 'face'}


def test_authorization_session_binding(app, db, voting_user, active_election, signed_cookie_for):
    app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x' + '33' * 20
    # Session A creates authorization
    session_a = _seed_authorized_session(db, voting_user)
    client_a = app.test_client()
    client_a.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(session_a.session_id))

    r_auth = client_a.post('/api/voting/authorize', json={'election_id': 1})
    assert r_auth.status_code == 200

    # Manually grant factors for session A
    va = VotingAuthorization.query.filter_by(user_id=voting_user.id, election_id=1).first()
    va.wallet_verified = True
    va.face_verified = True
    va.authorized = True
    db.session.commit()

    # Session B for same user attempts to submit ballot using session A's authorization
    session_b = _seed_authorized_session(db, voting_user)
    client_b = app.test_client()
    client_b.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(session_b.session_id))

    res = client_b.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert res.status_code == 403
    assert 'SESSION_MISMATCH' in res.get_json().get('error', '')


def test_authorization_expired_rejected(voting_client, voting_user, active_election, auth_session):
    # Seed an expired authorization
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db.session.add(va)
    db.session.commit()

    res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert res.status_code == 403
    assert 'AUTHORIZATION_EXPIRED' in res.get_json().get('error', '')


def test_authorization_consumed_rejected(voting_client, voting_user, active_election, auth_session):
    # Seed an already consumed authorization
    va = VotingAuthorization(
        user_id=voting_user.id,
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

    res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert res.status_code == 403
    assert 'AUTHORIZATION_CONSUMED' in res.get_json().get('error', '')


# ---------------------------------------------------------------------------
# 3. Factor Verification & Client Bypass Prevention (CRITICAL FIX #1)
# ---------------------------------------------------------------------------

def test_client_cannot_manually_assert_factors(voting_client, active_election):
    # User calls authorize
    voting_client.post('/api/voting/authorize', json={'election_id': 1})

    # Client tries to send fake factor verification
    res = voting_client.post('/api/voting/mark-factors', json={
        'election_id': 1,
        'wallet_ok': True,
        'face_ok': True,
        'bypassed': 'fake_proof',
    })
    assert res.status_code == 200
    data = res.get_json()
    # Server verifies real database records: since user has no verified wallet or face, factors must be False
    assert data['wallet_ok'] is False
    assert data['face_ok'] is False
    assert data['status'] == 'PENDING_FACTORS'

    # Attempting to submit ballot must fail with 403
    sub_res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
    assert sub_res.status_code == 403
    assert 'FACTORS_INCOMPLETE' in sub_res.get_json().get('error', '')


def test_genuine_factors_authorize(voting_client, voting_user, active_election, auth_session):
    auth_res = voting_client.post('/api/voting/authorize', json={'election_id': 1})
    assert auth_res.status_code == 200
    va_id = auth_res.get_json()['authorization_id']

    # Set up genuine wallet binding record
    wb = WalletBinding(
        user_id=voting_user.id,
        wallet_address='0x' + '11' * 20,
        is_verified=True,
        binding_method='signature',
    )
    db.session.add(wb)

    # Set up genuine face enrollment & successful face challenge
    fe = FaceEnrollment(
        user_id=voting_user.id,
        is_enrolled=True,
        consent_given=True,
        encrypted_embedding=b'dummy-embedding',
    )
    db.session.add(fe)

    fc = FaceChallenge(
        challenge_id='ch-test-123',
        user_id=voting_user.id,
        session_id=auth_session.session_id,
        challenge_type='LIVENESS',
        challenge_sequence='LEFT,RIGHT',
        nonce='test-nonce-123',
        integrity_mac='test-mac-123',
        completed=True,
        success=True,
        completed_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        authorization_id=va_id,
        election_id=1,
    )
    db.session.add(fc)
    db.session.commit()

    # Now mark-factors should detect genuine factor proofs
    res = voting_client.post('/api/voting/mark-factors', json={'election_id': 1})
    assert res.status_code == 200
    data = res.get_json()
    assert data['wallet_ok'] is True
    assert data['face_ok'] is True
    assert data['status'] == 'AUTHORIZED'


# ---------------------------------------------------------------------------
# 4. Election and Candidate Validation (FIX #6)
# ---------------------------------------------------------------------------

def test_ballot_inactive_election_rejected(voting_client, db, voting_user, auth_session):
    inactive = Election(
        election_id='2',
        title='Inactive Election',
        status='DRAFT',
    )
    db.session.add(inactive)
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=2,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    res = voting_client.post('/api/voting/submit', json={'election_id': 2, 'candidate': 0})
    assert res.status_code == 400
    assert 'ELECTION_NOT_ACTIVE' in res.get_json().get('error', '')


def test_ballot_cancelled_election_rejected(voting_client, db, voting_user, auth_session):
    cancelled = Election(
        election_id='3',
        title='Cancelled Election',
        status='CANCELLED',
    )
    db.session.add(cancelled)
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=3,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    res = voting_client.post('/api/voting/submit', json={'election_id': 3, 'candidate': 0})
    assert res.status_code == 400
    assert 'ELECTION_NOT_ACTIVE' in res.get_json().get('error', '')


def test_ballot_invalid_candidate_rejected(voting_client, voting_user, active_election, auth_session):
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    # Negative index
    res_neg = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': -1})
    assert res_neg.status_code == 400
    assert 'INVALID_CANDIDATE' in res_neg.get_json().get('error', '')

    # Out of range index (candidate_count is 2 by default, so index 5 is invalid)
    res_high = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 5})
    assert res_high.status_code == 400
    assert 'INVALID_CANDIDATE' in res_high.get_json().get('error', '')


# ---------------------------------------------------------------------------
# 5. Revoting Prohibition (FIX #4) & Unique Constraint (F-7.10)
# ---------------------------------------------------------------------------

def test_revoting_prohibited_sequence_strictly_one(voting_client, voting_user, active_election, auth_session):
    # Ensure single-ballot election policy is configured
    active_election.max_ballots = 1
    # Pre-create a finalized ballot for this user + election
    pseudonym = derive_pseudonym(voting_user.id, 1)
    b = BallotRecord(
        election_id=1,
        pseudonym=pseudonym,
        candidate=0,
        sequence=1,
        state='FINALIZED',
    )
    db.session.add(b)

    # Authorized voting authorization
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    # Submitting a second ballot must be rejected with 409 BALLOT_ALREADY_CAST
    res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 1})
    assert res.status_code == 409
    assert 'BALLOT_ALREADY_CAST' in res.get_json().get('error', '')


def test_database_level_unique_constraint_enforced(db, voting_user):
    pseudonym = derive_pseudonym(voting_user.id, 1)
    b1 = BallotRecord(
        election_id=1,
        pseudonym=pseudonym,
        candidate=0,
        sequence=1,
        state='FINALIZED',
    )
    db.session.add(b1)
    db.session.commit()

    # Attempting to insert duplicate (election_id, pseudonym) must fail at DB level
    b2 = BallotRecord(
        election_id=1,
        pseudonym=pseudonym,
        candidate=1,
        sequence=1,
        state='QUEUED',
    )
    db.session.add(b2)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# 6. Real Relayer Pipeline & State Transitions (FIX #2)
# ---------------------------------------------------------------------------

def test_relayer_pipeline_success_finalized(voting_client, voting_user, active_election, auth_session):
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    # Mock web3 so Relayer can execute deterministically in unit test
    with patch('app.relayer.relayer.Web3') as mock_w3_class:
        mock_w3 = MagicMock()
        mock_w3_class.return_value = mock_w3
        mock_w3.is_connected.return_value = True
        mock_w3.eth.accounts = ['0x' + '11' * 20]

        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = '0x1234567890abcdef'
        mock_contract = MagicMock()
        mock_contract.functions.castBallot.return_value.transact.return_value = mock_tx_hash
        mock_w3.eth.contract.return_value = mock_contract

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 100
        mock_receipt.transactionHash = mock_tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
        # Phase 8: submit immediately queues without synchronous blockchain broadcast
        assert res.status_code == 202
        data = res.get_json()
        assert data['status'] == 'QUEUED'
        assert 'tx_hash' not in data  # Privacy invariant: no tx_hash leaked to voter

        # Execute relayer independently (simulating background relayer processing)
        from app.relayer import Relayer
        relayer = Relayer(contract_address='0x' + '22' * 20)
        summary = relayer.process_queue(batch_size=10)
        assert summary['processed'] == 1
        assert summary['confirmed'] == 1

        # Check DB state
        pseudonym = derive_pseudonym(voting_user.id, 1)
        record = BallotRecord.query.filter_by(election_id=1, pseudonym=pseudonym).first()
        assert record is not None
        assert record.state == 'FINALIZED'
        assert record.tx_hash == '0x1234567890abcdef'
        assert record.block_number == 100

        # Query status endpoint: must be FINALIZED with privacy-preserving receipt and NO tx_hash
        res_status = voting_client.get('/api/voting/status?election_id=1')
        assert res_status.status_code == 200
        status_data = res_status.get_json()
        assert status_data['status'] == 'FINALIZED'
        assert status_data['finalized'] is True
        assert 'tx_hash' not in status_data
        assert 'receipt' in status_data
        assert status_data['receipt']['receipt_code'].startswith('REC-')


def test_relayer_pipeline_failure_does_not_finalize(voting_client, voting_user, active_election, auth_session):
    va = VotingAuthorization(
        user_id=voting_user.id,
        election_id=1,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    # Mock web3 with reverted transaction (receipt.status == 0)
    with patch('app.relayer.relayer.Web3') as mock_w3_class:
        mock_w3 = MagicMock()
        mock_w3_class.return_value = mock_w3
        mock_w3.is_connected.return_value = True
        mock_w3.eth.accounts = ['0x' + '11' * 20]

        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = '0xfailedtx'
        mock_contract = MagicMock()
        mock_contract.functions.castBallot.return_value.transact.return_value = mock_tx_hash
        mock_w3.eth.contract.return_value = mock_contract

        mock_receipt = MagicMock()
        mock_receipt.status = 0  # Reverted!
        mock_receipt.blockNumber = 101
        mock_receipt.transactionHash = mock_tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        res = voting_client.post('/api/voting/submit', json={'election_id': 1, 'candidate': 0})
        assert res.status_code == 202
        assert res.get_json()['status'] == 'QUEUED'

        # Execute relayer
        from app.relayer import Relayer
        relayer = Relayer(contract_address='0x' + '22' * 20)
        summary = relayer.process_queue(batch_size=10)
        assert summary['processed'] == 1
        assert summary['failed'] == 1

        pseudonym = derive_pseudonym(voting_user.id, 1)
        record = BallotRecord.query.filter_by(election_id=1, pseudonym=pseudonym).first()
        assert record is not None
        assert record.state == 'FAILED'
        assert record.state != 'FINALIZED'
        assert 'REVERTED' in (record.error or '')

        # Status endpoint returns FAILED and NO tx_hash
        res_status = voting_client.get('/api/voting/status?election_id=1')
        assert res_status.status_code == 200
        assert res_status.get_json()['status'] == 'FAILED'
        assert 'tx_hash' not in res_status.get_json()


# ---------------------------------------------------------------------------
# 7. Status Endpoint (FIX #3) & SQL Model Mismatch Fix
# ---------------------------------------------------------------------------

def test_status_endpoint_no_sql_crash_and_authoritative(voting_client, voting_user, active_election):
    # Case A: No ballot
    r_none = voting_client.get('/api/voting/status?election_id=1')
    assert r_none.status_code == 200
    assert r_none.get_json()['status'] == 'NONE'

    # Case B: Ballot in QUEUED state
    pseudonym = derive_pseudonym(voting_user.id, 1)
    b = BallotRecord(
        election_id=1,
        pseudonym=pseudonym,
        candidate=0,
        sequence=1,
        state='QUEUED',
    )
    db.session.add(b)
    db.session.commit()

    r_queued = voting_client.get('/api/voting/status?election_id=1')
    assert r_queued.status_code == 200
    assert r_queued.get_json()['status'] == 'QUEUED'
    assert r_queued.get_json()['finalized'] is False

    # Case C: FINALIZED state
    b.state = 'FINALIZED'
    b.receipt_code = 'REC-1-ABCDEF'
    db.session.commit()

    r_finalized = voting_client.get('/api/voting/status?election_id=1')
    assert r_finalized.status_code == 200
    d_fin = r_finalized.get_json()
    assert d_fin['status'] == 'FINALIZED'
    assert d_fin['finalized'] is True
    assert d_fin['receipt']['receipt_code'] == 'REC-1-ABCDEF'


# ---------------------------------------------------------------------------
# 8. Privacy & Section 8.6 Receipt Conformance (FIX #7)
# ---------------------------------------------------------------------------

def test_privacy_and_receipt_conformance(voting_client, voting_user, active_election):
    pseudonym = derive_pseudonym(voting_user.id, 1)
    b = BallotRecord(
        election_id=1,
        pseudonym=pseudonym,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        receipt_code='REC-1-testreceipt',
    )
    db.session.add(b)
    db.session.commit()

    res = voting_client.get('/api/voting/status?election_id=1')
    data = res.get_json()

    # Assert response contains NO pseudonym, NO candidate, NO wallet address
    body_str = str(data)
    assert pseudonym not in body_str
    assert 'candidate' not in data
    assert 'wallet_address' not in body_str

    # Receipt fields
    receipt = data['receipt']
    assert receipt['receipt_code'] == 'REC-1-testreceipt'
    assert 'election_title' in receipt
    assert 'timestamp' in receipt
    assert 'voter_id_last4' in receipt
    assert 'pseudonym' not in receipt
    assert 'candidate' not in receipt


# ---------------------------------------------------------------------------
# 9. Election Existence and Validation Regressions (Phase 7 Re-audit Remediation)
# ---------------------------------------------------------------------------

def test_authorize_nonexistent_election_rejected(voting_client):
    res = voting_client.post('/api/voting/authorize', json={'election_id': 99999})
    assert res.status_code == 404
    assert res.get_json().get('error') == 'ELECTION_NOT_FOUND'


def test_authorize_inactive_election_rejected(voting_client, db):
    draft_election = Election(
        election_id='8888',
        title='Draft Election',
        status='DRAFT',
    )
    db.session.add(draft_election)
    db.session.commit()
    res = voting_client.post('/api/voting/authorize', json={'election_id': 8888})
    assert res.status_code == 400
    assert res.get_json().get('error') == 'ELECTION_NOT_ACTIVE'


def test_mark_factors_nonexistent_election_rejected(voting_client):
    res = voting_client.post('/api/voting/mark-factors', json={'election_id': 99999})
    assert res.status_code == 404
    assert res.get_json().get('error') == 'ELECTION_NOT_FOUND'


def test_validate_election_and_candidate_nonexistent(app, db):
    with app.app_context():
        valid, err, count = VotingService.validate_election_and_candidate(99999, 0)
        assert valid is False
        assert err == 'ELECTION_NOT_FOUND'
        assert count == 0
