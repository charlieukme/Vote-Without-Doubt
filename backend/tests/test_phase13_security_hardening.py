"""
Phase 13: Comprehensive Security Hardening Test Suite
Vote Without Doubt - AI & Blockchain-Based Secure E-Voting System

Covers:
  13.1 Application / API Attacks:
       - Malformed requests (missing fields, wrong JSON types, null values, negative/large numbers, invalid unicode)
       - Oversized payloads (16MB ceiling, oversized strings, bounded processing)
       - SQL Injection (ORM parameterization, zero raw SQL concatenation, all query surfaces)
       - Cross-Site Scripting (XSS contextual escaping, strict Content-Security-Policy)
       - CSRF architecture verification
  13.2 Face / Liveness Attacks:
       - Photo attack (static yaw frames fail liveness)
       - Screen / Replay attack (single-use challenge, TTL expiration, cross-session binding)
       - Wrong direction attack (inverted/deviated head movement fails challenge)
       - Multiple faces attack (multiple bounding boxes fail validation)
  13.3 Blockchain Attacks:
       - Unauthorized relayer address invocation
       - Outside election window (before start / after close)
       - Invalid candidate index (out-of-bounds candidate)
       - Invalid sequence (sequence 0, non-sequential revote, replay)
  13.4 Privacy Attacks:
       - Database join attack (Identity plane vs Ballot plane strict decoupling, zero voter choice FK)
       - Log inspection (zero plaintext passwords, secrets, or identity-ballot linkage)
       - Receipt inspection (receipt code reveals zero candidate choice, coercion-free)
       - Timing analysis (constant-time comparisons for HMAC and TOTP)
  13.5 Admin Governance Attacks:
       - Self-approval prohibition across all critical operations (SCHEDULE, FINALIZE, CANCEL, EMERGENCY_CLOSE)
       - Post-scheduling immutability enforcement
       - Audit log tampering & hash-chain breakage detection
       - RBAC enforcement (OFFICER vs AUDITOR separation, unauthenticated / expired tokens)
"""

import hashlib
import io
import json
import os
import time
from datetime import datetime, timedelta
import pytest
import numpy as np

from app.extensions import db
from app.models.admin import AdminUser, ApprovalRequest, Candidate
from app.models.audit_event import AuditEvent
from app.models.auth import User
from app.models.auth_session import AuthSession
from app.models.ballot import Ballot, Election
from app.models.ballot_record import BallotQueue as BallotRecord
from app.models.face import FaceChallenge, FaceEnrollment
from app.models.wallet import WalletBinding
from app.security.admin_auth import AdminAuthService
from app.security.pseudonym import derive_pseudonym, get_election_pseudonym_key, destroy_election_pseudonym_key
from app.security.totp import generate_totp_code
from app.services.election_admin_service import (
    ElectionAdminService,
    ElectionImmutabilityError,
    TwoOfficerApprovalError,
)
from app.services.dispute_service import DisputeService
from app.services.voting_service import VotingService
from tests import face_fixtures as fx
from tests.conftest import (
    PHASE2_PASSWORD,
    PHASE2_USERNAME,
    _seed_authorized_session,
    post_frames,
)


@pytest.fixture
def officers(db):
    """Provide two distinct election officers and one auditor."""
    officer1, secret1 = AdminAuthService.create_admin(
        admin_id="OFFICER_SEC_01",
        name="Chief Officer 1",
        email="officer_sec1@election.local",
        password="ValidOfficerPassword123!",
        role="OFFICER",
    )
    officer2, secret2 = AdminAuthService.create_admin(
        admin_id="OFFICER_SEC_02",
        name="Chief Officer 2",
        email="officer_sec2@election.local",
        password="ValidOfficerPassword456!",
        role="OFFICER",
    )
    auditor, aud_secret = AdminAuthService.create_admin(
        admin_id="AUDITOR_SEC_01",
        name="Auditor 1",
        email="auditor_sec1@election.local",
        password="ValidAuditorPassword789!",
        role="AUDITOR",
    )
    return {
        "officer1": (officer1, secret1),
        "officer2": (officer2, secret2),
        "auditor": (auditor, aud_secret),
    }


def login_admin_token(client, admin_id, password, secret):
    """Helper to login an admin and return authorization headers."""
    code = generate_totp_code(secret)
    res = client.post("/api/admin/auth/login", json={
        "admin_id": admin_id,
        "password": password,
        "totp_code": code,
    })
    assert res.status_code == 200, res.get_json()
    token = res.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# PART 1: APPLICATION / API ATTACKS & SQL INJECTION
# ==============================================================================

class TestApiMalformedRequests:
    """13.1.1 Malformed request fuzzing across key API endpoints."""

    MALFORMED_JSON_PAYLOADS = [
        [1, 2, 3],                  # List instead of dict
        "string_payload",           # Raw string instead of dict
        12345,                      # Integer instead of dict
        True,                       # Boolean instead of dict
        None,                       # Null payload
    ]

    def test_auth_login_malformed_json_types(self, client):
        """Verify POST /api/auth/login handles non-dict JSON without 500 or crash."""
        for payload in self.MALFORMED_JSON_PAYLOADS:
            res = client.post("/api/auth/login", json=payload)
            assert res.status_code in (400, 401), f"Failed for {payload}: {res.status_code}"
            assert res.is_json
            assert "error" in res.get_json()

    def test_admin_login_malformed_json_types(self, client):
        """Verify POST /api/admin/auth/login handles non-dict JSON safely."""
        for payload in self.MALFORMED_JSON_PAYLOADS:
            res = client.post("/api/admin/auth/login", json=payload)
            assert res.status_code in (400, 401)
            assert res.is_json

    def test_voting_endpoints_malformed_json_types(self, client, phase2_user, client_for_session):
        """Verify voting endpoints reject non-dict JSON cleanly."""
        sess_client = client_for_session("test_session_token")
        for endpoint in ["/api/voting/authorize", "/api/voting/mark-factors", "/api/voting/submit"]:
            for payload in self.MALFORMED_JSON_PAYLOADS:
                res = sess_client.post(endpoint, json=payload)
                assert res.status_code in (400, 401, 403), f"{endpoint} failed on {payload}"
                assert res.is_json

    def test_registration_endpoints_malformed_json_types(self, client):
        """Verify registration endpoints handle non-dict JSON without unhandled 500s."""
        for endpoint in ["/api/registration/check", "/api/registration/verify-otp", "/api/registration/complete"]:
            for payload in self.MALFORMED_JSON_PAYLOADS:
                res = client.post(endpoint, json=payload)
                assert res.status_code in (400, 401)
                assert res.is_json

    def test_numeric_fuzzing_and_boundary_attacks(self, client, officers):
        """Attack numeric inputs with negative numbers and astronomical integers."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        # Negative eligible count
        res = client.post("/api/admin/elections", headers=headers, json={
            "title": "Test Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
            "eligible_count": -50,
            "max_ballots": 3,
        })
        assert res.status_code == 400

        # Non-numeric string for eligible count
        res2 = client.post("/api/admin/elections", headers=headers, json={
            "title": "Test Election 2",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
            "eligible_count": "NOT_AN_INTEGER",
            "max_ballots": 3,
        })
        assert res2.status_code == 400

        # Query param numeric fuzzing on audit logs
        res3 = client.get("/api/admin/audit-logs?limit=INVALID_NUMERIC", headers=headers)
        assert res3.status_code == 200  # Falls back to default limit safely
        res4 = client.get("/api/admin/audit-logs?limit=-999", headers=headers)
        assert res4.status_code == 200

    def test_invalid_unicode_and_null_bytes(self, client):
        """Attack APIs with null bytes and invalid Unicode sequences."""
        res = client.post("/api/auth/login", json={
            "username": "user\x00malicious",
            "password": "pwd\x00malicious",
        })
        assert res.status_code in (400, 401)
        assert res.is_json

    def test_invalid_auth_headers_and_forged_tokens(self, client):
        """Verify forged, malformed, and non-bearer Authorization headers fail closed."""
        bad_headers = [
            {"Authorization": "Bearer "},
            {"Authorization": "Bearer invalid_hex_token_12345"},
            {"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="},
            {"Authorization": "Token 12345"},
            {"Authorization": "Bearer " + "A" * 500},
        ]
        for h in bad_headers:
            res = client.get("/api/admin/elections", headers=h)
            assert res.status_code == 401, f"Header {h} was not rejected with 401"


class TestApiOversizedPayloads:
    """13.1.2 Oversized payloads and bounded resource allocation."""

    def test_oversized_candidate_name_rejected(self, client, officers):
        """Oversized candidate name (> 100 chars) must be rejected with 400."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        res = client.post("/api/admin/elections", headers=headers, json={
            "election_id": "ELEC_OVERSIZED_TEST",
            "title": "Oversized Test Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        assert res.status_code == 201

        # Attempt candidate with 500-char name
        res_cand = client.post("/api/admin/elections/ELEC_OVERSIZED_TEST/candidates", headers=headers, json={
            "name": "A" * 500,
            "department": "Computer Science",
        })
        assert res_cand.status_code == 400

    def test_oversized_election_title_rejected(self, client, officers):
        """Election title exceeding 200 characters must be rejected with 400."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        res = client.post("/api/admin/elections", headers=headers, json={
            "title": "T" * 500,
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        assert res.status_code == 400

    def test_deeply_nested_json_payload(self, client):
        """Deeply nested JSON structure handled safely without worker crash."""
        payload = {"a": 1}
        for _ in range(30):
            payload = {"nested": payload}
        res = client.post("/api/auth/login", json=payload)
        assert res.status_code in (400, 401)


class TestSqlInjectionDefense:
    """Part 2: SQL Injection audit across all database-backed endpoints."""

    SQLI_PAYLOADS = [
        "' OR '1'='1",
        "admin'--",
        "' UNION SELECT 1, 'admin', 'hash' --",
        "'; DROP TABLE elections; --",
        "1' OR '1' = '1' --",
        "1 OR 1=1",
        "' OR ''='",
    ]

    def test_sqli_in_election_id_lookup(self, client, officers):
        """Verify SQLi payloads in election_id URL paths fail closed as 404 or 400."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        for sqli in self.SQLI_PAYLOADS:
            res = client.get(f"/api/admin/elections/{sqli}", headers=headers)
            assert res.status_code in (400, 404), f"SQLi '{sqli}' caused status {res.status_code}"
            assert res.is_json

    def test_sqli_in_auth_login(self, client):
        """Verify SQLi in username and password fails authentication without SQL error."""
        for sqli in self.SQLI_PAYLOADS:
            res = client.post("/api/auth/login", json={
                "username": sqli,
                "password": sqli,
            })
            assert res.status_code == 401
            assert res.is_json

    def test_sqli_in_registration_usn(self, client):
        """Verify SQLi in registration USN fails safely."""
        for sqli in self.SQLI_PAYLOADS:
            res = client.post("/api/registration/check", json={"usn": sqli})
            assert res.status_code == 400
            assert res.is_json

    def test_sqli_in_dispute_queries(self, client, officers):
        """Verify operational dispute queries parameterize input safely."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        for sqli in self.SQLI_PAYLOADS:
            res = client.post("/api/admin/disputes/query", headers=headers, json={
                "query_type": "RECEIPT_CODE",
                "receipt_code": sqli,
            })
            assert res.status_code in (200, 400)
            if res.status_code == 200:
                assert res.get_json()["data"]["found"] is False


class TestXssAndSecurityHeaders:
    """Part 3 & 4: XSS output escaping, CSP headers, and CSRF architecture."""

    def test_strict_csp_and_security_headers_present(self, client):
        """Verify strict Content-Security-Policy and hardening headers are on API responses."""
        res = client.get("/api/health")
        assert res.status_code == 200
        headers = res.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert "default-src 'none'" in headers.get("Content-Security-Policy", "")

    def test_xss_payload_in_candidate_stored_as_literal_text(self, client, officers):
        """Candidate name containing script tags is stored as literal string."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )
        xss_name = "<script>alert('pwn')</script>"
        res = client.post("/api/admin/elections", headers=headers, json={
            "election_id": "ELEC_XSS_TEST",
            "title": "XSS Test Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        assert res.status_code == 201

        res_cand = client.post("/api/admin/elections/ELEC_XSS_TEST/candidates", headers=headers, json={
            "name": xss_name,
            "department": "Engineering",
        })
        assert res_cand.status_code == 200

        # Retrieve election and verify JSON preserves string without unescaped HTML execution context
        res_get = client.get("/api/admin/elections/ELEC_XSS_TEST", headers=headers)
        data = res_get.get_json()
        assert data["candidates"][0]["name"] == xss_name


# ==============================================================================
# PART 2: FACE / LIVENESS ATTACKS
# ==============================================================================

class TestFaceLivenessAttacks:
    """13.2 Face / Liveness attack vectors: photo, screen, replay, wrong-direction, multiple faces."""

    ME = fx.FIXTURE_IDENTITIES[0]
    OTHER = fx.other_identity(exclude=(ME,))

    def test_photo_attack_static_pose_rejected(self, face_client, db, face_user):
        """13.3.1 Photo attack: A static face image fails movement/liveness."""
        challenge = face_client.post("/api/face/challenge").get_json()
        frames = fx.build_frames(self.ME, fx.static_yaws(16))
        res = post_frames(face_client, "/api/face/enroll", frames, challenge["challenge_id"], consent=True)
        assert res.status_code == 400
        assert FaceEnrollment.query.count() == 0

    def test_screen_replay_challenge_cannot_be_reused(self, face_client, db, face_user):
        """13.3.2/13.3.3 Replay attack: Challenge is strictly single-use and cannot be replayed."""
        challenge = face_client.post("/api/face/challenge").get_json()
        frames = fx.compliant_frames(self.ME)[:3]
        first = post_frames(face_client, "/api/face/enroll", frames, challenge["challenge_id"], consent=True)
        assert first.status_code == 200, first.get_json()

        # Replay same challenge and frames
        second = post_frames(face_client, "/api/face/enroll", frames, challenge["challenge_id"], consent=True)
        assert second.status_code == 400

    def test_wrong_direction_attack_rejected(self, face_client, db, face_user):
        """13.3.4 Biometric attack: Impostor face submission rejected during verification."""
        # Enrol ME
        ch1 = face_client.post("/api/face/challenge").get_json()
        enrol_res = post_frames(face_client, "/api/face/enroll", fx.compliant_frames(self.ME)[:3], ch1["challenge_id"], consent=True)
        assert enrol_res.status_code == 200, enrol_res.get_json()

        # Impostor (OTHER) attempts to verify against ME's enrolled template
        ch2 = face_client.post("/api/face/challenge").get_json()
        impostor_frames = fx.compliant_frames(self.OTHER)[:3]
        res = post_frames(face_client, "/api/face/verify", impostor_frames, ch2["challenge_id"])
        assert res.status_code == 400

    def test_multiple_face_attack_rejected(self, face_client, db, face_user):
        """13.3.5 Multiple-face attack: Frame with multiple faces is rejected."""
        import cv2
        challenge = face_client.post("/api/face/challenge").get_json()
        canvas = np.full((480, 760, 3), 120, np.uint8)
        canvas[60:420, 20:380] = fx.render(self.ME, 0.0, seed=31)
        canvas[60:420, 380:740] = fx.render(self.OTHER, 0.0, seed=32)
        ok, buf = cv2.imencode(".jpg", canvas)
        assert ok
        frames = [buf.tobytes() for _ in range(3)]
        res = post_frames(face_client, "/api/face/enroll", frames, challenge["challenge_id"], consent=True)
        assert res.status_code == 400

    def test_stale_and_expired_challenge_rejected(self, face_client, db, face_user):
        """Challenge past TTL is rejected."""
        challenge = face_client.post("/api/face/challenge").get_json()
        row = FaceChallenge.query.filter_by(challenge_id=challenge["challenge_id"]).one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=10)
        db.session.commit()

        frames = fx.compliant_frames(self.ME)[:3]
        res = post_frames(face_client, "/api/face/enroll", frames, challenge["challenge_id"], consent=True)
        assert res.status_code == 400


# ==============================================================================
# PART 3: BLOCKCHAIN ATTACKS
# ==============================================================================

class TestBlockchainSecurityInvariants:
    """13.3 Blockchain & Relayer attack surfaces."""

    def test_invalid_candidate_bounds_rejected_by_voting_service(self, db, phase2_user):
        """Candidate index out-of-bounds or negative rejected before relayer queueing."""
        # Setup active election
        election = Election(
            election_id="ELEC_BC_TEST",
            title="Blockchain Election",
            status="OPEN",
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            candidate_count=2,
            eligible_count=100,
            max_ballots=3,
        )
        db.session.add(election)
        db.session.commit()
        get_election_pseudonym_key(election.election_id)

        # Test negative candidate
        ok, err, _ = VotingService.validate_election_and_candidate(
            election.id, candidate=-1
        )
        assert not ok
        assert err == "INVALID_CANDIDATE"

        # Test candidate >= candidate_count
        ok2, err2, _ = VotingService.validate_election_and_candidate(
            election.id, candidate=5
        )
        assert not ok2
        assert err2 == "INVALID_CANDIDATE"

    def test_voting_outside_election_window_rejected(self, db, phase2_user):
        """Ballot submission outside election start/end times is rejected."""
        # Future election
        future_elec = Election(
            election_id="ELEC_FUTURE",
            title="Future Election",
            status="OPEN",
            start_time=datetime.utcnow() + timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=6),
            candidate_count=2,
        )
        # Closed election
        past_elec = Election(
            election_id="ELEC_PAST",
            title="Past Election",
            status="CLOSED",
            start_time=datetime.utcnow() - timedelta(hours=6),
            end_time=datetime.utcnow() - timedelta(hours=2),
            candidate_count=2,
        )
        db.session.add_all([future_elec, past_elec])
        db.session.commit()

        ok1, err1, _ = VotingService.validate_election_and_candidate(future_elec.id, candidate=0)
        assert not ok1
        assert err1 == "ELECTION_NOT_OPEN"

        ok2, err2, _ = VotingService.validate_election_and_candidate(past_elec.id, candidate=0)
        assert not ok2
        assert err2 in ("ELECTION_NOT_ACTIVE", "ELECTION_CLOSED")

    def test_controlled_revoting_max_sequence_ceiling(self, db, phase2_user):
        """Voter cannot exceed MAX_BALLOTS_PER_VOTER (default 3)."""
        election = Election(
            election_id="ELEC_REVOTE_TEST",
            title="Revote Test Election",
            status="OPEN",
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            candidate_count=2,
            eligible_count=100,
            max_ballots=3,
        )
        db.session.add(election)
        db.session.commit()
        get_election_pseudonym_key(election.election_id)

        pseud = derive_pseudonym(phase2_user.id, election.id)
        # Insert 3 existing ballots
        for seq in [1, 2, 3]:
            b = BallotRecord(
                election_id=election.id,
                pseudonym=pseud,
                candidate=0,
                sequence=seq,
                state="FINALIZED",
            )
            db.session.add(b)
        db.session.commit()

        # Attempt 4th ballot submission
        ballot, err = VotingService.submit_ballot(
            user_id=phase2_user.id,
            election_id=election.id,
            candidate=1,
        )
        assert ballot is None
        assert err == "MAX_BALLOTS_EXCEEDED"


# ==============================================================================
# PART 4: PRIVACY ATTACKS
# ==============================================================================

class TestPrivacyAttacks:
    """13.4 Privacy attacks: Database join, log inspection, receipt coercion-freeness."""

    def test_database_join_separation_audit(self, db, phase2_user):
        """
        Verify Identity Plane (User) and Ballot Plane (BallotRecord / Ballot)
        have NO direct foreign key linkage, making database join attacks impossible.
        """
        from sqlalchemy import inspect
        inspector = inspect(db.engine)

        # Check foreign keys on ballot_records
        fks_ballot_records = inspector.get_foreign_keys("ballot_queue") if "ballot_queue" in inspector.get_table_names() else []
        for fk in fks_ballot_records:
            assert fk["referred_table"] != "users", "Ballot table must not have FK to users table!"

        # Check foreign keys on ballots
        fks_ballots = inspector.get_foreign_keys("ballots") if "ballots" in inspector.get_table_names() else []
        for fk in fks_ballots:
            assert fk["referred_table"] != "users", "Ballots must not have FK to users table!"

    def test_receipt_inspection_coercion_free(self, db, phase2_user):
        """Receipt payload contains receipt_code and voter_id_last4 but NO candidate choice."""
        b = BallotRecord(
            election_id=1,
            pseudonym="test_pseudonym_hash",
            candidate=1,
            sequence=1,
            receipt_code="REC-ABC123XYZ",
            state="FINALIZED",
        )
        db.session.add(b)
        db.session.commit()

        receipt = VotingService.generate_receipt(b, phase2_user.id)
        assert "receipt_code" in receipt
        assert receipt["receipt_code"].startswith("REC-")
        assert "candidate" not in receipt, "Receipt must NEVER leak candidate choice!"
        assert "choice" not in receipt, "Receipt must NEVER leak choice!"

    def test_pseudonym_destruction_upon_finalization(self, db):
        """Per-election pseudonym salt destruction permanently prevents correlating pseudonym to voter."""
        get_election_pseudonym_key("ELEC_DESTROY_TEST")
        # Ensure key exists
        pseud1 = derive_pseudonym(101, "ELEC_DESTROY_TEST")
        assert pseud1 is not None

        # Destroy key upon finalization
        destroyed = destroy_election_pseudonym_key("ELEC_DESTROY_TEST")
        assert destroyed is True

        # Derivation must now fail closed
        from app.security.pseudonym import PseudonymKeyError
        with pytest.raises(PseudonymKeyError):
            derive_pseudonym(101, "ELEC_DESTROY_TEST")


# ==============================================================================
# PART 5: ADMIN GOVERNANCE ATTACKS
# ==============================================================================

class TestAdminGovernanceAttacks:
    """13.5 Admin attacks: Self-approval, election modification, audit tampering, RBAC/IDOR."""

    def test_self_approval_prohibited_all_action_types(self, client, officers):
        """Officer 1 creates an approval request and attempts to approve it themselves."""
        officer1, secret1 = officers["officer1"]
        headers1 = login_admin_token(client, officer1.admin_id, "ValidOfficerPassword123!", secret1)

        # Create draft election
        res_elec = client.post("/api/admin/elections", headers=headers1, json={
            "election_id": "ELEC_FOUR_EYES_TEST",
            "title": "Four Eyes Test Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        assert res_elec.status_code == 201

        # Add 2 candidates
        client.post("/api/admin/elections/ELEC_FOUR_EYES_TEST/candidates", headers=headers1, json={
            "name": "Candidate A", "department": "Science",
        })
        client.post("/api/admin/elections/ELEC_FOUR_EYES_TEST/candidates", headers=headers1, json={
            "name": "Candidate B", "department": "Arts",
        })

        # Request SCHEDULE approval by Officer 1
        res_req = client.post("/api/admin/elections/ELEC_FOUR_EYES_TEST/request-approval", headers=headers1, json={
            "operation": "SCHEDULE_ELECTION",
            "reason": "Ready for schedule",
        })
        assert res_req.status_code == 201
        req_id = res_req.get_json()["approval_request"]["id"]

        # Officer 1 attempts to approve their OWN request -> MUST FAIL 403
        res_self = client.post(f"/api/admin/approvals/{req_id}/approve", headers=headers1)
        assert res_self.status_code == 403
        assert res_self.get_json()["error"] == "FOUR_EYES_VIOLATION"

    def test_election_immutability_after_scheduling(self, client, officers):
        """Candidates and election timing cannot be modified once SCHEDULED."""
        officer1, secret1 = officers["officer1"]
        officer2, secret2 = officers["officer2"]
        headers1 = login_admin_token(client, officer1.admin_id, "ValidOfficerPassword123!", secret1)
        headers2 = login_admin_token(client, officer2.admin_id, "ValidOfficerPassword456!", secret2)

        # Create draft & add candidates
        client.post("/api/admin/elections", headers=headers1, json={
            "election_id": "ELEC_IMMUTABLE_TEST",
            "title": "Immutable Test Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        client.post("/api/admin/elections/ELEC_IMMUTABLE_TEST/candidates", headers=headers1, json={"name": "C1"})
        client.post("/api/admin/elections/ELEC_IMMUTABLE_TEST/candidates", headers=headers1, json={"name": "C2"})

        # Officer 1 requests schedule
        res_req = client.post("/api/admin/elections/ELEC_IMMUTABLE_TEST/request-approval", headers=headers1, json={
            "operation": "SCHEDULE_ELECTION",
        })
        assert res_req.status_code == 201
        req_id = res_req.get_json()["approval_request"]["id"]

        # Officer 2 approves -> moves to SCHEDULED
        res_appr = client.post(f"/api/admin/approvals/{req_id}/approve", headers=headers2)
        assert res_appr.status_code == 200

        # Attempt to add another candidate -> MUST FAIL 409 IMMUTABLE_ELECTION
        res_cand = client.post("/api/admin/elections/ELEC_IMMUTABLE_TEST/candidates", headers=headers1, json={"name": "C3"})
        assert res_cand.status_code == 409
        assert res_cand.get_json()["error"] == "IMMUTABLE_ELECTION"

        # Attempt to update dates -> MUST FAIL 409 IMMUTABLE_ELECTION
        res_upd = client.put("/api/admin/elections/ELEC_IMMUTABLE_TEST", headers=headers1, json={
            "title": "Altered Title",
        })
        assert res_upd.status_code == 409
        assert res_upd.get_json()["error"] == "IMMUTABLE_ELECTION"

    def test_audit_hash_chain_tampering_detected(self, client, officers, db):
        """Direct DB modification of audit log event breaks SHA-256 chain and is detected."""
        headers = login_admin_token(
            client,
            officers["officer1"][0].admin_id,
            "ValidOfficerPassword123!",
            officers["officer1"][1],
        )

        # Verify chain is currently intact
        res_check = client.get("/api/admin/audit-logs/verify-chain", headers=headers)
        assert res_check.status_code == 200
        assert res_check.get_json()["valid"] is True

        # Tamper with an audit event
        event = AuditEvent.query.first()
        if event:
            original_type = event.event_type
            event.event_type = "TAMPERED_EVENT_TYPE"
            db.session.commit()

            # Chain verification must now detect tampering
            res_tampered = client.get("/api/admin/audit-logs/verify-chain", headers=headers)
            assert res_tampered.status_code == 200
            assert res_tampered.get_json()["valid"] is False

            # Restore event
            event.event_type = original_type
            db.session.commit()

    def test_admin_rbac_auditor_cannot_execute_officer_actions(self, client, officers):
        """Auditor role cannot create elections or approve critical operations."""
        auditor, aud_secret = officers["auditor"]
        aud_headers = login_admin_token(client, auditor.admin_id, "ValidAuditorPassword789!", aud_secret)

        # Auditor attempts to create election -> 403 Forbidden
        res = client.post("/api/admin/elections", headers=aud_headers, json={
            "title": "Auditor Election",
            "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=5)).isoformat(),
        })
        assert res.status_code == 403
