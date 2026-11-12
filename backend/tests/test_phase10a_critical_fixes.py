"""
Phase 10A Regression Tests — Strictly Scoped Critical Fixes 1, 3, and 4.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.extensions import db
from app.models import Election, FaceChallenge, VotingAuthorization
from app.models.admin import ApprovalRequest
from app.models.audit_event import AuditEvent
from app.security.admin_auth import AdminAuthService
from app.security.merkle import MerkleTree
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import generate_secure_scalar
from app.services.election_lifecycle_worker import ElectionLifecycleWorker
from app.services.v2_election_manager import V2ElectionManager


class _FakeCall:
    def __init__(self, val):
        self._val = val

    def call(self):
        return self._val


# =============================================================================
# Fix 1 — Face Challenge Missing Import & Non-Numeric Election ID Resolution
# =============================================================================

def test_face_challenge_standalone_without_va(face_client, face_user, face_session):
    res = face_client.post('/api/face/challenge', json={})
    assert res.status_code == 200, res.get_json()
    payload = res.get_json()
    assert 'challenge_id' in payload
    assert 'authorization_id' not in payload
    assert 'election_id' not in payload

    row = FaceChallenge.query.filter_by(challenge_id=payload['challenge_id']).one()
    assert row.user_id == face_user.id
    assert row.session_id == face_session.session_id
    assert row.authorization_id is None


def test_face_challenge_numeric_and_non_numeric_election_ids(face_client, face_user, face_session):
    now = datetime.utcnow()
    el = Election(
        election_id='ELEC_FACE_CHALLENGE_10A',
        title='Face Challenge Election',
        status='OPEN',
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        candidate_count=2,
        eligible_count=10,
    )
    db.session.add(el)
    db.session.flush()

    va = VotingAuthorization(
        user_id=face_user.id,
        election_id=el.id,
        session_id=face_session.session_id,
        wallet_verified=True,
        face_verified=False,
        expires_at=now + timedelta(minutes=15),
        consumed=False,
    )
    db.session.add(va)
    db.session.commit()

    # Numeric election ID
    r_num = face_client.post('/api/face/challenge', json={'election_id': el.id})
    assert r_num.status_code == 200, r_num.get_json()
    p_num = r_num.get_json()
    assert p_num['authorization_id'] == va.id
    assert p_num['election_id'] == el.id

    # Non-numeric public string election_id (previously failed with NameError: Election)
    r_str = face_client.post('/api/face/challenge', json={'election_id': el.election_id})
    assert r_str.status_code == 200, r_str.get_json()
    p_str = r_str.get_json()
    assert p_str['authorization_id'] == va.id
    assert p_str['election_id'] == el.id

    row = FaceChallenge.query.filter_by(challenge_id=p_str['challenge_id']).one()
    assert row.authorization_id == va.id
    assert row.session_id == face_session.session_id


def test_face_challenge_unknown_non_numeric_election_id_does_not_leak_va(
    face_client, face_user, face_session
):
    now = datetime.utcnow()
    el = Election(
        election_id='ELEC_REAL_FOR_LEAK_CHECK',
        title='Real Election',
        status='OPEN',
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        candidate_count=2,
        eligible_count=10,
    )
    db.session.add(el)
    db.session.flush()

    va = VotingAuthorization(
        user_id=face_user.id,
        election_id=el.id,
        session_id=face_session.session_id,
        wallet_verified=True,
        face_verified=False,
        expires_at=now + timedelta(minutes=15),
        consumed=False,
    )
    db.session.add(va)
    db.session.commit()

    res = face_client.post('/api/face/challenge', json={'election_id': 'ELEC_DOES_NOT_EXIST'})
    assert res.status_code == 200, res.get_json()
    payload = res.get_json()
    assert 'authorization_id' not in payload
    assert 'election_id' not in payload


def test_face_challenge_requires_authenticated_session(client):
    res = client.post('/api/face/challenge', json={'election_id': 'ELEC_ANY'})
    assert res.status_code == 401


# =============================================================================
# Fix 3 — Zero-Vote Finalization & Lifecycle Worker Backoff / Terminal Failure
# =============================================================================

def _make_fake_online_service(total_active=0, state=6, finalize_zero_error=None):
    class _FakeW3:
        class eth:
            chain_id = 1337

        def is_connected(self):
            return True

    class _FakeContract:
        address = '0x5FbDB2315678afecb367f032d93F642f64180aa3'

        class functions:
            @staticmethod
            def state():
                return _FakeCall(state)

            @staticmethod
            def candidateCount():
                return _FakeCall(2)

            @staticmethod
            def totalActiveBallots():
                return _FakeCall(total_active)

    class _FakeService:
        def __init__(self):
            self.finalize_zero_called = False
            self.finalize_tally_called = False
            self.close_voting_called = False

        def get_web3(self):
            return _FakeW3()

        def get_contract(self):
            return _FakeContract()

        def resolve_relayer_credentials(self):
            return ('0x' + '1' * 64, '0x1111111111111111111111111111111111111111')

        def resolve_admin_credentials(self):
            return ('0x' + '2' * 64, '0x2222222222222222222222222222222222222222')

        def close_voting(self, *_args, **_kwargs):
            self.close_voting_called = True
            return {'status': 1, 'tx_hash': '0xclose'}

        def finalize_zero_vote_election(self, *_args, **_kwargs):
            self.finalize_zero_called = True
            if finalize_zero_error is not None:
                raise finalize_zero_error
            return {'status': 1, 'tx_hash': '0xzero_fin'}

        def finalize_tally(self, *_args, **_kwargs):
            self.finalize_tally_called = True
            return {'status': 1, 'tx_hash': '0xfin'}

    return _FakeService()


def test_zero_vote_election_finalizes_via_dedicated_contract_method(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_ZERO_VOTE_OK',
            title='Zero Vote Future Contract',
            status='CLOSED',
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
            closed_at=now - timedelta(hours=1),
            candidate_count=2,
            eligible_count=10,
            v2_priv_key_1=str(generate_secure_scalar()),
            v2_priv_key_2=str(generate_secure_scalar()),
        )
        db.session.add(el)
        db.session.commit()

        fake_svc = _make_fake_online_service(total_active=0, state=6)
        prev_testing = app.config.get('TESTING')
        app.config['TESTING'] = False
        try:
            with patch.object(BlockchainV2Service, 'for_election', return_value=fake_svc):
                ok, _msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        finally:
            app.config['TESTING'] = prev_testing

        assert ok is True
        assert fake_svc.finalize_zero_called is True
        assert fake_svc.finalize_tally_called is False
        assert details['tallies'] == [0, 0]
        assert details['zero_vote'] is True
        assert details['finalized_on_chain'] is True

        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'FINALIZED'
        assert refreshed.finalized_at is not None
        assert refreshed.merkle_root == MerkleTree([]).root


def test_zero_vote_legacy_contract_never_marks_finalized(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_ZERO_VOTE_LEGACY',
            title='Zero Vote Legacy Contract',
            status='OPEN',
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
            candidate_count=2,
            eligible_count=10,
            v2_priv_key_1=str(generate_secure_scalar()),
            v2_priv_key_2=str(generate_secure_scalar()),
        )
        db.session.add(el)
        db.session.commit()

        fake_svc = _make_fake_online_service(
            total_active=0,
            state=6,
            finalize_zero_error=RuntimeError('execution reverted: NO_BALLOTS_CAST'),
        )
        prev_testing = app.config.get('TESTING')
        app.config['TESTING'] = False
        try:
            with patch.object(BlockchainV2Service, 'for_election', return_value=fake_svc):
                ok, _msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        finally:
            app.config['TESTING'] = prev_testing

        assert ok is False
        assert details['permanent'] is True
        assert details['error_code'] == 'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT'
        assert details['finalized_on_chain'] is False

        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'CLOSED'
        assert refreshed.closed_at is not None
        assert refreshed.finalized_at is None


def test_lifecycle_worker_exponential_backoff_and_recovery(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_WORKER_BACKOFF',
            title='Backoff Election',
            status='OPEN',
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(minutes=10),
            candidate_count=2,
            eligible_count=5,
            v2_priv_key_1='111',
            v2_priv_key_2='222',
        )
        db.session.add(el)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app, initial_backoff=10.0, max_backoff=25.0)

        with patch.object(
            V2ElectionManager,
            'close_and_finalize_election',
            return_value=(False, 'Transient RPC timeout', {'permanent': False}),
        ) as mock_close:
            # Tick 1 -> attempts once, schedules 10s backoff
            r1 = worker.tick()
            assert mock_close.call_count == 1
            assert r1['finalized'] == 0
            st1 = worker.get_failure_state('CLOSE', el.id)
            assert st1['status'] == 'RETRYING'
            assert st1['backoff_seconds'] == 10.0

            # Tick 2 immediately -> skipped due to backoff
            r2 = worker.tick()
            assert mock_close.call_count == 1
            assert r2['skipped_backoff'] == 1

            # Push next_retry_at into the past -> Tick 3 retries, schedules 20s backoff
            worker._failure_state[('CLOSE', el.id)]['next_retry_at'] = datetime.utcnow() - timedelta(seconds=1)
            worker.tick()
            assert mock_close.call_count == 2
            assert worker.get_failure_state('CLOSE', el.id)['backoff_seconds'] == 20.0

            # Push next_retry_at into the past -> Tick 4 retries, backoff caps at max_backoff=25s
            worker._failure_state[('CLOSE', el.id)]['next_retry_at'] = datetime.utcnow() - timedelta(seconds=1)
            worker.tick()
            assert mock_close.call_count == 3
            assert worker.get_failure_state('CLOSE', el.id)['backoff_seconds'] == 25.0

        # Next retry after recovery succeeds and clears failure state
        worker._failure_state[('CLOSE', el.id)]['next_retry_at'] = datetime.utcnow() - timedelta(seconds=1)
        with patch.object(
            V2ElectionManager,
            'close_and_finalize_election',
            return_value=(True, 'Finalized', {'tallies': [1, 0], 'finalized_on_chain': True}),
        ):
            r_ok = worker.tick()
            assert r_ok['finalized'] == 1
            assert worker.get_failure_state('CLOSE', el.id) == {}


def test_lifecycle_worker_permanent_failure_terminal_state(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_WORKER_PERM_FAIL',
            title='Permanent Failure Election',
            status='CLOSED',
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(minutes=5),
            closed_at=now - timedelta(minutes=5),
            candidate_count=2,
            eligible_count=5,
            v2_priv_key_1='111',
            v2_priv_key_2='222',
        )
        db.session.add(el)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app, initial_backoff=1.0, max_backoff=10.0)

        with patch.object(
            V2ElectionManager,
            'close_and_finalize_election',
            return_value=(
                False,
                'Zero-vote election unsupported on deployed contract',
                {'permanent': True, 'error_code': 'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT'},
            ),
        ) as mock_close:
            r1 = worker.tick()
            assert mock_close.call_count == 1
            assert r1['permanent_failures'] == 1
            st = worker.get_failure_state('CLOSE', el.id)
            assert st['status'] == 'PERMANENT_FAILURE'
            assert st['permanent'] is True

            # Subsequent ticks must stop retrying permanent failure
            r2 = worker.tick()
            r3 = worker.tick()
            assert mock_close.call_count == 1
            assert r2['permanent_failures'] == 1
            assert r3['permanent_failures'] == 1

            perm_events = AuditEvent.query.filter_by(
                event_type='ELECTION_LIFECYCLE_PERMANENT_FAILURE'
            ).all()
            assert len(perm_events) == 1


# =============================================================================
# Fix 4 — Offline / Test Close Validation & Closed Metadata
# =============================================================================

def test_offline_close_blocked_before_end_time_directly(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_OFFLINE_EARLY',
            title='Offline Early Close Blocked',
            status='OPEN',
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=3),
            candidate_count=2,
            eligible_count=10,
        )
        db.session.add(el)
        db.session.commit()

        ok, msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        assert ok is False
        assert details['error_code'] == 'INVALID_LIFECYCLE_TRANSITION'
        assert 'Cannot close election before end_time' in msg
        assert 'EMERGENCY_CLOSE' in msg

        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'OPEN'
        assert refreshed.closed_at is None


def test_offline_close_after_end_time_sets_closed_at_never_finalized(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_OFFLINE_EXPIRED',
            title='Offline Expired Close',
            status='OPEN',
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(minutes=5),
            candidate_count=2,
            eligible_count=10,
        )
        db.session.add(el)
        db.session.commit()

        ok, msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        assert ok is True
        assert 'not finalized on-chain' in msg
        assert details['finalized_on_chain'] is False
        assert details['offline'] is True

        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'CLOSED'
        assert refreshed.closed_at is not None
        assert refreshed.finalized_at is None


def test_online_close_blocked_before_end_time_without_emergency_approval(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_ONLINE_EARLY',
            title='Online Early Close Blocked',
            status='OPEN',
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            candidate_count=2,
            eligible_count=10,
        )
        db.session.add(el)
        db.session.commit()

        fake_svc = _make_fake_online_service(total_active=0, state=4)
        prev_testing = app.config.get('TESTING')
        app.config['TESTING'] = False
        try:
            with patch.object(BlockchainV2Service, 'for_election', return_value=fake_svc):
                ok, msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        finally:
            app.config['TESTING'] = prev_testing

        assert ok is False
        assert details['error_code'] == 'INVALID_LIFECYCLE_TRANSITION'
        assert 'EMERGENCY_CLOSE' in msg
        assert fake_svc.close_voting_called is False

        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'OPEN'
        assert refreshed.closed_at is None


def test_online_finalize_allowed_when_emergency_close_approved(app, db):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_EMERGENCY_APPROVED',
            title='Emergency Approved V2 Close',
            status='OPEN',
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=5),
            candidate_count=2,
            eligible_count=10,
            v2_priv_key_1=str(generate_secure_scalar()),
            v2_priv_key_2=str(generate_secure_scalar()),
        )
        o1, _ = AdminAuthService.create_admin(
            admin_id='OFF_10A_1',
            name='Officer 10A One',
            email='off10a1@election.local',
            password='ValidAdminPassword123!',
            role='OFFICER',
        )
        o2, _ = AdminAuthService.create_admin(
            admin_id='OFF_10A_2',
            name='Officer 10A Two',
            email='off10a2@election.local',
            password='ValidAdminPassword456!',
            role='OFFICER',
        )
        db.session.add(el)
        db.session.add(
            ApprovalRequest(
                election_id=el.election_id,
                action_type='EMERGENCY_CLOSE',
                payload_hash='e' * 64,
                requester_id=o1.id,
                approver_id=o2.id,
                status='APPROVED',
                expires_at=now + timedelta(hours=1),
            )
        )
        db.session.commit()

        fake_svc = _make_fake_online_service(total_active=0, state=4)
        # Simulate close_voting transitioning state 4 -> 6 cleanly
        class _TransitioningContract:
            address = '0x5FbDB2315678afecb367f032d93F642f64180aa3'

            class functions:
                @staticmethod
                def state():
                    return _FakeCall(6 if fake_svc.close_voting_called else 4)

                @staticmethod
                def candidateCount():
                    return _FakeCall(2)

                @staticmethod
                def totalActiveBallots():
                    return _FakeCall(0)

        fake_svc.get_contract = lambda: _TransitioningContract()

        prev_testing = app.config.get('TESTING')
        app.config['TESTING'] = False
        try:
            with patch.object(BlockchainV2Service, 'for_election', return_value=fake_svc):
                ok, _msg, details = V2ElectionManager.close_and_finalize_election(el.id)
        finally:
            app.config['TESTING'] = prev_testing

        assert ok is True
        assert fake_svc.close_voting_called is True
        assert fake_svc.finalize_zero_called is True
        assert details['tallies'] == [0, 0]
        assert details['finalized_on_chain'] is True
        refreshed = db.session.get(Election, el.id)
        assert refreshed.status == 'FINALIZED'
        assert refreshed.closed_at is not None
        assert refreshed.finalized_at is not None
