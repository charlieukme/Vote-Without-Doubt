"""
Security and Hardening Test Suite for FIX 3 V2 (Phase 1 Remediation).
Verifies:
- Strict session, student, election, and single-use authorization binding.
- ElectoralRoll eligibility enforcement with restricted VoterIdentity fallback.
- Atomic authorization consumption with queue rollback.
- Relayer key/account validation, fail-closed mismatch, and unlocked account policy.
- Broadcast uncertainty handling during send_raw_transaction.
- Backend restart persistence blocking subsequent broadcasts.
- Historical evidence preservation and retry blocking for failed sequences.
- Ignoring client-supplied private keys in favor of server relayer.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests.exceptions
from eth_account import Account
from web3.exceptions import TimeExhausted

from app.extensions import db
from app.models import Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.ballot_record_v2 import BallotQueueV2
from app.models.identity import VoterIdentity
from app.models.roll import ElectoralRoll
from app.services.blockchain_v2_service import BlockchainV2Service, BroadcastUncertainError


TEST_RELAYER_KEY = "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
TEST_RELAYER_ADDR = Account.from_key(TEST_RELAYER_KEY).address


@pytest.fixture
def test_setup(app, db):
    """Sets up an eligible user, active election, and auth session."""
    with app.app_context():
        app.config['RELAYER_PRIVATE_KEY'] = TEST_RELAYER_KEY
        app.config['RELAYER_ACCOUNT'] = TEST_RELAYER_ADDR
        app.config['APP_ENV'] = 'testing'

        now = datetime.utcnow()
        uid_suffix = secrets.token_hex(4)
        voter_id_str = f"USN_HARDENING_{uid_suffix}"
        user = User(
            username=f"student_h1_{uid_suffix}",
            email=f"student_{uid_suffix}@college.edu",
            voter_id=voter_id_str,
            password_hash="argon2_fake",
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)

        roll = ElectoralRoll(
            usn=voter_id_str,
            college_email=f"student_{uid_suffix}@college.edu",
            full_name=f"Student Hardening {uid_suffix}",
            is_eligible=True,
        )
        db.session.add(roll)

        election = Election(
            election_id=f"ELEC_HARDEN_{uid_suffix}",
            title="Hardened V2 Election",
            status="ACTIVE",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=24),
            candidate_count=2,
            eligible_count=100,
        )
        db.session.add(election)
        db.session.commit()

        sid = f"hardening_session_{secrets.token_hex(8)}"
        sess = AuthSession(
            session_id=sid,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=2),
            idle_expires_at=now + timedelta(minutes=30),
            last_activity=now,
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()

        return {
            "user_id": user.id,
            "voter_id": voter_id_str,
            "election_id": election.id,
            "session_id": sid,
        }


def _create_auth(user_id, election_id, session_id, **kwargs):
    """Helper to create a VotingAuthorization record with default valid attributes."""
    now = datetime.utcnow()
    params = {
        "user_id": user_id,
        "election_id": election_id,
        "session_id": session_id,
        "wallet_verified": True,
        "face_verified": True,
        "authorized": True,
        "consumed": False,
        "expires_at": now + timedelta(hours=1),
    }
    params.update(kwargs)
    va = VotingAuthorization(**params)
    db.session.add(va)
    db.session.commit()
    return va


# ==============================================================================
# 1. ELIGIBILITY & ELECTORAL ROLL FALLBACK TESTS
# ==============================================================================

def test_electoral_roll_ineligible_blocks_vote(client, test_setup):
    """Explicit ineligibility in ElectoralRoll returns 403 VOTER_NOT_ELIGIBLE without fallback."""
    uid = test_setup["user_id"]
    vid = test_setup["voter_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    roll = ElectoralRoll.query.filter_by(usn=vid).first()
    roll.is_eligible = False
    db.session.commit()

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "VOTER_NOT_ELIGIBLE"


def test_voter_identity_fallback_only_when_no_roll(client, test_setup):
    """When ElectoralRoll record is absent, falls back to VoterIdentity."""
    uid = test_setup["user_id"]
    vid = test_setup["voter_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    # Delete ElectoralRoll record to test fallback
    ElectoralRoll.query.filter_by(usn=vid).delete()
    db.session.commit()

    # Case A: VoterIdentity present and eligible
    v_id = VoterIdentity(
        voter_id=vid,
        full_name="Fallback Voter",
        email=f"fallback_{vid}@college.edu",
        is_eligible=True,
    )
    db.session.add(v_id)
    db.session.commit()

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {"status": 1, "tx_hash": "0xfallback_tx", "block_number": 50}
        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "CONFIRMED"

    # Case B: VoterIdentity explicitly ineligible
    v_id.is_eligible = False
    db.session.commit()
    _create_auth(uid, eid, sid)

    resp2 = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 2, "ciphertexts": [{}], "proof": {}},
    )
    assert resp2.status_code == 403
    assert resp2.get_json()["error"] == "VOTER_NOT_ELIGIBLE"


# ==============================================================================
# 2. AUTHORIZATION EXPIRY, REVOCATION, CONSUMPTION & BINDING
# ==============================================================================

def test_authorization_expired_rejected(client, test_setup):
    """Expired authorization rejected with 403 AUTHORIZATION_EXPIRED."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, sid, expires_at=datetime.utcnow() - timedelta(minutes=5))

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "AUTHORIZATION_EXPIRED"


def test_authorization_already_consumed_rejected(client, test_setup):
    """Consumed authorization rejected with 403 AUTHORIZATION_ALREADY_USED."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, sid, consumed=True, consumed_at=datetime.utcnow())

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "AUTHORIZATION_ALREADY_USED"


def test_authorization_session_mismatch_rejected(client, test_setup):
    """Authorization created under a different session rejected with 403 AUTHORIZATION_SESSION_MISMATCH."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, session_id="different_session_token_999")

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "AUTHORIZATION_SESSION_MISMATCH"


def test_authorization_election_mismatch_rejected(client, test_setup):
    """Authorization created for a different election rejected with 403 UNAUTHORIZED."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, election_id=999999, session_id=sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "UNAUTHORIZED"


def test_authorization_session_revoked_rejected(client, test_setup):
    """Revoked authentication session rejected with 401 NOT_AUTHENTICATED."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    sess = AuthSession.query.filter_by(session_id=sid).first()
    sess.revoked = True
    db.session.commit()

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "NOT_AUTHENTICATED"


def test_authorization_factors_incomplete_rejected(client, test_setup):
    """Authorization with incomplete factors (e.g. face unverified) rejected with 403."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, sid, face_verified=False)

    with client.session_transaction() as session:
        session["session_id"] = sid

    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "AUTHORIZATION_FACTORS_INCOMPLETE"


# ==============================================================================
# 3. ATOMICITY & ROLLBACK TESTS
# ==============================================================================

def test_queue_insertion_failure_rolls_back_authorization(client, test_setup):
    """Failure during BallotQueueV2 insertion rolls back the authorization consumption."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    from app.security.pseudonym import derive_pseudonym
    derive_pseudonym(uid, eid)

    va = _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    with patch.object(db.session, "commit", side_effect=[Exception("Simulated DB Write Error"), None]):
        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={"election_id": eid, "sequence": 1, "ciphertexts": [{}], "proof": {}},
        )
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "BALLOT_QUEUE_FAILED"

    # Reload authorization to verify rollback
    reloaded_va = db.session.get(VotingAuthorization, va.id)
    assert reloaded_va.consumed is False


def test_concurrent_authorization_consumption_atomic(app, test_setup):
    """
    Two simultaneous requests attempting to consume the same VotingAuthorization
    must result in exactly one successful claim and one rejected request.
    Uses threading.Barrier(2) to synchronize both requests immediately before
    the conditional atomic SQL UPDATE statement, verifying that the rejection
    comes strictly from the atomic claim failure (AUTHORIZATION_CONSUMED)
    and not from an earlier serial pre-read check.
    """
    from sqlalchemy.orm import Query

    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    from app.security.pseudonym import derive_pseudonym
    derive_pseudonym(uid, eid)

    va = _create_auth(uid, eid, sid)
    results = []

    # Configure SQLite WAL mode & busy timeout on engine connections to handle concurrent access cleanly
    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(db.text("PRAGMA journal_mode = WAL"))
            conn.execute(db.text("PRAGMA busy_timeout = 30000"))
            conn.commit()

    barrier = threading.Barrier(2, timeout=10)
    original_update = Query.update

    def _synchronized_update(self, *args, **kwargs):
        # Synchronize both requests immediately before executing the atomic SQL UPDATE on VotingAuthorization
        if self.column_descriptions and self.column_descriptions[0].get('entity') == VotingAuthorization:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return original_update(self, *args, **kwargs)

    def _cast_worker():
        with app.app_context():
            client = app.test_client()
            with client.session_transaction() as session:
                session["session_id"] = sid
            resp = client.post(
                "/api/v2/voting/cast-ballot",
                json={
                    "election_id": eid,
                    "sequence": 1,
                    "ciphertexts": [{}],
                    "proof": {},
                    "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
                },
            )
            results.append((resp.status_code, resp.get_json()))

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast, \
         patch.object(Query, "update", new=_synchronized_update):
        mock_cast.return_value = {"status": 1, "tx_hash": "0xconcurrent_tx_123", "block_number": 100}
        t1 = threading.Thread(target=_cast_worker)
        t2 = threading.Thread(target=_cast_worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

    with app.app_context():
        successes = [r for r in results if r[0] == 200]
        failures = [r for r in results if r[0] in (403, 409)]

        assert len(successes) == 1, f"Expected exactly one successful submission, got {len(successes)}: {results}"
        assert len(failures) == 1, f"Expected exactly one rejected submission, got {len(failures)}: {results}"

        # Must fail strictly at the atomic claim, not at the pre-read check
        assert failures[0][0] == 403
        assert failures[0][1]["error"] == "AUTHORIZATION_CONSUMED"
        assert "could not be claimed" in failures[0][1]["message"]

        # Database state: exactly one ballot committed and authorization is consumed
        ballots = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).all()
        assert len(ballots) == 1
        reloaded_va = db.session.get(VotingAuthorization, va.id)
        assert reloaded_va.consumed is True


# ==============================================================================
# 4. RELAYER CREDENTIALS & UNLOCKED ACCOUNT POLICY TESTS
# ==============================================================================

def test_relayer_key_account_mismatch_fails_closed(app):
    """When RELAYER_ACCOUNT does not match the key-derived address, raises RuntimeError."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config['RELAYER_PRIVATE_KEY'] = TEST_RELAYER_KEY
        app.config['RELAYER_ACCOUNT'] = "0x000000000000000000000000000000000000dead"
        app.config['APP_ENV'] = "development"

        with pytest.raises(RuntimeError, match="Security violation: Configured RELAYER_ACCOUNT does not match"):
            service.resolve_relayer_credentials()


def test_relayer_unlocked_account_default_disallowed(app):
    """When ALLOW_DEV_UNLOCKED_RELAYER is unset, it defaults to False and unlocked account fails closed."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config.pop('ALLOW_DEV_UNLOCKED_RELAYER', None)
        app.config['APP_ENV'] = "development"

        with pytest.raises(RuntimeError, match="No valid relayer configuration available"):
            service.resolve_relayer_credentials()


def test_relayer_unlocked_account_rejected_in_production(app):
    """Production strictly forbids unlocked RPC accounts even if ALLOW_DEV_UNLOCKED_RELAYER=True."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = True
        app.config['APP_ENV'] = "production"

        with pytest.raises(RuntimeError, match="strictly requires a configured RELAYER_PRIVATE_KEY"):
            service.resolve_relayer_credentials()


def test_relayer_unlocked_account_rejected_in_staging(app):
    """Staging strictly forbids unlocked RPC accounts even if ALLOW_DEV_UNLOCKED_RELAYER=True."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = True
        app.config['APP_ENV'] = "staging"

        with pytest.raises(RuntimeError, match="strictly requires a configured RELAYER_PRIVATE_KEY"):
            service.resolve_relayer_credentials()


def test_dev_unlocked_relayer_account_validated_against_node(app):
    """In development with ALLOW_DEV_UNLOCKED_RELAYER=True, RELAYER_ACCOUNT must exist in node accounts."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = True
        app.config['APP_ENV'] = "development"
        app.config['RELAYER_ACCOUNT'] = "0x1111111111111111111111111111111111111111"

        mock_w3 = MagicMock()
        mock_w3.eth.accounts = ["0x2222222222222222222222222222222222222222"]
        service._w3 = mock_w3

        with pytest.raises(RuntimeError, match="not available among the RPC node's unlocked accounts"):
            service.resolve_relayer_credentials()


def test_dev_unlocked_relayer_boolean_normalization(app):
    """Verifies that ALLOW_DEV_UNLOCKED_RELAYER accepts only valid truthy booleans/strings in development."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['RELAYER_ACCOUNT'] = None
        app.config['APP_ENV'] = "development"

        mock_w3 = MagicMock()
        mock_w3.eth.accounts = ["0x2222222222222222222222222222222222222222"]
        service._w3 = mock_w3

        # Truthy cases (enabled only in development)
        for truthy in (True, "true", "True", "1", "yes", "on"):
            app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = truthy
            key, addr = service.resolve_relayer_credentials()
            assert key is None
            assert addr == "0x2222222222222222222222222222222222222222"

        # Falsy cases (disabled)
        for falsy in (False, "false", "False", "0", "no", "off", None, ""):
            app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = falsy
            with pytest.raises(RuntimeError, match="No valid relayer configuration available"):
                service.resolve_relayer_credentials()

        # Unexpected cases (fail closed)
        for unexpected in ("random", "2", 123, ["true"]):
            app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = unexpected
            with pytest.raises(RuntimeError, match="No valid relayer configuration available"):
                service.resolve_relayer_credentials()


def test_dev_unlocked_relayer_string_true_rejected_in_production(app):
    """String 'true' must still be rejected unconditionally in production."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['RELAYER_ACCOUNT'] = None
        app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = "true"
        app.config['APP_ENV'] = "production"

        with pytest.raises(RuntimeError, match="strictly requires a configured RELAYER_PRIVATE_KEY"):
            service.resolve_relayer_credentials()


def test_dev_unlocked_relayer_string_true_rejected_in_testing(app):
    """String 'true' must still be rejected unconditionally in testing."""
    with app.app_context():
        service = BlockchainV2Service()
        app.config.pop('RELAYER_PRIVATE_KEY', None)
        app.config['RELAYER_ACCOUNT'] = None
        app.config['ALLOW_DEV_UNLOCKED_RELAYER'] = "true"
        app.config['APP_ENV'] = "testing"

        with pytest.raises(RuntimeError, match="No valid relayer configuration available"):
            service.resolve_relayer_credentials()


# ==============================================================================
# 5. BROADCAST UNCERTAINTY & RESTART PERSISTENCE TESTS
# ==============================================================================

def test_broadcast_transport_timeout_marks_uncertain_and_blocks_retry(client, test_setup):
    """Transport timeout during send_raw_transaction leaves ballot QUEUED/SUBMITTED and blocks retry."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    va = _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    with patch.object(
        BlockchainV2Service,
        "cast_ballot",
        side_effect=BroadcastUncertainError("Transport timeout during send_raw_transaction"),
    ):
        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={"election_id": eid, "sequence": 1, "ciphertexts": [{"x": 1}], "proof": {"z": 2}},
        )
        assert resp.status_code == 504
        data = resp.get_json()
        assert data["error"] == "TRANSACTION_BROADCAST_UNCERTAIN"
        assert data["status"] in ("QUEUED", "SUBMITTED")

    # Verify persistent state: ballot is NOT FAILED, auth is NOT released
    ballot = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
    assert ballot is not None
    assert ballot.state in ("QUEUED", "SUBMITTED")
    assert "Transport timeout" in ballot.error

    reloaded_va = db.session.get(VotingAuthorization, va.id)
    assert reloaded_va.consumed is True

    # Immediate retry attempt rejected as in-flight
    _create_auth(uid, eid, sid)
    resp2 = client.post(
        "/api/v2/voting/cast-ballot",
        json={"election_id": eid, "sequence": 1, "ciphertexts": [{"x": 1}], "proof": {"z": 2}},
    )
    assert resp2.status_code == 409
    assert resp2.get_json()["error"] == "BALLOT_TRANSACTION_IN_FLIGHT"


def test_broadcast_timeout_restart_blocks_subsequent_broadcast(client, test_setup):
    """Simulates server restart after timeout; verifies no additional broadcast occurs."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    with patch.object(
        BlockchainV2Service,
        "cast_ballot",
        side_effect=BroadcastUncertainError("Network timeout on node socket"),
    ):
        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={"election_id": eid, "sequence": 1, "ciphertexts": [{"x": 1}], "proof": {"z": 2}},
        )
        assert resp.status_code == 504

    # Simulate complete backend restart: close SQLAlchemy session, dispose connection cache
    db.session.remove()

    # Verify reloaded records from persistent storage
    ballot = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
    assert ballot.state in ("QUEUED", "SUBMITTED")

    # Spy on BlockchainV2Service.cast_ballot: MUST NOT be called again
    with patch.object(BlockchainV2Service, "cast_ballot") as spy_cast:
        _create_auth(uid, eid, sid)
        resp2 = client.post(
            "/api/v2/voting/cast-ballot",
            json={"election_id": eid, "sequence": 1, "ciphertexts": [{"x": 1}], "proof": {"z": 2}},
        )
        assert resp2.status_code == 409
        assert resp2.get_json()["error"] == "BALLOT_TRANSACTION_IN_FLIGHT"
        spy_cast.assert_not_called()


def test_receipt_polling_timeout_marks_submitted_with_tx_hash(client, test_setup):
    """
    When transaction broadcast succeeds with a tx_hash but receipt polling times out:
    - Ballot state is set to SUBMITTED.
    - Transaction hash is preserved in database and returned in API response.
    - VotingAuthorization remains consumed.
    - Second submission attempt is blocked (BALLOT_TRANSACTION_IN_FLIGHT).
    - Existing transaction evidence is not overwritten.
    """
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    from app.security.pseudonym import derive_pseudonym
    derive_pseudonym(uid, eid)

    va = _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    broadcast_tx_hash = "0x" + "aa" * 32

    with patch.object(
        BlockchainV2Service,
        "cast_ballot",
        side_effect=BroadcastUncertainError(
            f"Confirmation timeout waiting for receipt of transaction {broadcast_tx_hash}",
            tx_hash=broadcast_tx_hash,
        ),
    ):
        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": eid,
                "sequence": 1,
                "ciphertexts": [{"ct": "initial_payload"}],
                "proof": {"proof": "initial_proof"},
                "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            },
        )
        assert resp.status_code == 504
        data = resp.get_json()
        assert data["error"] == "TRANSACTION_BROADCAST_UNCERTAIN"
        assert data["status"] == "SUBMITTED"
        assert data["tx_hash"] == broadcast_tx_hash

    # Verify DB persistence
    ballot = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
    assert ballot is not None
    assert ballot.state == "SUBMITTED"
    assert ballot.tx_hash == broadcast_tx_hash
    assert "Confirmation timeout" in ballot.error

    # Authorization remains consumed
    reloaded_va = db.session.get(VotingAuthorization, va.id)
    assert reloaded_va.consumed is True

    # Attempting to submit another ballot with consumed authorization is blocked with 403
    resp_consumed = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": eid,
            "sequence": 1,
            "ciphertexts": [{"ct": "second_attempt"}],
            "proof": {"proof": "second_proof"},
            "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
        },
    )
    assert resp_consumed.status_code == 403
    assert resp_consumed.get_json()["error"] == "AUTHORIZATION_ALREADY_USED"

    # Even if voter is issued a fresh authorization, submission is blocked with 409 (BALLOT_TRANSACTION_IN_FLIGHT)
    _create_auth(uid, eid, sid)
    resp_retry = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": eid,
            "sequence": 1,
            "ciphertexts": [{"ct": "second_attempt"}],
            "proof": {"proof": "second_proof"},
            "contract_address": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
        },
    )
    assert resp_retry.status_code == 409
    assert resp_retry.get_json()["error"] == "BALLOT_TRANSACTION_IN_FLIGHT"

    # Verify original ballot evidence is completely intact and not overwritten
    db.session.remove()
    reloaded_ballot = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
    assert reloaded_ballot.state == "SUBMITTED"
    assert reloaded_ballot.tx_hash == broadcast_tx_hash
    assert "initial_payload" in reloaded_ballot.ciphertexts_json
    assert "second_attempt" not in reloaded_ballot.ciphertexts_json


# ==============================================================================
# 6. HISTORICAL EVIDENCE PRESERVATION TESTS
# ==============================================================================

def test_historical_ballot_evidence_preserved_on_rejected_retry(client, test_setup):
    """Rejected retries of REVERTED sequences preserve original evidence byte-for-byte."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    from app.security.pseudonym import derive_pseudonym
    p = derive_pseudonym(uid, eid)

    original_cts = json.dumps([{"a": {"x": 10, "y": 20}}])
    original_proof = json.dumps({"z_sum": 9999})
    reverted_ballot = BallotQueueV2(
        election_id=eid,
        pseudonym=p,
        sequence=1,
        ciphertexts_json=original_cts,
        proof_json=original_proof,
        state="REVERTED",
        tx_hash="0xoriginal_reverted_tx",
        block_number=42,
        error="TRANSACTION_REVERTED_ON_CHAIN",
    )
    db.session.add(reverted_ballot)
    db.session.commit()

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    # Attempt to submit a new ballot for the same sequence 1
    resp = client.post(
        "/api/v2/voting/cast-ballot",
        json={
            "election_id": eid,
            "sequence": 1,
            "ciphertexts": [{"a": {"x": 88, "y": 99}}],
            "proof": {"z_sum": 1111},
        },
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "RETRY_BLOCKED_PENDING_MIGRATION"

    # Reload record and verify ZERO mutations
    reloaded = BallotQueueV2.query.filter_by(election_id=eid, sequence=1).first()
    assert reloaded.ciphertexts_json == original_cts
    assert reloaded.proof_json == original_proof
    assert reloaded.tx_hash == "0xoriginal_reverted_tx"
    assert reloaded.block_number == 42
    assert reloaded.state == "REVERTED"
    assert reloaded.sequence == 1


# ==============================================================================
# 7. CLIENT PRIVATE KEY REJECTION & SERVER RELAYER ENFORCEMENT
# ==============================================================================

def test_client_provided_private_key_strictly_ignored(client, test_setup):
    """Client providing sender_private_key in payload does NOT use client key; uses server relayer."""
    uid = test_setup["user_id"]
    eid = test_setup["election_id"]
    sid = test_setup["session_id"]

    _create_auth(uid, eid, sid)

    with client.session_transaction() as session:
        session["session_id"] = sid

    attacker_key = "0x6cbed15c793ce57650b9877cf21164d8d9f449f49cad3add29c0ff4c817ce88e"
    attacker_addr = Account.from_key(attacker_key).address

    with patch.object(BlockchainV2Service, "cast_ballot") as mock_cast:
        mock_cast.return_value = {"status": 1, "tx_hash": "0xrelayer_tx", "block_number": 80}

        resp = client.post(
            "/api/v2/voting/cast-ballot",
            json={
                "election_id": eid,
                "sequence": 1,
                "ciphertexts": [{}],
                "proof": {},
                "sender_private_key": attacker_key,
                "sender_account": attacker_addr,
            },
        )
        assert resp.status_code == 200

        # Assert cast_ballot was invoked with SERVER relayer key, NOT client attacker key
        _, kwargs = mock_cast.call_args
        assert kwargs["sender_address"] == TEST_RELAYER_ADDR
        assert kwargs["private_key"] == TEST_RELAYER_KEY
        assert kwargs["private_key"] != attacker_key
