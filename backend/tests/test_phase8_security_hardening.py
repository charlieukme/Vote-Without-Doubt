"""Phase 8 tests: V2 officer key encryption at rest and finalize-tally auth/relayer enforcement."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from eth_account import Account

from app.extensions import db
from app.models import AdminSession, AdminUser, Candidate, Election
from app.security.password import hash_password
from app.security.v2_keys import V2KeyEncryptionError, decrypt_v2_scalar, encrypt_v2_scalar
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import G, generate_secure_scalar, point_add, point_mul
from app.services.v2_election_manager import V2ElectionManager


def _create_admin_session(role: str, admin_id: str) -> str:
    now = datetime.utcnow()
    user = AdminUser.query.filter_by(admin_id=admin_id).first()
    if not user:
        user = AdminUser(
            admin_id=admin_id,
            name=admin_id,
            email=f"{admin_id.lower()}@college.edu",
            password_hash=hash_password("StrongOfficerPass123!"),
            role=role,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
    token = secrets.token_hex(32)
    db.session.add(
        AdminSession(
            session_token=token,
            admin_id=user.id,
            role=role,
            ip_address="127.0.0.1",
            user_agent="pytest",
            expires_at=now + timedelta(hours=2),
            revoked=False,
        )
    )
    db.session.commit()
    return token


def test_phase8_v2_scalar_encryption_roundtrip_and_legacy_support(app, client):
    with app.app_context():
        app.config["V2_KEY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        scalar = generate_secure_scalar()
        token = encrypt_v2_scalar(scalar)

        assert token.startswith("enc:v1:")
        assert str(scalar) not in token
        assert decrypt_v2_scalar(token) == scalar

        # Legacy unencrypted decimal & hex strings remain readable
        assert decrypt_v2_scalar("123456789") == 123456789
        assert decrypt_v2_scalar("0x1a2b") == 0x1A2B

        # Wrong key fails closed
        app.config["V2_KEY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        app.config["PSEUDONYM_MASTER_KEY"] = None
        with patch.dict("os.environ", {"V2_KEY_ENCRYPTION_KEY": "", "PSEUDONYM_MASTER_KEY": ""}):
            with pytest.raises(V2KeyEncryptionError):
                decrypt_v2_scalar(token)


def test_phase8_provision_encrypts_keys_and_key_status_derives_joint_key(app, client):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="ELEC_P8_ENC",
            title="Phase 8 Encrypted Key Election",
            status="SCHEDULED",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=3),
            candidate_count=2,
            eligible_count=10,
        )
        db.session.add(el)
        db.session.flush()
        db.session.add(Candidate(election_id=el.election_id, candidate_index=0, name="A", department="CS"))
        db.session.add(Candidate(election_id=el.election_id, candidate_index=1, name="B", department="EE"))
        db.session.commit()

        ok, _msg = V2ElectionManager.provision_and_open_election(el.id)
        assert ok is True

        db.session.refresh(el)
        assert el.v2_priv_key_1.startswith("enc:v1:")
        assert el.v2_priv_key_2.startswith("enc:v1:")

        s1 = decrypt_v2_scalar(el.v2_priv_key_1)
        s2 = decrypt_v2_scalar(el.v2_priv_key_2)
        expected_y = point_add(point_mul(G, s1), point_mul(G, s2))

        ks = client.get(f"/api/v2/officer/key-status?election_id={el.id}")
        assert ks.status_code == 200
        jk = ks.get_json()["joint_public_key"]
        assert jk == {"x": str(expected_y[0]), "y": str(expected_y[1])}


def test_phase8_finalize_tally_requires_officer_auth_and_ignores_client_key(app, client):
    relayer_key = "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
    relayer_addr = Account.from_key(relayer_key).address
    attacker_key = "0x6cbed15c793ce57650b9877cf21164d8d9f449f49cad3add29c0ff4c817ce88e"
    attacker_addr = Account.from_key(attacker_key).address

    with app.app_context():
        app.config["RELAYER_PRIVATE_KEY"] = relayer_key
        app.config["RELAYER_ACCOUNT"] = relayer_addr
        now = datetime.utcnow()
        el = Election(
            election_id="ELEC_P8_FIN",
            title="Phase 8 Finalize Security",
            status="CLOSED",
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
            candidate_count=2,
        )
        db.session.add(el)
        db.session.commit()

        off_token = _create_admin_session("OFFICER", "OFFICER_01")
        aud_token = _create_admin_session("AUDITOR", "AUDITOR_01")

        # 1. Unauthenticated rejected
        r_unauth = client.post("/api/v2/voting/finalize-tally", json={"election_id": el.id, "tallies": [1, 0]})
        assert r_unauth.status_code == 401

        # 2. Auditor rejected
        r_aud = client.post(
            "/api/v2/voting/finalize-tally",
            json={"election_id": el.id, "tallies": [1, 0]},
            headers={"Authorization": f"Bearer {aud_token}"},
        )
        assert r_aud.status_code == 403

        # 3. Officer accepted, attacker sender_private_key/sender_account strictly ignored
        with patch.object(BlockchainV2Service, "finalize_tally", return_value={"status": 1, "tx_hash": "0xp8_fin"}) as mock_fin:
            r_ok = client.post(
                "/api/v2/voting/finalize-tally",
                json={
                    "election_id": el.id,
                    "tallies": [1, 0],
                    "sender_account": attacker_addr,
                    "sender_private_key": attacker_key,
                },
                headers={"Authorization": f"Bearer {off_token}"},
            )
            assert r_ok.status_code == 200
            _, kwargs = mock_fin.call_args
            assert kwargs["sender_address"] == relayer_addr
            assert kwargs["private_key"] == relayer_key
            assert kwargs["private_key"] != attacker_key

