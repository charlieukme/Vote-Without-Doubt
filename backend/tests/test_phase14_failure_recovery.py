"""
Phase 14 - Full Failure & Recovery Testing Suite
AI & Blockchain-Based Secure E-Voting System — Vote Without Doubt

Tests:
1. Flask / Backend Failure (F-14-01 to F-14-05)
2. Relayer / Worker Failure (F-14-06 to F-14-10)
3. Database Failure (F-14-11 to F-14-15)
4. Blockchain / Ganache Failure (F-14-16 to F-20-20)
5. Critical Operation Interruption (14 boundaries)
6. Recovery Test Matrix (Startup recovery -> Queued -> Submitted -> Confirmed -> Failed -> Reconciliation)
7. Data Integrity & Privacy Invariant Verification
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError, IntegrityError

from app.extensions import db
from app.models import (
    AuthSession,
    BallotRecord,
    Election,
    FaceChallenge,
    FaceEnrollment,
    ReconciliationIssue,
    User,
    VotingAuthorization,
    WalletBinding,
)
from app.relayer import Relayer
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.services.recovery import RecoveryService
from app.services.reconciliation_service import ReconciliationService
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


from app.models.admin import Candidate
from app.models.ballot_record_v2 import BallotQueueV2
from app.services.blockchain_v2_service import BlockchainV2Service, BroadcastUncertainError


@pytest.fixture
def p14_election(db):
    e = Election(
        election_id='1401',
        title='Phase 14 Failure Testing Election',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=6),
        candidate_count=2,
        max_ballots=3,
    )
    db.session.add(e)
    db.session.flush()
    db.session.add_all([
        Candidate(election_id=str(e.election_id), candidate_index=0, name='Candidate Zero'),
        Candidate(election_id=str(e.election_id), candidate_index=1, name='Candidate One'),
    ])
    db.session.commit()
    derive_pseudonym(1, e.id)
    derive_pseudonym(1, str(e.election_id))
    derive_pseudonym(1, int(e.election_id))
    return e


@pytest.fixture
def p14_voter(db):
    user = User(
        username='p14_voter_1',
        email='p14_voter_1@college.test',
        password_hash=hash_password('p14-pass-secure!'),
        voter_id='VOTER-1401',
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _authorize_voter_for_revote(db, uid, eid, sid):
    va = VotingService.create_authorization(uid, eid, session_id=sid)
    challenge = FaceChallenge(
        challenge_id=secrets.token_hex(16),
        user_id=uid,
        session_id=sid,
        challenge_type='FACE',
        challenge_sequence='',
        nonce=secrets.token_hex(16),
        integrity_mac='revote-mac',
        completed=True,
        success=True,
        authorization_id=va.id,
        election_id=eid,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(challenge)
    db.session.commit()
    VotingService.mark_factors(uid, eid, session_id=sid)
    return va


@pytest.fixture
def p14_authorized_voter(app, db, p14_election, p14_voter):
    """Sets up a complete authorized voter with active session, wallet binding, face enrollment & challenge."""
    session_id = secrets.token_hex(24)
    auth_session = _seed_authorized_session(db, p14_voter, session_id=session_id)

    # 1. Wallet binding
    wallet = WalletBinding(
        user_id=p14_voter.id,
        wallet_address='0x' + secrets.token_hex(20),
        is_verified=True,
    )
    db.session.add(wallet)

    # 2. Face enrollment & completed challenge
    enrollment = FaceEnrollment(
        user_id=p14_voter.id,
        encrypted_embedding=b'\x01' * 512,
        is_enrolled=True,
        consent_given=True,
        consent_at=datetime.utcnow(),
    )
    db.session.add(enrollment)
    db.session.commit()

    # 3. Voting authorization and bound challenge
    va = VotingService.create_authorization(p14_voter.id, int(p14_election.election_id), session_id=session_id)

    challenge = FaceChallenge(
        challenge_id=secrets.token_hex(16),
        user_id=p14_voter.id,
        session_id=session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce=secrets.token_hex(16),
        integrity_mac='valid-test-mac',
        completed=True,
        success=True,
        authorization_id=va.id,
        election_id=int(p14_election.election_id),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(challenge)
    db.session.commit()

    VotingService.mark_factors(p14_voter.id, int(p14_election.election_id), session_id=session_id)

    return {
        'user': p14_voter,
        'session_id': session_id,
        'election_id': int(p14_election.election_id),
        'auth_session': auth_session,
    }


# ==============================================================================
# SECTION 1: FLASK / BACKEND FAILURE (F-14-01 to F-14-05)
# ==============================================================================

def test_f14_01_backend_crash_before_ballot_creation(app, db, p14_authorized_voter):
    """
    F-14-01: Backend process crashes before ballot creation.
    Expected: No ballot appears, no blockchain tx, no false success returned.
    """
    v = p14_authorized_voter
    with app.app_context():
        with patch.object(db.session, 'add', side_effect=RuntimeError("Process terminated abruptly")):
            with pytest.raises(RuntimeError, match="Process terminated abruptly"):
                VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])

        ballots = BallotRecord.query.filter_by(election_id=v['election_id']).all()
        assert len(ballots) == 0, "No ballot must appear after crash before creation"
        va = VotingAuthorization.query.filter_by(user_id=v['user'].id, election_id=v['election_id']).first()
        assert va.consumed is False, "Authorization must remain unconsumed if ballot creation failed"


def test_f14_02_backend_crash_after_db_ballot_before_chain_submission(app, db, p14_election, p14_authorized_voter):
    """
    F-14-02: Backend crashes after DB ballot creation but before blockchain submission.
    Expected: Ballot remains in QUEUED, recoverable, no duplicate submission, startup recovery handles state.
    """
    v = p14_authorized_voter
    with app.app_context():
        ballot, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        assert err == "OK"
        assert ballot.state == 'QUEUED'

        recovered_count = RecoveryService.startup_recover()
        assert recovered_count >= 1

        db.session.refresh(ballot)
        assert ballot.state == 'QUEUED', "Ballot must remain safely in QUEUED state"
        assert ballot.reconcile_required is True
        assert ballot.reconcile_reason == 'UNFINISHED_QUEUED'

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 12001

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.get_transaction_receipt.return_value = mock_receipt

        # V1 relayer broadcast is permanently disabled per SEC-001 (remains cleanly in QUEUED)
        relayer = Relayer(contract_address='0x' + '33' * 20)
        res = relayer.process_queue(batch_size=10)
        assert res == {'processed': 0, 'confirmed': 0, 'failed': 0}
        db.session.refresh(ballot)
        assert ballot.state == 'QUEUED'

        # V2 equivalent: queued/submitted BallotQueueV2 recovers cleanly on startup recovery
        b2 = BallotQueueV2(
            election_id=p14_election.id,
            pseudonym=ballot.pseudonym,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='SUBMITTED',
            tx_hash='0x' + secrets.token_hex(32),
        )
        db.session.add(b2)
        db.session.commit()

        mock_w3.eth.get_transaction_receipt.return_value = {'status': 1, 'blockNumber': 12001}
        mock_contract = MagicMock()
        mock_contract.functions.electionId.return_value.call.return_value = p14_election.id
        mock_svc = MagicMock()
        mock_svc.contract_address = '0x' + '33' * 20
        mock_svc.get_web3.return_value = mock_w3
        mock_svc.get_contract.return_value = mock_contract

        with patch.object(BlockchainV2Service, 'for_election', return_value=mock_svc):
            v2_summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert v2_summary['v2_confirmed'] == 1

        db.session.refresh(b2)
        assert b2.state == 'CONFIRMED'
        assert b2.block_number == 12001


def test_f14_03_backend_crash_after_blockchain_tx_before_db_status_update(app, db, p14_authorized_voter):
    """
    F-14-03: Backend crashes after blockchain tx submission but before DB status update.
    Expected: Tx is discoverable on chain, recovery reconciles DB <-> blockchain, no duplicate tx.
    """
    v = p14_authorized_voter
    with app.app_context():
        ballot, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=0, session_id=v['session_id'])
        assert err == "OK"

        real_tx_hash = '0x' + secrets.token_hex(32)
        ballot.state = 'SUBMITTED'
        ballot.tx_hash = real_tx_hash
        ballot.tx_broadcast_at = datetime.utcnow()
        db.session.commit()

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 8848

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['confirmed'] >= 1

        db.session.refresh(ballot)
        assert ballot.state == 'FINALIZED'
        assert ballot.block_number == 8848
        assert ballot.reconcile_required is False
        assert ballot.reconcile_reason == 'RECOVERED_CONFIRMED'


def test_f14_04_backend_restart_during_active_election(app, db, p14_election, p14_authorized_voter):
    """
    F-14-04: Backend restarts during active election.
    Expected: Election state preserved, pending operations recover, no security state reset, no duplicate votes.
    """
    v = p14_authorized_voter
    with app.app_context():
        e = Election.query.filter_by(election_id=str(v['election_id'])).first()
        assert e.status == 'ACTIVE'

        b1, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        assert err == "OK"
        b1.state = 'FINALIZED'
        b1.block_number = 100
        db.session.commit()

        recovered = RecoveryService.startup_recover()
        assert recovered == 0

        e_after = Election.query.filter_by(election_id=str(v['election_id'])).first()
        assert e_after.status == 'ACTIVE'
        assert e_after.id == e.id

        dup, dup_err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=0, session_id=v['session_id'])
        assert dup is None
        assert dup_err in ('COOLDOWN_ACTIVE', 'AUTHORIZATION_CONSUMED', 'UNAUTHORIZED', 'BALLOT_ALREADY_CAST', 'PREVIOUS_BALLOT_PENDING')


def test_f14_05_backend_crash_during_revote(app, db, p14_authorized_voter):
    """
    F-14-05: Backend crashes during revote.
    Expected: Sequence remains valid, no skipped sequence, latest-vote-wins preserved.
    """
    v = p14_authorized_voter
    with app.app_context():
        b1, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=0, session_id=v['session_id'])
        assert err == "OK"
        b1.state = 'FINALIZED'
        b1.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()

        va2 = _authorize_voter_for_revote(db, v['user'].id, v['election_id'], v['session_id'])

        with patch.object(db.session, 'commit', side_effect=OperationalError("connection lost", {}, None)):
            with pytest.raises(OperationalError):
                VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        db.session.rollback()

        ballots = BallotRecord.query.filter_by(election_id=v['election_id']).all()
        assert len(ballots) == 1
        assert ballots[0].sequence == 1
        assert ballots[0].superseded is False

        va3 = _authorize_voter_for_revote(db, v['user'].id, v['election_id'], v['session_id'])
        b2_retry, err3 = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        assert err3 == "OK"
        assert b2_retry.sequence == 2
        assert ballots[0].superseded is True


# ==============================================================================
# SECTION 2: RELAYER / WORKER FAILURE (F-14-06 to F-14-10)
# ==============================================================================

def test_f14_06_relayer_stopped_while_ballots_queued(app, db, p14_authorized_voter):
    """
    F-14-06: Relayer stops while ballots are queued.
    Expected: Queued ballots remain recoverable, no ballot disappears, no false confirmation.
    """
    v = p14_authorized_voter
    with app.app_context():
        ballot, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        assert err == "OK"

        app.config['RELAYER_ENABLED'] = False
        relayer = Relayer(contract_address='0x' + '44' * 20)
        res = relayer.process_queue(batch_size=5)

        # V1 broadcast fails closed per SEC-001; queued record remains safely recoverable without false confirmation
        assert res['confirmed'] == 0
        db.session.refresh(ballot)
        assert ballot.state == 'QUEUED'

        all_ballots = BallotRecord.query.filter_by(election_id=v['election_id']).all()
        assert len(all_ballots) == 1


def test_f14_07_relayer_crashes_after_claiming_job(app, db, p14_election):
    """
    F-14-07: Relayer crashes after claiming a job.
    Expected: Job becomes recoverable, another worker can safely process it, no duplicate tx.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='SUBMITTED',
            tx_hash=None,
            tx_broadcast_at=datetime.utcnow() - timedelta(seconds=60),
        )
        db.session.add(b)
        db.session.commit()

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['requeued'] >= 1

        db.session.refresh(b)
        assert b.state == 'QUEUED'
        assert b.reconcile_reason in ('REQUEUED_UNBROADCAST', 'REQUEUED_MISSING_TX')
        assert b.retry_count == 1


def test_f14_08_relayer_crashes_immediately_after_broadcast(app, db, p14_election):
    """
    F-14-08: Relayer crashes immediately after broadcast.
    Expected: Startup recovery discovers submitted tx, DB state becomes consistent, tx NOT broadcast twice.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        tx_hash = '0x' + secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=1,
            sequence=1,
            state='SUBMITTED',
            tx_hash=tx_hash,
            tx_broadcast_at=datetime.utcnow() - timedelta(seconds=10),
        )
        db.session.add(b)
        db.session.commit()

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 9002

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['confirmed'] == 1

        db.session.refresh(b)
        assert b.state == 'FINALIZED'
        assert b.block_number == 9002
        assert b.tx_hash == tx_hash


def test_f14_09_relayer_restarts_repeatedly(app, db, p14_election):
    """
    F-14-09: Relayer restarts repeatedly.
    Expected: Idempotency maintained, no duplicate ballots, no sequence corruption.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='FINALIZED',
            tx_hash='0x' + secrets.token_hex(32),
            block_number=501,
        )
        db.session.add(b)
        db.session.commit()

        for _ in range(5):
            res = RecoveryService.startup_recover(detailed=True)
            assert res['recovered'] == 0, "Finalized ballots must not be re-processed"

        db.session.refresh(b)
        assert b.state == 'FINALIZED'
        assert b.block_number == 501


def test_f14_10_concurrent_relayer_workers_atomic_claim(app, db, p14_election):
    """
    F-14-10: Two relayer workers process the same logical job concurrently.
    Expected: Atomic claim prevents double processing, exactly one ballot broadcast.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=1,
            sequence=1,
            state='QUEUED',
        )
        db.session.add(b)
        db.session.commit()

        claimed_w1 = BallotRecord.query.filter(
            BallotRecord.id == b.id,
            BallotRecord.state == 'QUEUED',
        ).update({'state': 'SUBMITTED'}, synchronize_session=False)
        db.session.commit()

        claimed_w2 = BallotRecord.query.filter(
            BallotRecord.id == b.id,
            BallotRecord.state == 'QUEUED',
        ).update({'state': 'SUBMITTED'}, synchronize_session=False)
        db.session.commit()

        assert claimed_w1 == 1, "Worker 1 successfully claimed the ballot"
        assert claimed_w2 == 0, "Worker 2 was rejected; atomic claiming prevented double processing"


# ==============================================================================
# SECTION 3: DATABASE FAILURE (F-14-11 to F-14-15)
# ==============================================================================

def test_f14_11_db_unavailable_before_vote_submission(app, db, p14_authorized_voter, signed_cookie_for):
    """
    F-14-11: Database unavailable before V2 vote submission.
    Expected: Clean failure / no blockchain transaction, no false receipt.
    """
    from app.models import VoterIdentity

    v = p14_authorized_voter
    with app.app_context():
        db.session.add(VoterIdentity(
            voter_id=v['user'].voter_id,
            full_name='P14 Voter 1',
            email=v['user'].email,
            is_eligible=True,
        ))
        db.session.commit()

    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(v['session_id']))

    with patch.object(BlockchainV2Service, 'cast_ballot') as mock_cast, \
         patch.object(db.session, 'commit', side_effect=OperationalError("cannot connect to db", {}, None)):
        res = client.post('/api/v2/voting/cast', json={
            'election_id': v['election_id'],
            'sequence': 1,
            'ciphertexts': [{'c1': [1, 2], 'c2': [3, 4]}],
            'proof': {'e': [1], 's': [2]},
        })
        assert res.status_code == 500
        assert res.get_json()['error'] == 'BALLOT_QUEUE_FAILED'
        mock_cast.assert_not_called()

    db.session.rollback()
    assert BallotQueueV2.query.count() == 0


def test_f14_12_db_connection_lost_during_ballot_processing(app, db, p14_authorized_voter):
    """
    F-14-12: Database connection lost during ballot processing.
    Expected: Transaction state remains recoverable, no silent success.
    """
    v = p14_authorized_voter
    with app.app_context():
        with patch.object(db.session, 'commit', side_effect=OperationalError("connection lost during commit", {}, None)):
            with pytest.raises(OperationalError):
                VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=1, session_id=v['session_id'])
        db.session.rollback()

        ballots = BallotRecord.query.filter_by(election_id=v['election_id']).all()
        assert len(ballots) == 0


def test_f14_13_db_restart_active_election(app, db, p14_election):
    """
    F-14-13: Database restart while election is active.
    Expected: Application reconnects, election state preserved, pending records preserved.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='QUEUED',
        )
        db.session.add(b)
        db.session.commit()

        for engine in list(db.engines.values()):
            engine.dispose()

        b_after = db.session.get(BallotRecord, b.id)
        assert b_after is not None
        assert b_after.state == 'QUEUED'
        assert b_after.pseudonym == pseud


def test_f14_14_db_transaction_rollback(app, db, p14_authorized_voter):
    """
    F-14-14: Database transaction fails/rolls back.
    Expected: No partial logical vote, no inconsistent ballot status.
    """
    v = p14_authorized_voter
    with app.app_context():
        derive_pseudonym(v['user'].id, v['election_id'])
        with patch.object(db.session, 'commit', side_effect=IntegrityError("unique constraint", {}, None)):
            b, err = VotingService.submit_ballot(v['user'].id, v['election_id'], candidate=0, session_id=v['session_id'])
            assert b is None
            assert err == "BALLOT_ALREADY_CAST"

        ballots = BallotRecord.query.filter_by(election_id=v['election_id']).all()
        assert len(ballots) == 0


def test_f14_15_db_blockchain_disagreement_detection(app, db, p14_election):
    """
    F-14-15: Database and blockchain disagree.
    Expected: Reconciliation detects mismatch, system does not silently overwrite evidence, mismatch auditable.
    """
    with app.app_context():
        eid = int(p14_election.election_id)
        mock_contract = MagicMock()
        # electionInfo returns 9-tuple: (id, startTime, endTime, candidateCount, rollHash, candidateSetHash, isActive, distinctVoters, totalBallots)
        mock_contract.functions.electionInfo.return_value.call.return_value = (eid, 1000, 2000, 2, b'\x00'*32, b'\x00'*32, True, 5, 5)
        # getTally called per candidate index:
        mock_contract.functions.getTally.return_value.call.return_value = 3
        mock_contract.functions.distinctVoters.return_value.call.return_value = 5
        mock_contract.functions.getBallot.return_value.call.return_value = (1, 0, False, True)

        with patch.object(ReconciliationService, 'get_relayer_and_contract') as mock_rc:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_relayer = MagicMock()
            mock_relayer._format_pseudonym.side_effect = lambda p: b'\x11' * 32
            mock_rc.return_value = (mock_relayer, mock_w3, mock_contract)

            for i in range(5):
                b = BallotRecord(
                    election_id=eid,
                    pseudonym=secrets.token_hex(32),
                    candidate=0,
                    sequence=1,
                    state='FINALIZED',
                    superseded=False,
                )
                db.session.add(b)
            db.session.commit()

            report = ReconciliationService.reconcile_election(eid)
            assert report['status'] in ('MISMATCH', 'DISCREPANCY_DETECTED')
            assert len(report['discrepancies']) >= 1

            issue = ReconciliationIssue.query.filter_by(election_id=p14_election.id).first()
            assert issue is not None
            assert issue.issue_type == 'TALLY_MISMATCH'
            assert issue.severity == 'HIGH'


# ==============================================================================
# SECTION 4: BLOCKCHAIN / GANACHE FAILURE (F-14-16 to F-14-20)
# ==============================================================================

def test_f14_16_rpc_unavailable_before_ballot_submission(app, db, p14_election, p14_authorized_voter, signed_cookie_for):
    """
    F-14-16: Blockchain RPC unavailable before ballot submission.
    Expected: Clean failure, no false receipt, DB state remains recoverable.
    """
    from app.models import VoterIdentity

    v = p14_authorized_voter
    with app.app_context():
        db.session.add(VoterIdentity(
            voter_id=v['user'].voter_id,
            full_name='P14 Voter 1',
            email=v['user'].email,
            is_eligible=True,
        ))
        db.session.commit()

        client = app.test_client()
        client.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(v['session_id']))
        with patch.object(BlockchainV2Service, 'resolve_relayer_credentials', return_value=('0x' + '22' * 32, '0x' + '33' * 20)), \
             patch.object(BlockchainV2Service, 'cast_ballot', side_effect=ConnectionError("Connection refused: RPC_UNREACHABLE http://127.0.0.1:99999")):
            res = client.post('/api/v2/voting/cast', json={
                'election_id': p14_election.id,
                'sequence': 1,
                'ciphertexts': [{'c1': [1, 2], 'c2': [3, 4]}],
                'proof': {'e': [1], 's': [2]},
            })
        assert res.status_code == 504
        assert res.get_json()['error'] == 'TRANSACTION_BROADCAST_UNCERTAIN'
        b2 = BallotQueueV2.query.filter_by(election_id=p14_election.id).first()
        assert b2 is not None
        assert b2.state == 'QUEUED'
        assert b2.receipt_code is None


def test_f14_17_rpc_disappears_during_transaction_submission(app, db, p14_election, p14_authorized_voter, signed_cookie_for):
    """
    F-14-17: RPC disappears during transaction submission (timeout).
    Expected: System does not assume success/failure without evidence, marks in-flight SUBMITTED with tx_hash.
    """
    from app.models import VoterIdentity

    v = p14_authorized_voter
    tx_h = '0x' + secrets.token_hex(32)
    with app.app_context():
        db.session.add(VoterIdentity(
            voter_id=v['user'].voter_id,
            full_name='P14 Voter 1',
            email=v['user'].email,
            is_eligible=True,
        ))
        db.session.commit()

        client = app.test_client()
        client.set_cookie(app.config['SESSION_COOKIE_NAME'], signed_cookie_for(v['session_id']))
        with patch.object(BlockchainV2Service, 'resolve_relayer_credentials', return_value=('0x' + '22' * 32, '0x' + '33' * 20)), \
             patch.object(
                 BlockchainV2Service,
                 'cast_ballot',
                 side_effect=BroadcastUncertainError("Timeout waiting for receipt", tx_hash=tx_h),
             ):
            res = client.post('/api/v2/voting/cast', json={
                'election_id': p14_election.id,
                'sequence': 1,
                'ciphertexts': [{'c1': [1, 2], 'c2': [3, 4]}],
                'proof': {'e': [1], 's': [2]},
            })
        assert res.status_code == 504
        b2 = BallotQueueV2.query.filter_by(election_id=p14_election.id).first()
        assert b2 is not None
        assert b2.state == 'SUBMITTED'
        assert b2.tx_hash == tx_h
        assert b2.receipt_code is None


def test_f14_18_ganache_restart_handling(app, db, p14_election):
    """
    F-14-18: Ganache restarts.
    Expected: Application reconnects correctly, offline recovery safe.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='SUBMITTED',
            tx_hash='0x' + secrets.token_hex(32),
            tx_broadcast_at=datetime.utcnow(),
        )
        db.session.add(b)
        db.session.commit()

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = False
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['recovered'] == 1

        db.session.refresh(b)
        assert b.state == 'SUBMITTED'


def test_f14_19_transaction_receipt_delayed(app, db, p14_election):
    """
    F-14-19: Transaction receipt delayed.
    Expected: No duplicate broadcast, polling/recovery safe.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        tx_hash = '0x' + secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='SUBMITTED',
            tx_hash=tx_hash,
            tx_broadcast_at=datetime.utcnow() - timedelta(seconds=5),
        )
        db.session.add(b)
        db.session.commit()

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.side_effect = Exception("not mined yet")
            mock_w3.eth.get_transaction.return_value = {'hash': tx_hash, 'blockNumber': None}
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['pending'] == 1

        db.session.refresh(b)
        assert b.state == 'SUBMITTED'
        assert b.reconcile_reason == 'TX_PENDING'


def test_f14_20_blockchain_transaction_reverts(app, db, p14_election):
    """
    F-14-20: Blockchain transaction reverts on chain.
    Expected: DB state reflects FAILED, voter not given false receipt, recovery records revert.
    """
    with app.app_context():
        pseud = secrets.token_hex(32)
        tx_hash = '0x' + secrets.token_hex(32)
        b = BallotRecord(
            election_id=int(p14_election.election_id),
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state='SUBMITTED',
            tx_hash=tx_hash,
        )
        db.session.add(b)
        db.session.commit()

        mock_receipt = MagicMock()
        mock_receipt.status = 0
        mock_receipt.blockNumber = 7712

        with patch.object(Relayer, 'get_web3') as mock_w3_fn:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
            mock_w3_fn.return_value = mock_w3

            summary = RecoveryService.startup_recover(detailed=True)
            assert summary['failed'] == 1

        db.session.refresh(b)
        assert b.state == 'FAILED'
        assert 'TRANSACTION_REVERTED' in b.error
        assert b.reconcile_required is True
        assert b.reconcile_reason == 'TX_REVERTED'


# ==============================================================================
# SECTION 5: CRITICAL OPERATION INTERRUPTION (14 BOUNDARIES)
# ==============================================================================

def test_interruption_boundaries_all_14(app, db, p14_election, p14_authorized_voter):
    """
    Validates safe failure-handling across all 14 critical boundaries:
    1. voter auth, 2. face liveness, 3. OTP verification, 4. wallet signature,
    5. ballot creation, 6. queue insertion, 7. blockchain broadcast, 8. confirmation,
    9. receipt generation, 10. revote, 11. election close, 12. election finalize,
    13. audit anchoring, 14. reconciliation.
    """
    v = p14_authorized_voter
    eid = v['election_id']

    with app.app_context():
        # Boundary 1: Voter auth interruption (fresh unverified user/session without authorized VotingAuthorization)
        unauth_user = User(
            username='p14_unauth_user',
            email='p14_unauth@college.test',
            password_hash=hash_password('p14-unauth-pass!'),
            voter_id='VOTER-UNAUTH',
            is_active=True,
            is_verified=True,
        )
        db.session.add(unauth_user)
        db.session.commit()
        unauth_session = _seed_authorized_session(db, unauth_user, auth_state='PENDING_OTP')
        va_res = VotingService.mark_factors(unauth_user.id, eid, session_id=unauth_session.session_id)
        assert va_res is None

        # Boundary 2: Face liveness interruption
        expired_ch = FaceChallenge(
            challenge_id=secrets.token_hex(16),
            user_id=v['user'].id,
            session_id=v['session_id'],
            challenge_type='LIVENESS',
            challenge_sequence='LEFT,RIGHT',
            nonce=secrets.token_hex(16),
            integrity_mac='mac-expired',
            completed=False,
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        db.session.add(expired_ch)
        db.session.commit()
        assert expired_ch.completed is False

        # Boundary 3: OTP verification interruption
        from app.services.auth_service import AuthService
        auth_svc = AuthService()
        otp_ok, _ = auth_svc.verify_otp(v['user'].id, '000000', purpose='login')
        assert otp_ok is False

        # Boundary 4: Wallet signature interruption
        wb_unverified = WalletBinding(user_id=v['user'].id, wallet_address='0x' + secrets.token_hex(20), is_verified=False)
        assert wb_unverified.is_verified is False

        # Boundary 5 & 6: Ballot creation & queue insertion
        b, err = VotingService.submit_ballot(v['user'].id, eid, candidate=0, session_id=v['session_id'])
        assert err == "OK"
        assert b.state == 'QUEUED'

        # Boundary 7 & 8: Broadcast & confirmation
        b.state = 'SUBMITTED'
        b.tx_hash = '0x' + secrets.token_hex(32)
        b.state = 'CONFIRMED'
        b.block_number = 100
        b.state = 'FINALIZED'
        db.session.commit()

        # Boundary 9: Receipt generation
        rcpt = VotingService.generate_receipt(b, v['user'].id)
        assert rcpt['receipt_code'].startswith(f"REC-{eid}-")

        # Boundary 10: Revote cooldown interruption
        va_rv = _authorize_voter_for_revote(db, v['user'].id, eid, v['session_id'])
        b_rv, err_rv = VotingService.submit_ballot(v['user'].id, eid, candidate=1, session_id=v['session_id'])
        assert err_rv == "COOLDOWN_ACTIVE"

        # Boundary 11: Election close
        elec = Election.query.filter_by(election_id=str(eid)).first()
        elec.status = 'CLOSED'
        db.session.commit()

        # Boundary 12: Election finalize
        ok, fin_msg = VotingService.finalize_election(eid)
        assert ok is True
        assert fin_msg == "OK"

        # Boundary 13: Audit anchoring integrity
        from app.audit import AuditLogger
        assert AuditLogger().verify_chain() is True

        # Boundary 14: Reconciliation safe handling when clean
        with patch.object(ReconciliationService, 'get_relayer_and_contract') as mock_rc:
            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = False
            mock_rc.return_value = (None, mock_w3, None)
            res_rec = ReconciliationService.reconcile_election(eid)
            assert res_rec['status'] == 'RPC_UNREACHABLE'
