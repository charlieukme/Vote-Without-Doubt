"""
Phase 2 Stabilization Tests: Official Receipt Generation, Status Parity, & Inclusion Proofs.
Covers:
- V2 ballot cast -> receipt_code persisted & returned cleanly without leaking tx_hash in receipt
- /api/voting/status and /api/v2/voting/status parity across CONFIRMED, FAILED, and SUBMITTED/UNCERTAIN attempts
- /api/verification/receipt/<code> HMAC verification and settlement details
- /api/verification/receipt/<code>/inclusion-proof for active V2 leaf vs superseded leaf vs unsettled ballot
- MerkleTree.verify_proof end-to-end validation over V2 finalized Merkle root
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from eth_account import Account

from app.extensions import db
from app.models import Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.ballot_record_v2 import BallotQueueV2
from app.models.roll import ElectoralRoll
from app.security.merkle import verify_inclusion_proof
from app.security.pseudonym import derive_pseudonym
from app.services.blockchain_v2_service import BlockchainV2Service
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
    db.session.add(
        ElectoralRoll(
            usn=voter_id,
            college_email=f'{username}@example.edu',
            full_name=username,
            is_eligible=True,
        )
    )
    db.session.commit()

    now = datetime.utcnow()
    sid = f'sid_{username}_{now.timestamp()}'
    db.session.add(
        AuthSession(
            session_id=sid,
            user_id=u.id,
            created_at=now,
            expires_at=now + timedelta(hours=2),
            idle_expires_at=now + timedelta(minutes=30),
            last_activity=now,
            revoked=False,
        )
    )
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
def phase2_election(app):
    with app.app_context():
        app.config['REVOTE_COOLDOWN_SECONDS'] = 0
        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_PHASE2_TEST',
            title='Phase 2 Receipt Verification Election',
            status='OPEN',
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=12),
            candidate_count=2,
            eligible_count=50,
            max_ballots=3,
            v2_priv_key_1=str(generate_secure_scalar()),
            v2_priv_key_2=str(generate_secure_scalar()),
        )
        db.session.add(el)
        db.session.commit()
        return el.id


def test_phase2_receipt_verification_and_inclusion_proof(app, client, phase2_election):
    with app.app_context():
        uid1, sid1 = _create_voter(app, 'p2_voter1', 'USN_P2_1')
        uid2, sid2 = _create_voter(app, 'p2_voter2', 'USN_P2_2')

        # Cast seq=1 then revote seq=2 for voter 1
        _issue_va(uid1, phase2_election, sid1)
        with client.session_transaction() as sess:
            sess['session_id'] = sid1

        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xphase2tx1', 'block_number': 21}):
            r1 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(phase2_election, uid1, 1, 0))
            assert r1.status_code == 200
            rec1 = r1.get_json()['receipt_code']

        _issue_va(uid1, phase2_election, sid1)
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xphase2tx2', 'block_number': 22}):
            r2 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(phase2_election, uid1, 2, 1))
            assert r2.status_code == 200
            rec2 = r2.get_json()['receipt_code']
            assert rec2 != rec1

        # Cast seq=1 for voter 2 so tree has 2 leaves
        _issue_va(uid2, phase2_election, sid2)
        with client.session_transaction() as sess:
            sess['session_id'] = sid2

        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xphase2tx3', 'block_number': 23}):
            r3 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(phase2_election, uid2, 1, 0))
            assert r3.status_code == 200
            rec3 = r3.get_json()['receipt_code']

        # Verify /voting/status and /v2/voting/status parity for voter 1
        with client.session_transaction() as sess:
            sess['session_id'] = sid1
        st_v1 = client.get(f'/api/voting/status?election_id={phase2_election}')
        st_v2 = client.get(f'/api/v2/voting/status?election_id={phase2_election}')
        assert st_v1.status_code == 200 and st_v2.status_code == 200
        j1, j2 = st_v1.get_json(), st_v2.get_json()
        assert j1['has_ballot'] is True
        assert j1['status'] in ('CONFIRMED', 'FINALIZED')
        assert j2['state'] == 'CONFIRMED'
        assert j1['sequence'] == j2['sequence'] == 2
        assert j1['submissions_used'] == j2['submissions_used'] == 2
        assert j1['receipt']['receipt_code'] == j2['receipt']['receipt_code'] == rec2
        assert 'tx_hash' not in j1['receipt']
        assert 'tx_hash' not in j2['receipt']

        # Receipt HMAC lookup (offline node -> on_chain_checked=False, online mocked -> on_chain_confirmed=True)
        vr_offline = client.get(f'/api/verification/receipt/{rec2}')
        assert vr_offline.status_code == 200
        vr_off_json = vr_offline.get_json()
        assert vr_off_json['status'] == 'VALID'
        assert vr_off_json['hmac_verified'] is True
        assert vr_off_json['block_number'] == 22

        class _FakeW3:
            def is_connected(self):
                return True

        class _FakeCall:
            def __init__(self, val):
                self._val = val

            def call(self):
                return self._val

        class _FakeContract:
            class functions:
                @staticmethod
                def voterSequence(_pseud_bytes):
                    return _FakeCall(2)

        with patch('app.services.verification_service.VerificationService._resolve_target_contract', return_value='0x610178dA211FEF7D417bC0e6FeD39F05609AD788'):
            with patch.object(BlockchainV2Service, 'get_web3', return_value=_FakeW3()):
                with patch.object(BlockchainV2Service, 'get_contract', return_value=_FakeContract()):
                    vr = client.get(f'/api/verification/receipt/{rec2}')
                    assert vr.status_code == 200
                    vr_json = vr.get_json()
                    assert vr_json['status'] == 'VALID'
                    assert vr_json['on_chain_checked'] is True
                    assert vr_json['on_chain_confirmed'] is True
                    assert vr_json['block_number'] == 22

        # Before finalization -> inclusion proof reports pending / 400 BALLOT_NOT_SETTLED
        ip_pending = client.get(f'/api/verification/receipt/{rec2}/inclusion-proof')
        assert ip_pending.status_code == 400
        assert ip_pending.get_json()['data']['status'] == 'BALLOT_NOT_SETTLED'

        # Close election & finalize Merkle root via real V2ElectionManager path (mocking chain RPC boundary at state=7)
        election = db.session.get(Election, phase2_election)
        election.status = 'CLOSED'
        election.end_time = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

        class _FinalizeW3:
            class eth:
                chain_id = 1337

            def is_connected(self):
                return True

        class _FinalizeContract:
            address = '0x610178dA211FEF7D417bC0e6FeD39F05609AD788'

            class functions:
                @staticmethod
                def state():
                    return _FakeCall(7)

                @staticmethod
                def candidateCount():
                    return _FakeCall(2)

        class _FinalizeService:
            def get_web3(self):
                return _FinalizeW3()

            def get_contract(self):
                return _FinalizeContract()

            def resolve_relayer_credentials(self):
                return ('0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d', '0x1111111111111111111111111111111111111111')

            def get_final_tally(self, _idx, contract_address=None):
                return 1

        prev_testing = app.config.get('TESTING')
        app.config['TESTING'] = False
        try:
            with patch.object(BlockchainV2Service, 'for_election', return_value=_FinalizeService()):
                ok, _msg, _data = V2ElectionManager.close_and_finalize_election(phase2_election)
                assert ok is True
        finally:
            app.config['TESTING'] = prev_testing
        db.session.refresh(election)
        assert election.merkle_root is not None

        # Superseded receipt -> explicit BALLOT_SUPERSEDED 400
        ip_sup = client.get(f'/api/verification/receipt/{rec1}/inclusion-proof')
        assert ip_sup.status_code == 400
        assert ip_sup.get_json()['data']['status'] == 'BALLOT_SUPERSEDED'

        # Active receipts -> valid Merkle inclusion proof verifying against stored root
        for active_rec in (rec2, rec3):
            ip_ok = client.get(f'/api/verification/receipt/{active_rec}/inclusion-proof')
            assert ip_ok.status_code == 200
            proof_data = ip_ok.get_json()
            assert proof_data['verified'] is True
            assert proof_data['status'] == 'VALID INCLUSION PROOF'
            assert proof_data['merkle_root'] == election.merkle_root
            assert proof_data['total_leaves'] == 2
            ok_proof, msg_proof = verify_inclusion_proof(
                proof_data['commitment'],
                proof_data['merkle_root'],
                proof_data['audit_path'],
            )
            assert ok_proof is True
            assert msg_proof == 'VALID INCLUSION PROOF'


def test_phase2_failed_and_submitted_attempts_preserve_confirmed_receipt(app, client, phase2_election):
    with app.app_context():
        uid, sid = _create_voter(app, 'p2_retry_voter', 'USN_P2_RETRY')
        with client.session_transaction() as sess:
            sess['session_id'] = sid

        _issue_va(uid, phase2_election, sid)
        with patch.object(BlockchainV2Service, 'cast_ballot', return_value={'status': 1, 'tx_hash': '0xp2c1', 'block_number': 41}):
            r1 = client.post('/api/v2/voting/cast-ballot', json=_build_ballot_payload(phase2_election, uid, 1, 0))
            assert r1.status_code == 200
            rec1 = r1.get_json()['receipt_code']

        # Simulated failed seq=2 attempt after cooldown elapsed
        pseud = derive_pseudonym(uid, phase2_election)
        confirmed_b1 = BallotQueueV2.query.filter_by(election_id=phase2_election, pseudonym=pseud, sequence=1).first()
        confirmed_b1.tx_confirmed_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.add(
            BallotQueueV2(
                election_id=phase2_election,
                pseudonym=pseud,
                sequence=2,
                ciphertexts_json='[]',
                proof_json='{}',
                state='FAILED',
                error='RPC reverted test',
            )
        )
        db.session.commit()

        s_v1 = client.get(f'/api/voting/status?election_id={phase2_election}').get_json()
        s_v2 = client.get(f'/api/v2/voting/status?election_id={phase2_election}').get_json()
        assert s_v1['status'] == 'FAILED'
        assert s_v1['active_sequence'] == 1
        assert s_v1['submissions_used'] == 1
        assert s_v1['next_sequence'] == 2
        assert s_v1['retry_allowed'] is True
        assert s_v1['receipt']['receipt_code'] == rec1
        assert s_v2['submissions_used'] == 1
        assert s_v2['receipt']['receipt_code'] == rec1

        # Simulated in-flight SUBMITTED attempt
        latest_failed = BallotQueueV2.query.filter_by(election_id=phase2_election, pseudonym=pseud, sequence=2).first()
        latest_failed.state = 'SUBMITTED'
        db.session.commit()

        s_sub = client.get(f'/api/voting/status?election_id={phase2_election}').get_json()
        assert s_sub['status'] == 'SUBMITTED'
        assert s_sub['retry_allowed'] is False
        assert s_sub['submissions_used'] == 1
        assert s_sub['receipt']['receipt_code'] == rec1
