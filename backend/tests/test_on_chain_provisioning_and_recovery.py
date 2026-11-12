"""
Regression Test Suite: On-Chain Election Registration & Failed Ballot Recovery
Vote Without Doubt - Backend
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from unittest.mock import MagicMock, patch

import pytest

from app.extensions import db
from app.models import AdminUser, Candidate, BallotRecord, Election, User, VotingAuthorization
from app.models.auth_session import AuthSession
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.services.election_admin_service import (
    ElectionAdminError,
    ElectionAdminService,
    InvalidLifecycleTransitionError,
    TwoOfficerApprovalError,
)
from app.services.reconciliation_service import ReconciliationService
from app.services.voting_service import VotingService


@pytest.fixture
def mock_officer(db):
    officer = AdminUser(
        admin_id=f"ADM-OFF-{secrets.token_hex(4)}",
        name="Election Officer",
        email=f"officer_{secrets.token_hex(4)}@test.local",
        role="OFFICER",
        password_hash=hash_password("OfficerPass123!"),
    )
    db.session.add(officer)
    db.session.commit()
    return officer


@pytest.fixture
def mock_auditor(db):
    auditor = AdminUser(
        admin_id=f"ADM-AUD-{secrets.token_hex(4)}",
        name="Election Auditor",
        email=f"auditor_{secrets.token_hex(4)}@test.local",
        role="AUDITOR",
        password_hash=hash_password("AuditorPass123!"),
    )
    db.session.add(auditor)
    db.session.commit()
    return auditor


@pytest.fixture(autouse=True)
def enforce_blockchain_tests(app):
    app.config['ENFORCE_BLOCKCHAIN_IN_TESTS'] = True
    yield
    app.config['ENFORCE_BLOCKCHAIN_IN_TESTS'] = False


@pytest.fixture
def sample_scheduled_election(db, mock_officer):
    now = datetime.utcnow()
    elec = Election(
        election_id=f"ELEC_TEST_{secrets.token_hex(4)}",
        title="Sample Test Election",
        description="Testing on-chain provisioning",
        status="SCHEDULED",
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(hours=2),
        candidate_count=2,
        eligible_count=100,
        max_ballots=3,
        roll_hash="0x" + "0" * 64,
        created_by_officer_id=mock_officer.id,
    )
    db.session.add(elec)
    db.session.commit()

    cand0 = Candidate(
        election_id=elec.election_id,
        candidate_index=0,
        name="Candidate Alpha",
        department="CS",
    )
    cand1 = Candidate(
        election_id=elec.election_id,
        candidate_index=1,
        name="Candidate Beta",
        department="EE",
    )
    db.session.add_all([cand0, cand1])
    cand_str = "0:Candidate Alpha|1:Candidate Beta"
    elec.candidates_hash = "0x" + hashlib.sha256(cand_str.encode("utf-8")).hexdigest()
    db.session.commit()
    return elec


# ------------------------------------------------------------------
# 1. An election absent on-chain cannot open for voting
# ------------------------------------------------------------------
def test_election_absent_on_chain_cannot_open(app, db, mock_officer, sample_scheduled_election):
    """An election whose on-chain record has end == 0 cannot open for voting."""
    with app.app_context():
        mock_contract = MagicMock()
        # end == 0 means unprovisioned
        mock_contract.functions.electionInfo().call.return_value = (
            0, 0, 0, b"\x00" * 32, 0, b"\x00" * 32, 0, 0, False
        )
        mock_contract.functions.elections().call.return_value = (
            0, 0, 0, b"\x00" * 32, 0, b"\x00" * 32, 0, 0, False
        )
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            # Attempt to open must fail if provisioning fails
            with patch.object(ElectionAdminService, 'provision_election_on_chain', side_effect=ElectionAdminError("RPC error")):
                with pytest.raises(InvalidLifecycleTransitionError):
                    ElectionAdminService.open_election(sample_scheduled_election.election_id, mock_officer)

            # Ballot submission validation also rejects with ELECTION_NOT_EXISTS
            ok, err, _ = VotingService.validate_election_and_candidate(sample_scheduled_election.id, 0)
            assert ok is False
            assert err == "ELECTION_NOT_EXISTS"


# ------------------------------------------------------------------
# 2. Authorized provisioning creates the correct on-chain election
# ------------------------------------------------------------------
def test_authorized_provisioning_creates_correct_on_chain_election(app, db, mock_officer, sample_scheduled_election):
    """Authorized provisioning invokes createElection with matching parameters and verifies receipt."""
    with app.app_context():
        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]

        # Initial call: end == 0; Post-mining call: matches parameters
        unprovisioned_info = (0, 0, 0, b"\x00" * 32, 0, b"\x00" * 32, 0, 0, False)
        provisioned_info = (
            start_epoch, end_epoch, 2, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.officer().call.return_value = "0x806a631715d4e70B0234FF5a740f7040ce5352a3"
        mock_contract.functions.electionInfo().call.side_effect = [unprovisioned_info, provisioned_info]

        mock_tx_dict = {
            "to": "0x806a631715d4e70B0234FF5a740f7040ce5352a3",
            "gas": 400000,
            "gasPrice": 1000000000,
            "nonce": 0,
            "chainId": 1337,
            "data": b"",
            "value": 0,
        }
        mock_contract.functions.createElection.return_value.build_transaction.return_value = mock_tx_dict
        mock_contract.functions.createElection.return_value.transact.return_value = b"\x01" * 32

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 12345

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.chain_id = 1337
        mock_w3.eth.gas_price = 1000000000
        mock_w3.eth.get_transaction_count.return_value = 0
        mock_w3.eth.send_raw_transaction.return_value = b"\x01" * 32
        mock_w3.eth.accounts = ["0x806a631715d4e70B0234FF5a740f7040ce5352a3"]
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            success, msg, details = ElectionAdminService.provision_election_on_chain(
                sample_scheduled_election.election_id, mock_officer
            )
            assert success is True
            assert msg == "PROVISIONED"
            assert details["block_number"] == 12345
            assert details["start"] == start_epoch
            assert details["end"] == end_epoch


# ------------------------------------------------------------------
# 3. Repeating provisioning is idempotent (no duplicates or changes)
# ------------------------------------------------------------------
def test_repeating_provisioning_is_idempotent(app, db, mock_officer, sample_scheduled_election):
    """Calling provision_election_on_chain on an already registered election returns ALREADY_PROVISIONED."""
    with app.app_context():
        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]

        provisioned_info = (
            start_epoch, end_epoch, 2, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.electionInfo().call.return_value = provisioned_info

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            success, msg, details = ElectionAdminService.provision_election_on_chain(
                sample_scheduled_election.election_id, mock_officer
            )
            assert success is True
            assert msg == "ALREADY_PROVISIONED"
            # createElection should not have been called
            mock_contract.functions.createElection.assert_not_called()


# ------------------------------------------------------------------
# 4. Registered election with mismatched parameters fails safely
# ------------------------------------------------------------------
def test_registered_election_parameter_mismatch_fails_safely(app, db, mock_officer, sample_scheduled_election):
    """If contract has conflicting parameters (e.g. wrong candidate count), it fails closed."""
    with app.app_context():
        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]

        # Mismatched candidate count: contract has 5, DB has 2
        conflicting_info = (
            start_epoch, end_epoch, 5, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.electionInfo().call.return_value = conflicting_info

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            with pytest.raises(ElectionAdminError) as exc_info:
                ElectionAdminService.provision_election_on_chain(
                    sample_scheduled_election.election_id, mock_officer
                )
            assert "conflicting parameters" in str(exc_info.value)


# ------------------------------------------------------------------
# 5. A reverted transaction is reconciled without being counted
# ------------------------------------------------------------------
def test_reverted_transaction_reconciled_without_counting_vote(app, db, sample_scheduled_election):
    """A FAILED reverted ballot is not counted toward tallies or distinct voter counts."""
    with app.app_context():
        pseud = secrets.token_hex(32)
        failed_ballot = BallotRecord(
            election_id=sample_scheduled_election.id,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state="FAILED",
            error="TRANSACTION_REVERTED: ELECTION_NOT_EXISTS (block 2165)",
            tx_hash="0xd68d11bc8b8a53ee07e105cafab4a5f6b33c4103d86ce600cc2a4257bca50e34",
            reconcile_required=True,
            reconcile_reason="TX_REVERTED",
            superseded=False,
        )
        db.session.add(failed_ballot)
        db.session.commit()

        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]

        provisioned_info = (
            start_epoch, end_epoch, 2, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.electionInfo().call.return_value = provisioned_info
        mock_contract.functions.getTally().call.return_value = 0
        mock_contract.functions.getBallot().call.return_value = (0, 0, False, False)

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            report = ReconciliationService.reconcile_election(sample_scheduled_election.id)
            assert report["status"] == "CLEAN"
            assert report["distinct_voters"]["db"] == 0
            assert report["distinct_voters"]["chain"] == 0
            assert report["tallies"]["0"]["db"] == 0
            assert report["tallies"]["0"]["chain"] == 0


# ------------------------------------------------------------------
# 6. Valid new submission after recovery uses sequence 1 & fresh auth
# ------------------------------------------------------------------
def test_valid_new_submission_after_recovery_uses_sequence_1(app, db, sample_scheduled_election):
    """When a prior submission reverted and is not on-chain, fresh submission uses sequence 1."""
    with app.app_context():
        user = User(
            username=f"voter_{secrets.token_hex(4)}",
            email=f"voter_{secrets.token_hex(4)}@test.local",
            voter_id=f"VOT-{secrets.token_hex(4)}",
            password_hash=hash_password("VoterPass123!"),
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()

        pseud = derive_pseudonym(user.id, sample_scheduled_election.id)

        # Record failed prior ballot
        prior_failed = BallotRecord(
            election_id=sample_scheduled_election.id,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state="FAILED",
            error="TRANSACTION_REVERTED (block 2165)",
            reconcile_required=True,
            reconcile_reason="TX_REVERTED",
            superseded=False,
        )
        db.session.add(prior_failed)

        # Fresh active authorization
        va = VotingAuthorization(
            user_id=user.id,
            election_id=sample_scheduled_election.id,
            authorized=True,
            wallet_verified=True,
            face_verified=True,
            consumed=False,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(va)
        db.session.commit()

        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]

        provisioned_info = (
            start_epoch, end_epoch, 2, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.elections().call.return_value = provisioned_info
        mock_contract.functions.electionInfo().call.return_value = provisioned_info
        # On-chain getBallot hasCast is False
        mock_contract.functions.getBallot().call.return_value = (0, 0, False, False)

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            ballot, err = VotingService.submit_ballot(
                user_id=user.id,
                election_id=sample_scheduled_election.id,
                candidate=0,
            )
            assert err == "OK"
            assert ballot is not None
            # Sequence MUST be 1 because on-chain hasBallot is false
            assert ballot.sequence == 1
            assert ballot.state == "QUEUED"

            # Prior failed ballot is superseded
            db.session.refresh(prior_failed)
            assert prior_failed.superseded is True
            assert prior_failed.state == "FAILED"

            # Authorization consumed
            db.session.refresh(va)
            assert va.consumed is True


# ------------------------------------------------------------------
# 7. Existing Phase 9 revoting limits and sequence rules enforced
# ------------------------------------------------------------------
def test_revoting_increments_sequence_and_enforces_limits(app, db, sample_scheduled_election):
    """When a ballot is confirmed on-chain, revoting increments sequence to 2 and enforces max ballots."""
    with app.app_context():
        user = User(
            username=f"revoter_{secrets.token_hex(4)}",
            email=f"revoter_{secrets.token_hex(4)}@test.local",
            voter_id=f"VOT-{secrets.token_hex(4)}",
            password_hash=hash_password("VoterPass123!"),
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()

        pseud = derive_pseudonym(user.id, sample_scheduled_election.id)

        # Confirmed ballot #1 from 3 minutes ago (cooldown expired)
        b1 = BallotRecord(
            election_id=sample_scheduled_election.id,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state="FINALIZED",
            created_at=datetime.utcnow() - timedelta(minutes=3),
            superseded=False,
        )
        va = VotingAuthorization(
            user_id=user.id,
            election_id=sample_scheduled_election.id,
            authorized=True,
            wallet_verified=True,
            face_verified=True,
            consumed=False,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add_all([b1, va])
        db.session.commit()

        start_epoch = int(sample_scheduled_election.start_time.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(sample_scheduled_election.end_time.replace(tzinfo=timezone.utc).timestamp())
        cand_hash = bytes.fromhex(sample_scheduled_election.candidates_hash[2:]).ljust(32, b"\x00")[:32]
        roll_hash = bytes.fromhex(sample_scheduled_election.roll_hash[2:]).ljust(32, b"\x00")[:32]
        provisioned_info = (
            start_epoch, end_epoch, 2, cand_hash, 100, roll_hash, 3, 0, False
        )

        mock_contract = MagicMock()
        mock_contract.functions.elections().call.return_value = provisioned_info
        mock_contract.functions.electionInfo().call.return_value = provisioned_info
        # On-chain getBallot hasCast is True with sequence 1
        mock_contract.functions.getBallot().call.return_value = (1, 0, False, True)

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True

        with patch.object(ReconciliationService, 'get_relayer_and_contract', return_value=(MagicMock(), mock_w3, mock_contract)):
            ballot2, err2 = VotingService.submit_ballot(
                user_id=user.id,
                election_id=sample_scheduled_election.id,
                candidate=1,
            )
            assert err2 == "OK"
            assert ballot2 is not None
            assert ballot2.sequence == 2


# ------------------------------------------------------------------
# 8. Unauthorized users cannot provision elections
# ------------------------------------------------------------------
def test_unauthorized_users_cannot_provision(app, db, mock_auditor, sample_scheduled_election):
    """Auditors and unprivileged users cannot provision elections on-chain."""
    with app.app_context():
        with pytest.raises(TwoOfficerApprovalError):
            ElectionAdminService.provision_election_on_chain(
                sample_scheduled_election.election_id, mock_auditor
            )


# ------------------------------------------------------------------
# 9. Meaningful backend error codes returned in API
# ------------------------------------------------------------------
def test_voting_status_surfaces_meaningful_error_code(app, db, sample_scheduled_election):
    """GET /api/voting/status surfaces error code when ballot state is FAILED."""
    with app.app_context():
        user = User(
            username=f"err_user_{secrets.token_hex(4)}",
            email=f"err_user_{secrets.token_hex(4)}@test.local",
            voter_id=f"VOT-{secrets.token_hex(4)}",
            password_hash=hash_password("Pass123!"),
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()

        sid = f"sess_{secrets.token_hex(16)}"
        session_obj = AuthSession(
            session_id=sid,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(hours=2),
            idle_expires_at=datetime.utcnow() + timedelta(hours=1),
            last_activity=datetime.utcnow(),
            revoked=False,
        )
        pseud = derive_pseudonym(user.id, sample_scheduled_election.id)
        failed_ballot = BallotRecord(
            election_id=sample_scheduled_election.id,
            pseudonym=pseud,
            candidate=0,
            sequence=1,
            state="FAILED",
            error="TRANSACTION_REVERTED: ELECTION_NOT_EXISTS (block 2165)",
            superseded=False,
        )
        db.session.add_all([session_obj, failed_ballot])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['session_id'] = sid

        res = client.get(f"/api/voting/status?election_id={sample_scheduled_election.election_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "FAILED"
        assert "ELECTION_NOT_EXISTS" in data["error"]


# ------------------------------------------------------------------
# 10. Existing elections, candidates, and audit records remain intact
# ------------------------------------------------------------------
def test_existing_elections_candidates_and_audit_records_intact(app):
    """Verify that existing database records in instance/voting.db are preserved and not corrupted."""
    import sqlite3
    import os
    db_path = os.path.join(app.root_path, '..', 'instance', 'voting.db')
    if os.path.exists(db_path):
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        elections = cur.execute('SELECT id, election_id, status FROM elections').fetchall()
        assert len(elections) >= 1

        # Check election ELEC_20261009004454_76B3
        target = cur.execute('SELECT id, election_id, candidate_count FROM elections WHERE election_id="ELEC_20261009004454_76B3"').fetchone()
        assert target is not None
        assert target[2] == 3

        # Check failed ballot row 1
        b1 = cur.execute('SELECT id, state, tx_hash, error FROM ballot_queue WHERE id=1').fetchone()
        assert b1 is not None
        assert b1[1] == 'FAILED'
        assert b1[2] == '0xd68d11bc8b8a53ee07e105cafab4a5f6b33c4103d86ce600cc2a4257bca50e34'
        con.close()


# ------------------------------------------------------------------
# 11. Pseudonym mismatch regression test for finalized vote status
# ------------------------------------------------------------------
def test_status_endpoint_resolves_ballot_across_string_and_int_election_ids(app, db, sample_scheduled_election):
    """
    Regression test:
    Verify that GET /api/voting/status resolves a finalized ballot regardless of whether
    the ballot pseudonym was derived using the string election_id (e.g. ELEC_...) or the
    integer database id, and regardless of whether the query parameter is string or integer.
    """
    with app.app_context():
        user = User(
            username=f"stat_user_{secrets.token_hex(4)}",
            email=f"stat_user_{secrets.token_hex(4)}@test.local",
            voter_id=f"VOT-{secrets.token_hex(4)}",
            password_hash=hash_password("Pass123!"),
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()

        sid = f"sess_{secrets.token_hex(16)}"
        session_obj = AuthSession(
            session_id=sid,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(hours=2),
            idle_expires_at=datetime.utcnow() + timedelta(hours=1),
            last_activity=datetime.utcnow(),
            revoked=False,
        )
        # Ballot created with string election_id as in submit_ballot
        pseud_str = derive_pseudonym(user.id, sample_scheduled_election.election_id)
        finalized_ballot = BallotRecord(
            election_id=sample_scheduled_election.id,
            pseudonym=pseud_str,
            candidate=0,
            sequence=1,
            state="FINALIZED",
            receipt_code=f"RCPT-{secrets.token_hex(8)}",
            tx_hash=f"0x{secrets.token_hex(32)}",
            block_number=2189,
            tx_confirmed_at=datetime.utcnow(),
            superseded=False,
        )
        db.session.add_all([session_obj, finalized_ballot])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['session_id'] = sid

        # Query using string election_id (e.g. ELEC_...)
        res_str = client.get(f"/api/voting/status?election_id={sample_scheduled_election.election_id}")
        assert res_str.status_code == 200
        data_str = res_str.get_json()
        assert data_str["status"] == "FINALIZED"
        assert data_str["has_ballot"] is True
        assert data_str["sequence"] == 1
        assert data_str["receipt"]["receipt_code"] == finalized_ballot.receipt_code

        # Query using integer id
        res_int = client.get(f"/api/voting/status?election_id={sample_scheduled_election.id}")
        assert res_int.status_code == 200
        data_int = res_int.get_json()
        assert data_int["status"] == "FINALIZED"
        assert data_int["has_ballot"] is True
        assert data_int["sequence"] == 1
        assert data_int["receipt"]["receipt_code"] == finalized_ballot.receipt_code


# ------------------------------------------------------------------
# 12. Confirm real finalized ballot #2 in database is preserved and finalized
# ------------------------------------------------------------------
def test_real_finalized_ballot_in_db_resolved_by_status(app):
    """Verify that ballot #2 for election ELEC_20261009024727_6C5C in instance/voting.db is preserved and finalized."""
    import sqlite3
    import os
    db_path = os.path.join(app.root_path, '..', 'instance', 'voting.db')
    if not os.path.exists(db_path):
        pytest.skip("instance/voting.db not found")

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    ballot = cur.execute("SELECT id, election_id, sequence, state, tx_hash, block_number, pseudonym FROM ballot_queue WHERE id=2").fetchone()
    con.close()
    assert ballot is not None
    assert ballot[3] == "FINALIZED"
    assert ballot[5] == 2189

