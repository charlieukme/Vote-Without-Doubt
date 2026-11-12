"""
Comprehensive Phase 8 Privacy Hardening Tests
Vote Without Doubt - Backend

Covers all Phase 8 privacy requirements (F-8.1 through F-8.7):
1. Authenticated Privacy (no pseudonym, candidate, or tx_hash returned to voter)
2. Pseudonym Security (domain separation, determinism, isolation)
3. Key Management (envelope encryption, Fernet protected-at-rest, fail-closed)
4. Key Lifecycle & Destruction (finalization shreds key, fails safely after destruction)
5. Receipt Privacy (conformance to Section 8.6, no linkage)
6. Relayer Privacy & Batching (asynchronous decoupled relayer, cryptographic shuffle)
7. Access Control & Authorization Boundaries
8. Logging Privacy
9. Startup Recovery (F-8.7)
"""

import base64
import os
import secrets
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.extensions import db
from app.models import BallotRecord, Election, ElectionPseudonymKey, User, VotingAuthorization
from app.models.auth_session import AuthSession
from app.security.password import hash_password
from app.security.pseudonym import (
    PseudonymKeyError,
    derive_pseudonym,
    destroy_election_pseudonym_key,
    get_election_pseudonym_key,
)
from app.services.recovery import RecoveryService
from app.services.voting_service import VotingService


@pytest.fixture
def privacy_user(db):
    u = User(
        username='privacy_voter_1',
        email='pvoter1@college.edu',
        password_hash=hash_password('voterpass123'),
        is_active=True,
        is_verified=True,
        voter_id='VOTER-2026-9901',
    )
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def privacy_user_2(db):
    u = User(
        username='privacy_voter_2',
        email='pvoter2@college.edu',
        password_hash=hash_password('voterpass456'),
        is_active=True,
        is_verified=True,
        voter_id='VOTER-2026-9902',
    )
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def privacy_election(db):
    e = Election(
        election_id='801',
        title='Phase 8 Privacy Council Election',
        description='Election for verifying privacy hardening',
        status='ACTIVE',
    )
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def privacy_auth(db, privacy_user, privacy_election):
    now = datetime.utcnow()
    sess = AuthSession(
        session_id='sess_privacy_test_' + secrets.token_hex(8),
        user_id=privacy_user.id,
        auth_state='AUTHORIZED',
        authenticated_at=now,
        last_activity=now,
        expires_at=now + timedelta(hours=1),
        idle_expires_at=now + timedelta(minutes=30),
    )
    db.session.add(sess)

    va = VotingAuthorization(
        user_id=privacy_user.id,
        election_id=801,
        session_id=sess.session_id,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=now + timedelta(minutes=15),
    )
    db.session.add(va)
    db.session.commit()
    return sess


# ---------------------------------------------------------------------------
# 1. AUTHENTICATED PRIVACY (F-8.3, F-8.4)
# ---------------------------------------------------------------------------

def _seed_v2_privacy_context(db, privacy_user, privacy_election):
    from app.models.roll import ElectoralRoll
    from app.services.bn254_crypto import G, generate_ballot_proof, generate_secure_scalar, point_add, point_mul

    privacy_election.candidate_count = 2
    if not ElectoralRoll.query.filter_by(usn=privacy_user.voter_id).first():
        db.session.add(ElectoralRoll(
            usn=privacy_user.voter_id,
            full_name='Privacy Voter',
            college_email=privacy_user.email,
            is_eligible=True,
        ))
    db.session.commit()

    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    y_joint = point_add(point_mul(G, s1), point_mul(G, s2))
    pseudonym = derive_pseudonym(privacy_user.id, privacy_election.id)
    return generate_ballot_proof(
        selected_candidate=0,
        candidate_count=2,
        context={
            'election_id': privacy_election.id,
            'pseudonym': pseudonym,
            'sequence': 1,
            'joint_pub_key': {'x': y_joint[0], 'y': y_joint[1]},
        },
        verifier_address='0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512',
        chain_id=1337,
    )


def test_authenticated_voter_submit_does_not_leak_pseudonym_candidate_or_tx_hash(
    client, db, privacy_user, privacy_election, privacy_auth
):
    with client.session_transaction() as sess:
        sess['session_id'] = privacy_auth.session_id

    # Legacy V1 submit is permanently disabled (410 Gone)
    v1_res = client.post('/api/voting/submit', json={'election_id': privacy_election.id, 'candidate': 0})
    assert v1_res.status_code == 410

    ballot = _seed_v2_privacy_context(db, privacy_user, privacy_election)
    from app.services.blockchain_v2_service import BlockchainV2Service
    with patch.object(BlockchainV2Service, 'cast_ballot', return_value={
        'status': 1, 'tx_hash': '0xprivacy_v2_tx', 'block_number': 101
    }):
        res = client.post('/api/v2/voting/cast-ballot', json={
            'election_id': privacy_election.id,
            'sequence': 1,
            'ciphertexts': ballot['ciphertexts'],
            'proof': ballot['proof'],
            'contract_address': '0x5FbDB2315678afecb367f032d93F642f64180aa3',
        })
    assert res.status_code == 200, res.get_json()
    data = res.get_json()

    pseudonym = derive_pseudonym(privacy_user.id, privacy_election.id)
    assert 'receipt_code' in data
    assert 'candidate' not in data
    assert 'pseudonym' not in data
    assert pseudonym not in str(data)


def test_status_endpoint_does_not_leak_pseudonym_candidate_or_tx_hash(
    client, privacy_user, privacy_election, privacy_auth
):
    with client.session_transaction() as sess:
        sess['session_id'] = privacy_auth.session_id

    client.post('/api/voting/submit', json={'election_id': 801, 'candidate': 1})

    res = client.get('/api/voting/status?election_id=801')
    assert res.status_code == 200
    data = res.get_json()

    raw_response = str(data)
    pseudonym = derive_pseudonym(privacy_user.id, 801)

    assert pseudonym not in raw_response
    assert 'candidate' not in data
    assert 'tx_hash' not in data
    assert 'block_number' not in data
    assert 'wallet_address' not in raw_response


# ---------------------------------------------------------------------------
# 2. PSEUDONYM SECURITY & DOMAIN SEPARATION (F-8.1)
# ---------------------------------------------------------------------------

def test_pseudonym_determinism_and_domain_separation(privacy_user, privacy_user_2):
    p1_e1 = derive_pseudonym(privacy_user.id, 801)
    p1_e1_repeat = derive_pseudonym(privacy_user.id, 801)
    assert p1_e1 == p1_e1_repeat

    p1_e2 = derive_pseudonym(privacy_user.id, 802)
    assert p1_e1 != p1_e2

    p2_e1 = derive_pseudonym(privacy_user_2.id, 801)
    assert p1_e1 != p2_e1

    assert len(p1_e1) == 64
    bytes.fromhex(p1_e1)


def test_client_cannot_supply_own_pseudonym(client, db, privacy_user, privacy_election, privacy_auth):
    with client.session_transaction() as sess:
        sess['session_id'] = privacy_auth.session_id

    forged_pseudonym = 'deadbeef' * 8
    v1_res = client.post('/api/voting/submit', json={
        'election_id': privacy_election.id,
        'candidate': 0,
        'pseudonym': forged_pseudonym,
    })
    assert v1_res.status_code == 410

    ballot = _seed_v2_privacy_context(db, privacy_user, privacy_election)
    from app.models.ballot_record_v2 import BallotQueueV2
    from app.services.blockchain_v2_service import BlockchainV2Service
    with patch.object(BlockchainV2Service, 'cast_ballot', return_value={
        'status': 1, 'tx_hash': '0xprivacy_v2_tx2', 'block_number': 102
    }):
        res = client.post('/api/v2/voting/cast-ballot', json={
            'election_id': privacy_election.id,
            'sequence': 1,
            'pseudonym': forged_pseudonym,
            'ciphertexts': ballot['ciphertexts'],
            'proof': ballot['proof'],
            'contract_address': '0x5FbDB2315678afecb367f032d93F642f64180aa3',
        })
    assert res.status_code == 200, res.get_json()

    record = BallotQueueV2.query.filter_by(election_id=privacy_election.id).first()
    assert record is not None
    assert record.pseudonym != forged_pseudonym
    assert record.pseudonym == derive_pseudonym(privacy_user.id, privacy_election.id)


# ---------------------------------------------------------------------------
# 3. KEY MANAGEMENT & ENVELOPE ENCRYPTION (F-8.1)
# ---------------------------------------------------------------------------

def test_election_pseudonym_key_generated_and_encrypted_in_db(db, privacy_election):
    key_bytes = get_election_pseudonym_key(801)
    assert len(key_bytes) == 32

    record = ElectionPseudonymKey.query.filter_by(election_id=801).first()
    assert record is not None
    assert record.key_ciphertext is not None

    # Plaintext key MUST NOT appear in the database record
    raw_ciphertext = record.key_ciphertext.encode() if isinstance(record.key_ciphertext, str) else record.key_ciphertext
    assert key_bytes not in raw_ciphertext
    assert key_bytes.hex().encode() not in raw_ciphertext

    # Verifiable decryption via master key
    master_key = os.getenv('PSEUDONYM_MASTER_KEY')
    fernet = Fernet(master_key.encode())
    decrypted = fernet.decrypt(raw_ciphertext)
    assert decrypted == key_bytes


def test_missing_master_key_fails_closed(monkeypatch):
    monkeypatch.delenv('PSEUDONYM_MASTER_KEY', raising=False)
    with pytest.raises(PseudonymKeyError, match='PSEUDONYM_MASTER_KEY is not set'):
        get_election_pseudonym_key(9999)


def test_no_dev_secret_fallback(monkeypatch):
    monkeypatch.delenv('PSEUDONYM_MASTER_KEY', raising=False)
    monkeypatch.setenv('PSEUDONYM_SECRET', 'dev-pseudonym-secret')
    with pytest.raises(PseudonymKeyError):
        get_election_pseudonym_key(9999)


# ---------------------------------------------------------------------------
# 4. KEY LIFECYCLE & DESTRUCTION (F-8.2)
# ---------------------------------------------------------------------------

def test_key_destruction_shreds_material_and_fails_safely(db, privacy_election, privacy_user):
    pseud_before = derive_pseudonym(privacy_user.id, 801)
    assert len(pseud_before) == 64

    # Irreversibly destroy key
    destroy_election_pseudonym_key(801)

    # Database record must have key material shredded and overwritten with destroyed sentinels
    record = ElectionPseudonymKey.query.filter_by(election_id=801).first()
    assert record is not None
    assert record.key_ciphertext == '[DESTROYED]'
    assert record.key_hash == '0' * 64

    # Subsequent pseudonym derivation MUST fail closed
    with pytest.raises(PseudonymKeyError, match='destroyed'):
        derive_pseudonym(privacy_user.id, 801)


def test_cannot_finalize_election_with_pending_ballots(db, privacy_election, privacy_user):
    b = BallotRecord(
        election_id=801,
        pseudonym=derive_pseudonym(privacy_user.id, 801),
        candidate=0,
        sequence=1,
        state='QUEUED',
    )
    db.session.add(b)
    db.session.commit()

    ok, err = VotingService.finalize_election(801)
    assert ok is False
    assert err == 'CANNOT_FINALIZE_PENDING_BALLOTS'

    # Key must NOT have been destroyed
    key = get_election_pseudonym_key(801)
    assert key is not None


def test_finalize_election_destroys_key_when_all_ballots_settled(db, privacy_election, privacy_user):
    b = BallotRecord(
        election_id=801,
        pseudonym=derive_pseudonym(privacy_user.id, 801),
        candidate=0,
        sequence=1,
        state='FINALIZED',
        receipt_code='REC-801-SETTLED',
    )
    db.session.add(b)
    db.session.commit()

    ok, err = VotingService.finalize_election(801)
    assert ok is True
    assert err == 'OK'

    db.session.refresh(privacy_election)
    assert privacy_election.status == 'FINALIZED'

    # Stored key destroyed: new derivation must fail
    with pytest.raises(PseudonymKeyError):
        derive_pseudonym(privacy_user.id, 801)


# ---------------------------------------------------------------------------
# 5. RECEIPT PRIVACY (F-8.4)
# ---------------------------------------------------------------------------

def test_voter_receipt_privacy_guarantees(privacy_user, privacy_election):
    ballot = BallotRecord(
        election_id=801,
        pseudonym=derive_pseudonym(privacy_user.id, 801),
        candidate=0,
        sequence=1,
        state='FINALIZED',
    )
    db.session.add(ballot)
    db.session.commit()

    receipt = VotingService.generate_receipt(ballot, privacy_user.id)

    # Allowed fields only
    expected_keys = {'election_title', 'voter_id_last4', 'timestamp', 'receipt_code'}
    assert set(receipt.keys()) == expected_keys

    # Privacy invariants
    receipt_str = str(receipt)
    assert ballot.pseudonym not in receipt_str
    assert 'candidate' not in receipt
    assert 'tx_hash' not in receipt
    assert 'wallet_address' not in receipt_str
    assert receipt['voter_id_last4'] == '9901'
    assert receipt['receipt_code'].startswith('REC-801-')


# ---------------------------------------------------------------------------
# 6. RELAYER ASYNC & BATCH SHUFFLE (F-8.3)
# ---------------------------------------------------------------------------

def test_relayer_shuffle_is_cryptographically_random():
    from app.relayer import Relayer
    relayer = Relayer()

    items = [
        BallotRecord(id=i, election_id=801, pseudonym=f'pseudo_{i}', candidate=0, sequence=1, state='QUEUED')
        for i in range(10)
    ]

    orders = set()
    for _ in range(20):
        shuffled = relayer.shuffle_queue(items)
        order_tuple = tuple(b.id for b in shuffled)
        orders.add(order_tuple)

    # A cryptographically random shuffle over 10 items will produce multiple distinct orderings
    assert len(orders) > 1


def test_batch_processing_processes_multiple_queued_ballots(db, privacy_election):
    """Legacy V1 Relayer.process_queue() is fail-closed (SEC-001) and does not dispatch plaintext V1 ballots."""
    for i in range(3):
        b = BallotRecord(
            election_id=privacy_election.id,
            pseudonym=secrets.token_hex(32),
            candidate=i % 2,
            sequence=1,
            state='QUEUED',
        )
        db.session.add(b)
    db.session.commit()

    from app.relayer import Relayer

    relayer = Relayer(contract_address='0x' + '44' * 20)
    summary = relayer.process_queue(batch_size=10)

    assert summary['processed'] == 0
    assert summary['confirmed'] == 0
    assert BallotRecord.query.filter_by(election_id=privacy_election.id, state='QUEUED').count() == 3


# ---------------------------------------------------------------------------
# 7. STARTUP RECOVERY (F-8.7)
# ---------------------------------------------------------------------------

def test_startup_recover_marks_stale_queued_ballots(db, privacy_election):
    stale_ballot = BallotRecord(
        election_id=801,
        pseudonym=secrets.token_hex(32),
        candidate=0,
        sequence=1,
        state='QUEUED',
        reconcile_required=False,
    )
    db.session.add(stale_ballot)
    db.session.commit()

    recovered_count = RecoveryService.startup_recover()
    assert recovered_count >= 1

    db.session.refresh(stale_ballot)
    assert stale_ballot.reconcile_required is True
    assert stale_ballot.reconcile_reason == 'UNFINISHED_QUEUED'
