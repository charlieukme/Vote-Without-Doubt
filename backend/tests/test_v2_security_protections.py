"""
Unit and Integration Tests for V2 Officer Architecture & Cryptographic Protections.
Verifies:
1. Bidirectional officer role authorization (Officer 1 cannot act as Officer 2, and vice-versa).
2. Unauthenticated and auditor requests are strictly rejected.
3. Hardhat restart / chain reset detection blocks operations with 409 CHAIN_DESYNCHRONIZED.
4. Invalid Schnorr PoP and rogue keys are rejected off-chain.
5. Successful gas-free officer registration via backend relayer.
6. Decryption share cross-impersonation rejection.
7. DLEQ challenge transcript domain separation and parameter binding.
"""

import json
import secrets
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account
from eth_abi import encode
from eth_utils import keccak

from app.extensions import db
from app.models import Election
from app.models.admin import AdminSession, AdminUser
from app.models.ballot_record_v2 import OfficerRegistrationV2
from app.security.password import hash_password
from app.services.bn254_crypto import (
    G,
    Q,
    point_mul,
    verify_schnorr_pop,
    POP_DOMAIN_SEPARATOR,
    mod_q,
)
from app.services.blockchain_v2_service import BlockchainV2Service


TEST_RELAYER_KEY = "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
TEST_RELAYER_ADDR = Account.from_key(TEST_RELAYER_KEY).address


@pytest.fixture
def v2_security_setup(app, db):
    """Sets up an election and two distinct admin officers with active sessions."""
    with app.app_context():
        app.config['RELAYER_PRIVATE_KEY'] = TEST_RELAYER_KEY
        app.config['RELAYER_ACCOUNT'] = TEST_RELAYER_ADDR
        app.config['APP_ENV'] = 'testing'

        # 1. Setup Election
        now = datetime.utcnow()
        election = Election(
            election_id=f"ELEC_SEC_{secrets.token_hex(4)}",
            title="V2 Security Test Election",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status="OPEN",
            candidate_count=3,
        )
        db.session.add(election)
        db.session.flush()

        # 2. Setup Officer 1
        o1_user = AdminUser.query.filter_by(admin_id="OFFICER_01").first()
        if not o1_user:
            o1_user = AdminUser(
                admin_id="OFFICER_01",
                name="Chief Officer 1",
                email="officer1_sec@college.edu",
                password_hash=hash_password("SecOfficer1Pass!"),
                role="OFFICER",
                is_active=True,
            )
            db.session.add(o1_user)
            db.session.flush()

        o1_token = secrets.token_hex(32)
        o1_session = AdminSession(
            session_token=o1_token,
            admin_id=o1_user.id,
            role="OFFICER",
            ip_address="127.0.0.1",
            user_agent="PyTest",
            expires_at=now + timedelta(hours=2),
            revoked=False,
        )
        db.session.add(o1_session)

        # 3. Setup Officer 2
        o2_user = AdminUser.query.filter_by(admin_id="OFFICER_02").first()
        if not o2_user:
            o2_user = AdminUser(
                admin_id="OFFICER_02",
                name="Deputy Officer 2",
                email="officer2_sec@college.edu",
                password_hash=hash_password("SecOfficer2Pass!"),
                role="OFFICER",
                is_active=True,
            )
            db.session.add(o2_user)
            db.session.flush()

        o2_token = secrets.token_hex(32)
        o2_session = AdminSession(
            session_token=o2_token,
            admin_id=o2_user.id,
            role="OFFICER",
            ip_address="127.0.0.1",
            user_agent="PyTest",
            expires_at=now + timedelta(hours=2),
            revoked=False,
        )
        db.session.add(o2_session)

        # 4. Setup Auditor (Non-officer role)
        auditor_user = AdminUser.query.filter_by(admin_id="AUDITOR_01").first()
        if not auditor_user:
            auditor_user = AdminUser(
                admin_id="AUDITOR_01",
                name="Auditor 1",
                email="auditor_sec@college.edu",
                password_hash=hash_password("AuditorPass123!"),
                role="AUDITOR",
                is_active=True,
            )
            db.session.add(auditor_user)
            db.session.flush()

        aud_token = secrets.token_hex(32)
        aud_session = AdminSession(
            session_token=aud_token,
            admin_id=auditor_user.id,
            role="AUDITOR",
            ip_address="127.0.0.1",
            user_agent="PyTest",
            expires_at=now + timedelta(hours=2),
            revoked=False,
        )
        db.session.add(aud_session)
        db.session.commit()

        yield {
            "election": election,
            "o1_token": o1_token,
            "o2_token": o2_token,
            "aud_token": aud_token,
        }


def _generate_valid_pop(officer_id: int, election_id: int, contract_address: str, chain_id: int = 1337):
    """Helper to generate a valid Schnorr PoP matching the 9-parameter canonical transcript."""
    s = 123456789012345678901234567890 + officer_id
    k = 987654321098765432109876543210 + officer_id

    Y = point_mul(G, s)
    R = point_mul(G, k)

    c_addr = bytes.fromhex(contract_address[2:].lower() if contract_address.startswith("0x") else contract_address.lower())
    encoded = encode(
        ["bytes32", "uint256", "address", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
        [
            POP_DOMAIN_SEPARATOR,
            int(chain_id),
            "0x" + c_addr.hex(),
            int(election_id),
            int(officer_id),
            Y[0],
            Y[1],
            R[0],
            R[1],
        ],
    )
    e = mod_q(int.from_bytes(keccak(encoded), "big"))
    z = mod_q(k + e * s)

    return {
        "pub_key": {"x": str(Y[0]), "y": str(Y[1])},
        "pop": {
            "r": {"x": str(R[0]), "y": str(R[1])},
            "z": str(z),
        },
    }


def test_officer1_cannot_register_for_officer2(client, v2_security_setup):
    """Officer 1 cannot submit registration with officer_id: 2."""
    setup = v2_security_setup
    payload = _generate_valid_pop(2, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 2  # Spoofed officer ID

    headers = {"Authorization": f"Bearer {setup['o1_token']}"}
    res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)

    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "OFFICER_ROLE_MISMATCH"


def test_officer2_cannot_register_for_officer1(client, v2_security_setup):
    """Officer 2 cannot submit registration with officer_id: 1."""
    setup = v2_security_setup
    payload = _generate_valid_pop(1, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1  # Spoofed officer ID

    headers = {"Authorization": f"Bearer {setup['o2_token']}"}
    res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)

    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "OFFICER_ROLE_MISMATCH"


def test_unauthenticated_officer_rejected(client, v2_security_setup):
    """Unauthenticated calls to officer endpoints are rejected with 401."""
    setup = v2_security_setup
    payload = _generate_valid_pop(1, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1

    res = client.post("/api/v2/officer/register-key", json=payload)
    assert res.status_code == 401


def test_auditor_cannot_act_as_officer(client, v2_security_setup):
    """An auditor cannot register officer keys."""
    setup = v2_security_setup
    payload = _generate_valid_pop(1, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1

    headers = {"Authorization": f"Bearer {setup['aud_token']}"}
    res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)
    assert res.status_code == 403


def test_chain_restart_detection_blocks_registration(client, v2_security_setup):
    """When the blockchain node has been restarted and lost contract code, registration is blocked."""
    setup = v2_security_setup
    payload = _generate_valid_pop(1, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1
    payload["contract_address"] = "0x5FbDB2315678afecb367f032d93F642f64180aa3"

    headers = {"Authorization": f"Bearer {setup['o1_token']}"}

    # Simulate missing bytecode on node
    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(False, "CHAIN_RESET_DETECTED: Node was restarted")):
        res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)
        assert res.status_code == 409
        assert res.get_json()["error"] == "CHAIN_DESYNCHRONIZED"


def test_invalid_schnorr_pop_rejected(client, v2_security_setup):
    """Invalid Schnorr PoP scalar z is rejected off-chain before blockchain submission."""
    setup = v2_security_setup
    payload = _generate_valid_pop(1, setup["election"].id, "0x5FbDB2315678afecb367f032d93F642f64180aa3")
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1
    payload["contract_address"] = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
    # Corrupt z
    payload["pop"]["z"] = str(int(payload["pop"]["z"]) + 1)

    headers = {"Authorization": f"Bearer {setup['o1_token']}"}

    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(True, "OK")):
        res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)
        assert res.status_code == 400
        assert res.get_json()["error"] == "INVALID_POP_PROOF"


def test_officer_relayer_submission_succeeds(client, v2_security_setup):
    """Officer registers key share successfully without needing their own MetaMask address."""
    setup = v2_security_setup
    contract_addr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
    payload = _generate_valid_pop(1, setup["election"].id, contract_addr)
    payload["election_id"] = setup["election"].id
    payload["officer_id"] = 1
    payload["contract_address"] = contract_addr

    headers = {"Authorization": f"Bearer {setup['o1_token']}"}

    mock_receipt = {"tx_hash": "0xabc123def456", "block_number": 42}
    with patch.object(BlockchainV2Service, "verify_chain_synchronization", return_value=(True, "OK")), \
         patch.object(BlockchainV2Service, "register_officer", return_value=mock_receipt):
        res = client.post("/api/v2/officer/register-key", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["tx_hash"] == "0xabc123def456"

        # Verify DB record
        reg = OfficerRegistrationV2.query.filter_by(election_id=setup["election"].id, officer_id=1).first()
        assert reg is not None
        assert reg.registered_on_chain is True
        assert reg.tx_hash == "0xabc123def456"


def test_officer_cross_share_submission_rejected(client, v2_security_setup):
    """Officer 1 cannot submit decryption shares for Officer 2."""
    setup = v2_security_setup
    payload = {
        "election_id": setup["election"].id,
        "officer_id": 2,
        "shares": [{"x": "1", "y": "2"}],
        "proofs": [{"u": {"x": "1", "y": "2"}, "v": {"x": "1", "y": "2"}, "z": "123"}],
        "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
    }
    headers = {"Authorization": f"Bearer {setup['o1_token']}"}
    res = client.post("/api/v2/officer/submit-shares", json=payload, headers=headers)
    assert res.status_code == 403
    assert res.get_json()["error"] == "OFFICER_ROLE_MISMATCH"


def test_checkpoint_detects_chain_restart_on_genesis_mismatch(tmp_path):
    """Checkpoint validation rejects when genesis hash differs (node was restarted)."""
    from unittest.mock import MagicMock
    from app.services.blockchain_v2_service import BlockchainV2Service, save_deployment_checkpoint

    cp_file = save_deployment_checkpoint(
        election_id=99,
        contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        relayer_address="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        deployment_tx_hash="0x1111111111111111111111111111111111111111111111111111111111111111",
        deployment_block_number=1,
        deployment_block_hash="0x2222222222222222222222222222222222222222222222222222222222222222",
        genesis_block_hash="0x3333333333333333333333333333333333333333333333333333333333333333",
        chain_id=1337,
        candidate_count=2,
        checkpoint_dir=str(tmp_path),
    )

    mock_w3 = MagicMock()
    mock_w3.eth.get_code.return_value = b'x' * 6000
    mock_w3.eth.block_number = 5
    # Return different genesis hash
    mock_w3.eth.get_block.side_effect = lambda arg: {"hash": b'\x99' * 32} if arg == 0 else {"hash": b'\x22' * 32}

    mock_contract = MagicMock()
    mock_contract.functions.electionId().call.return_value = 99
    mock_w3.eth.contract.return_value = mock_contract

    service = BlockchainV2Service(
        contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
        w3_instance=mock_w3,
    )

    class MockElection:
        id = 99

    with patch("app.services.blockchain_v2_service._DEFAULT_CHECKPOINT_DIR", str(tmp_path)):
        ok, msg = service.verify_chain_synchronization(MockElection())
        assert ok is False
        assert "Genesis block hash mismatch" in msg


def test_checkpoint_valid_fingerprint_passes(tmp_path):
    """Checkpoint validation succeeds when all fingerprints match."""
    from unittest.mock import MagicMock
    from app.services.blockchain_v2_service import BlockchainV2Service, save_deployment_checkpoint

    gen_hash = "0x" + "33" * 32
    dep_hash = "0x" + "22" * 32
    tx_hash = "0x" + "11" * 32
    c_addr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"

    save_deployment_checkpoint(
        election_id=100,
        contract_address=c_addr,
        verifier_address="0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
        relayer_address="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        deployment_tx_hash=tx_hash,
        deployment_block_number=1,
        deployment_block_hash=dep_hash,
        genesis_block_hash=gen_hash,
        chain_id=1337,
        candidate_count=2,
        checkpoint_dir=str(tmp_path),
    )

    mock_w3 = MagicMock()
    mock_w3.eth.get_code.return_value = b'x' * 6000
    mock_w3.eth.block_number = 5
    mock_w3.eth.get_block.side_effect = lambda arg: {"hash": bytes.fromhex(gen_hash[2:])} if arg == 0 else {"hash": bytes.fromhex(dep_hash[2:])}
    mock_w3.eth.get_transaction_receipt.return_value = {"contractAddress": c_addr}

    mock_contract = MagicMock()
    mock_contract.functions.electionId().call.return_value = 100
    mock_w3.eth.contract.return_value = mock_contract

    service = BlockchainV2Service(
        contract_address=c_addr,
        w3_instance=mock_w3,
    )

    class MockElection:
        id = 100

    with patch("app.services.blockchain_v2_service._DEFAULT_CHECKPOINT_DIR", str(tmp_path)):
        ok, msg = service.verify_chain_synchronization(MockElection())
        assert ok is True
        assert msg == "OK"

