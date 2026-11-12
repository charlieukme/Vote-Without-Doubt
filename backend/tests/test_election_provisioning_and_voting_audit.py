"""
Comprehensive Regression Test Suite:
Election Provisioning, Candidate Association, Lifecycle Governance, and Student Ballot Routing
Vote Without Doubt (VWD)
"""

import os
import hashlib
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import MagicMock, patch

from app import create_app
from app.extensions import db
from app.models.admin import AdminUser, Candidate, ApprovalRequest
from app.models.ballot import Election
from app.models import BallotRecord
from app.models.roll import ElectoralRoll
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.security.pseudonym import derive_pseudonym
from app.services.election_admin_service import ElectionAdminService, ElectionAdminError
from app.services.voting_service import VotingService


@pytest.fixture
def isolated_app(tmp_path):
    test_db = tmp_path / "test_election_audit.db"
    old_db = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db}"

    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{test_db}"

    with app.app_context():
        db.create_all()

        # Seed two distinct officers
        officer1 = AdminUser(
            admin_id="OFFICER_01",
            name="Chief Election Officer",
            email="officer1@votewithoutdoubt.local",
            password_hash="argon2id_hash_1",
            role="OFFICER",
            is_active=True,
        )
        officer2 = AdminUser(
            admin_id="OFFICER_02",
            name="Deputy Election Officer",
            email="officer2@votewithoutdoubt.local",
            password_hash="argon2id_hash_2",
            role="OFFICER",
            is_active=True,
        )
        db.session.add_all([officer1, officer2])

        # Seed eligible roll
        roll = ElectoralRoll(
            usn="1XX23CS000",
            full_name="Test Student",
            college_email="student@example.edu",
            is_eligible=True,
            department="CSE",
            year_of_study=3,
        )
        db.session.add(roll)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

    if old_db:
        os.environ["DATABASE_URL"] = old_db
    else:
        os.environ.pop("DATABASE_URL", None)


def test_admin_create_draft_and_add_candidates(isolated_app):
    """Admin creates election draft, adds candidates, and candidate_count stays consistent."""
    with isolated_app.app_context():
        officer1 = AdminUser.query.filter_by(admin_id="OFFICER_01").first()

        now = datetime.utcnow()
        ele = ElectionAdminService.create_election(
            election_id="ELEC_TEST_DRAFT",
            title="General Council 2026",
            description="Student council voting",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=5),
            officer=officer1,
        )
        assert ele.status == "DRAFT"
        assert ele.candidate_count == 0

        # Add candidate 1
        c1 = ElectionAdminService.add_candidate(ele.election_id, "Candidate Alpha", officer1, department="CSE")
        assert c1.candidate_index == 0
        assert ele.candidate_count == 1

        # Add candidate 2
        c2 = ElectionAdminService.add_candidate(ele.election_id, "Candidate Beta", officer1, department="ECE")
        assert c2.candidate_index == 1
        assert ele.candidate_count == 2

        # Check candidate count consistency
        cands = Candidate.query.filter_by(election_id=ele.election_id).order_by(Candidate.candidate_index.asc()).all()
        assert len(cands) == 2
        assert [c.candidate_index for c in cands] == [0, 1]
        assert ele.candidates_hash is not None


def test_schedule_requires_minimum_two_candidates(isolated_app):
    """Scheduling fails if election has fewer than 2 candidates."""
    with isolated_app.app_context():
        officer1 = AdminUser.query.filter_by(admin_id="OFFICER_01").first()

        now = datetime.utcnow()
        ele = ElectionAdminService.create_election(
            election_id="ELEC_TEST_SOLO",
            title="Solo Runner",
            description="Only 1 candidate",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=5),
            officer=officer1,
        )
        ElectionAdminService.add_candidate(ele.election_id, "Solo Runner", officer1)

        with pytest.raises(ValueError, match="at least 2 candidates"):
            ElectionAdminService.request_approval(
                ele.election_id,
                action_type="SCHEDULE_ELECTION",
                requester=officer1,
            )


def test_two_officer_approval_and_blockchain_provisioning(isolated_app):
    """Two-officer approval enforces four-eyes principle and synchronizes on-chain provisioning parameters."""
    with isolated_app.app_context():
        officer1 = AdminUser.query.filter_by(admin_id="OFFICER_01").first()
        officer2 = AdminUser.query.filter_by(admin_id="OFFICER_02").first()

        now = datetime.utcnow()
        start = now + timedelta(hours=1)
        end = now + timedelta(hours=5)

        ele = ElectionAdminService.create_election(
            election_id="ELEC_TEST_PROV",
            title="Approved Election",
            description="Testing provisioning",
            start_time=start,
            end_time=end,
            officer=officer1,
        )
        ElectionAdminService.add_candidate(ele.election_id, "Alice", officer1)
        ElectionAdminService.add_candidate(ele.election_id, "Bob", officer1)

        # Officer 1 requests schedule
        req = ElectionAdminService.request_approval(ele.election_id, action_type="SCHEDULE_ELECTION", requester=officer1)
        assert ele.status == "PENDING_APPROVAL"

        # Self-approval must be rejected
        with pytest.raises(Exception, match="Self-approval is strictly forbidden"):
            ElectionAdminService.approve_request(req.id, officer1)

        # Mock Web3 and smart contract for provisioning
        mock_contract = MagicMock()
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.chain_id = 1337
        mock_w3.eth.accounts = ["0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"]
        mock_contract.functions.officer().call.return_value = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

        # Simulate on-chain contract state matching post-provisioning
        start_epoch = int(start.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(end.replace(tzinfo=timezone.utc).timestamp())
        cand_str = "0:Alice|1:Bob"
        cand_hash = bytes.fromhex(hashlib.sha256(cand_str.encode("utf-8")).hexdigest())

        election_data = [
            start_epoch, end_epoch, 2, cand_hash, 100, b"\x00" * 32, 3, 0, False
        ]
        mock_contract.functions.elections(ele.id).call.return_value = election_data
        mock_contract.functions.electionInfo(ele.id).call.return_value = election_data
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 10
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        with patch("app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract", return_value=(MagicMock(), mock_w3, mock_contract)):
            ElectionAdminService.approve_request(req.id, officer2)

            assert ele.status == "SCHEDULED"
            assert ele.approved_by_officer_id == officer2.id

            # Verify post-provisioning verification returns PROVISIONED_MATCH without parameter mismatch
            valid, status, details = ElectionAdminService.verify_on_chain_provisioning(ele.election_id)
            assert valid is True
            assert status == "PROVISIONED_MATCH"
            assert details["candidate_count"] == 2


def test_zero_candidate_election_rejected_for_voting(isolated_app):
    """Voting service rejects ballot attempts for elections with fewer than 2 candidates."""
    with isolated_app.app_context():
        # Manually create an election with 0 candidates in ACTIVE status
        ele = Election(
            election_id="ELEC_EMPTY_01",
            title="Empty Election",
            status="ACTIVE",
            start_time=datetime.utcnow() - timedelta(minutes=10),
            end_time=datetime.utcnow() + timedelta(hours=2),
            candidate_count=0,
        )
        db.session.add(ele)
        db.session.commit()

        # Validating candidates on this election must fail with ELECTION_NO_CANDIDATES
        ok, err, count = VotingService.validate_election_and_candidate(ele.id, candidate=0)
        assert ok is False
        assert err == "ELECTION_NO_CANDIDATES"


def test_invalid_candidate_bounds_rejection(isolated_app):
    """Candidate bounds check rejects out-of-bounds and negative indices."""
    with isolated_app.app_context():
        ele = Election(
            election_id="ELEC_VALID_01",
            title="Two Candidate Election",
            status="ACTIVE",
            start_time=datetime.utcnow() - timedelta(minutes=10),
            end_time=datetime.utcnow() + timedelta(hours=2),
            candidate_count=2,
        )
        db.session.add(ele)
        db.session.flush()

        c0 = Candidate(election_id=ele.election_id, candidate_index=0, name="Alpha")
        c1 = Candidate(election_id=ele.election_id, candidate_index=1, name="Beta")
        db.session.add_all([c0, c1])
        db.session.commit()

        # Index 0: valid
        ok, err, _ = VotingService.validate_election_and_candidate(ele.id, candidate=0)
        assert ok is True

        # Index 1: valid
        ok, err, _ = VotingService.validate_election_and_candidate(ele.id, candidate=1)
        assert ok is True

        # Index 2: invalid (>= 2)
        ok, err, _ = VotingService.validate_election_and_candidate(ele.id, candidate=2)
        assert ok is False
        assert err == "INVALID_CANDIDATE"

        # Index -1 without null ballot: invalid
        ok, err, _ = VotingService.validate_election_and_candidate(ele.id, candidate=-1, is_null=False)
        assert ok is False
        assert err == "INVALID_CANDIDATE"

        # Null ballot: valid
        ok, err, _ = VotingService.validate_election_and_candidate(ele.id, candidate=-1, is_null=True)
        assert ok is True


def test_authoritative_election_selection_skips_zero_candidates(isolated_app):
    """Voting resolution skips zero-candidate elections and selects the valid candidate-populated election."""
    with isolated_app.app_context():
        from app.routes.voting import _resolve_default_election

        # 1. Zero candidate election
        e_empty = Election(
            election_id="ELEC_EMPTY_RECENT",
            title="Empty Election",
            status="OPEN",
            candidate_count=0,
            start_time=datetime.utcnow() - timedelta(minutes=5),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )
        # 2. Populated candidate election
        e_valid = Election(
            election_id="ELEC_VALID_OLDER",
            title="Valid Election",
            status="OPEN",
            candidate_count=2,
            start_time=datetime.utcnow() - timedelta(minutes=10),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add_all([e_empty, e_valid])
        db.session.flush()

        c0 = Candidate(election_id=e_valid.election_id, candidate_index=0, name="C1")
        c1 = Candidate(election_id=e_valid.election_id, candidate_index=1, name="C2")
        db.session.add_all([c0, c1])
        db.session.commit()

        # Default election must resolve to e_valid, not e_empty
        chosen = _resolve_default_election()
        assert chosen.election_id == "ELEC_VALID_OLDER"


def test_ballot_failed_state_and_safe_retry_integrity(isolated_app):
    """Authoritative ballot status correctly distinguishes FAILED from FINALIZED and enables safe retry."""
    with isolated_app.app_context():
        user = User(
            id=101,
            username="student1",
            email="student1@example.com",
            password_hash="hash",
            voter_id="1XX23CS000",
            is_active=True,
            is_verified=True,
        )
        db.session.add(user)
        db.session.flush()

        ele = Election(
            id=99,
            election_id="ELEC_TEST_BALLOT",
            title="Active Election",
            status="OPEN",
            candidate_count=2,
            start_time=datetime.utcnow() - timedelta(minutes=10),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(ele)
        db.session.flush()

        p = derive_pseudonym(101, 99)

        # Failed ballot without tx broadcast
        b_failed = BallotRecord(
            election_id=ele.id,
            pseudonym=p,
            candidate=0,
            sequence=1,
            state="FAILED",
            error="NO_CONTRACT_ADDRESS",
            tx_hash=None,
            tx_broadcast_at=None,
            tx_confirmed_at=None,
        )
        db.session.add(b_failed)
        db.session.commit()

        # Build mock auth session
        sess = AuthSession(
            session_id="test_sess_id",
            user_id=101,
            auth_state="AUTHORIZED",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            idle_expires_at=datetime.utcnow() + timedelta(minutes=15),
            last_activity=datetime.utcnow(),
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()

        client = isolated_app.test_client()
        with client.session_transaction() as s:
            s["session_id"] = "test_sess_id"

        with patch("app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract") as mock_relayer:
            mock_relayer.return_value = (MagicMock(), None, None)
            res = client.get(f"/api/voting/status?election_id={ele.election_id}")
            assert res.status_code == 200
            data = res.get_json()

            assert data["has_ballot"] is True
            assert data["status"] == "FAILED"
            assert data["finalized"] is False
            assert data["retry_allowed"] is True
            assert data["retry_blocked_reason"] is None
            assert data["ballot_count"] == 0  # Failed attempt does not count against quota
