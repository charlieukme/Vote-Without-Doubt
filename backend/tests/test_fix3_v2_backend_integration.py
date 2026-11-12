"""
Backend Integration Test Suite for FIX 3 V2: On-Chain Candidate Choice Privacy.
Tests:
1. Two-Officer key registration via API with Schnorr PoP.
2. Key status queries and contract state tracking.
3. Encrypted ballot submission and homomorphic revoting.
4. Sequence monotonicity enforcement and replay protection.
5. Officer decryption shares submission with DLEQ proof validation.
6. Zero-trust tally finalization and verified results retrieval.
7. V1 vs V2 coexistence and isolation.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from app.extensions import db
from app.models import Election, User
from app.models.admin import AdminSession, AdminUser
from app.models.auth_session import AuthSession
from app.models.ballot_record import BallotQueue as BallotRecord, VotingAuthorization
from app.models.ballot_record_v2 import BallotQueueV2, OfficerRegistrationV2
from app.models.election_key import ElectionPseudonymKey
from app.models.roll import ElectoralRoll
from app.services.bn254_crypto import (
    G,
    generate_ballot_proof,
    generate_officer_decryption_shares,
    generate_schnorr_pop,
    generate_secure_scalar,
    point_add,
    point_mul,
)
from app.services.blockchain_v2_service import BlockchainV2Service


@pytest.fixture
def test_user(app):
    with app.app_context():
        from eth_account import Account
        test_key = '0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d'
        app.config['RELAYER_PRIVATE_KEY'] = test_key
        app.config['RELAYER_ACCOUNT'] = Account.from_key(test_key).address
        user = User(
            username="alice_v2",
            email="alice.v2@example.edu",
            voter_id="USN_ALICE_V2",
            password_hash="argon2_fake_hash",
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        roll = ElectoralRoll(
            usn="USN_ALICE_V2",
            college_email="alice.v2@example.edu",
            full_name="Alice V2",
            is_eligible=True,
        )
        db.session.add(roll)
        db.session.commit()
        return user.id


@pytest.fixture
def auth_session(app, test_user):
    with app.app_context():
        sid = "test_v2_session_token_12345"
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
def active_election(app):
    with app.app_context():
        now = datetime.utcnow()
        election = Election(
            election_id="ELEC_V2_TEST_001",
            title="V2 Privacy Election",
            status="ACTIVE",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=24),
            candidate_count=2,
            eligible_count=100,
        )
        db.session.add(election)
        db.session.commit()
        return election.id


@pytest.fixture
def admin_headers(app):
    with app.app_context():
        import secrets
        admin = AdminUser(
            admin_id="OFFICER_V2_TEST",
            name="V2 Test Officer",
            email="v2officer@votewithoutdoubt.local",
            password_hash="argon2_fake_hash",
            role="OFFICER",
            is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        token = secrets.token_hex(32)
        sess = AdminSession(
            session_token=token,
            admin_id=admin.id,
            role=admin.role,
            ip_address="127.0.0.1",
            expires_at=datetime.utcnow() + timedelta(hours=2),
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()
        return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# SUITE 1: OFFICER REGISTRATION & KEY LIFECYCLE API
# ==============================================================================

def test_api_officer_registration_success(client, active_election, admin_headers):
    """Officer registers public key share with valid Schnorr PoP via API."""
    s1 = generate_secure_scalar()
    officer_addr = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    contract_addr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"

    pop_data = generate_schnorr_pop(
        priv_key=s1,
        officer_id=1,
        election_id=active_election,
        contract_address=contract_addr,
        chain_id=1337,
    )

    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(True, None)), \
         patch.object(BlockchainV2Service, "register_officer") as mock_reg:
        mock_reg.return_value = {
            "status": 1,
            "tx_hash": "0xabc123456789",
            "block_number": 42,
        }

        resp = client.post(
            "/api/v2/officer/register-key",
            headers=admin_headers,
            json={
                "election_id": active_election,
                "officer_id": 1,
                "pub_key": pop_data["pub_key"],
                "pop": pop_data["pop"],
                "officer_address": officer_addr,
                "contract_address": contract_addr,
            },
        )

        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["success"] is True
        assert data["tx_hash"] == "0xabc123456789"

        # Verify database record
        reg = OfficerRegistrationV2.query.filter_by(
            election_id=active_election, officer_id=1
        ).first()
        assert reg is not None
        assert reg.registered_on_chain is True
        assert reg.tx_hash == "0xabc123456789"


def test_api_officer_registration_rejects_off_curve_key(client, active_election, admin_headers):
    """Rejects malformed/off-curve public key coordinates."""
    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(True, None)):
        resp = client.post(
            "/api/v2/officer/register-key",
            headers=admin_headers,
            json={
                "election_id": active_election,
                "officer_id": 1,
                "pub_key": {"x": 5, "y": 5},  # Off-curve point
                "pop": {"r": {"x": 1, "y": 2}, "z": 12345},
                "officer_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "INVALID_OFFICER_KEY"


def test_api_key_status_query(client, active_election):
    """Retrieves officer registration status and state from smart contract."""
    with patch.object(BlockchainV2Service, "get_contract") as mock_contract_fn:
        mock_contract = MagicMock()
        mock_contract.functions.state().call.return_value = 3  # KeyRegistrationComplete
        mock_contract.functions.officer1Registered().call.return_value = True
        mock_contract.functions.officer2Registered().call.return_value = True
        mock_contract.functions.jointPubKey().call.return_value = (100, 200)
        mock_contract.functions.verifier().call.return_value = "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512"
        mock_contract_fn.return_value = mock_contract

        resp = client.get(f"/api/v2/officer/key-status?election_id={active_election}")
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["state"] == 3
        assert data["officer1_registered"] is True
        assert data["officer2_registered"] is True
        assert data["joint_public_key"] == {"x": "100", "y": "200"}


# ==============================================================================
# SUITE 2: ENCRYPTED BALLOT CASTING & HOMOMORPHIC REVOTING API
# ==============================================================================

def test_api_cast_ballot_v2_success(client, active_election, auth_session, test_user):
    """Voter submits valid encrypted ballot vector with non-circular CDS proof."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y_joint = point_add(point_mul(G, s1), point_mul(G, s2))

    # Seed fresh unconsumed voting authorization
    now = datetime.utcnow()
    va = VotingAuthorization(
        user_id=test_user,
        election_id=active_election,
        session_id=auth_session,
        authorized=True,
        wallet_verified=True,
        face_verified=True,
        consumed=False,
        expires_at=now + timedelta(hours=1),
    )
    db.session.add(va)
    db.session.commit()

    # Derive ballot
    context = {
        "election_id": active_election,
        "pseudonym": "0x" + "a" * 64,
        "sequence": 1,
        "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
    }
    ballot = generate_ballot_proof(
        selected_candidate=0,
        candidate_count=2,
        context=context,
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        chain_id=1337,
    )

    with client.session_transaction() as sess:
        sess["session_id"] = auth_session

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {
            "status": 1,
            "tx_hash": "0xballot_tx_123",
            "block_number": 101,
        }

        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election,
                "sequence": 1,
                "ciphertexts": ballot["ciphertexts"],
                "proof": ballot["proof"],
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )

        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["status"] == "CONFIRMED"
        assert data["sequence"] == 1
        assert data["tx_hash"] == "0xballot_tx_123"

        # Verify database record in BallotQueueV2
        record = BallotQueueV2.query.filter_by(
            election_id=active_election, sequence=1
        ).first()
        assert record is not None
        assert record.state == "CONFIRMED"
        assert record.tx_hash == "0xballot_tx_123"


def test_api_revoting_increments_sequence_monotonically(client, active_election, auth_session, test_user):
    """Voter submits revote (sequence 2) accurately overriding sequence 1."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y_joint = point_add(point_mul(G, s1), point_mul(G, s2))

    # Seed fresh unconsumed voting authorization for sequence 2
    now = datetime.utcnow()
    va = VotingAuthorization(
        user_id=test_user,
        election_id=active_election,
        session_id=auth_session,
        authorized=True,
        wallet_verified=True,
        face_verified=True,
        consumed=False,
        expires_at=now + timedelta(hours=1),
    )
    db.session.add(va)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["session_id"] = auth_session

    # Seed sequence 1 (backdated past the 120s revote cooldown)
    ballot1 = BallotQueueV2(
        election_id=active_election,
        pseudonym="test_pseudonym",
        sequence=1,
        ciphertexts_json="[]",
        proof_json="{}",
        state="CONFIRMED",
        created_at=now - timedelta(minutes=5),
    )
    from app.security.pseudonym import derive_pseudonym
    sess_obj = AuthSession.query.filter_by(session_id=auth_session).first()
    p_actual = derive_pseudonym(sess_obj.user_id, active_election)
    ballot1.pseudonym = p_actual
    db.session.add(ballot1)
    db.session.commit()

    context = {
        "election_id": active_election,
        "pseudonym": p_actual,
        "sequence": 2,
        "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
    }
    ballot2 = generate_ballot_proof(
        selected_candidate=1,
        candidate_count=2,
        context=context,
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        chain_id=1337,
    )

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {
            "status": 1,
            "tx_hash": "0xrevote_tx_456",
            "block_number": 105,
        }

        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": active_election,
                "sequence": 2,
                "ciphertexts": ballot2["ciphertexts"],
                "proof": ballot2["proof"],
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["sequence"] == 2


def test_api_out_of_order_sequence_rejected(client, active_election, auth_session, test_user):
    """Submitting sequence 3 when sequence 1 is active reverts with INVALID_SEQUENCE_ORDER."""
    now = datetime.utcnow()
    va = VotingAuthorization(
        user_id=test_user,
        election_id=active_election,
        session_id=auth_session,
        authorized=True,
        wallet_verified=True,
        face_verified=True,
        consumed=False,
        expires_at=now + timedelta(hours=1),
    )
    db.session.add(va)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["session_id"] = auth_session

    sess_obj = AuthSession.query.filter_by(session_id=auth_session).first()
    from app.security.pseudonym import derive_pseudonym
    p_actual = derive_pseudonym(sess_obj.user_id, active_election)

    # Sequence 1 in DB
    ballot1 = BallotQueueV2(
        election_id=active_election,
        pseudonym=p_actual,
        sequence=1,
        ciphertexts_json="[]",
        proof_json="{}",
        state="CONFIRMED",
    )
    db.session.add(ballot1)
    db.session.commit()

    # Attempt sequence 3
    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": active_election,
            "sequence": 3,
            "ciphertexts": [{}],
            "proof": {},
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "INVALID_SEQUENCE_ORDER"


# ==============================================================================
# SUITE 3: DECRYPTION SHARES & TALLY FINALIZATION API
# ==============================================================================

def test_api_submit_decryption_shares(client, active_election, admin_headers):
    """Submits officer decryption shares and DLEQ proofs via API."""
    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(True, None)), \
         patch.object(BlockchainV2Service, "submit_decryption_shares") as mock_sub:
        mock_sub.return_value = {
            "status": 1,
            "tx_hash": "0xshares_tx_789",
        }

        resp = client.post(
            "/api/v2/officer/submit-shares",
            headers=admin_headers,
            json={
                "election_id": active_election,
                "officer_id": 1,
                "shares": [{"x": 10, "y": 20}, {"x": 30, "y": 40}],
                "proofs": [
                    {"u": {"x": 1, "y": 2}, "v": {"x": 3, "y": 4}, "z": 5},
                    {"u": {"x": 1, "y": 2}, "v": {"x": 3, "y": 4}, "z": 5},
                ],
                "officer_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["tx_hash"] == "0xshares_tx_789"


def test_api_finalize_tally_and_get_results(client, active_election, admin_headers):
    """Finalizes tally and reads verified results from contract."""
    with patch.object(BlockchainV2Service, "finalize_tally") as mock_final:
        mock_final.return_value = {
            "status": 1,
            "tx_hash": "0xfinal_tx_999",
        }

        resp = client.post(
            "/api/v2/voting/finalize-tally",
            headers=admin_headers,
            json={
                "election_id": active_election,
                "tallies": [2, 1],
            },
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["tx_hash"] == "0xfinal_tx_999"

    with patch.object(BlockchainV2Service, "get_final_tally") as mock_get_tally:
        mock_get_tally.side_effect = [2, 1]

        res_resp = client.get(f"/api/v2/voting/results?election_id={active_election}")
        assert res_resp.status_code == 200
        data = res_resp.get_json()
        assert data["is_finalized"] is True
        assert data["tallies"] == [2, 1]


# ==============================================================================
# SUITE 4: V1 VS V2 ISOLATION
# ==============================================================================

def test_v1_and_v2_database_isolation(client, active_election):
    """Confirms V1 BallotRecord (plaintext int candidate) and V2 BallotQueueV2 (ciphertexts) do not interfere."""
    # V1 ballot
    v1_ballot = BallotRecord(
        election_id=active_election,
        pseudonym="v1_pseudonym",
        candidate=1,
        sequence=1,
        state="CONFIRMED",
    )
    db.session.add(v1_ballot)

    # V2 ballot
    v2_ballot = BallotQueueV2(
        election_id=active_election,
        pseudonym="v2_pseudonym",
        sequence=1,
        ciphertexts_json="[{\"a\": 1}]",
        proof_json="{\"z\": 2}",
        state="CONFIRMED",
    )
    db.session.add(v2_ballot)
    db.session.commit()

    # Query V1
    v1_records = BallotRecord.query.filter_by(election_id=active_election).all()
    assert len(v1_records) == 1
    assert v1_records[0].candidate == 1

    # Query V2
    v2_records = BallotQueueV2.query.filter_by(election_id=active_election).all()
    assert len(v2_records) == 1
    assert v2_records[0].ciphertexts_json == "[{\"a\": 1}]"
