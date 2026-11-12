"""
Phase 1 Stabilization Tests: V2 Ballot History, Superseded Tracking, & Merkle Consistency.
Tests (Mocked BlockchainV2Service boundary; real Flask routes & SQLite DB):
- First vote (seq=1 CONFIRMED, superseded=False, receipt_code assigned)
- Second vote replacing first (seq=1 superseded=True, seq=2 CONFIRMED, active count=1)
- Third vote replacing second (seq=1 & seq=2 superseded=True, seq=3 CONFIRMED, active count=1)
- Failed revote (seq=2 FAILED preserves seq=1 CONFIRMED, active count=1)
- Duplicate submission (seq=1 re-cast rejected 400 INVALID_SEQUENCE_ORDER)
- Uncertain transaction (BroadcastUncertainError -> SUBMITTED/QUEUED, prior confirmed intact, next blocked 409)
- Multiple different voters (independent superseded tracking per voter)
- Authoritative active ballot count & Merkle leaf count for finalized elections
- Existing finalized election pre-computed merkle_root preserved unmodified
"""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from eth_account import Account

from app.extensions import db
from app.models import Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.ballot_record_v2 import (
    BallotQueueV2,
    compute_v2_ballot_leaf_hash,
    get_active_v2_election_ballots,
    get_latest_confirmed_v2_ballot,
    get_latest_v2_attempt,
)
from app.models.roll import ElectoralRoll
from app.security.merkle import MerkleTree
from app.security.pseudonym import derive_pseudonym
from app.services.blockchain_v2_service import BlockchainV2Service, BroadcastUncertainError
from app.services.bn254_crypto import G, generate_ballot_proof, generate_secure_scalar, point_add, point_mul
from app.services.v2_election_manager import V2ElectionManager


def _create_voter(app, username, voter_id):
    test_key = '0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d'
    app.config['RELAYER_PRIVATE_KEY'] = test_key
    app.config['RELAYER_ACCOUNT'] = Account.from_key(test_key).address

    u = User(
        username=username,
        email=f'{username}@example.edu',
        voter_id=voter_id,
        password_hash='argon2_test_hash',
        is_active=True,
        is_verified=True,
    )
    db.session.add(u)
    roll = ElectoralRoll(
        usn=voter_id,
        college_email=f'{username}@example.edu',
        full_name=username,
        is_eligible=True,
    )
    db.session.add(roll)
    db.session.commit()

    now = datetime.utcnow()
    sid = f'sid_{username}_{now.timestamp()}'
    sess = AuthSession(
        session_id=sid,
        user_id=u.id,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        idle_expires_at=now + timedelta(minutes=30),
        last_activity=now,
        revoked=False,
    )
    db.session.add(sess)
    db.session.commit()
    return u.id, sid


def _issue_va(user_id, election_id, sid):
    now = datetime.utcnow()
    va = VotingAuthorization(
        user_id=user_id,
        election_id=election_id,
        session_id=sid,
        authorized=True,
        wallet_verified=True,
        face_verified=True,
        consumed=False,
        expires_at=now + timedelta(hours=1),
    )
    db.session.add(va)
    db.session.commit()
    return va.id


def _build_ballot_payload(election_id, user_id, sequence, candidate=0):
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y_joint = point_add(point_mul(G, s1), point_mul(G, s2))
    pseud = derive_pseudonym(user_id, election_id)
    proof_bundle = generate_ballot_proof(
        selected_candidate=candidate,
        candidate_count=2,
        context={
            'election_id': election_id,
            'pseudonym': pseud,
            'sequence': sequence,
            'joint_pub_key': {'x': Y_joint[0], 'y': Y_joint[1]},
        },
        verifier_address='0x8A791620dd6260079BF849Dc5567aDC3F2FdC318',
        chain_id=1337,
    )
    return {
        'election_id': election_id,
        'sequence': sequence,
        'ciphertexts': proof_bundle['ciphertexts'],
        'proof': proof_bundle['proof'],
        'contract_address': '0x610178dA211FEF7D417bC0e6FeD39F05609AD788',
    }


@pytest.fixture
def open_v2_election(app):
    with app.app_context():
        app.config['REVOTE_COOLDOWN_SECONDS'] = 0
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_PHASE1_TEST',
            title='Phase 1 Consistency Election',
            status='OPEN',
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=12),
            candidate_count=2,
            eligible_count=100,
            max_ballots=3,
            v2_priv_key_1=str(generate_secure_scalar()),
            v2_priv_key_2=str(generate_secure_scalar()),
        )
        db.session.add(el)
        db.session.commit()
        return el.id


def test_phase1_revote_superseding_and_merkle_tree(app, client, open_v2_election):
    with app.app_context():
        uid1, sid1 = _create_voter(app, 'voter_one', 'USN_V1')
        uid2, sid2 = _create_voter(app, 'voter_two', 'USN_V2')

        # 1. First vote (Voter 1, seq=1)
        _issue_va(uid1, open_v2_election, sid1)
        with client.session_transaction() as sess:
            sess['session_id'] = sid1
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xtx1', 'block_number': 10}):
            r1 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid1, 1, 0))
            assert r1.status_code == 200
            assert r1.get_json()['receipt_code'].startswith(f'REC-{open_v2_election}-')

        b1 = BallotQueueV2.query.filter_by(election_id=open_v2_election, sequence=1).first()
        assert b1.state == 'CONFIRMED'
        assert b1.superseded is False

        # 2. Duplicate submission for seq=1 rejected cleanly without mutating b1
        _issue_va(uid1, open_v2_election, sid1)
        r_dup = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid1, 1, 1))
        assert r_dup.status_code == 400
        assert r_dup.get_json()['error'] == 'INVALID_SEQUENCE_ORDER'

        # 3. Second vote replaces first
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xtx2', 'block_number': 11}):
            r2 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid1, 2, 1))
            assert r2.status_code == 200

        db.session.refresh(b1)
        b2 = BallotQueueV2.query.filter_by(election_id=open_v2_election, sequence=2).first()
        assert b1.superseded is True
        assert b2.state == 'CONFIRMED'
        assert b2.superseded is False

        # 4. Third vote replaces second
        _issue_va(uid1, open_v2_election, sid1)
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xtx3', 'block_number': 12}):
            r3 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid1, 3, 0))
            assert r3.status_code == 200

        db.session.refresh(b2)
        b3 = BallotQueueV2.query.filter_by(election_id=open_v2_election, sequence=3).first()
        assert b1.superseded is True
        assert b2.superseded is True
        assert b3.superseded is False

        pseud1 = derive_pseudonym(uid1, open_v2_election)
        assert get_latest_confirmed_v2_ballot(open_v2_election, pseud1).id == b3.id

        # 5. Multiple voters: Voter 2 casts seq=1
        _issue_va(uid2, open_v2_election, sid2)
        with client.session_transaction() as sess:
            sess['session_id'] = sid2
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xtx4', 'block_number': 13}):
            rv2 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid2, 1, 1))
            assert rv2.status_code == 200

        # Active ballots across election: strictly 2 (1 per voter), despite 4 total rows
        active = get_active_v2_election_ballots(open_v2_election)
        assert len(active) == 2
        assert {b.pseudonym for b in active} == {pseud1, derive_pseudonym(uid2, open_v2_election)}

        # Finalize election Merkle tree in offline/test mode helper verification
        el = db.session.get(Election, open_v2_election)
        leaves = [compute_v2_ballot_leaf_hash(b) for b in active]
        expected_tree = MerkleTree(leaves, sort_leaves=True)
        assert expected_tree.leaf_count == 2
        el.merkle_root = expected_tree.root
        el.status = 'FINALIZED'
        db.session.commit()

        # Verify V2ElectionManager preserves pre-existing finalized merkle_root (historical protection)
        with patch.object(BlockchainV2Service, 'for_election') as mock_svc:
            mock_svc.return_value.get_web3.side_effect = Exception('offline')
            ok, _msg, _data = V2ElectionManager.close_and_finalize_election(open_v2_election)
            assert ok is True
        db.session.refresh(el)
        assert el.merkle_root == expected_tree.root


def test_phase1_failed_and_uncertain_revotes_preserve_prior_confirmed(app, client, open_v2_election):
    with app.app_context():
        uid, sid = _create_voter(app, 'voter_err', 'USN_VERR')
        pseud = derive_pseudonym(uid, open_v2_election)

        with client.session_transaction() as sess:
            sess['session_id'] = sid

        # Seq 1 succeeds
        _issue_va(uid, open_v2_election, sid)
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xok1', 'block_number': 20}):
            assert client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid, 1, 0)).status_code == 200

        # Seq 2 fails on-chain (hard exception -> FAILED)
        _issue_va(uid, open_v2_election, sid)
        with patch.object(BlockchainV2Service, 'cast_ballot', side_effect=RuntimeError('EVM_REVERT')):
            rf = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid, 2, 1))
            assert rf.status_code == 500

        active = get_active_v2_election_ballots(open_v2_election)
        assert len(active) == 1
        assert active[0].sequence == 1
        assert active[0].superseded is False
        assert get_latest_confirmed_v2_ballot(open_v2_election, pseud).sequence == 1
        assert get_latest_v2_attempt(open_v2_election, pseud).state == 'FAILED'

        # Another voter gets BroadcastUncertainError on seq 2 -> SUBMITTED; prior seq 1 stays active, next cast blocked 409
        uid_u, sid_u = _create_voter(app, 'voter_unc', 'USN_VUNC')
        pseud_u = derive_pseudonym(uid_u, open_v2_election)
        with client.session_transaction() as sess:
            sess['session_id'] = sid_u

        _issue_va(uid_u, open_v2_election, sid_u)
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xok_u1', 'block_number': 21}):
            assert client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid_u, 1, 0)).status_code == 200

        _issue_va(uid_u, open_v2_election, sid_u)
        with patch.object(BlockchainV2Service, 'cast_ballot', side_effect=BroadcastUncertainError('RPC timeout', tx_hash='0xunc2')):
            ru = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid_u, 2, 1))
            assert ru.status_code == 504
            assert ru.get_json()['status'] == 'SUBMITTED'

        assert get_latest_confirmed_v2_ballot(open_v2_election, pseud_u).sequence == 1
        assert get_latest_confirmed_v2_ballot(open_v2_election, pseud_u).superseded is False
        assert get_latest_v2_attempt(open_v2_election, pseud_u).state == 'SUBMITTED'

        _issue_va(uid_u, open_v2_election, sid_u)
        r_blk = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(open_v2_election, uid_u, 2, 1))
        assert r_blk.status_code == 409
        assert r_blk.get_json()['error'] == 'BALLOT_TRANSACTION_IN_FLIGHT'

