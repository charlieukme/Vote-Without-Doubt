"""
Tests for FIX 1: Client-Side Commitment Nonce Generation and Independent Voter Verification
Vote Without Doubt - Backend Test Suite
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from app.extensions import db
from app.models import BallotRecord, Election, User, VotingAuthorization
from app.security.merkle import (
    compute_ballot_commitment,
    generate_commitment_nonce,
    MerkleTree,
    verify_inclusion_proof,
)
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


@pytest.fixture
def voting_user(db):
    user = User(
        username='voter_fix1',
        email='voter_fix1@college.test',
        password_hash=hash_password('test-password-123'),
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
        title='Fix 1 Test Election',
        description='Test election for client-side commitment verification',
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


def _grant_voting_auth(db, user_id, election_id, session_id):
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
# 1. Commitment Formula Exact Specification
# ---------------------------------------------------------------------------

def test_commitment_formula_exact_sha256():
    """Verify exact formula SHA-256("VWD_BALLOT_COMMITMENT_V1:" + election_id + ":" + candidate_index + ":" + nonce)"""
    election_id = "1"
    candidate_index = 0
    nonce = bytes.fromhex("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    expected_preimage = (
        f"VWD_BALLOT_COMMITMENT_V1:{election_id}:{candidate_index}:".encode("utf-8") + nonce
    )
    expected_hash = hashlib.sha256(expected_preimage).hexdigest()

    computed_hash = compute_ballot_commitment(election_id, candidate_index, nonce)
    assert computed_hash == expected_hash
    assert len(computed_hash) == 64


# ---------------------------------------------------------------------------
# 2. Client-Side Commitment Submission & Validation
# ---------------------------------------------------------------------------

def test_client_submitted_commitment_accepted(voting_client, voting_user, active_election, auth_session):
    """Client generates 32-byte nonce & commitment, backend validates and accepts."""
    _grant_voting_auth(db, voting_user.id, active_election.id, auth_session.session_id)

    client_nonce_bytes = secrets.token_bytes(32)
    client_nonce_hex = client_nonce_bytes.hex()
    client_commitment = compute_ballot_commitment(active_election.election_id, 0, client_nonce_bytes)

    res = voting_client.post('/api/voting/submit', json={
        'election_id': active_election.election_id,
        'candidate': 0,
        'client_commitment': client_commitment,
        'client_nonce': client_nonce_hex,
    })
    assert res.status_code == 202
    data = res.get_json()
    assert data['status'] == 'QUEUED'

    # Verify database persistence of client-supplied values
    pseudonym = derive_pseudonym(voting_user.id, active_election.id)
    ballot = BallotRecord.query.filter_by(election_id=active_election.id, pseudonym=pseudonym).first()
    assert ballot is not None
    assert ballot.commitment == client_commitment
    assert ballot.commitment_nonce == client_nonce_hex


def test_client_submitted_commitment_mismatch_rejected(voting_client, voting_user, active_election, auth_session):
    """If client commitment doesn't match election_id, candidate, and nonce, reject with 400."""
    _grant_voting_auth(db, voting_user.id, active_election.id, auth_session.session_id)

    client_nonce_bytes = secrets.token_bytes(32)
    client_nonce_hex = client_nonce_bytes.hex()
    # Compute commitment for candidate 1, but submit candidate 0
    tampered_commitment = compute_ballot_commitment(active_election.election_id, 1, client_nonce_bytes)

    res = voting_client.post('/api/voting/submit', json={
        'election_id': active_election.election_id,
        'candidate': 0,
        'client_commitment': tampered_commitment,
        'client_nonce': client_nonce_hex,
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data['error'] == 'CLIENT_COMMITMENT_MISMATCH'

    # Authorization must NOT be consumed on rejection
    va = VotingAuthorization.query.filter_by(user_id=voting_user.id, election_id=active_election.id).first()
    assert va.consumed is False


def test_client_submitted_invalid_nonce_rejected(voting_client, voting_user, active_election, auth_session):
    """Nonce must be 32 bytes (64 hex characters)."""
    _grant_voting_auth(db, voting_user.id, active_election.id, auth_session.session_id)

    res = voting_client.post('/api/voting/submit', json={
        'election_id': active_election.election_id,
        'candidate': 0,
        'client_commitment': '0' * 64,
        'client_nonce': 'short_nonce_hex',
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data['error'] == 'INVALID_CLIENT_NONCE'


# ---------------------------------------------------------------------------
# 3. Backward Compatibility (Legacy Submissions Without Client Nonce)
# ---------------------------------------------------------------------------

def test_legacy_submission_without_client_commitment_fallback(voting_client, voting_user, active_election, auth_session):
    """Submissions without client_commitment seamlessly generate server-side nonce."""
    _grant_voting_auth(db, voting_user.id, active_election.id, auth_session.session_id)

    res = voting_client.post('/api/voting/submit', json={
        'election_id': active_election.election_id,
        'candidate': 1,
    })
    assert res.status_code == 202
    data = res.get_json()
    assert data['status'] == 'QUEUED'

    pseudonym = derive_pseudonym(voting_user.id, active_election.id)
    ballot = BallotRecord.query.filter_by(election_id=active_election.id, pseudonym=pseudonym).first()
    assert ballot is not None
    assert ballot.commitment is not None
    assert len(ballot.commitment) == 64
    assert ballot.commitment_nonce is not None
    assert len(ballot.commitment_nonce) == 64  # hex format in string column


# ---------------------------------------------------------------------------
# 4. Authenticated Opening Retrieval vs Public Nonce Protection
# ---------------------------------------------------------------------------

def test_authenticated_status_endpoint_returns_opening_data(voting_client, voting_user, active_election, auth_session):
    """Authenticated voter session receives the opening tuple in receipt once finalized."""
    _grant_voting_auth(db, voting_user.id, active_election.id, auth_session.session_id)

    client_nonce_bytes = secrets.token_bytes(32)
    client_nonce_hex = client_nonce_bytes.hex()
    client_commitment = compute_ballot_commitment(active_election.election_id, 0, client_nonce_bytes)

    submit_res = voting_client.post('/api/voting/submit', json={
        'election_id': active_election.election_id,
        'candidate': 0,
        'client_commitment': client_commitment,
        'client_nonce': client_nonce_hex,
    })
    assert submit_res.status_code == 202

    # Transition ballot to FINALIZED so receipt is generated
    pseudonym = derive_pseudonym(voting_user.id, active_election.id)
    ballot = BallotRecord.query.filter_by(election_id=active_election.id, pseudonym=pseudonym).first()
    assert ballot is not None
    ballot.state = 'FINALIZED'
    ballot.receipt_code = 'REC-1-CF314B8D772BF3A1'
    db.session.commit()

    # Query authenticated status endpoint
    status_res = voting_client.get(f'/api/voting/status?election_id={active_election.election_id}')
    data = status_res.get_json()
    receipt = data['receipt']
    assert receipt is not None
    assert receipt['receipt_code'] == 'REC-1-CF314B8D772BF3A1'

    opening = data['opening']
    assert opening is not None
    assert opening['commitment'] == client_commitment
    assert opening['commitment_nonce'] == client_nonce_hex
    assert opening['candidate_index'] == 0


def test_public_verification_endpoints_withhold_nonce(client, db, voting_user, active_election):
    """Public endpoints (without voter session) NEVER return commitment_nonce."""
    client_nonce_bytes = secrets.token_bytes(32)
    client_nonce_hex = client_nonce_bytes.hex()
    client_commitment = compute_ballot_commitment(active_election.election_id, 0, client_nonce_bytes)
    pseudonym = derive_pseudonym(voting_user.id, active_election.id)

    ballot = BallotRecord(
        election_id=active_election.id,
        pseudonym=pseudonym,
        sequence=1,
        candidate=0,
        commitment=client_commitment,
        commitment_nonce=client_nonce_hex,
        state='FINALIZED',
        tx_hash='0x' + 'aa' * 32,
        block_number=101,
    )
    db.session.add(ballot)
    db.session.commit()

    receipt_dict = VotingService.generate_receipt(ballot, voting_user.id)
    receipt_code = receipt_dict['receipt_code']
    ballot.receipt_code = receipt_code
    db.session.commit()

    # 1. Public receipt endpoint
    r1 = client.get(f'/api/verification/receipt/{receipt_code}')
    assert r1.status_code == 200
    d1 = r1.get_json()
    assert 'commitment_nonce' not in d1
    assert 'candidate_index' not in d1
    assert 'candidate' not in d1

    # 2. Public inclusion proof endpoint
    r2 = client.get(f'/api/verification/receipt/{receipt_code}/inclusion-proof')
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert 'commitment_nonce' not in d2
    assert d2.get('commitment') == client_commitment


# ---------------------------------------------------------------------------
# 5. Client-Side Verification Math & Tamper Rejection Simulation
# ---------------------------------------------------------------------------

def test_client_side_opening_and_inclusion_verification_tamper_rejection():
    """Simulates frontend verification logic and asserts rejection of any modification."""
    election_id = "1"
    true_candidate = 1
    true_nonce = secrets.token_bytes(32)

    # 1. Client computes genuine commitment
    genuine_commitment = compute_ballot_commitment(election_id, true_candidate, true_nonce)

    # 2. Build canonical Merkle tree containing this commitment and two other ballots
    other_c1 = compute_ballot_commitment(election_id, 0, secrets.token_bytes(32))
    other_c2 = compute_ballot_commitment(election_id, 2, secrets.token_bytes(32))
    all_commitments = [genuine_commitment, other_c1, other_c2]

    tree = MerkleTree(all_commitments)
    merkle_root = tree.root
    proof = tree.get_audit_proof(genuine_commitment)
    assert proof is not None
    audit_path = proof['audit_path']

    # Case A: Genuine receipt verification -> MUST PASS
    # Step 1: Recompute commitment
    recomputed = compute_ballot_commitment(election_id, true_candidate, true_nonce)
    assert recomputed == genuine_commitment
    # Step 2: Verify inclusion proof
    valid, msg = verify_inclusion_proof(recomputed, merkle_root, audit_path)
    assert valid is True

    # Case B: Tampered candidate choice (e.g. claiming voted for candidate 0) -> MUST FAIL
    tampered_candidate = 0
    recomputed_tampered_cand = compute_ballot_commitment(election_id, tampered_candidate, true_nonce)
    assert recomputed_tampered_cand != genuine_commitment  # Recomputation fails

    # Case C: Tampered nonce -> MUST FAIL
    tampered_nonce = secrets.token_bytes(32)
    recomputed_tampered_nonce = compute_ballot_commitment(election_id, true_candidate, tampered_nonce)
    assert recomputed_tampered_nonce != genuine_commitment

    # Case D: Tampered Merkle Root -> MUST FAIL
    tampered_root = "0x" + "ff" * 32
    valid_root, _ = verify_inclusion_proof(genuine_commitment, tampered_root, audit_path)
    assert valid_root is False

    # Case E: Tampered sibling in audit path -> MUST FAIL
    tampered_audit_path = [
        {"hash": "0x" + "00" * 32, "direction": step["direction"]}
        for step in audit_path
    ]
    valid_path, _ = verify_inclusion_proof(genuine_commitment, merkle_root, tampered_audit_path)
    assert valid_path is False
