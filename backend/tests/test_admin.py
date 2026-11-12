"""
Phase 11: Admin & Election Management Test Suite
Vote Without Doubt - Backend

Tests covering:
  1. Admin Authentication (password + RFC 6238 TOTP, brute force lockout, session revocation)
  2. Role-Based Access Control (RBAC: OFFICER vs AUDITOR)
  3. Election Lifecycle State Machine (DRAFT -> PENDING_APPROVAL -> SCHEDULED -> OPEN -> CLOSED -> FINALIZED)
  4. Two-Officer Approval Mechanism (four-eyes enforcement, self-approval prevention, stale request rejection)
  5. Post-Scheduling Immutability (freeze candidates, dates, roll hash, eligible count)
  6. Administrative Audit Trail (SHA-256 hash chaining, zero voter choice leakage)
  7. Privacy-Preserving Operational Disputes (diagnostics without candidate or ballot content exposure)
  8. Concurrency & Race Conditions (concurrent approvals, atomic state transitions)
"""

import hashlib
import time
from datetime import datetime, timedelta
import pytest
from app.extensions import db
from app.models.admin import AdminUser, AdminSession, ApprovalRequest, Candidate
from app.models.ballot import Election
from app.models.auth import User
from app.models.face import FaceEnrollment
from app.models.wallet import WalletBinding
from app.models.roll import ElectoralRoll
from app.models.audit_event import AuditEvent
from app.security.admin_auth import AdminAuthService
from app.security.totp import generate_totp_secret, generate_totp_code
from app.services.election_admin_service import (
    ElectionAdminService,
    TwoOfficerApprovalError,
    ElectionImmutabilityError,
    InvalidLifecycleTransitionError,
)
from app.services.dispute_service import DisputeService


@pytest.fixture
def officers(db):
    """Fixture providing two officers and one auditor."""
    officer1, secret1 = AdminAuthService.create_admin(
        admin_id="OFFICER_01",
        name="Chief Election Officer 1",
        email="officer1@election.local",
        password="ValidAdminPassword123!",
        role="OFFICER",
    )
    officer2, secret2 = AdminAuthService.create_admin(
        admin_id="OFFICER_02",
        name="Chief Election Officer 2",
        email="officer2@election.local",
        password="ValidAdminPassword456!",
        role="OFFICER",
    )
    auditor, aud_secret = AdminAuthService.create_admin(
        admin_id="AUDITOR_01",
        name="Election Auditor 1",
        email="auditor1@election.local",
        password="ValidAuditorPassword789!",
        role="AUDITOR",
    )
    return {
        "officer1": (officer1, secret1),
        "officer2": (officer2, secret2),
        "auditor": (auditor, aud_secret),
    }


def login_admin(client, admin_id, password, secret, for_time=None):
    """Helper to login an admin and return authorization headers."""
    code = generate_totp_code(secret, for_time=for_time)
    res = client.post("/api/admin/auth/login", json={
        "admin_id": admin_id,
        "password": password,
        "totp_code": code,
    })
    assert res.status_code == 200, res.get_json()
    token = res.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# SECTION 1: ADMIN AUTHENTICATION & SESSION MANAGEMENT
# ==============================================================================

class TestAdminAuthentication:
    def test_successful_login(self, client, officers):
        officer1, secret1 = officers["officer1"]
        code = generate_totp_code(secret1)
        res = client.post("/api/admin/auth/login", json={
            "admin_id": officer1.admin_id,
            "password": "ValidAdminPassword123!",
            "totp_code": code,
        })
        assert res.status_code == 200
        data = res.get_json()
        assert "token" in data
        assert data["admin"]["admin_id"] == "OFFICER_01"
        assert data["admin"]["role"] == "OFFICER"

    def test_invalid_password_rejected(self, client, officers):
        officer1, secret1 = officers["officer1"]
        code = generate_totp_code(secret1)
        res = client.post("/api/admin/auth/login", json={
            "admin_id": officer1.admin_id,
            "password": "WrongPassword!",
            "totp_code": code,
        })
        assert res.status_code == 401
        assert res.get_json()["error"] == "INVALID_CREDENTIALS"

    def test_invalid_totp_rejected(self, client, officers):
        officer1, _ = officers["officer1"]
        res = client.post("/api/admin/auth/login", json={
            "admin_id": officer1.admin_id,
            "password": "ValidAdminPassword123!",
            "totp_code": "000000",
        })
        assert res.status_code == 401
        assert res.get_json()["error"] == "INVALID_TOTP"

    def test_missing_totp_rejected(self, client, officers):
        officer1, _ = officers["officer1"]
        res = client.post("/api/admin/auth/login", json={
            "admin_id": officer1.admin_id,
            "password": "ValidAdminPassword123!",
        })
        assert res.status_code == 401
        assert res.get_json()["error"] == "TOTP_REQUIRED"

    def test_brute_force_lockout_after_five_failed_attempts(self, client, officers):
        officer1, secret1 = officers["officer1"]
        for _ in range(5):
            res = client.post("/api/admin/auth/login", json={
                "admin_id": officer1.admin_id,
                "password": "WrongPassword!",
                "totp_code": "123456",
            })
            assert res.status_code in (401, 403)

        # 6th attempt with correct password and correct TOTP should still be locked out
        code = generate_totp_code(secret1)
        res = client.post("/api/admin/auth/login", json={
            "admin_id": officer1.admin_id,
            "password": "ValidAdminPassword123!",
            "totp_code": code,
        })
        assert res.status_code == 403
        assert res.get_json()["error"] == "ACCOUNT_LOCKED"

    def test_logout_and_session_revocation(self, client, officers):
        officer1, secret1 = officers["officer1"]
        headers = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", secret1)

        # Verify authenticated access
        me_res = client.get("/api/admin/auth/me", headers=headers)
        assert me_res.status_code == 200

        # Logout
        logout_res = client.post("/api/admin/auth/logout", headers=headers)
        assert logout_res.status_code == 200

        # Access with revoked token should fail
        me_res2 = client.get("/api/admin/auth/me", headers=headers)
        assert me_res2.status_code == 401
        assert me_res2.get_json()["error"] in ("REVOKED_SESSION", "INVALID_SESSION")

    def test_unauthenticated_access_rejected(self, client):
        res = client.get("/api/admin/elections")
        assert res.status_code == 401


# ==============================================================================
# SECTION 2: ROLE-BASED ACCESS CONTROL (RBAC)
# ==============================================================================

class TestAdminRBAC:
    def test_auditor_cannot_create_election(self, client, officers):
        auditor, secret = officers["auditor"]
        headers = login_admin(client, auditor.admin_id, "ValidAuditorPassword789!", secret)

        res = client.post("/api/admin/elections", json={
            "title": "Unauthorized Auditor Election",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=headers)
        assert res.status_code == 403
        assert res.get_json()["error"] in ("INSUFFICIENT_PERMISSIONS", "ROLE_UNAUTHORIZED")

    def test_auditor_cannot_request_approval(self, client, officers):
        officer1, s1 = officers["officer1"]
        auditor, s_aud = officers["auditor"]
        h_off = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)
        h_aud = login_admin(client, auditor.admin_id, "ValidAuditorPassword789!", s_aud)

        # Officer creates draft
        create_res = client.post("/api/admin/elections", json={
            "title": "Auditor Approval Test",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=h_off)
        assert create_res.status_code == 201
        elec_id = create_res.get_json()["election"]["id"]

        # Auditor attempts to request approval -> 403
        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h_aud)
        assert req_res.status_code == 403

    def test_auditor_can_inspect_elections_and_audits(self, client, officers):
        auditor, s_aud = officers["auditor"]
        h_aud = login_admin(client, auditor.admin_id, "ValidAuditorPassword789!", s_aud)

        # Can view elections
        res_e = client.get("/api/admin/elections", headers=h_aud)
        assert res_e.status_code == 200

        # Can view audit logs
        res_a = client.get("/api/admin/audit-logs", headers=h_aud)
        assert res_a.status_code == 200

        # Can verify hash chain
        res_c = client.get("/api/admin/audit-logs/verify-chain", headers=h_aud)
        assert res_c.status_code == 200


# ==============================================================================
# SECTION 3: ELECTION LIFECYCLE & TWO-OFFICER APPROVAL
# ==============================================================================

class TestElectionLifecycleAndApproval:
    def test_complete_valid_lifecycle(self, client, officers):
        officer1, s1 = officers["officer1"]
        officer2, s2 = officers["officer2"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)
        h2 = login_admin(client, officer2.admin_id, "ValidAdminPassword456!", s2)

        # 1. Officer 1 creates draft election
        start = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        end = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        res = client.post("/api/admin/elections", json={
            "title": "Presidential Election 2026",
            "start_time": start,
            "end_time": end,
            "eligible_count": 1000,
            "roll_hash": "a" * 64,
        }, headers=h1)
        assert res.status_code == 201
        elec = res.get_json()["election"]
        elec_id = elec["id"]
        assert elec["status"] == "DRAFT"

        # 2. Add candidates
        c_res = client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [
                {"name": "Alice Candidate", "party": "Tech Party", "candidate_index": 1},
                {"name": "Bob Candidate", "party": "Science Party", "candidate_index": 2},
            ]
        }, headers=h1)
        assert c_res.status_code == 200
        assert len(c_res.get_json()["candidates"]) == 2

        # 3. Officer 1 requests approval to SCHEDULE
        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
            "justification": "Electoral roll imported and verified.",
        }, headers=h1)
        assert req_res.status_code == 201
        req_id = req_res.get_json()["approval_request"]["id"]

        # Check election status is PENDING_APPROVAL
        check_e = client.get(f"/api/admin/elections/{elec_id}", headers=h1).get_json()["election"]
        assert check_e["status"] == "PENDING_APPROVAL"

        # 4. Officer 1 tries to approve own request -> MUST BE REJECTED (Four-eyes)
        self_appr = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h1)
        assert self_appr.status_code == 403
        assert self_appr.get_json()["error"] == "FOUR_EYES_VIOLATION"

        # 5. Auditor tries to approve -> MUST BE REJECTED
        auditor, s_aud = officers["auditor"]
        h_aud = login_admin(client, auditor.admin_id, "ValidAuditorPassword789!", s_aud)
        aud_appr = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h_aud)
        assert aud_appr.status_code == 403

        # 6. Distinct Officer 2 approves request
        appr_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert appr_res.status_code == 200
        assert appr_res.get_json()["election_status"] == "SCHEDULED"

        # Check election status is now SCHEDULED
        sched_e = client.get(f"/api/admin/elections/{elec_id}", headers=h2).get_json()["election"]
        assert sched_e["status"] == "SCHEDULED"

        # 7. Open election
        open_res = client.post(f"/api/admin/elections/{elec_id}/open", headers=h1)
        assert open_res.status_code == 200
        assert open_res.get_json()["election"]["status"] == "OPEN"

        # 8. Close election (after end_time has arrived)
        e_obj = Election.query.filter_by(election_id=elec_id).first()
        e_obj.end_time = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

        close_res = client.post(f"/api/admin/elections/{elec_id}/close", headers=h1)
        assert close_res.status_code == 200
        assert close_res.get_json()["election"]["status"] == "CLOSED"

    def test_duplicate_approval_rejected(self, client, officers):
        officer1, s1 = officers["officer1"]
        officer2, s2 = officers["officer2"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)
        h2 = login_admin(client, officer2.admin_id, "ValidAdminPassword456!", s2)

        res = client.post("/api/admin/elections", json={
            "title": "Duplicate Approval Test",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=h1)
        elec_id = res.get_json()["election"]["id"]

        client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [
                {"name": "Cand 1", "candidate_index": 1},
                {"name": "Cand 2", "candidate_index": 2},
            ]
        }, headers=h1)

        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h1)
        req_id = req_res.get_json()["approval_request"]["id"]

        # First approval succeeds
        appr1 = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert appr1.status_code == 200

        # Second approval fails
        appr2 = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert appr2.status_code == 400
        assert appr2.get_json()["error"] == "INVALID_APPROVAL_STATE"

    def test_invalid_lifecycle_transition_rejected(self, client, officers):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        res = client.post("/api/admin/elections", json={
            "title": "Skip Transition Test",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=h1)
        elec_id = res.get_json()["election"]["id"]

        # Attempt to open DRAFT election directly without scheduling -> 400
        open_res = client.post(f"/api/admin/elections/{elec_id}/open", headers=h1)
        assert open_res.status_code == 400
        assert open_res.get_json()["error"] == "INVALID_LIFECYCLE_TRANSITION"


# ==============================================================================
# SECTION 4: POST-SCHEDULING IMMUTABILITY
# ==============================================================================

class TestElectionImmutability:
    @pytest.fixture
    def scheduled_election(self, client, officers):
        officer1, s1 = officers["officer1"]
        officer2, s2 = officers["officer2"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)
        h2 = login_admin(client, officer2.admin_id, "ValidAdminPassword456!", s2)

        res = client.post("/api/admin/elections", json={
            "title": "Immutable Election",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "eligible_count": 500,
            "roll_hash": "b" * 64,
        }, headers=h1)
        elec_id = res.get_json()["election"]["id"]

        client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [
                {"name": "Charlie", "candidate_index": 1},
                {"name": "Dana", "candidate_index": 2},
            ]
        }, headers=h1)

        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h1)
        req_id = req_res.get_json()["approval_request"]["id"]

        client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        return elec_id, h1

    def test_cannot_modify_dates_after_scheduled(self, client, scheduled_election):
        elec_id, h1 = scheduled_election
        new_start = (datetime.utcnow() + timedelta(days=5)).isoformat()
        res = client.put(f"/api/admin/elections/{elec_id}", json={
            "start_time": new_start,
        }, headers=h1)
        assert res.status_code == 409
        assert res.get_json()["error"] == "IMMUTABLE_ELECTION"

    def test_cannot_modify_eligible_count_after_scheduled(self, client, scheduled_election):
        elec_id, h1 = scheduled_election
        res = client.put(f"/api/admin/elections/{elec_id}", json={
            "eligible_count": 9999,
        }, headers=h1)
        assert res.status_code == 409
        assert res.get_json()["error"] == "IMMUTABLE_ELECTION"

    def test_cannot_modify_roll_hash_after_scheduled(self, client, scheduled_election):
        elec_id, h1 = scheduled_election
        res = client.put(f"/api/admin/elections/{elec_id}", json={
            "roll_hash": "c" * 64,
        }, headers=h1)
        assert res.status_code == 409
        assert res.get_json()["error"] == "IMMUTABLE_ELECTION"

    def test_cannot_add_candidates_after_scheduled(self, client, scheduled_election):
        elec_id, h1 = scheduled_election
        res = client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [{"name": "Late Candidate", "candidate_index": 2}]
        }, headers=h1)
        assert res.status_code == 409
        assert res.get_json()["error"] == "IMMUTABLE_ELECTION"


# ==============================================================================
# SECTION 5: AUDIT TRAIL INTEGRITY & ZERO PRIVACY LEAKAGE
# ==============================================================================

class TestAdministrativeAuditTrail:
    def test_administrative_actions_logged_to_audit_events(self, client, officers):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        # Create election
        client.post("/api/admin/elections", json={
            "title": "Audit Trail Election",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=h1)

        # Retrieve audit events
        res = client.get("/api/admin/audit-logs", headers=h1)
        assert res.status_code == 200
        events = res.get_json()["events"]
        assert len(events) >= 2  # At least LOGIN + ELECTION_CREATED

        actions = [e["event_type"] for e in events]
        assert "ADMIN_LOGIN_SUCCESS" in actions
        assert "ELECTION_CREATED" in actions

    def test_audit_hash_chain_validity(self, client, officers):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        res = client.get("/api/admin/audit-logs/verify-chain", headers=h1)
        assert res.status_code == 200
        data = res.get_json()
        assert data["valid"] is True
        assert data["verified_count"] >= 1

    def test_audit_events_never_contain_ballot_choices(self, client, officers):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        res = client.get("/api/admin/audit-logs", headers=h1)
        assert res.status_code == 200
        for ev in res.get_json()["events"]:
            desc = str(ev.get("description", ""))
            assert "candidate_choice" not in desc
            assert "pseudonym" not in desc


# ==============================================================================
# SECTION 6: PRIVACY-PRESERVING DISPUTE HANDLING
# ==============================================================================

class TestPrivacyPreservingDisputes:
    def test_receipt_investigation_does_not_reveal_candidate(self, client, officers, db):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        # Insert a simulated ballot queue item directly
        from app.models.ballot_record import BallotQueue
        bq = BallotQueue(
            election_id=1,
            pseudonym="fake_pseudonym_hash",
            candidate=2,  # Candidate 2 voted!
            sequence=1,
            state="CONFIRMED",
            receipt_code="RCPT-TEST-12345",
            tx_hash="0x" + "1" * 64,
            block_number=42,
        )
        db.session.add(bq)
        db.session.commit()

        # Query dispute endpoint
        res = client.post("/api/admin/disputes/query", json={
            "query_type": "RECEIPT",
            "receipt_code": "RCPT-TEST-12345",
        }, headers=h1)
        assert res.status_code == 200
        data = res.get_json()["data"]

        # Confirm operational facts are returned
        assert data["receipt_found"] is True
        assert data["state"] == "CONFIRMED"
        assert data["block_number"] == 42

        # PRIVACY INVARIANT: Ensure candidate is NOT revealed
        assert "candidate" not in data
        assert "pseudonym" not in data
        assert "candidate_index" not in data
        assert "choice" not in data

    def test_voter_operational_lookup_does_not_reveal_ballot(self, client, officers, db):
        officer1, s1 = officers["officer1"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        # Create user & roll entry
        u = User(username="stu_1001", password_hash="dummy")
        u.voter_id = "VOTER-1001"
        u.email = "stu@college.test"
        db.session.add(u)
        roll = ElectoralRoll(
            usn="VOTER-1001",
            full_name="Alice Student",
            college_email="stu@college.test",
            is_eligible=True,
        )
        db.session.add(roll)
        db.session.commit()

        # Query dispute endpoint
        res = client.post("/api/admin/disputes/query", json={
            "query_type": "VOTER",
            "voter_id": "VOTER-1001",
        }, headers=h1)
        assert res.status_code == 200
        data = res.get_json()["data"]

        # Operational status is available
        assert data["account_registered"] is True
        assert data["electoral_roll_status"] == "ELIGIBLE"

        # No ballot choices or secret pseudonyms exposed
        assert "candidate" not in data
        assert "ballot" not in data
        assert "pseudonym" not in data


# ==============================================================================
# SECTION 7: CONCURRENCY & RACE CONDITIONS
# ==============================================================================

class TestConcurrencyAndRaceConditions:
    def test_concurrent_approval_race(self, client, officers, db):
        """Simulate two concurrent officers attempting to approve the same request."""
        import concurrent.futures

        officer1, s1 = officers["officer1"]
        officer2, s2 = officers["officer2"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)

        # Create election with 2 candidates
        res = client.post("/api/admin/elections", json={
            "title": "Race Test Election",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        }, headers=h1)
        elec_id = res.get_json()["election"]["id"]

        client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [
                {"name": "C1", "candidate_index": 1},
                {"name": "C2", "candidate_index": 2},
            ]
        }, headers=h1)

        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h1)
        req_id = req_res.get_json()["approval_request"]["id"]

        # Run two simultaneous approval attempts by Officer 2
        results = []
        def try_approve():
            # Create a separate client or call service directly with app context
            from app import create_app
            with client.application.app_context():
                off2 = AdminUser.query.filter_by(admin_id=officer2.admin_id).first()
                success, reason = ElectionAdminService.approve_request(req_id, off2)
                return success, reason

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(try_approve)
            f2 = executor.submit(try_approve)
            results = [f1.result(), f2.result()]

        # Invariant: EXACTLY one approval succeeds, the other fails
        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]
        assert len(successes) == 1
        assert len(failures) == 1

    def test_config_drift_invalidates_pending_approval(self, client, officers, db):
        """Tampering with election configuration after approval requested invalidates it."""
        officer1, s1 = officers["officer1"]
        officer2, s2 = officers["officer2"]
        h1 = login_admin(client, officer1.admin_id, "ValidAdminPassword123!", s1)
        h2 = login_admin(client, officer2.admin_id, "ValidAdminPassword456!", s2)

        res = client.post("/api/admin/elections", json={
            "title": "Config Drift Election",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "eligible_count": 100,
        }, headers=h1)
        elec_id = res.get_json()["election"]["id"]

        client.post(f"/api/admin/elections/{elec_id}/candidates", json={
            "candidates": [
                {"name": "C1", "candidate_index": 1},
                {"name": "C2", "candidate_index": 2},
            ]
        }, headers=h1)

        # Officer 1 requests scheduling
        req_res = client.post(f"/api/admin/elections/{elec_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h1)
        req_id = req_res.get_json()["approval_request"]["id"]

        # Backdoor or direct mutation to eligible_count before Officer 2 reviews
        election = Election.query.filter_by(election_id=elec_id).first()
        election.eligible_count = 99999
        db.session.commit()

        # Officer 2 attempts to approve -> MUST FAIL due to config drift hash mismatch
        appr_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert appr_res.status_code == 400
        assert appr_res.get_json()["error"] in ("APPROVAL_FAILED", "INVALID_APPROVAL_STATE")

        # Approval request must be marked INVALIDATED
        req = ApprovalRequest.query.get(req_id)
        assert req.status == "INVALIDATED"


# ==============================================================================
# SECTION 9: ELECTION FINALIZATION & TOTP REPLAY PREVENTION (SEC-11-01 & SEC-11-02)
# ==============================================================================

class TestElectionFinalizationAndKeyDestruction:
    """Tests covering SEC-11-01: CLOSED -> FINALIZED transition, alphanumeric IDs, Phase 10 safety, and key shredding."""

    def _setup_closed_election(self, client, officers, election_id="ELEC_TEST_01"):
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h2 = login_admin(client, "OFFICER_02", "ValidAdminPassword456!", officers["officer2"][1])
        now = datetime.utcnow()

        # 1. Create DRAFT (with future end_time so it can legitimately open)
        client.post("/api/admin/elections", json={
            "election_id": election_id,
            "title": f"Test Finalization {election_id}",
            "start_time": (now - timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
            "eligible_count": 100,
        }, headers=h1)

        # 2. Add candidates
        client.post(f"/api/admin/elections/{election_id}/candidates", json={
            "candidates": [
                {"name": "Alice", "candidate_index": 0},
                {"name": "Bob", "candidate_index": 1},
            ]
        }, headers=h1)

        # 3. Request Schedule
        req = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "SCHEDULE_ELECTION",
        }, headers=h1)
        req_id = req.get_json()["approval_request"]["id"]

        # 4. Officer 2 approves Schedule -> SCHEDULED
        client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)

        # Ensure pseudonym key is created while election is SCHEDULED
        from app.security.pseudonym import get_election_pseudonym_key
        key = get_election_pseudonym_key(election_id, create_if_missing=True)
        assert key is not None

        # 5. Open and Close
        client.post(f"/api/admin/elections/{election_id}/open", headers=h1)

        # Advance end_time to past so election can legally close
        elec = Election.query.filter_by(election_id=election_id).first()
        elec.end_time = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

        client.post(f"/api/admin/elections/{election_id}/close", headers=h1)

        return h1, h2

    def test_normal_finalization_closed_to_finalized(self, client, officers):
        """Test 1: CLOSED -> FINALIZED succeeds with alphanumeric ID after two-officer approval."""
        election_id = "ELEC_ALPHA_FINAL_01"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        # Officer 1 requests finalization
        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
            "justification": "Election ended, all ballots settled",
        }, headers=h1)
        assert req_res.status_code == 201
        fin_req_id = req_res.get_json()["approval_request"]["id"]

        # Officer 2 approves finalization
        appr_res = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)
        assert appr_res.status_code == 200
        assert appr_res.get_json()["status"] == "APPROVED"

        # Verify election state in DB
        election = Election.query.filter_by(election_id=election_id).first()
        assert election.status == "FINALIZED"
        assert election.finalized_at is not None

    def test_finalization_self_approval_rejected(self, client, officers):
        """Test 2: Self-approval rejected with 403 FOUR_EYES_VIOLATION."""
        election_id = "ELEC_SELF_REJECT_01"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        # Officer 1 requests finalization
        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]

        # Officer 1 attempts to approve own request
        self_appr = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h1)
        assert self_appr.status_code == 403
        assert self_appr.get_json()["error"] == "FOUR_EYES_VIOLATION"

    def test_numeric_election_id_finalization(self, client, officers):
        """Test 4: Numeric election ID finalization succeeds."""
        election_id = "901"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]

        appr_res = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)
        assert appr_res.status_code == 200

        election = Election.query.filter_by(election_id=election_id).first()
        assert election.status == "FINALIZED"

    def test_repeated_finalization_rejected(self, client, officers):
        """Test 5: Repeated finalization on already FINALIZED election is rejected."""
        election_id = "ELEC_REPEATED_FINAL"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]
        client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)

        # Try to request finalization again
        repeat_req = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        assert repeat_req.status_code == 400
        assert repeat_req.get_json()["error"] == "INVALID_STATE"

    def test_unsafe_finalization_rejected_with_pending_ballots(self, client, officers):
        """Test 6A: Unsafe finalization rejected when ballots remain QUEUED or SUBMITTED."""
        election_id = "ELEC_UNSAFE_BALLOTS"
        h1, h2 = self._setup_closed_election(client, officers, election_id)
        election = Election.query.filter_by(election_id=election_id).first()

        # Seed an unsettled SUBMITTED ballot
        from app.models import BallotRecord
        b = BallotRecord(
            election_id=election.id,
            pseudonym="0x" + "a" * 64,
            candidate=0,
            sequence=1,
            state="SUBMITTED",
        )
        db.session.add(b)
        db.session.commit()

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]

        # Attempt approval -> must fail due to pending ballots
        appr_res = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)
        assert appr_res.status_code == 400
        assert "CANNOT_FINALIZE_PENDING_BALLOTS" in appr_res.get_json()["message"]

        # Election must remain CLOSED
        db.session.refresh(election)
        assert election.status == "CLOSED"

    def test_unsafe_finalization_rejected_with_recovery_pending(self, client, officers):
        """Test 6B: Unsafe finalization rejected when ballots have reconcile_required or open issues."""
        election_id = "ELEC_UNSAFE_RECONCILE"
        h1, h2 = self._setup_closed_election(client, officers, election_id)
        election = Election.query.filter_by(election_id=election_id).first()

        from app.models.reconciliation import ReconciliationIssue
        issue = ReconciliationIssue(
            election_id=election.id,
            issue_type="TRANSACTION_REVERTED",
            severity="HIGH",
            status="OPEN",
        )
        db.session.add(issue)
        db.session.commit()

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]

        appr_res = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)
        assert appr_res.status_code == 400
        assert "CANNOT_FINALIZE_UNRESOLVED_RECONCILIATION_ISSUES" in appr_res.get_json()["message"]

    def test_key_destruction_and_fail_closed_derivation(self, client, officers):
        """Test 7: After finalization, pseudonym keys are shredded and derivation fails closed."""
        election_id = "ELEC_KEY_SHRED_01"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]
        appr_res = client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)
        assert appr_res.status_code == 200

        # Verify key shredded in DB
        from app.models.election_key import ElectionPseudonymKey
        from app.security.pseudonym import derive_pseudonym, PseudonymKeyError
        election = Election.query.filter_by(election_id=election_id).first()
        key_record = ElectionPseudonymKey.query.filter_by(election_id=election.id).first()
        assert key_record is not None
        assert key_record.key_ciphertext == "[DESTROYED]"
        assert key_record.key_hash == "0" * 64

        # Derivation must fail closed
        with pytest.raises(PseudonymKeyError):
            derive_pseudonym(user_id=1, election_id=election_id)

    def test_finalization_audit_events_logged(self, client, officers):
        """Test 8: Finalization records administrative audit events."""
        election_id = "ELEC_AUDIT_LOG_01"
        h1, h2 = self._setup_closed_election(client, officers, election_id)

        req_res = client.post(f"/api/admin/elections/{election_id}/request-approval", json={
            "operation": "FINALIZE_ELECTION",
        }, headers=h1)
        fin_req_id = req_res.get_json()["approval_request"]["id"]
        client.post(f"/api/admin/approvals/{fin_req_id}/approve", headers=h2)

        fin_events = AuditEvent.query.filter(
            AuditEvent.event_type.in_(["ELECTION_FINALIZED", "PSEUDONYM_KEY_DESTROYED", "APPROVAL_GRANTED"])
        ).all()
        assert len(fin_events) >= 2


class TestTOTPReplayPrevention:
    """Tests covering SEC-11-02: RFC 6238 in-window token replay prevention."""

    def test_totp_in_window_replay_rejected(self, client, officers):
        """Test 9: Replaying the same valid TOTP code within the 30-second window is rejected."""
        officer1, secret1 = officers["officer1"]
        admin_id = officer1.admin_id
        code = generate_totp_code(secret1)

        # First login with this code -> SUCCESS
        res1 = client.post("/api/admin/auth/login", json={
            "admin_id": admin_id,
            "password": "ValidAdminPassword123!",
            "totp_code": code,
        })
        assert res1.status_code == 200
        assert "token" in res1.get_json()

        # Immediate replay with the exact same code -> REJECTED (403 TOTP_REPLAY_REJECTED)
        res2 = client.post("/api/admin/auth/login", json={
            "admin_id": admin_id,
            "password": "ValidAdminPassword123!",
            "totp_code": code,
        })
        assert res2.status_code == 403
        assert res2.get_json()["error"] == "TOTP_REPLAY_REJECTED"

    def test_concurrent_totp_reuse_exactly_one_succeeds(self, client, officers):
        """Test 10: Two simultaneous login attempts with identical TOTP code -> exactly 1 succeeds."""
        officer2, secret2 = officers["officer2"]
        admin_id = officer2.admin_id
        code = generate_totp_code(secret2)

        import concurrent.futures

        def do_login():
            return client.post("/api/admin/auth/login", json={
                "admin_id": admin_id,
                "password": "ValidAdminPassword456!",
                "totp_code": code,
            })

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_login)
            f2 = executor.submit(do_login)
            r1 = f1.result()
            r2 = f2.result()

        results = [r1.status_code, r2.status_code]
        assert results.count(200) == 1
        assert results.count(403) == 1


