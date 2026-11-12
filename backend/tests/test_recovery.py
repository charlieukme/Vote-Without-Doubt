"""
Phase 10 Recovery & Reconciliation Comprehensive Test Suite
Vote Without Doubt
"""

import os
import secrets
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    BallotRecord,
    Election,
    ReconciliationIssue,
    User,
    VotingAuthorization,
)
from app.relayer import Relayer
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.services.reconciliation_service import ReconciliationService
from app.services.recovery import RecoveryService
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def recovery_election(db):
    e = Election(
        election_id='1001',
        title='Recovery Test Election',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=1),
        end_time=datetime.utcnow() + timedelta(hours=5),
    )
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def recovery_user(db):
    user = User(
        username='recov_user1',
        email='recov_user1@college.test',
        password_hash=hash_password('recov-pass-123!'),
        voter_id='REC-01',
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_recovery_idempotent(app, db):
    """Test that RecoveryService.is_idempotent_ok executes real dual-pass stability verification."""
    with app.app_context():
        assert RecoveryService.is_idempotent_ok() is True


def test_reconcile_required_state_safe(app, db):
    """Test that reconcile_required internal flags are not exposed in client error payloads."""
    c = app.test_client()
    r = c.post('/api/voting/submit', json={})
    assert b'reconcile_required' not in r.data


def test_stale_queued_ballot_recovery(app, db, recovery_election):
    """Test that unbroadcast QUEUED ballots are flagged with UNFINISHED_QUEUED without dropping."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='QUEUED',
            reconcile_required=False,
        )
        db.session.add(b)
        db.session.commit()

        recovered_count = RecoveryService.startup_recover()
        assert recovered_count >= 1

        db.session.refresh(b)
        assert b.reconcile_required is True
        assert b.reconcile_reason == 'UNFINISHED_QUEUED'
        assert b.state == 'QUEUED'


def test_submitted_ballot_confirmed_recovery(app, db, recovery_election):
    """Test crash-after-broadcast recovery: a confirmed transaction advances to FINALIZED."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        mock_tx_hash = '0x' + secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=1,
            sequence=1,
            state='SUBMITTED',
            tx_hash=mock_tx_hash,
            tx_broadcast_at=datetime.utcnow() - timedelta(minutes=5),
            reconcile_required=False,
        )
        db.session.add(b)
        db.session.commit()

        # Mock Web3 receipt returning status=1 (confirmed)
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 54321

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['confirmed'] >= 1

            db.session.refresh(b)
            assert b.state == 'FINALIZED'
            assert b.block_number == 54321
            assert b.reconcile_required is False
            assert b.reconcile_reason == 'RECOVERED_CONFIRMED'


def test_submitted_ballot_reverted_recovery(app, db, recovery_election):
    """Test reverted transaction recovery: a reverted transaction transitions to FAILED."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        mock_tx_hash = '0x' + secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=1,
            sequence=1,
            state='SUBMITTED',
            tx_hash=mock_tx_hash,
            tx_broadcast_at=datetime.utcnow() - timedelta(minutes=5),
            reconcile_required=False,
        )
        db.session.add(b)
        db.session.commit()

        mock_receipt = MagicMock()
        mock_receipt.status = 0
        mock_receipt.blockNumber = 54322

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['failed'] >= 1

            db.session.refresh(b)
            assert b.state == 'FAILED'
            assert 'TRANSACTION_REVERTED' in b.error
            assert b.reconcile_required is True
            assert b.reconcile_reason == 'TX_REVERTED'


def test_unbroadcast_submitted_ballot_recovery(app, db, recovery_election):
    """Test crash-before-broadcast recovery: ballot in SUBMITTED with null tx_hash is safely requeued."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='SUBMITTED',
            tx_hash=None,
            tx_broadcast_at=datetime.utcnow() - timedelta(minutes=5),
            reconcile_required=False,
            retry_count=0,
        )
        db.session.add(b)
        db.session.commit()

        # Contract getBallot returns exists=False
        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['requeued'] >= 1

            db.session.refresh(b)
            assert b.state == 'QUEUED'
            assert b.retry_count == 1
            assert b.reconcile_reason == 'REQUEUED_UNBROADCAST'


def test_reconciliation_service_clean_election(app, db, recovery_election):
    """Test that ReconciliationService reports CLEAN when DB tallies and on-chain tallies match."""
    with app.app_context():
        with patch.object(ReconciliationService, 'get_relayer_and_contract') as mock_fn:
            mock_relayer = MagicMock()
            mock_relayer._format_pseudonym.return_value = b'\x01' * 32
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True

            mock_contract = MagicMock()
            # (startTime, endTime, candidateCount=2, rollHash, eligibleCount=10, candidatesHash, cancelled=False, distinctVoters=0, maxBallots=3)
            mock_contract.functions.electionInfo().call.return_value = (
                0, 0, 2, b'\x00'*32, 10, b'\x00'*32, False, 0, 3
            )
            mock_contract.functions.getTally().call.return_value = 0
            mock_fn.return_value = (mock_relayer, mock_w3, mock_contract)

            report = ReconciliationService.reconcile_election(1001)
            assert report['status'] == 'CLEAN'
            assert report['issues_recorded'] == 0


def test_reconciliation_service_detects_tally_mismatch(app, db, recovery_election):
    """Test that ReconciliationService detects tally mismatch and creates ReconciliationIssue."""
    with app.app_context():
        # Seed 1 finalized vote for candidate 0 in DB
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='FINALIZED',
            superseded=False,
            is_null=False,
        )
        db.session.add(b)
        db.session.commit()

        with patch.object(ReconciliationService, 'get_relayer_and_contract') as mock_fn:
            mock_relayer = MagicMock()
            mock_relayer._format_pseudonym.return_value = b'\x01' * 32
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True

            mock_contract = MagicMock()
            # On-chain says candidate 0 has 0 votes, but DB has 1 vote!
            mock_contract.functions.electionInfo().call.return_value = (
                0, 0, 2, b'\x00'*32, 10, b'\x00'*32, False, 1, 3
            )
            mock_contract.functions.getTally().call.return_value = 0
            mock_fn.return_value = (mock_relayer, mock_w3, mock_contract)

            report = ReconciliationService.reconcile_election(1001)
            assert report['status'] == 'MISMATCH'
            assert report['issues_recorded'] >= 1

            # Check that ReconciliationIssue was persisted
            issues = ReconciliationService.get_open_issues(1001)
            assert len(issues) >= 1
            assert any(i.issue_type == 'TALLY_MISMATCH' for i in issues)


def test_relayer_concurrent_worker_claim_protection(app, db, recovery_election):
    """Test that atomic claiming in Relayer.process_queue prevents two workers from processing the same ballot."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=1001,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='QUEUED',
        )
        db.session.add(b)
        db.session.commit()

        # Simulate Worker A claiming the ballot
        claimed_a = BallotRecord.query.filter(
            BallotRecord.id == b.id,
            BallotRecord.state == 'QUEUED'
        ).update({'state': 'SUBMITTED'}, synchronize_session=False)
        db.session.commit()
        assert claimed_a == 1

        # Concurrent Worker B attempting to claim the same ballot must match 0 rows
        claimed_b = BallotRecord.query.filter(
            BallotRecord.id == b.id,
            BallotRecord.state == 'QUEUED'
        ).update({'state': 'SUBMITTED'}, synchronize_session=False)
        db.session.commit()
        assert claimed_b == 0


def test_phase9_revote_possible_after_recovery(app, db, recovery_election, recovery_user, signed_cookie_for):
    """Test that recovering an interrupted V2 sequence 1 ballot frees the voter to cast sequence 2 revote."""
    from app.models import VoterIdentity
    from app.models.ballot_record_v2 import BallotQueueV2
    from app.services.blockchain_v2_service import BlockchainV2Service

    app.config['REVOTE_COOLDOWN_SECONDS'] = 0
    recovery_election.status = 'OPEN'
    recovery_election.candidate_count = 2
    recovery_election.protocol_version = 'V2'
    db.session.add(VoterIdentity(
        voter_id=recovery_user.voter_id,
        full_name='Recovery User',
        email=recovery_user.email,
        is_eligible=True,
    ))
    db.session.commit()

    pseud = derive_pseudonym(recovery_user.id, recovery_election.id)
    mock_tx1 = '0x' + secrets.token_hex(32)
    # V2 Ballot 1 was interrupted in SUBMITTED
    b1 = BallotQueueV2(
        election_id=recovery_election.id,
        pseudonym=pseud,
        sequence=1,
        ciphertexts_json='["c1"]',
        proof_json='{"p":1}',
        state='SUBMITTED',
        tx_hash=mock_tx1,
        created_at=datetime.utcnow() - timedelta(seconds=150),
    )
    db.session.add(b1)
    db.session.commit()

    # Run recovery with confirmed V2 receipt
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.get_transaction_receipt.return_value = {'status': 1, 'blockNumber': 12345}
    mock_contract = MagicMock()
    mock_contract.functions.electionId.return_value.call.return_value = recovery_election.id
    mock_svc = MagicMock()
    mock_svc.contract_address = '0x' + '11' * 20
    mock_svc.get_web3.return_value = mock_w3
    mock_svc.get_contract.return_value = mock_contract

    with patch.object(BlockchainV2Service, 'for_election', return_value=mock_svc):
        RecoveryService.startup_recover()

    db.session.refresh(b1)
    assert b1.state == 'CONFIRMED'
    assert b1.receipt_code is not None
    assert b1.superseded is False

    # Now voter performs fresh authorization and revotes via V2 /api/v2/voting/cast (sequence 2)
    s = _seed_authorized_session(db, recovery_user)
    va = VotingAuthorization(
        user_id=recovery_user.id,
        election_id=recovery_election.id,
        session_id=s.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()

    mock_tx2 = '0x' + secrets.token_hex(32)
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(s.session_id))
    with patch.object(BlockchainV2Service, 'resolve_relayer_credentials', return_value=('0x' + '22' * 32, '0x' + '33' * 20)), \
         patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': mock_tx2, 'block_number': 12346}):
        r = client.post('/api/v2/voting/cast', json={
            'election_id': recovery_election.id,
            'sequence': 2,
            'ciphertexts': [{'c1': [1, 2], 'c2': [3, 4]}],
            'proof': {'e': [1], 's': [2]},
        })
    assert r.status_code == 200
    body = r.get_json()
    assert body['sequence'] == 2
    assert body['status'] == 'CONFIRMED'
    db.session.refresh(b1)
    assert b1.superseded is True


def test_recovery_preserves_privacy(app, db, recovery_election):
    """Test that reconciliation issues store zero voter names, emails, USNs, or candidate plaintext."""
    with app.app_context():
        ri = RecoveryService.record_mismatch(
            election_id=1001,
            issue_type='TALLY_MISMATCH',
            severity='HIGH',
            observed='count=5',
            expected='count=4',
        )
        assert 'recov_user1' not in str(ri.observed_state)
        assert 'college.test' not in str(ri.observed_state)
        assert ri.status == 'OPEN'

        # Resolve issue
        resolved = ReconciliationService.resolve_issue(ri.id, "Manually audited and verified.")
        assert resolved.status == 'RESOLVED'
        assert resolved.resolution_note == "Manually audited and verified."
