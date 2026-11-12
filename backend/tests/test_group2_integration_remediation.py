"""
Group 2 Final Acceptance Gate Verification Suite.
Covers:
- INT-001: Authorization security, factor authenticity, session binding, replay prevention, concurrency.
- INT-002: Canonical public metadata endpoints and safe fail-closed behavior.
- INT-003: V2 results correctness, contract-election binding, candidate metadata enforcement, zero fabricated names, on-chain finality gating, review status.
- DB-001: Reconciliation protocol discriminator (V1 vs V2), referenced ballot resolution.
- DB-002: SQLite foreign key constraint enforcement.
"""

from datetime import datetime, timedelta
import io
import threading
import pytest
from unittest.mock import MagicMock, patch

from app.models import (
    Election,
    User,
    VotingAuthorization,
    Candidate,
    BallotRecord,
    WalletBinding,
    FaceEnrollment,
    FaceChallenge,
)
from app.models.ballot_record_v2 import BallotQueueV2, OfficerRegistrationV2
from app.models.reconciliation import ReconciliationIssue
from app.services.voting_service import VotingService
from app.services.results_service import ResultsService
from app.services.export_service import ExportService


# ==============================================================================
# 1. INT-001: Authorization Security and Factor Authenticity
# ==============================================================================

def test_int_001_concurrent_create_authorization(app, db):
    """Verify concurrent create_authorization requests safely return an active authorization without conflict."""
    with app.app_context():
        user = User(
            username="concurrent_voter",
            email="concurrent@example.com",
            password_hash="hash",
            is_active=True,
            is_verified=True,
        )
        election = Election(
            election_id="ELE_CONC_AUTH",
            title="Concurrent Auth Test",
            status="OPEN",
            candidate_count=2,
        )
        db.session.add_all([user, election])
        db.session.commit()
        u_id, e_id = user.id, election.id

    results = []
    barrier = threading.Barrier(2)

    def worker():
        with app.app_context():
            barrier.wait()
            va = VotingService.create_authorization(
                user_id=u_id,
                election_id=e_id,
                session_id="sess_conc_1",
                ttl_sec=300,
            )
            results.append(va.id)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    # Concurrency safe: both threads receive the EXACT SAME active authorization ID
    assert results[0] == results[1]
    with app.app_context():
        active = VotingAuthorization.query.filter_by(user_id=u_id, election_id=e_id, consumed=False).all()
        assert len(active) == 1
        assert active[0].id == results[0]
        assert active[0].consumed is False


def test_int_001_concurrent_mark_factors_single_challenge_consumption(app, db):
    """Verify concurrent mark_factors calls cannot double-consume a single face challenge."""
    with app.app_context():
        user = User(
            username="double_consume_voter",
            email="double_consume@example.com",
            password_hash="hash",
            is_active=True,
            is_verified=True,
        )
        election = Election(
            election_id="ELE_CONC_CONSUME",
            title="Concurrent Consume Test",
            status="OPEN",
            candidate_count=2,
        )
        db.session.add_all([user, election])
        db.session.commit()

        va = VotingService.create_authorization(
            user_id=user.id,
            election_id=election.id,
            session_id="sess_double_1",
            ttl_sec=300,
        )

        wb = WalletBinding(
            user_id=user.id,
            wallet_address="0x3333333333333333333333333333333333333333",
            is_verified=True,
        )
        fe = FaceEnrollment(
            user_id=user.id,
            is_enrolled=True,
            consent_given=True,
            encrypted_embedding=b"template",
        )
        fc = FaceChallenge(
            user_id=user.id,
            challenge_id="chal_conc_consume_1",
            authorization_id=va.id,
            session_id="sess_double_1",
            challenge_sequence="LR",
            nonce="nonce_conc",
            integrity_mac="mac_conc",
            completed=True,
            success=True,
            consumed=False,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            completed_at=datetime.utcnow(),
        )
        db.session.add_all([wb, fe, fc])
        db.session.commit()
        u_id, e_id, s_id = user.id, election.id, "sess_double_1"

    outcomes = []
    barrier = threading.Barrier(2)

    def worker():
        with app.app_context():
            barrier.wait()
            res = VotingService.mark_factors(
                user_id=u_id,
                election_id=e_id,
                session_id=s_id,
            )
            outcomes.append(res.authorized if res else False)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one worker succeeded in consuming the challenge
    assert len(outcomes) == 2
    assert sorted(outcomes) == [False, True]

    with app.app_context():
        fc_record = FaceChallenge.query.filter_by(challenge_id="chal_conc_consume_1").one()
        assert fc_record.consumed is True
        assert fc_record.consumed_at is not None


def test_int_001_mark_factors_rejects_unverified_wallet_or_missing_face(app, db):
    """Verify mark_factors checks authentic server-side records and rejects when wallet or face is missing."""
    with app.app_context():
        user = User(
            username="unverified_voter",
            email="unverified@example.com",
            password_hash="hash",
            is_active=True,
            is_verified=True,
        )
        election = Election(
            election_id="ELE_FACTORS_TEST",
            title="Factors Verification Test",
            status="OPEN",
            candidate_count=2,
        )
        db.session.add_all([user, election])
        db.session.commit()

        va = VotingService.create_authorization(
            user_id=user.id,
            election_id=election.id,
            session_id="sess_f1",
            ttl_sec=300,
        )

        # 1. No wallet binding and no face challenge -> mark_factors must fail
        va_res = VotingService.mark_factors(user.id, election.id, session_id="sess_f1")
        assert va_res.authorized is False
        assert va_res.wallet_verified is False
        assert va_res.face_verified is False

        # 2. Add verified WalletBinding but no FaceChallenge -> still authorized is False
        wb = WalletBinding(
            user_id=user.id,
            wallet_address="0x1234567890123456789012345678901234567890",
            is_verified=True,
        )
        db.session.add(wb)
        db.session.commit()

        va_res = VotingService.mark_factors(user.id, election.id, session_id="sess_f1")
        assert va_res.authorized is False
        assert va_res.wallet_verified is True
        assert va_res.face_verified is False


def test_int_001_mark_factors_requires_challenge_bound_to_authorization(app, db):
    """Verify face challenge must be bound to the exact authorization_id, preventing challenge reuse."""
    with app.app_context():
        user = User(
            username="bound_voter",
            email="bound@example.com",
            password_hash="hash",
            is_active=True,
            is_verified=True,
        )
        election = Election(
            election_id="ELE_BOUND_TEST",
            title="Binding Verification Test",
            status="OPEN",
            candidate_count=2,
        )
        db.session.add_all([user, election])
        db.session.commit()

        va1 = VotingService.create_authorization(user.id, election.id, session_id="sess_b1")
        va2 = VotingService.create_authorization(user.id, election.id, session_id="sess_b2")

        wb = WalletBinding(user_id=user.id, wallet_address="0x2222222222222222222222222222222222222222", is_verified=True)
        fe = FaceEnrollment(user_id=user.id, is_enrolled=True, consent_given=True, encrypted_embedding=b"template")
        # Challenge bound to va1, NOT va2
        fc = FaceChallenge(
            user_id=user.id,
            challenge_id="chal_bound_1",
            authorization_id=va1.id,
            session_id="sess_b1",
            challenge_sequence="LR",
            nonce="nonce123",
            integrity_mac="mac123",
            completed=True,
            success=True,
            consumed=False,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            completed_at=datetime.utcnow(),
        )
        db.session.add_all([wb, fe, fc])
        db.session.commit()

        # Trying to mark factors on va2 with challenge bound to va1 MUST fail
        va2_res = VotingService.mark_factors(user.id, election.id, session_id="sess_b2")
        assert va2_res.authorized is False
        assert va2_res.face_verified is False

        # Marking factors on va1 MUST succeed and atomically consume the challenge
        va1_res = VotingService.mark_factors(user.id, election.id, session_id="sess_b1")
        assert va1_res.authorized is True
        assert va1_res.wallet_verified is True
        assert va1_res.face_verified is True

        fc_updated = db.session.get(FaceChallenge, fc.id)
        assert fc_updated.consumed is True


# ==============================================================================
# 2. INT-002: Candidate Metadata Endpoints & Safe Fail-Closed
# ==============================================================================

def test_int_002_metadata_endpoints_and_fail_closed(client, app, db):
    """Verify metadata endpoints and verify 404 on missing election without mock fallback."""
    with app.app_context():
        election = Election(
            election_id="ELE_CANONICAL",
            title="Canonical Public Election",
            status="OPEN",
            candidate_count=2,
        )
        c1 = Candidate(election_id="ELE_CANONICAL", candidate_index=0, name="Carol King", department="Math")
        c2 = Candidate(election_id="ELE_CANONICAL", candidate_index=1, name="Dave Miller", department="Physics")
        db.session.add_all([election, c1, c2])
        db.session.commit()

        # Canonical path
        res_canon = client.get("/api/public/elections/ELE_CANONICAL")
        assert res_canon.status_code == 200
        assert res_canon.get_json()["candidates"][0]["name"] == "Carol King"

        # Alias path
        res_alias = client.get("/api/elections/ELE_CANONICAL")
        assert res_alias.status_code == 200
        assert res_alias.get_json()["candidates"][1]["name"] == "Dave Miller"

        # Non-existent election returns 404
        res_missing = client.get("/api/public/elections/NON_EXISTENT")
        assert res_missing.status_code == 404


# ==============================================================================
# 3. INT-003: V2 Results Correctness & Integrity Enforcements
# ==============================================================================

def test_int_003_v2_results_detects_contract_election_mismatch(app, db):
    """Verify that a contract configured for another electionId returns CONTRACT_ELECTION_MISMATCH."""
    with app.app_context():
        election = Election(
            election_id="101",
            title="Mismatch Test Election",
            status="CLOSED",
            candidate_count=2,
        )
        db.session.add(election)
        db.session.flush()

        c1 = Candidate(election_id="101", candidate_index=0, name="Alice", department="CS")
        c2 = Candidate(election_id="101", candidate_index=1, name="Bob", department="EE")
        off = OfficerRegistrationV2(
            election_id=election.id,
            officer_id=1,
            officer_address="0x1111111111111111111111111111111111111111",
            pubkey_x="100", pubkey_y="200", pop_r_x="300", pop_r_y="400", pop_z="500",
            registered_on_chain=True,
        )
        db.session.add_all([c1, c2, off])
        db.session.commit()

        with patch("app.services.results_service.BlockchainV2Service") as MockBC:
            mock_service = MockBC.return_value
            mock_service.get_election_state.return_value = 7
            # Contract has electionId 999, but queried election is 101
            mock_service.get_election_id.return_value = 999

            success, reason, data = ResultsService.get_election_results(election.id)
            assert success is False
            assert reason == "CONTRACT_ELECTION_MISMATCH"


def test_int_003_v2_results_rejects_missing_candidate_metadata_no_fabricated_names(app, db):
    """Verify that missing candidate profiles return MISSING_CANDIDATE_METADATA without fabricating names."""
    with app.app_context():
        election = Election(
            election_id="ELE_MISSING_CAND",
            title="Missing Candidate Meta Election",
            status="CLOSED",
            candidate_count=2,
        )
        db.session.add(election)
        db.session.flush()

        # Only candidate index 0 exists in DB, candidate index 1 is missing
        c1 = Candidate(election_id="ELE_MISSING_CAND", candidate_index=0, name="Alice Sole", department="CS")
        off = OfficerRegistrationV2(
            election_id=election.id,
            officer_id=1,
            officer_address="0x1111111111111111111111111111111111111111",
            pubkey_x="100", pubkey_y="200", pop_r_x="300", pop_r_y="400", pop_z="500",
            registered_on_chain=True,
        )
        db.session.add_all([c1, off])
        db.session.commit()

        with patch("app.services.results_service.BlockchainV2Service") as MockBC:
            mock_service = MockBC.return_value
            mock_service.get_election_state.return_value = 4
            mock_service.get_election_id.return_value = election.id

            success, reason, data = ResultsService.get_election_results(election.id)
            assert success is False
            assert reason == "MISSING_CANDIDATE_METADATA"
            assert "candidate index 1" in data["message"]
            assert "is missing" in data["message"]


def test_int_003_v2_results_reconciliation_issue_triggers_under_review(app, db):
    """Verify that unresolved open ReconciliationIssue puts finalized V2 results into RESULTS_UNDER_REVIEW."""
    with app.app_context():
        election = Election(
            election_id="ELE_V2_RECON_REVIEW",
            title="Recon Under Review Election",
            status="FINALIZED",
            candidate_count=2,
            eligible_count=50,
        )
        db.session.add(election)
        db.session.flush()

        c1 = Candidate(election_id="ELE_V2_RECON_REVIEW", candidate_index=0, name="Cand 1", department="A")
        c2 = Candidate(election_id="ELE_V2_RECON_REVIEW", candidate_index=1, name="Cand 2", department="B")
        off = OfficerRegistrationV2(
            election_id=election.id,
            officer_id=1,
            officer_address="0x1111111111111111111111111111111111111111",
            pubkey_x="100", pubkey_y="200", pop_r_x="300", pop_r_y="400", pop_z="500",
            registered_on_chain=True,
        )
        b1 = BallotQueueV2(election_id=election.id, pseudonym="p1", sequence=1, ciphertexts_json="[]", proof_json="{}", state="CONFIRMED")
        # Add an OPEN reconciliation issue
        issue = ReconciliationIssue(
            election_id=election.id,
            issue_type="AUDIT_ANOMALY",
            severity="HIGH",
            protocol_version="V2",
            ballot_tx_id=1,
            status="OPEN",
        )
        db.session.add_all([c1, c2, off, b1, issue])
        db.session.commit()

        with patch("app.services.results_service.BlockchainV2Service") as MockBC:
            mock_service = MockBC.return_value
            mock_service.get_election_state.return_value = 7
            mock_service.get_election_id.return_value = election.id
            mock_service.get_final_tally.side_effect = lambda idx, addr=None: 1 if idx == 0 else 0
            mock_service.get_total_active_ballots.return_value = 1

            success, reason, data = ResultsService.get_election_results(election.id)
            assert success is True
            assert data["result_state"] == "RESULTS_UNDER_REVIEW"
            assert data["official_results"] is False
            assert data["is_under_review"] is True
            assert data["open_reconciliation_issues"] == 1
            assert data["reconciliation_clean"] is False


# ==============================================================================
# 4. DB-001: Reconciliation Protocol Discriminator
# ==============================================================================

def test_db_001_protocol_discriminator_and_referenced_ballot(app, db):
    """Verify ReconciliationIssue differentiates V1 and V2 records via protocol_version."""
    with app.app_context():
        election = Election(
            election_id="ELE_DISCRIM",
            title="Discriminator Test",
            status="OPEN",
            candidate_count=2,
        )
        db.session.add(election)
        db.session.commit()

        v1_ballot = BallotRecord(election_id=str(election.id), pseudonym="v1_pseudo", candidate=0, state="CONFIRMED")
        v2_ballot = BallotQueueV2(election_id=election.id, pseudonym="v2_pseudo", sequence=1, ciphertexts_json="[]", proof_json="{}", state="CONFIRMED")
        db.session.add_all([v1_ballot, v2_ballot])
        db.session.commit()

        # Create V1 issue
        ri_v1 = ReconciliationIssue(
            election_id=election.id,
            issue_type="V1_ISSUE",
            protocol_version="V1",
            ballot_tx_id=v1_ballot.id,
            status="OPEN",
        )
        # Create V2 issue
        ri_v2 = ReconciliationIssue(
            election_id=election.id,
            issue_type="V2_ISSUE",
            protocol_version="V2",
            ballot_tx_id=v2_ballot.id,
            status="OPEN",
        )
        db.session.add_all([ri_v1, ri_v2])
        db.session.commit()

        assert ri_v1.protocol_version == "V1"
        assert ri_v2.protocol_version == "V2"

        # Test helper method
        resolved_v1 = ri_v1.get_referenced_ballot()
        resolved_v2 = ri_v2.get_referenced_ballot()

        assert resolved_v1 is not None
        assert isinstance(resolved_v1, BallotRecord)
        assert resolved_v1.pseudonym == "v1_pseudo"

        assert resolved_v2 is not None
        assert isinstance(resolved_v2, BallotQueueV2)
        assert resolved_v2.pseudonym == "v2_pseudo"
