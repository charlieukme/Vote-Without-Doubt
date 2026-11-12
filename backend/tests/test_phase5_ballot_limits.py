"""Phase 5 tests: V2 max ballots ceiling, cooldown enforcement, and status parity."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models import Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.ballot_record_v2 import BallotQueueV2
from app.models.roll import ElectoralRoll
from app.security.pseudonym import derive_pseudonym
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import G, generate_ballot_proof, generate_secure_scalar, point_add, point_mul


def _setup_v2_voter(app, username: str, usn: str, max_ballots: int = 3):
    now = datetime.utcnow()
    user = User(
        username=username,
        email=f"{username}@college.edu",
        voter_id=usn,
        password_hash="argon2_fake",
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    roll = ElectoralRoll(
        usn=usn,
        college_email=f"{username}@college.edu",
        full_name=f"Voter {username}",
        is_eligible=True,
    )
    db.session.add(roll)
    el = Election(
        election_id=f"ELEC_P5_{secrets.token_hex(4)}",
        title="Phase 5 Limit Election",
        status="OPEN",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=4),
        candidate_count=2,
        eligible_count=100,
        max_ballots=max_ballots,
        v2_priv_key_1=str(generate_secure_scalar()),
        v2_priv_key_2=str(generate_secure_scalar()),
    )
    db.session.add(el)
    db.session.commit()

    sid = f"sid_p5_{secrets.token_hex(6)}"
    db.session.add(
        AuthSession(
            session_id=sid,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=2),
            idle_expires_at=now + timedelta(minutes=30),
            last_activity=now,
            revoked=False,
        )
    )
    db.session.commit()
    return user.id, sid, el.id


def _issue_va(uid: int, eid: int, sid: str) -> VotingAuthorization:
    now = datetime.utcnow()
    va = VotingAuthorization(
        user_id=uid,
        election_id=eid,
        session_id=sid,
        wallet_verified=True,
        face_verified=True,
        authorized=True,
        consumed=False,
        expires_at=now + timedelta(minutes=20),
    )
    db.session.add(va)
    db.session.commit()
    return va


def _ballot_payload(eid: int, uid: int, seq: int, cand_idx: int):
    pseud = derive_pseudonym(uid, eid)
    y = point_add(point_mul(G, generate_secure_scalar()), point_mul(G, generate_secure_scalar()))
    bundle = generate_ballot_proof(
        selected_candidate=cand_idx,
        candidate_count=2,
        context={"election_id": eid, "pseudonym": pseud, "sequence": seq, "joint_pub_key": {"x": y[0], "y": y[1]}},
        verifier_address="0x8A791620dd6260079BF849Dc5567aDC3F2FdC318",
        chain_id=1337,
    )
    return {
        "election_id": eid,
        "sequence": seq,
        "ciphertexts": bundle["ciphertexts"],
        "proof": bundle["proof"],
        "contract_address": "0x610178dA211FEF7D417bC0e6FeD39F05609AD788",
    }


def test_phase5_v2_max_ballots_enforced_and_respects_election_cap(app, client):
    with app.app_context():
        app.config["REVOTE_COOLDOWN_SECONDS"] = 0
        app.config["MAX_BALLOTS_PER_VOTER"] = 3

        uid, sid, eid = _setup_v2_voter(app, f"p5_max_{secrets.token_hex(3)}", f"USN_P5_{secrets.token_hex(3)}", max_ballots=2)
        with client.session_transaction() as sess:
            sess["session_id"] = sid

        st0 = client.get(f"/api/v2/voting/status?election_id={eid}").get_json()
        assert st0["max_ballots"] == 2

        with patch.object(BlockchainV2Service, "cast_ballot", side_effect=[
            {"status": 1, "tx_hash": "0xp5_1", "block_number": 10},
            {"status": 1, "tx_hash": "0xp5_2", "block_number": 11},
        ]):
            _issue_va(uid, eid, sid)
            r1 = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 1, 0))
            assert r1.status_code == 200

            _issue_va(uid, eid, sid)
            r2 = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 2, 1))
            assert r2.status_code == 200

        va3 = _issue_va(uid, eid, sid)
        r3 = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 3, 0))
        assert r3.status_code == 409
        body3 = r3.get_json()
        assert body3["error"] == "MAX_BALLOTS_EXCEEDED"
        assert body3["max_ballots"] == 2
        assert body3["submissions_used"] == 2

        db.session.refresh(va3)
        assert va3.consumed is False

        pseud = derive_pseudonym(uid, eid)
        rows = BallotQueueV2.query.filter_by(election_id=eid, pseudonym=pseud).order_by(BallotQueueV2.sequence.asc()).all()
        assert [r.sequence for r in rows] == [1, 2]
        assert rows[0].superseded is True
        assert rows[1].superseded is False


def test_phase5_v2_cooldown_enforced_and_expires(app, client):
    with app.app_context():
        app.config["REVOTE_COOLDOWN_SECONDS"] = 120
        app.config["MAX_BALLOTS_PER_VOTER"] = 3

        uid, sid, eid = _setup_v2_voter(app, f"p5_cd_{secrets.token_hex(3)}", f"USN_P5C_{secrets.token_hex(3)}", max_ballots=3)
        with client.session_transaction() as sess:
            sess["session_id"] = sid

        with patch.object(BlockchainV2Service, "cast_ballot", return_value={"status": 1, "tx_hash": "0xp5_cd1", "block_number": 20}):
            _issue_va(uid, eid, sid)
            r1 = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 1, 0))
            assert r1.status_code == 200

        st_cd = client.get(f"/api/v2/voting/status?election_id={eid}").get_json()
        assert st_cd["cooldown_active"] is True
        assert st_cd["cooldown_remaining_sec"] > 0
        assert st_cd["can_revote"] is False

        va2 = _issue_va(uid, eid, sid)
        r2_blocked = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 2, 1))
        assert r2_blocked.status_code == 429
        assert r2_blocked.get_json()["error"] == "COOLDOWN_ACTIVE"
        assert r2_blocked.get_json()["cooldown_remaining_sec"] > 0

        db.session.refresh(va2)
        assert va2.consumed is False

        # Age confirmation beyond 120s window
        b1 = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
        b1.tx_confirmed_at = datetime.utcnow() - timedelta(seconds=130)
        b1.created_at = datetime.utcnow() - timedelta(seconds=130)
        db.session.commit()

        st_ok = client.get(f"/api/v2/voting/status?election_id={eid}").get_json()
        assert st_ok["cooldown_active"] is False
        assert st_ok["can_revote"] is True

        with patch.object(BlockchainV2Service, "cast_ballot", return_value={"status": 1, "tx_hash": "0xp5_cd2", "block_number": 21}):
            r2_ok = client.post("/api/v2/voting/cast-ballot", json=_ballot_payload(eid, uid, 2, 1))
            assert r2_ok.status_code == 200

