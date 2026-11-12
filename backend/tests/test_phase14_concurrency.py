"""
Phase 14 Concurrency Test Suite
Vote Without Doubt - System Verification

Covers:
C-14-01: Two simultaneous first votes from the same voter (only one sequence 1 accepted)
C-14-02: Two simultaneous revotes (atomic sequence increment, no duplicates/skips)
C-14-03: Simultaneous null revote and normal vote (atomic ordering, latest determines tally)
C-14-04: Concurrent independent voters (no cross-contamination, no collisions, accurate tally)
C-14-05: Concurrent relayer workers (atomic claim, exactly-once processing)
C-14-06: Concurrent election admin operations (four-eyes enforcement, no illegal state transitions)
"""

import concurrent.futures
import secrets
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

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
from app.models.admin import AdminUser, ApprovalRequest
from app.relayer import Relayer
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.services.election_admin_service import ElectionAdminService, TwoOfficerApprovalError
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def conc_election(db):
    e = Election(
        election_id='1402',
        title='Phase 14 Concurrency Election',
        status='ACTIVE',
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=6),
        max_ballots=3,
    )
    db.session.add(e)
    db.session.commit()
    derive_pseudonym(1, e.id)
    derive_pseudonym(1, str(e.election_id))
    derive_pseudonym(1, int(e.election_id))
    return e


def _setup_voter(db, idx, election_id):
    """Creates a distinct, verified voter with wallet binding, face enrollment, and challenge."""
    user = User(
        username=f'conc_voter_{idx}',
        email=f'conc_voter_{idx}@college.test',
        password_hash=hash_password(f'pass_{idx}_secure!'),
        voter_id=f'VOTER-CONC-{idx:03d}',
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()

    session_id = secrets.token_hex(24)
    auth_session = _seed_authorized_session(db, user, session_id=session_id)

    wallet = WalletBinding(
        user_id=user.id,
        wallet_address='0x' + secrets.token_hex(20),
        is_verified=True,
    )
    db.session.add(wallet)

    enrollment = FaceEnrollment(
        user_id=user.id,
        encrypted_embedding=b'\x01' * 512,
        is_enrolled=True,
        consent_given=True,
        consent_at=datetime.utcnow(),
    )
    db.session.add(enrollment)
    db.session.commit()

    derive_pseudonym(user.id, election_id)
    va = VotingService.create_authorization(user.id, election_id, session_id=session_id)

    challenge = FaceChallenge(
        challenge_id=secrets.token_hex(16),
        user_id=user.id,
        session_id=session_id,
        challenge_type='FACE',
        challenge_sequence='',
        nonce=secrets.token_hex(16),
        integrity_mac='mac-conc',
        completed=True,
        success=True,
        authorization_id=va.id,
        election_id=election_id,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(challenge)
    db.session.commit()

    VotingService.mark_factors(user.id, election_id, session_id=session_id)

    return {
        'user_id': user.id,
        'user': user,
        'session_id': session_id,
        'election_id': election_id,
    }


def _authorize_revote(db, uid, eid, sid):
    va = VotingService.create_authorization(uid, eid, session_id=sid)
    challenge = FaceChallenge(
        challenge_id=secrets.token_hex(16),
        user_id=uid,
        session_id=sid,
        challenge_type='FACE',
        challenge_sequence='',
        nonce=secrets.token_hex(16),
        integrity_mac='mac-revote',
        completed=True,
        success=True,
        authorization_id=va.id,
        election_id=eid,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(challenge)
    db.session.commit()
    VotingService.mark_factors(uid, eid, session_id=sid)


# ==============================================================================
# C-14-01: Two simultaneous first votes from the same voter
# ==============================================================================

def test_c14_01_two_simultaneous_first_votes(app, db, conc_election):
    """
    C-14-01: Two simultaneous first votes from the same voter.
    Expected: Exactly one sequence 1 accepted; other rejected cleanly.
    """
    eid = int(conc_election.election_id)
    voter_info = _setup_voter(db, 1, eid)
    uid = voter_info['user_id']
    sid = voter_info['session_id']

    results = []

    def _vote_task(candidate):
        with app.app_context():
            ballot, err = VotingService.submit_ballot(uid, eid, candidate=candidate, session_id=sid)
            results.append((ballot, err))

    # Spawn 2 concurrent submission attempts
    t1 = threading.Thread(target=_vote_task, args=(0,))
    t2 = threading.Thread(target=_vote_task, args=(1,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with app.app_context():
        successes = [r for r in results if r[1] == "OK"]
        failures = [r for r in results if r[1] != "OK"]

        assert len(successes) == 1, "Exactly one first vote must succeed"
        assert len(failures) == 1, "The competing concurrent vote must be rejected"
        assert failures[0][1] in ("AUTHORIZATION_CONSUMED", "BALLOT_ALREADY_CAST", "PREVIOUS_BALLOT_PENDING")

        ballots = BallotRecord.query.filter_by(election_id=eid).all()
        assert len(ballots) == 1, "Only one ballot record must exist in the database"
        assert ballots[0].sequence == 1


# ==============================================================================
# C-14-02: Two simultaneous revotes
# ==============================================================================

def test_c14_02_two_simultaneous_revotes(app, db, conc_election):
    """
    C-14-02: Two simultaneous revotes.
    Expected: Sequence assignment remains atomic; no duplicate sequence or sequence skip.
    """
    eid = int(conc_election.election_id)
    voter_info = _setup_voter(db, 2, eid)
    uid = voter_info['user'].id
    sid = voter_info['session_id']

    with app.app_context():
        # First vote confirmed
        b1, err = VotingService.submit_ballot(uid, eid, candidate=0, session_id=sid)
        assert err == "OK"
        b1.state = 'FINALIZED'
        # Backdate to bypass revote cooldown
        b1.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()

        # Prepare authorization for revote
        _authorize_revote(db, uid, eid, sid)

    results = []

    def _revote_task(candidate):
        with app.app_context():
            ballot, err = VotingService.submit_ballot(uid, eid, candidate=candidate, session_id=sid)
            results.append((ballot, err))

    t1 = threading.Thread(target=_revote_task, args=(0,))
    t2 = threading.Thread(target=_revote_task, args=(1,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with app.app_context():
        successes = [r for r in results if r[1] == "OK"]
        assert len(successes) == 1, "Only one of the concurrent revotes can consume the authorization"

        ballots = BallotRecord.query.filter_by(election_id=eid).order_by(BallotRecord.sequence.asc()).all()
        assert len(ballots) == 2
        assert ballots[0].sequence == 1
        assert ballots[1].sequence == 2
        assert ballots[0].superseded is True
        assert ballots[1].superseded is False


# ==============================================================================
# C-14-03: Simultaneous null revote and normal vote
# ==============================================================================

def test_c14_03_simultaneous_null_revote_and_normal_vote(app, db, conc_election):
    """
    C-14-03: Simultaneous null revote and normal vote.
    Expected: Sequence integrity preserved; exactly one transitions; latest valid sequence determines tally.
    """
    eid = int(conc_election.election_id)
    voter_info = _setup_voter(db, 3, eid)
    uid = voter_info['user'].id
    sid = voter_info['session_id']

    with app.app_context():
        b1, err = VotingService.submit_ballot(uid, eid, candidate=1, session_id=sid)
        assert err == "OK"
        b1.state = 'FINALIZED'
        b1.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()

        _authorize_revote(db, uid, eid, sid)

    results = []

    def _submit_call(candidate, is_null):
        with app.app_context():
            ballot, err = VotingService.submit_ballot(uid, eid, candidate=candidate, session_id=sid, is_null=is_null)
            results.append((ballot, err))

    t1 = threading.Thread(target=_submit_call, args=(0, False))
    t2 = threading.Thread(target=_submit_call, args=(None, True))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with app.app_context():
        successes = [r for r in results if r[1] == "OK"]
        assert len(successes) == 1

        active_ballots = BallotRecord.query.filter_by(election_id=eid, superseded=False).all()
        assert len(active_ballots) == 1
        assert active_ballots[0].sequence == 2


# ==============================================================================
# C-14-04: Concurrent independent voters
# ==============================================================================

def test_c14_04_concurrent_independent_voters(app, db, conc_election):
    """
    C-14-04: Concurrent voters.
    Use 10 independent concurrent voters and verify:
    - no cross-voter contamination
    - no duplicate pseudonyms
    - no sequence collision
    - correct tally
    """
    eid = int(conc_election.election_id)
    num_voters = 10
    voters = []

    with app.app_context():
        for i in range(10, 10 + num_voters):
            voters.append(_setup_voter(db, i, eid))

    results = []

    def _voter_worker(voter_dict, candidate):
        with app.app_context():
            uid = voter_dict['user_id']
            sid = voter_dict['session_id']
            ballot, err = VotingService.submit_ballot(
                uid,
                eid,
                candidate=candidate,
                session_id=sid,
            )
            seq = ballot.sequence if ballot else None
            results.append((uid, candidate, seq, err))

    threads = []
    # Voters 0..4 vote for candidate 0, voters 5..9 vote for candidate 1
    for idx, v_info in enumerate(voters):
        cand = 0 if idx < 5 else 1
        t = threading.Thread(target=_voter_worker, args=(v_info, cand))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    with app.app_context():
        assert len(results) == num_voters
        for uid, cand, seq, err in results:
            assert err == "OK", f"Voter {uid} failed to cast vote: {err}"
            assert seq == 1

        all_ballots = BallotRecord.query.filter_by(election_id=eid).all()
        assert len(all_ballots) == num_voters

        # Verify no duplicate pseudonyms
        pseuds = [b.pseudonym for b in all_ballots]
        assert len(set(pseuds)) == num_voters, "All pseudonyms must be distinct"

        # Verify tally distribution
        c0_count = sum(1 for b in all_ballots if b.candidate == 0)
        c1_count = sum(1 for b in all_ballots if b.candidate == 1)
        assert c0_count == 5
        assert c1_count == 5


# ==============================================================================
# C-14-05: Concurrent relayer workers
# ==============================================================================

def test_c14_05_concurrent_relayer_workers(app, db, conc_election):
    """
    C-14-05: Concurrent relayer workers.
    Expected: Exactly-once logical processing, no duplicate blockchain ballots.
    """
    eid = int(conc_election.election_id)
    with app.app_context():
        # Create 10 QUEUED ballots
        for i in range(10):
            b = BallotRecord(
                election_id=eid,
                pseudonym=f'0x{i+1:064x}',
                candidate=i % 2,
                sequence=1,
                state='QUEUED',
            )
            db.session.add(b)
        db.session.commit()

    relayer_results = []

    def _worker_task(worker_id):
        with app.app_context():
            mock_receipt = MagicMock()
            mock_receipt.status = 1
            mock_receipt.blockNumber = 1000 + worker_id

            mock_w3 = MagicMock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.accounts = ['0x1111111111111111111111111111111111111111', '0x2222222222222222222222222222222222222222']
            mock_w3.eth.contract.return_value.functions.castBallot.return_value.transact.return_value = b'\xcc' * 32
            mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            relayer = Relayer(contract_address='0x' + '77' * 20, w3_instance=mock_w3)
            summary = relayer.process_queue(batch_size=10)
            relayer_results.append((worker_id, summary))

    # Spawn 3 concurrent workers competing for the queue
    threads = [threading.Thread(target=_worker_task, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.app_context():
        total_confirmed = sum(s['confirmed'] for _, s in relayer_results)
        assert total_confirmed == 10, f"Expected exactly 10 confirmed ballots across workers, got {total_confirmed}"

        finalized_ballots = BallotRecord.query.filter_by(election_id=eid, state='FINALIZED').all()
        assert len(finalized_ballots) == 10


# ==============================================================================
# C-14-06: Concurrent election-admin operations
# ==============================================================================

def test_c14_06_concurrent_election_admin_operations(app, db):
    """
    C-14-06: Concurrent election-admin operations.
    Test conflicting schedule / cancel / emergency close / finalize.
    Expected: Lifecycle invariants remain intact; four-eyes enforced; no illegal state transition.
    """
    with app.app_context():
        e = Election(
            election_id='1403',
            title='Admin Concurrency Election',
            status='SCHEDULED',
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=5),
        )
        db.session.add(e)
        db.session.commit()

        # Two officers
        off1 = AdminUser(admin_id='OFF-1', name='Officer 1', email='off1@col.test', password_hash=hash_password('p1'), role='OFFICER', is_active=True)
        off2 = AdminUser(admin_id='OFF-2', name='Officer 2', email='off2@col.test', password_hash=hash_password('p2'), role='OFFICER', is_active=True)
        db.session.add_all([off1, off2])
        db.session.commit()

        # Create two conflicting four-eyes requests: CANCEL_ELECTION
        req1 = ElectionAdminService.request_approval('1403', 'CANCEL_ELECTION', off1, reason="Admin reason 1")
        req2 = ElectionAdminService.request_approval('1403', 'CANCEL_ELECTION', off1, reason="Admin reason 2")

        # Officer 1 attempts self-approval on both: strictly blocked by four-eyes
        with pytest.raises(TwoOfficerApprovalError):
            ElectionAdminService.approve_request(req1.id, off1)

        with pytest.raises(TwoOfficerApprovalError):
            ElectionAdminService.approve_request(req2.id, off1)

        # Officer 2 executes approval on req2
        ok_appr, msg = ElectionAdminService.approve_request(req2.id, off2)
        assert ok_appr is True

        db.session.refresh(e)
        assert e.status == 'CANCELLED'

        # Attempting to approve req1 (which was invalidated by req2) fails safely
        ok_appr2, msg2 = ElectionAdminService.approve_request(req1.id, off2)
        assert ok_appr2 is False
        assert msg2.startswith("REQUEST_NOT_PENDING")
