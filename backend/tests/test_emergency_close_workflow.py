"""
Vote Without Doubt - Emergency Early Election Closure Test Suite
Validates the complete Two-Officer (Four-Eyes) Emergency Closure workflow:
1. Scheduled closure rules (only allowed once end_time arrives).
2. Early closure blocked on normal close endpoint with instructive message.
3. Mandatory justification validation on emergency close request.
4. Approvals queue exposure (including election title and emergency justification reason).
5. Four-eyes self-approval prevention (requester cannot approve own request).
6. Auditor / unauthorized approval rejection.
7. Second-officer rejection (election remains OPEN).
8. Second-officer approval and execution (election becomes CLOSED, audit logged).
9. Prevention of replay / duplicate approvals.
10. Post-emergency closure voting rejection.
"""

from datetime import datetime, timedelta
import pytest
from app.extensions import db
from app.models.admin import AdminUser, ApprovalRequest
from app.models.ballot import Election
from app.models.audit_event import AuditEvent
from app.security.admin_auth import AdminAuthService
from app.security.totp import generate_totp_code


@pytest.fixture
def officers(db):
    """Fixture providing two officers and one auditor."""
    officer1, secret1 = AdminAuthService.create_admin(
        admin_id="OFFICER_01",
        name="Chief Election Officer",
        email="officer1@election.local",
        password="ValidAdminPassword123!",
        role="OFFICER",
    )
    officer2, secret2 = AdminAuthService.create_admin(
        admin_id="OFFICER_02",
        name="Deputy Election Officer",
        email="officer2@election.local",
        password="ValidAdminPassword456!",
        role="OFFICER",
    )
    auditor, aud_secret = AdminAuthService.create_admin(
        admin_id="AUDITOR_01",
        name="Election Auditor",
        email="auditor1@election.local",
        password="ValidAuditorPassword789!",
        role="AUDITOR",
    )
    return {
        "officer1": (officer1, secret1),
        "officer2": (officer2, secret2),
        "auditor": (auditor, aud_secret),
    }


def login_admin(client, admin_id, password, secret):
    code = generate_totp_code(secret)
    res = client.post("/api/admin/auth/login", json={
        "admin_id": admin_id,
        "password": password,
        "totp_code": code,
    })
    assert res.status_code == 200, res.get_json()
    token = res.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def create_open_election(election_id="ELEC_TEST_EMERGENCY", title="Emergency Test Election", end_in_hours=2):
    now = datetime.utcnow()
    election = Election(
        election_id=election_id,
        title=title,
        description="Testing early emergency closure workflow",
        status="OPEN",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=end_in_hours),
        candidate_count=2,
        eligible_count=100,
        scheduled_at=now - timedelta(hours=2),
    )
    db.session.add(election)
    db.session.commit()
    return election


class TestEmergencyCloseWorkflow:

    def test_normal_close_success_after_end_time(self, client, officers):
        """A normal closure succeeds without two-officer approval if end_time has passed."""
        # Create election whose end_time was 1 hour ago
        election = create_open_election(election_id="ELEC_EXPIRED_01", end_in_hours=-1)
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        res = client.post(f"/api/admin/elections/{election.election_id}/close", headers=headers)
        assert res.status_code == 200, res.get_json()
        data = res.get_json()
        assert data["status"] == "CLOSED"

        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "CLOSED"
        assert refreshed.closed_at is not None

    def test_normal_close_blocked_before_end_time(self, client, officers):
        """Attempting unilateral close before end_time is rejected with an instructive error."""
        election = create_open_election(election_id="ELEC_ACTIVE_01", end_in_hours=2)
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        res = client.post(f"/api/admin/elections/{election.election_id}/close", headers=headers)
        assert res.status_code == 400
        data = res.get_json()
        assert data["error"] == "INVALID_LIFECYCLE_TRANSITION"
        assert "Cannot close election before end_time" in data["message"]
        assert "EMERGENCY_CLOSE" in data["message"]

        # Election must remain OPEN
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "OPEN"

    def test_emergency_close_request_requires_non_empty_justification(self, client, officers):
        """Requesting emergency closure without a non-empty justification is rejected with 400."""
        election = create_open_election(election_id="ELEC_JUST_01", end_in_hours=2)
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        # Empty string
        res1 = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=headers,
            json={"action_type": "EMERGENCY_CLOSE", "reason": ""}
        )
        assert res1.status_code == 400
        assert res1.get_json()["error"] == "MISSING_JUSTIFICATION"

        # Whitespace only
        res2 = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=headers,
            json={"action_type": "EMERGENCY_CLOSE", "reason": "   \n\t  "}
        )
        assert res2.status_code == 400
        assert res2.get_json()["error"] == "MISSING_JUSTIFICATION"

        # Missing reason field
        res3 = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=headers,
            json={"action_type": "EMERGENCY_CLOSE"}
        )
        assert res3.status_code == 400
        assert res3.get_json()["error"] == "MISSING_JUSTIFICATION"

    def test_emergency_close_listed_in_approvals_with_title_and_reason(self, client, officers):
        """The emergency close request surfaces the election title, requesting officer, and reason in the queue."""
        election = create_open_election(election_id="ELEC_LIST_01", title="Campus General Election 2026", end_in_hours=3)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h2 = login_admin(client, "OFFICER_02", "ValidAdminPassword456!", officers["officer2"][1])

        justification = "Urgent: Physical polling location power failure and server outage."
        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": justification}
        )
        assert req_res.status_code in (200, 201), req_res.get_json()
        req_id = req_res.get_json().get("request_id")

        # Officer 2 queries approvals
        list_res = client.get("/api/admin/approvals", headers=h2)
        assert list_res.status_code == 200
        items = list_res.get_json()["approval_requests"]
        target = next((item for item in items if item["id"] == req_id), None)
        assert target is not None
        assert target["election_id"] == election.election_id
        assert target["election_title"] == "Campus General Election 2026"
        assert target["action_type"] == "EMERGENCY_CLOSE"
        assert target["requester"] == "OFFICER_01"
        assert target["requester_name"] == "Chief Election Officer"
        assert target["reason"] == justification
        assert target["status"] == "PENDING"

    def test_self_approval_blocked_by_four_eyes_principle(self, client, officers):
        """The requesting officer cannot approve their own EMERGENCY_CLOSE request."""
        election = create_open_election(election_id="ELEC_SELF_01", end_in_hours=4)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": "Self approval test justification"}
        )
        req_id = req_res.get_json()["request_id"]

        # Officer 1 attempts to approve own request
        app_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h1)
        assert app_res.status_code in (400, 403)
        err = app_res.get_json()
        assert "FOUR_EYES_VIOLATION" in err.get("message", "") or "distinct" in err.get("message", "").lower()

        # Election must stay OPEN
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "OPEN"

    def test_auditor_cannot_approve_emergency_close(self, client, officers):
        """Auditors have read-only privileges and cannot approve emergency closure requests."""
        election = create_open_election(election_id="ELEC_AUD_01", end_in_hours=4)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h_aud = login_admin(client, "AUDITOR_01", "ValidAuditorPassword789!", officers["auditor"][1])

        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": "Testing auditor authorization boundary"}
        )
        req_id = req_res.get_json()["request_id"]

        app_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h_aud)
        assert app_res.status_code == 403

        # Election remains OPEN
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "OPEN"

    def test_second_officer_rejection_leaves_election_open(self, client, officers):
        """When the second officer rejects the request, election remains OPEN."""
        election = create_open_election(election_id="ELEC_REJ_01", end_in_hours=3)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h2 = login_admin(client, "OFFICER_02", "ValidAdminPassword456!", officers["officer2"][1])

        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": "Suspected anomalous voting pattern"}
        )
        req_id = req_res.get_json()["request_id"]

        rej_res = client.post(
            f"/api/admin/approvals/{req_id}/reject",
            headers=h2,
            json={"reason": "Pattern verified benign by IT security review."}
        )
        assert rej_res.status_code == 200

        # Request status is REJECTED
        req_record = db.session.query(ApprovalRequest).filter_by(id=req_id).first()
        assert req_record.status == "REJECTED"
        assert "Pattern verified" in (req_record.rejection_reason or "")

        # Election remains OPEN
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "OPEN"

    def test_second_officer_approval_executes_closure_and_audit(self, client, officers):
        """When approved by a distinct officer, the election is closed and audit logged."""
        election = create_open_election(election_id="ELEC_EXEC_01", title="Executive Election 2026", end_in_hours=5)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h2 = login_admin(client, "OFFICER_02", "ValidAdminPassword456!", officers["officer2"][1])

        justification = "Confirmed severe compromise of key ceremony environment."
        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": justification}
        )
        assert req_res.status_code in (200, 201)
        req_id = req_res.get_json()["request_id"]

        # Distinct Officer 2 approves
        app_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert app_res.status_code == 200, app_res.get_json()

        # 1. Approval record is APPROVED
        req_record = db.session.query(ApprovalRequest).filter_by(id=req_id).first()
        assert req_record.status == "APPROVED"
        assert req_record.approver.admin_id == "OFFICER_02"

        # 2. Election is CLOSED with closed_at timestamp
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "CLOSED"
        assert refreshed.closed_at is not None

        # 3. Audit trail contains ELECTION_EMERGENCY_CLOSED event with justification
        audit_events = db.session.query(AuditEvent).filter_by(event_type="ELECTION_EMERGENCY_CLOSED").all()
        assert len(audit_events) > 0
        latest_audit = audit_events[-1]
        audit_payload = latest_audit.event_metadata or {}
        assert audit_payload.get("election_id") == election.election_id
        assert audit_payload.get("reason") == justification
        assert audit_payload.get("request_id") == req_id

        # 4. Duplicate approval attempt fails
        dup_res = client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)
        assert dup_res.status_code == 400
        assert "INVALID_APPROVAL_STATE" in dup_res.get_json().get("error", "")

    def test_voting_blocked_after_emergency_close(self, client, officers):
        """Voting authorization fails immediately after emergency closure."""
        election = create_open_election(election_id="ELEC_VOTE_BLOCK_01", end_in_hours=5)
        h1 = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        h2 = login_admin(client, "OFFICER_02", "ValidAdminPassword456!", officers["officer2"][1])

        # Emergency close the election
        req_res = client.post(
            f"/api/admin/elections/{election.election_id}/request-approval",
            headers=h1,
            json={"action_type": "EMERGENCY_CLOSE", "reason": "Immediate voting shutdown required."}
        )
        req_id = req_res.get_json()["request_id"]
        client.post(f"/api/admin/approvals/{req_id}/approve", headers=h2)

        # Confirm election is closed
        refreshed = db.session.query(Election).filter_by(election_id=election.election_id).first()
        assert refreshed.status == "CLOSED"

        # Attempt to authorize voting on closed election
        vote_auth_res = client.post("/api/voting/authorize", json={
            "election_id": election.election_id,
        })
        assert vote_auth_res.status_code in (400, 401, 403)
        # Even without user auth, or with user auth, it cannot proceed as active
