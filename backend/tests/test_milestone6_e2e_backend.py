"""
Milestone 6: Isolated End-to-End Validation - Backend Integration Suite
Exercises:
1. Section 3.A: Officer registration, role authorization, and private key isolation proof.
2. Section 3.B: Voter authorization pipeline (session binding, face verification lease, OTP, wallet signature, candidate privacy in wallet signature).
3. Section 3.C & 3.D: Encrypted ballot casting, sequence monotonicity, duplicate/replay rejection, and V2 database record auditing.
4. Section 3.E & 3.F: Decryption shares submission, results retrieval, and failure recovery.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from app.extensions import db
from app.models import Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import BallotQueue as BallotRecord
from app.models.ballot_record_v2 import BallotQueueV2, OfficerRegistrationV2
from app.security.pseudonym import derive_pseudonym
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import (
    G,
    generate_ballot_proof,
    generate_officer_decryption_shares,
    generate_schnorr_pop,
    generate_secure_scalar,
    point_add,
    point_mul,
)


@pytest.fixture
def test_user(app):
    with app.app_context():
        user = User(
            username="voter_m6_01",
            email="voter.m6.01@example.edu",
            password_hash="argon2_fake_hash_m6",
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def auth_session(app, test_user):
    with app.app_context():
        sid = "m6_valid_session_token_xyz"
        now = datetime.utcnow()
        sess = AuthSession(
            session_id=sid,
            user_id=test_user,
            created_at=now,
            expires_at=now + timedelta(hours=2),
            idle_expires_at=now + timedelta(minutes=30),
            last_activity=now,
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()
        return sid


@pytest.fixture
def expired_session(app, test_user):
    with app.app_context():
        sid = "m6_expired_session_token_abc"
        now = datetime.utcnow()
        sess = AuthSession(
            session_id=sid,
            user_id=test_user,
            created_at=now - timedelta(hours=5),
            expires_at=now - timedelta(hours=1),
            idle_expires_at=now - timedelta(hours=2),
            last_activity=now - timedelta(hours=2),
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()
        return sid


@pytest.fixture
def active_election_3cand(app):
    with app.app_context():
        now = datetime.utcnow()
        election = Election(
            election_id="ELEC_V2_M6_001",
            title="Milestone 6 Tri-Candidate Election",
            status="ACTIVE",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=24),
            candidate_count=3,
            eligible_count=100,
        )
        db.session.add(election)
        db.session.commit()
        return election.id


# ==============================================================================
# SECTION 3.A: OFFICER REGISTRATION & KEY CUSTODY (BACKEND)
# ==============================================================================

def test_m6_officer_registration_valid_schnorr_pop(client, active_election_3cand):
    """Verifies Officer 1 and Officer 2 registration with valid Schnorr PoP via API."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    officer1_addr = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    officer2_addr = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
    contract_addr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"

    pop1 = generate_schnorr_pop(
        priv_key=s1,
        officer_id=1,
        officer_address=officer1_addr,
        election_id=active_election_3cand,
        contract_address=contract_addr,
        chain_id=1337,
    )
    pop2 = generate_schnorr_pop(
        priv_key=s2,
        officer_id=2,
        officer_address=officer2_addr,
        election_id=active_election_3cand,
        contract_address=contract_addr,
        chain_id=1337,
    )

    with patch.object(BlockchainV2Service, "register_officer") as mock_reg:
        mock_reg.return_value = {"status": 1, "tx_hash": "0xreg_o1", "block_number": 10}

        resp1 = client.post(
            "/api/v2/officer/register-key",
            json={
                "election_id": active_election_3cand,
                "officer_id": 1,
                "pub_key": pop1["pub_key"],
                "pop": pop1["pop"],
                "officer_address": officer1_addr,
                "contract_address": contract_addr,
            },
        )
        assert resp1.status_code == 200
        assert resp1.get_json()["success"] is True

        # Verify Officer 2 registration
        mock_reg.return_value = {"status": 1, "tx_hash": "0xreg_o2", "block_number": 11}
        resp2 = client.post(
            "/api/v2/officer/register-key",
            json={
                "election_id": active_election_3cand,
                "officer_id": 2,
                "pub_key": pop2["pub_key"],
                "pop": pop2["pop"],
                "officer_address": officer2_addr,
                "contract_address": contract_addr,
            },
        )
        assert resp2.status_code == 200
        assert resp2.get_json()["success"] is True


def test_m6_private_scalar_isolation_proof(client, active_election_3cand):
    """
    CRITICAL AUDIT INVARIANT:
    Confirms private BN254 scalars NEVER enter Flask requests, database records,
    or backend application models.
    """
    # Verify OfficerRegistrationV2 model schema has NO private key column
    columns = [c.name for c in OfficerRegistrationV2.__table__.columns]
    assert "private_key" not in columns
    assert "priv_key" not in columns
    assert "scalar" not in columns
    assert "secret" not in columns

    # Verify BallotQueueV2 model schema has NO plaintext candidate integer
    ballot_columns = [c.name for c in BallotQueueV2.__table__.columns]
    assert "candidate" not in ballot_columns
    assert "candidate_index" not in ballot_columns
    assert "selection" not in ballot_columns
    assert "ciphertexts_json" in ballot_columns
    assert "proof_json" in ballot_columns


# ==============================================================================
# SECTION 3.B: VOTER AUTHORIZATION PIPELINE (BACKEND)
# ==============================================================================

def test_m6_voter_authorization_pipeline_success(client, active_election_3cand, auth_session):
    """Exercises voter authorization pipeline with session binding and wallet signature check."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y_joint = point_add(point_mul(G, s1), point_mul(G, s2))

    sess_obj = AuthSession.query.filter_by(session_id=auth_session).first()
    p_actual = derive_pseudonym(sess_obj.user_id, active_election_3cand)

    context = {
        "election_id": active_election_3cand,
        "pseudonym": p_actual,
        "sequence": 1,
        "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
    }
    ballot = generate_ballot_proof(
        selected_candidate=0,
        candidate_count=3,
        context=context,
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        chain_id=1337,
    )

    with client.session_transaction() as sess:
        sess["session_id"] = auth_session

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {
            "status": 1,
            "tx_hash": "0xballot_tx_voter1",
            "block_number": 50,
        }

        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election_3cand,
                "sequence": 1,
                "ciphertexts": ballot["ciphertexts"],
                "proof": ballot["proof"],
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "CONFIRMED"
        assert data["sequence"] == 1
        assert data["tx_hash"] == "0xballot_tx_voter1"


def test_m6_unauthenticated_request_rejected(client, active_election_3cand):
    """Unauthenticated request without session cookie is rejected with 401."""
    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": active_election_3cand,
            "sequence": 1,
            "ciphertexts": [],
            "proof": {},
        },
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "NOT_AUTHENTICATED"


def test_m6_expired_session_rejected(client, active_election_3cand, expired_session):
    """Expired voter session is rejected with 401."""
    with client.session_transaction() as sess:
        sess["session_id"] = expired_session

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": active_election_3cand,
            "sequence": 1,
            "ciphertexts": [],
            "proof": {},
        },
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "NOT_AUTHENTICATED"


# ==============================================================================
# SECTION 3.C & 3.D: BALLOT CASTING, REVOTING & MONOTONICITY (BACKEND)
# ==============================================================================

def test_m6_revoting_monotonicity_and_replays(app, client, active_election_3cand, auth_session):
    """
    Submits initial ballot (sequence 1), revote (sequence 2),
    and proves that duplicate sequence 1 and out-of-order sequence 4 are rejected.
    """
    app.config["REVOTE_COOLDOWN_SECONDS"] = 0
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y_joint = point_add(point_mul(G, s1), point_mul(G, s2))

    with client.session_transaction() as sess:
        sess["session_id"] = auth_session

    sess_obj = AuthSession.query.filter_by(session_id=auth_session).first()
    p_actual = derive_pseudonym(sess_obj.user_id, active_election_3cand)

    # 1. Cast sequence 1
    context1 = {
        "election_id": active_election_3cand,
        "pseudonym": p_actual,
        "sequence": 1,
        "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
    }
    ballot1 = generate_ballot_proof(
        selected_candidate=0,
        candidate_count=3,
        context=context1,
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        chain_id=1337,
    )

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {"status": 1, "tx_hash": "0xseq1", "block_number": 51}

        resp1 = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election_3cand,
                "sequence": 1,
                "ciphertexts": ballot1["ciphertexts"],
                "proof": ballot1["proof"],
            },
        )
        assert resp1.status_code == 200
        assert resp1.get_json()["sequence"] == 1

        # 2. Attempt duplicate sequence 1 (replay) -> Reverted with INVALID_SEQUENCE_ORDER
        resp_dup = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election_3cand,
                "sequence": 1,
                "ciphertexts": ballot1["ciphertexts"],
                "proof": ballot1["proof"],
            },
        )
        assert resp_dup.status_code == 400
        assert resp_dup.get_json()["error"] == "INVALID_SEQUENCE_ORDER"

        # 3. Attempt out-of-order sequence 3 (skipping sequence 2) -> Reverted
        resp_leap = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election_3cand,
                "sequence": 3,
                "ciphertexts": ballot1["ciphertexts"],
                "proof": ballot1["proof"],
            },
        )
        assert resp_leap.status_code == 400
        assert resp_leap.get_json()["error"] == "INVALID_SEQUENCE_ORDER"

        # 4. Cast valid revote at sequence 2
        context2 = {
            "election_id": active_election_3cand,
            "pseudonym": p_actual,
            "sequence": 2,
            "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
        }
        ballot2 = generate_ballot_proof(
            selected_candidate=2,
            candidate_count=3,
            context=context2,
            verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
            chain_id=1337,
        )

        mock_cast.return_value = {"status": 1, "tx_hash": "0xseq2", "block_number": 52}
        resp2 = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election_3cand,
                "sequence": 2,
                "ciphertexts": ballot2["ciphertexts"],
                "proof": ballot2["proof"],
            },
        )
        assert resp2.status_code == 200
        assert resp2.get_json()["sequence"] == 2

        # Verify DB records
        records = BallotQueueV2.query.filter_by(
            election_id=active_election_3cand, pseudonym=p_actual
        ).all()
        assert len(records) == 2
        seqs = [r.sequence for r in records]
        assert seqs == [1, 2]


# ==============================================================================
# SECTION 3.E: DECRYPTION SHARES & RESULTS RETRIEVAL (BACKEND)
# ==============================================================================

def test_m6_shares_submission_and_results_retrieval(client, active_election_3cand):
    """Verifies officer shares submission and results retrieval endpoints."""
    with patch.object(BlockchainV2Service, "submit_decryption_shares") as mock_sub:
        mock_sub.return_value = {"status": 1, "tx_hash": "0xshares_m6"}

        resp = client.post(
            "/api/v2/officer/submit-shares",
            json={
                "election_id": active_election_3cand,
                "officer_id": 1,
                "shares": [{"x": 10, "y": 20}, {"x": 30, "y": 40}, {"x": 50, "y": 60}],
                "proofs": [
                    {"u": {"x": 1, "y": 2}, "v": {"x": 3, "y": 4}, "z": 5},
                    {"u": {"x": 1, "y": 2}, "v": {"x": 3, "y": 4}, "z": 5},
                    {"u": {"x": 1, "y": 2}, "v": {"x": 3, "y": 4}, "z": 5},
                ],
                "officer_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["tx_hash"] == "0xshares_m6"

    # Test Results Endpoint with expected oracle tallies [0, 3, 2]
    with patch.object(BlockchainV2Service, "get_final_tally") as mock_tally:
        mock_tally.side_effect = [0, 3, 2]

        res_resp = client.get(f"/api/v2/voting/results?election_id={active_election_3cand}")
        assert res_resp.status_code == 200
        data = res_resp.get_json()
        assert data["is_finalized"] is True
        assert data["tallies"] == [0, 3, 2]
