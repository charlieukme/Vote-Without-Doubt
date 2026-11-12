"""
Test Suite: Candidate Photo Upload and Election Schedule Cancellation
Vote Without Doubt (VWD)

Verifies:
1. Candidate photo upload supporting JPG, PNG, and WebP formats.
2. File content validation (actual image payload, not just extension).
3. Max file size enforcement (<= 5 MB; oversized files rejected with 400).
4. Secure image serving via /api/public/candidate-photo/<filename> with nosniff and cache control.
5. Strict filename validation preventing path traversal attacks.
6. Candidate registration storing and persisting uploaded image URLs.
7. Candidate photo replacement for existing candidates in DRAFT state.
8. Safe election schedule cancellation:
   - Clears start_time and end_time.
   - Leaves election in appropriate non-voting state (DRAFT).
   - Prevents stale scheduled auto-opening.
   - Records administrative cancellation in the tamper-evident audit trail.
9. Independence of new election creation and scheduling.
"""

import io
import os
import re
from datetime import datetime, timedelta
import pytest
from PIL import Image

from app.extensions import db
from app.models.admin import AdminUser, Candidate
from app.models.ballot import Election
from app.models.audit_event import AuditEvent
from app.security.admin_auth import AdminAuthService
from app.security.totp import generate_totp_code
from app.services.election_admin_service import ElectionAdminService


@pytest.fixture
def officers(db):
    """Provide authenticated election officers."""
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
    return {
        "officer1": (officer1, secret1),
        "officer2": (officer2, secret2),
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


def make_test_image(format="JPEG", size=(64, 64), color="red"):
    """Generate in-memory image bytes."""
    mode = "RGBA" if format == "PNG" else "RGB"
    img = Image.new(mode, size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf


class TestCandidatePhotoUpload:

    def test_upload_valid_jpeg(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        img_buf = make_test_image(format="JPEG", size=(120, 120), color="blue")

        data = {"photo": (img_buf, "candidate_blue.jpg", "image/jpeg")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 200, res.get_json()

        payload = res.get_json()
        assert "photo_url" in payload
        assert "filename" in payload
        assert payload["photo_url"].startswith("/api/public/candidate-photo/")
        assert re.match(r'^[a-f0-9]{32}\.jpg$', payload["filename"])

        # Verify photo retrieval
        get_res = client.get(payload["photo_url"])
        assert get_res.status_code == 200
        assert get_res.headers.get("X-Content-Type-Options") == "nosniff"
        assert len(get_res.data) > 0

    def test_upload_valid_png(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        img_buf = make_test_image(format="PNG", size=(80, 80), color="green")

        data = {"photo": (img_buf, "candidate_green.png", "image/png")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 200, res.get_json()

        payload = res.get_json()
        assert payload["filename"].endswith(".png")

        # Verify photo retrieval
        get_res = client.get(payload["photo_url"])
        assert get_res.status_code == 200
        assert len(get_res.data) > 0

    def test_upload_valid_webp(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        img_buf = make_test_image(format="WEBP", size=(90, 90), color="purple")

        data = {"photo": (img_buf, "candidate_purple.webp", "image/webp")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 200, res.get_json()

        payload = res.get_json()
        assert payload["filename"].endswith(".webp")

        # Verify photo retrieval
        get_res = client.get(payload["photo_url"])
        assert get_res.status_code == 200

    def test_upload_invalid_content_rejected(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        # Text file pretending to be jpg
        fake_buf = io.BytesIO(b"This is not a real image file, just plain text payload disguised.")

        data = {"photo": (fake_buf, "malicious.jpg", "image/jpeg")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json().get("error") in ("IMAGE_PROCESSING_FAILED", "INVALID_FILE", "INVALID_FORMAT")

    def test_upload_oversized_rejected(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        # 5.1 MB dummy content
        oversized = io.BytesIO(b"X" * (5 * 1024 * 1024 + 1024))

        data = {"photo": (oversized, "huge.jpg", "image/jpeg")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json().get("error") == "FILE_TOO_LARGE"

    def test_path_traversal_prevented(self, client):
        # Attempt to escape upload directory
        res = client.get("/api/public/candidate-photo/../../etc/passwd")
        assert res.status_code in (400, 404)

        res2 = client.get("/api/public/candidate-photo/..%2F..%2Fapp.py")
        assert res2.status_code in (400, 404)

    def test_candidate_registration_with_uploaded_photo(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        # Create draft election
        now = datetime.utcnow()
        election = Election(
            election_id="ELEC_CAND_PHOTO_TEST",
            title="Photo Upload Test Election",
            status="DRAFT",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=2),
            eligible_count=100,
        )
        db.session.add(election)
        db.session.commit()

        # Upload photo
        img_buf = make_test_image(format="JPEG", size=(100, 100), color="orange")
        data = {"photo": (img_buf, "candidate_orange.jpg", "image/jpeg")}
        up_res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert up_res.status_code == 200
        photo_url = up_res.get_json()["photo_url"]

        # Register candidate with the returned photo_url
        cand_res = client.post(
            f"/api/admin/elections/{election.election_id}/candidates",
            headers=headers,
            json={
                "name": "Alice Springs",
                "position": "Student President",
                "photo_url": photo_url,
                "slogan": "Integrity and Action",
            }
        )
        assert cand_res.status_code == 200, cand_res.get_json()

        # Query database and verify persistence
        cand = Candidate.query.filter_by(election_id=election.election_id, name="Alice Springs").first()
        assert cand is not None
        assert cand.photo_url == photo_url

        # Replace photo on existing candidate
        new_img_buf = make_test_image(format="PNG", size=(100, 100), color="yellow")
        replace_res = client.post(
            f"/api/admin/elections/{election.election_id}/candidates/{cand.candidate_index}/photo",
            headers=headers,
            data={"photo": (new_img_buf, "candidate_yellow.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert replace_res.status_code == 200, replace_res.get_json()
        new_photo_url = replace_res.get_json()["photo_url"]

        refreshed_cand = Candidate.query.filter_by(election_id=election.election_id, candidate_index=cand.candidate_index).first()
        assert refreshed_cand.photo_url == new_photo_url

        # Check public election directory visibility
        pub_res = client.get(f"/api/public/elections/{election.election_id}")
        assert pub_res.status_code == 200
        pub_cand = pub_res.get_json()["candidates"][0]
        assert pub_cand["photo_url"] == new_photo_url

    def test_upload_missing_file_rejected(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data={}, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json().get("error") == "MISSING_FILE"

    def test_upload_tiny_file_rejected(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])
        tiny_buf = io.BytesIO(b"short")
        data = {"photo": (tiny_buf, "tiny.jpg", "image/jpeg")}
        res = client.post("/api/admin/candidates/upload-photo", headers=headers, data=data, content_type="multipart/form-data")
        assert res.status_code == 400
        assert res.get_json().get("error") in ("INVALID_FILE", "IMAGE_PROCESSING_FAILED")


class TestCancelScheduledElectionStart:

    def test_clear_election_schedule(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        # Create election with future start time (e.g. scheduled for 4:05 PM)
        now = datetime.utcnow()
        election = Election(
            election_id="ELEC_CANCEL_SCHED_01",
            title="Scheduled 4:05 PM Start Election",
            status="DRAFT",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            eligible_count=200,
        )
        db.session.add(election)
        db.session.commit()

        # Call clear-schedule endpoint
        res = client.post(
            f"/api/admin/elections/{election.election_id}/clear-schedule",
            headers=headers,
            json={"reason": "Cancel 4:05 PM scheduled start per administrator instruction"}
        )
        assert res.status_code == 200, res.get_json()
        data = res.get_json()
        assert data["start_time"] is None
        assert data["end_time"] is None
        assert data["status"] == "DRAFT"

        # Verify database record
        refreshed = Election.query.filter_by(election_id=election.election_id).first()
        assert refreshed.start_time is None
        assert refreshed.end_time is None
        assert refreshed.status == "DRAFT"
        # It must NOT be CLOSED or ARCHIVED
        assert refreshed.status not in ("CLOSED", "ARCHIVED", "OPEN", "ACTIVE")

        # Verify audit trail
        ev = AuditEvent.query.filter_by(event_type="ELECTION_SCHEDULE_CANCELLED").order_by(AuditEvent.id.desc()).first()
        assert ev is not None
        payload = ev.event_metadata or {}
        assert payload.get("election_id") == election.election_id
        assert payload.get("officer_id") == "OFFICER_01"
        assert "Cancel 4:05 PM" in payload.get("reason", "")

    def test_create_and_schedule_new_election_after_cancellation(self, client, officers):
        headers = login_admin(client, "OFFICER_01", "ValidAdminPassword123!", officers["officer1"][1])

        now = datetime.utcnow()
        new_start = now + timedelta(days=2)
        new_end = now + timedelta(days=3)

        res = client.post(
            "/api/admin/elections",
            headers=headers,
            json={
                "title": "Fresh Independent Election 2026",
                "description": "Completely new election following schedule cancellation",
                "start_time": new_start.isoformat() + "Z",
                "end_time": new_end.isoformat() + "Z",
                "eligible_count": 300,
                "max_ballots": 3,
            }
        )
        assert res.status_code == 201, res.get_json()
        new_eid = res.get_json()["election_id"]

        # Confirm new election has its own start/end times and is in DRAFT
        new_elec = Election.query.filter_by(election_id=new_eid).first()
        assert new_elec is not None
        assert new_elec.status == "DRAFT"
        assert new_elec.start_time is not None
        assert new_elec.end_time is not None
