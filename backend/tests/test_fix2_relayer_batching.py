"""
Tests for FIX 2: Relayer Batching and Timing De-Correlation
Vote Without Doubt - Backend Test Suite
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import AuditEvent, BallotRecord, Election, User
from app.relayer import Relayer, RelayerDispatcher, get_dispatcher
from app.security.password import hash_password
from tests.conftest import _seed_authorized_session


@pytest.fixture
def mock_w3(monkeypatch):
    """Mock Web3 and contract for deterministic testing without live blockchain dependency."""
    w3 = MagicMock()
    w3.is_connected.return_value = True
    w3.eth.accounts = ['0x' + '1' * 40, '0x' + '2' * 40]
    w3.eth.chain_id = 1337
    w3.eth.gas_price = 20_000_000_000

    receipt = MagicMock()
    receipt.status = 1
    receipt.blockNumber = 1234
    w3.eth.wait_for_transaction_receipt.return_value = receipt

    contract = MagicMock()
    tx_fn = MagicMock()
    tx_fn.transact.return_value = b'\x12' * 32
    tx_fn.build_transaction.return_value = None
    contract.functions.castBallot.return_value = tx_fn
    contract.functions.castNullBallot.return_value = tx_fn
    w3.eth.contract.return_value = contract

    monkeypatch.setattr(Relayer, 'get_web3', lambda self: w3)
    return w3


@pytest.fixture
def active_election(db):
    election = Election(
        election_id='1001',
        title='Relayer Batching Election 1',
        description='Test election for timing de-correlation',
        status='OPEN',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


@pytest.fixture
def second_election(db):
    election = Election(
        election_id='1002',
        title='Relayer Batching Election 2',
        description='Second isolated test election',
        status='OPEN',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(election)
    db.session.commit()
    return election


def test_single_queued_ballot_not_immediately_dispatched(app, db, active_election, mock_w3):
    """Test Requirement 1: A single queued ballot is NOT dispatched when threshold K=5 is not met."""
    ballot = BallotRecord(
        election_id=active_election.id,
        pseudonym='a' * 64,
        candidate=0,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow(),
    )
    db.session.add(ballot)
    db.session.commit()

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)
    # Check eligibility directly
    eligible, reason, queued, wait_sec = relayer.check_election_batch_eligibility(active_election.id)
    assert eligible is False
    assert reason == 'THRESHOLD_NOT_MET'

    # Run dispatch without force
    summary = relayer.dispatch_election_batch(active_election.id, force=False)
    assert summary['status'] == 'SKIPPED'
    assert summary['processed'] == 0

    # Verify ballot is still QUEUED in database
    db.session.refresh(ballot)
    assert ballot.state == 'QUEUED'
    assert ballot.tx_hash is None


def test_five_ballots_shuffled_and_dispatched_correctly(app, db, active_election, mock_w3):
    """Test Requirement 2: Five ballots (threshold K=5) are shuffled and dispatched in a single batch."""
    ballots = []
    for i in range(5):
        b = BallotRecord(
            election_id=active_election.id,
            pseudonym=f'{i:02x}' * 32,
            candidate=i % 2,
            sequence=1,
            state='QUEUED',
            created_at=datetime.utcnow(),
        )
        ballots.append(b)
        db.session.add(b)
    db.session.commit()

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)
    eligible, reason, queued, _ = relayer.check_election_batch_eligibility(active_election.id)
    assert eligible is True
    assert reason == 'THRESHOLD_MET'

    summary = relayer.dispatch_election_batch(active_election.id, force=False)
    assert summary['status'] == 'DISPATCHED'
    assert summary['processed'] == 5
    assert summary['confirmed'] == 5
    assert summary['trigger_reason'] == 'THRESHOLD_MET'
    assert summary['degraded_privacy'] is False

    # Check all ballots are now FINALIZED
    for b in ballots:
        db.session.refresh(b)
        assert b.state == 'FINALIZED'
        assert b.block_number == 1234

    # Verify audit event was logged
    audit_event = AuditEvent.query.filter_by(event_type='RELAYER_BATCH_DISPATCHED').order_by(AuditEvent.id.desc()).first()
    assert audit_event is not None
    assert audit_event.event_metadata['batch_size'] == 5
    assert audit_event.event_metadata['trigger_reason'] == 'THRESHOLD_MET'
    assert audit_event.event_metadata['min_threshold'] == 5
    assert audit_event.event_metadata['degraded_privacy'] is False


def test_ballots_from_different_elections_never_mixed(app, db, active_election, second_election, mock_w3):
    """Test Requirement 11: Ballots from Election 1 and Election 2 are strictly isolated and never mixed."""
    # 3 ballots for Election 1
    e1_ballots = [
        BallotRecord(election_id=active_election.id, pseudonym=f'1{i:02x}' * 32, candidate=0, sequence=1, state='QUEUED')
        for i in range(3)
    ]
    # 3 ballots for Election 2
    e2_ballots = [
        BallotRecord(election_id=second_election.id, pseudonym=f'2{i:02x}' * 32, candidate=1, sequence=1, state='QUEUED')
        for i in range(3)
    ]
    db.session.add_all(e1_ballots + e2_ballots)
    db.session.commit()

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)

    # Total ballots = 6, but each election only has 3 (< K=5).
    # Dispatcher must NOT combine them!
    summary = relayer.dispatch_due_batches(force=False)
    assert summary['total_processed'] == 0
    assert summary['batches_dispatched'] == 0

    for b in e1_ballots + e2_ballots:
        db.session.refresh(b)
        assert b.state == 'QUEUED'

    # Now add 2 more ballots to Election 1 to reach 5
    e1_more = [
        BallotRecord(election_id=active_election.id, pseudonym=f'1{i:02x}' * 32, candidate=0, sequence=1, state='QUEUED')
        for i in (3, 4)
    ]
    db.session.add_all(e1_more)
    db.session.commit()

    # Election 1 now has 5 ballots (dispatches). Election 2 still has 3 (remains queued).
    summary2 = relayer.dispatch_due_batches(force=False)
    assert summary2['batches_dispatched'] == 1
    assert summary2['total_processed'] == 5

    # Election 1 ballots finalized
    for b in e1_ballots + e1_more:
        db.session.refresh(b)
        assert b.state == 'FINALIZED'

    # Election 2 ballots STILL QUEUED
    for b in e2_ballots:
        db.session.refresh(b)
        assert b.state == 'QUEUED'


def test_revote_sequence_ordering_preserved(app, db, active_election, mock_w3):
    """Test Requirement 5: For a voter with multiple revotes, sequence 1 is ALWAYS processed before sequence 2."""
    pseud_voter = 'ab' * 32
    v1 = BallotRecord(election_id=active_election.id, pseudonym=pseud_voter, candidate=0, sequence=1, state='QUEUED')
    v2 = BallotRecord(election_id=active_election.id, pseudonym=pseud_voter, candidate=1, sequence=2, state='QUEUED')

    # Add 3 other voters
    others = [
        BallotRecord(election_id=active_election.id, pseudonym=f'{i:02x}' * 32, candidate=0, sequence=1, state='QUEUED')
        for i in range(3)
    ]
    db.session.add_all([v1, v2] + others)
    db.session.commit()

    call_sequences = []

    def fake_cast_ballot(eid, pseudo_bytes, cand, seq):
        if pseudo_bytes == bytes.fromhex(pseud_voter):
            call_sequences.append(seq)
        tx_fn = MagicMock()
        tx_fn.transact.return_value = b'\x55' * 32
        return tx_fn

    mock_w3.eth.contract.return_value.functions.castBallot.side_effect = fake_cast_ballot

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)
    summary = relayer.dispatch_election_batch(active_election.id, force=False)
    assert summary['processed'] == 5

    # Assert sequence 1 was called BEFORE sequence 2
    assert call_sequences == [1, 2], f"Expected sequence [1, 2] but got {call_sequences}"


def test_maximum_waiting_policy_behaves_correctly(app, db, active_election, mock_w3):
    """Test Requirement 3: Bounded waiting policy dispatches a ballot when max wait time expires."""
    stale_time = datetime.utcnow() - timedelta(seconds=35)
    b = BallotRecord(
        election_id=active_election.id,
        pseudonym='ff' * 32,
        candidate=0,
        sequence=1,
        state='QUEUED',
        created_at=stale_time,
    )
    db.session.add(b)
    db.session.commit()

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)
    eligible, reason, queued, wait_sec = relayer.check_election_batch_eligibility(active_election.id)
    assert eligible is True
    assert reason == 'MAX_WAIT_EXCEEDED'
    assert wait_sec >= 30.0

    summary = relayer.dispatch_election_batch(active_election.id, force=False)
    assert summary['status'] == 'DISPATCHED'
    assert summary['processed'] == 1
    assert summary['trigger_reason'] == 'MAX_WAIT_EXCEEDED'
    assert summary['degraded_privacy'] is True

    db.session.refresh(b)
    assert b.state == 'FINALIZED'


def test_election_closure_handles_pending_ballots_safely(app, db, active_election, mock_w3):
    """Test Requirement 7: Closing an election flushes all pending ballots, leaving zero stranded."""
    b1 = BallotRecord(election_id=active_election.id, pseudonym='c1' * 32, candidate=0, sequence=1, state='QUEUED')
    b2 = BallotRecord(election_id=active_election.id, pseudonym='c2' * 32, candidate=1, sequence=1, state='QUEUED')
    db.session.add_all([b1, b2])
    db.session.commit()

    # Close the election
    active_election.status = 'CLOSED'
    active_election.closed_at = datetime.utcnow()
    db.session.commit()

    relayer = Relayer(w3_instance=mock_w3, contract_address='0x' + '3' * 40)
    eligible, reason, queued, _ = relayer.check_election_batch_eligibility(active_election.id)
    assert eligible is True
    assert reason == 'ELECTION_CLOSED'

    summary = relayer.dispatch_election_batch(active_election.id, force=False)
    assert summary['status'] == 'DISPATCHED'
    assert summary['processed'] == 2
    assert summary['trigger_reason'] == 'ELECTION_CLOSED'
    assert summary['degraded_privacy'] is True

    db.session.refresh(b1)
    db.session.refresh(b2)
    assert b1.state == 'FINALIZED'
    assert b2.state == 'FINALIZED'


def test_worker_restart_does_not_lose_queued_ballots(app, db, active_election, mock_w3):
    """Test Requirement 4 & Worker Restart: Stopping and restarting dispatcher retains all queued ballots."""
    b1 = BallotRecord(election_id=active_election.id, pseudonym='d1' * 32, candidate=0, sequence=1, state='QUEUED')
    b2 = BallotRecord(election_id=active_election.id, pseudonym='d2' * 32, candidate=1, sequence=1, state='QUEUED')
    db.session.add_all([b1, b2])
    db.session.commit()

    dispatcher = RelayerDispatcher(app=app, dispatch_interval=1.0)
    dispatcher.start()
    assert dispatcher.is_running is True

    # Stop dispatcher (worker shutdown)
    dispatcher.stop()
    assert dispatcher.is_running is False

    # Ballots are intact in the database
    db.session.refresh(b1)
    db.session.refresh(b2)
    assert b1.state == 'QUEUED'
    assert b2.state == 'QUEUED'

    # Add 3 more to reach 5
    more = [
        BallotRecord(election_id=active_election.id, pseudonym=f'd{i:02x}' * 32, candidate=0, sequence=1, state='QUEUED')
        for i in (3, 4, 5)
    ]
    db.session.add_all(more)
    db.session.commit()

    # Restart dispatcher and tick
    new_dispatcher = RelayerDispatcher(app=app, dispatch_interval=1.0)
    summary = new_dispatcher.tick(force=False, contract_address='0x' + '3' * 40)
    assert summary['total_processed'] == 5

    for b in [b1, b2] + more:
        db.session.refresh(b)
        assert b.state == 'FINALIZED'


def test_http_submission_decoupled_from_dispatch(app, client, db, active_election, signed_cookie_for):
    """Test Requirement 1 & HTTP Decoupling: Voting via POST /api/voting/submit does NOT immediately dispatch."""
    from app.models import VotingAuthorization

    user = User(
        username='decoupled_voter',
        email='decoupled@college.test',
        password_hash=hash_password('test-password-123'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()

    auth_session = _seed_authorized_session(db, user)
    va = VotingAuthorization(
        user_id=user.id,
        election_id=active_election.id,
        session_id=auth_session.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    client.set_cookie(
        app.config['SESSION_COOKIE_NAME'],
        signed_cookie_for(auth_session.session_id),
    )

    res = client.post(
        '/api/voting/submit',
        json={
            'election_id': active_election.id,
            'candidate': 0,
        },
    )
    assert res.status_code == 202
    data = res.get_json()
    assert data['status'] == 'QUEUED'

    # Verify ballot in DB is QUEUED, not yet confirmed on chain
    ballot = BallotRecord.query.filter_by(election_id=active_election.id).first()
    assert ballot is not None
    assert ballot.state == 'QUEUED'
    assert ballot.tx_hash is None
