"""Phase 6 tests: Strict election-specific V2 contract resolution without global fallback."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models import Candidate, Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.roll import ElectoralRoll
from app.services.blockchain_v2_service import (
    BlockchainV2Service,
    load_deployment_checkpoint,
    save_deployment_checkpoint,
)
from app.services.bn254_crypto import G, generate_ballot_proof, generate_secure_scalar, point_add, point_mul
from app.services.results_service import ResultsService
from app.services.verification_service import VerificationService
from app.security.pseudonym import derive_pseudonym


def _make_v2_election(eid_str: str, status: str = "OPEN") -> Election:
    now = datetime.utcnow()
    el = Election(
        election_id=eid_str,
        title=f"Election {eid_str}",
        status=status,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=4),
        candidate_count=2,
        eligible_count=20,
        max_ballots=3,
        v2_priv_key_1=str(generate_secure_scalar()),
        v2_priv_key_2=str(generate_secure_scalar()),
    )
    db.session.add(el)
    db.session.flush()
    db.session.add(Candidate(election_id=el.election_id, candidate_index=0, name="Cand A", department="CS"))
    db.session.add(Candidate(election_id=el.election_id, candidate_index=1, name="Cand B", department="EE"))
    db.session.commit()
    return el


def test_phase6_election_scoped_service_never_falls_back_to_global_env(app, client, tmp_path):
    with app.app_context():
        app.config["BALLOTBOX_V2_CONTRACT_ADDRESS"] = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
        el = _make_v2_election("ELEC_P6_NO_CP", status="FINALIZED")

        with patch("app.services.blockchain_v2_service._DEFAULT_CHECKPOINT_DIR", str(tmp_path)):
            svc = BlockchainV2Service(election_id=el.id)
            assert svc.contract_address is None
            with pytest.raises(ValueError, match="deployment checkpoint"):
                svc.get_contract()

            assert VerificationService._resolve_target_contract(el) is None

            res_resp = client.get(f"/api/v2/officer/key-status?election_id={el.id}")
            assert res_resp.status_code == 200
            ks = res_resp.get_json()
            assert ks["contract_address"] is None
            assert ks["chain_id"] == int(app.config.get("WALLET_AUTH_CHAIN_ID", 1337))

            ok, _code, res_data = ResultsService.get_election_results(el.election_id)
            assert ok is True
            assert res_data["official_results"] is False
            assert "checkpoint" in (res_data.get("notice") or "").lower()


def test_phase6_mismatched_checkpoint_election_id_and_chain_id_rejected(app, client, tmp_path):
    with app.app_context():
        el = _make_v2_election("ELEC_P6_MISMATCH", status="OPEN")

        # Save a checkpoint whose JSON says election_id=999 under el.id's filename
        bad_file = tmp_path / f"v2_checkpoint_election_{el.id}.json"
        bad_file.write_text(json.dumps({
            "election_id": 999,
            "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            "chain_id": 1337,
        }))
        assert load_deployment_checkpoint(el.id, checkpoint_dir=str(tmp_path)) is None

        # Valid election_id, wrong chain_id vs connected node
        save_deployment_checkpoint(
            election_id=el.id,
            contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
            verifier_address="0x8A791620dd6260079BF849Dc5567aDC3F2FdC318",
            relayer_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            deployment_tx_hash="0x" + "1" * 64,
            deployment_block_number=1,
            deployment_block_hash="0x" + "2" * 64,
            genesis_block_hash="0x" + "3" * 64,
            chain_id=99999,
            candidate_count=2,
            checkpoint_dir=str(tmp_path),
        )

        class _MockContractFn:
            def call(self):
                return el.id

        class _MockContract:
            class functions:
                @staticmethod
                def electionId():
                    return _MockContractFn()

        class _MockEth:
            chain_id = 1337
            block_number = 5

            @staticmethod
            def get_code(_addr):
                return b"\x60" * 6000

        class _MockW3:
            eth = _MockEth()

        with patch("app.services.blockchain_v2_service._DEFAULT_CHECKPOINT_DIR", str(tmp_path)):
            svc = BlockchainV2Service(election_id=el.id, w3_instance=_MockW3())
            with patch.object(svc, "get_contract", return_value=_MockContract()):
                ok, reason = svc.verify_chain_synchronization(el)
                assert ok is False
                assert "chain_id" in reason


def test_phase6_cast_ballot_rejects_mismatched_client_contract_override(app, client, tmp_path):
    with app.app_context():
        el = _make_v2_election("ELEC_P6_CAST", status="OPEN")
        now = datetime.utcnow()
        usn = f"USN_P6_{secrets.token_hex(3)}"
        user = User(username=f"p6_{secrets.token_hex(3)}", email=f"{usn}@college.edu", voter_id=usn, password_hash="x", is_active=True, is_verified=True)
        db.session.add(user)
        db.session.add(ElectoralRoll(usn=usn, college_email=user.email, full_name="P6 Voter", is_eligible=True))
        db.session.commit()

        sid = f"sid_p6_{secrets.token_hex(6)}"
        db.session.add(AuthSession(session_id=sid, user_id=user.id, created_at=now, expires_at=now + timedelta(hours=1), idle_expires_at=now + timedelta(minutes=30), last_activity=now, revoked=False))
        db.session.add(VotingAuthorization(user_id=user.id, election_id=el.id, session_id=sid, wallet_verified=True, face_verified=True, authorized=True, consumed=False, expires_at=now + timedelta(minutes=20)))
        db.session.commit()

        save_deployment_checkpoint(
            election_id=el.id,
            contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
            verifier_address="0x8A791620dd6260079BF849Dc5567aDC3F2FdC318",
            relayer_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            deployment_tx_hash="0x" + "1" * 64,
            deployment_block_number=1,
            deployment_block_hash="0x" + "2" * 64,
            genesis_block_hash="0x" + "3" * 64,
            chain_id=1337,
            candidate_count=2,
            checkpoint_dir=str(tmp_path),
        )

        pseud = derive_pseudonym(user.id, el.id)
        y = point_add(point_mul(G, generate_secure_scalar()), point_mul(G, generate_secure_scalar()))
        bundle = generate_ballot_proof(
            selected_candidate=0,
            candidate_count=2,
            context={"election_id": el.id, "pseudonym": pseud, "sequence": 1, "joint_pub_key": {"x": y[0], "y": y[1]}},
            verifier_address="0x8A791620dd6260079BF849Dc5567aDC3F2FdC318",
            chain_id=1337,
        )

        with client.session_transaction() as sess:
            sess["session_id"] = sid

        with patch("app.services.blockchain_v2_service._DEFAULT_CHECKPOINT_DIR", str(tmp_path)):
            resp = client.post(
                "/api/v2/voting/cast-ballot",
                json={
                    "election_id": el.id,
                    "sequence": 1,
                    "ciphertexts": bundle["ciphertexts"],
                    "proof": bundle["proof"],
                    "contract_address": "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
                },
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "CONTRACT_ELECTION_MISMATCH"

