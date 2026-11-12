"""
Test Suite for Election Results Export (CSV and XLSX)
Task 6 - Vote Without Doubt Backend Test Suite

Tests:
1.  Unauthenticated request rejected (401)
2.  Unauthorized role rejected (403, e.g. non-officer/non-auditor)
3.  Authorized OFFICER can export (200)
4.  Authorized AUDITOR can export (200)
5.  Unknown election returns 404
6.  Invalid format query parameter rejected (400)
7.  OPEN, SCHEDULED, and DRAFT elections return 403 (results withheld)
8.  PROCESSING_PENDING_BALLOTS returns 423
9.  RESULTS_UNDER_REVIEW returns 403 (withheld until resolved)
10. Unknown/missing result states fail closed (403)
11. Provisional results export generates CSV with 'PROVISIONAL — NOT CERTIFIED'
12. Finalized results export generates CSV with 'OFFICIAL FINALIZED RESULTS'
13. XLSX export produces valid spreadsheet (openpyxl or zipfile inspection)
14. XLSX contains all three required worksheets
15. CSV formula injection characters (=, +, -, @) safely escaped
16. Untrusted text in XLSX written via write_string or sanitized
17. Sensitive fields strictly absent: no student names, USNs, emails, wallet addresses,
    biometric data, pseudonyms, receipt codes, raw roll hash, internal database primary keys
18. No cross-election tally or candidate leakage
19. Successful export records ELECTION_RESULTS_EXPORTED audit event
20. Audit failure prevents export download (500)
21. File generation failure does not record audit event
22. Export operation does not mutate ballots, ballot queue, or election records
"""

import io
import json
import secrets
import zipfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.audit.audit import AuditEvent, AuditLogger
from app.extensions import db
from app.models.admin import AdminSession, AdminUser, Candidate
from app.models.ballot import Ballot, Election
from app.models.ballot_record import BallotQueue
from app.models.reconciliation import ReconciliationIssue
from app.security.admin_auth import AdminAuthService, hash_password
from app.services.export_service import ExportService, sanitize_cell
from app.services.results_service import ResultsService


@pytest.fixture
def officers(db):
    """Seed distinct officer, auditor, and unauthorized admin with valid 64-char sessions."""
    now = datetime.utcnow()

    # Officer
    off = AdminUser(
        admin_id="OFF_EXPORT_01",
        name="Chief Officer",
        email="officer@vwd.test",
        password_hash=hash_password("OfficerPass123!"),
        role="OFFICER",
        is_active=True,
    )
    db.session.add(off)
    db.session.flush()

    off_token = secrets.token_hex(32)
    off_sess = AdminSession(
        session_token=off_token,
        admin_id=off.id,
        role="OFFICER",
        expires_at=now + timedelta(hours=8),
        revoked=False,
    )
    db.session.add(off_sess)

    # Auditor
    aud = AdminUser(
        admin_id="AUD_EXPORT_01",
        name="Lead Auditor",
        email="auditor@vwd.test",
        password_hash=hash_password("AuditorPass123!"),
        role="AUDITOR",
        is_active=True,
    )
    db.session.add(aud)
    db.session.flush()

    aud_token = secrets.token_hex(32)
    aud_sess = AdminSession(
        session_token=aud_token,
        admin_id=aud.id,
        role="AUDITOR",
        expires_at=now + timedelta(hours=8),
        revoked=False,
    )
    db.session.add(aud_sess)

    # Unauthorized Role (e.g. VIEWER or STUDENT)
    unauth = AdminUser(
        admin_id="UNAUTH_01",
        name="Unauthorized User",
        email="viewer@vwd.test",
        password_hash=hash_password("ViewerPass123!"),
        role="OBSERVER",
        is_active=True,
    )
    db.session.add(unauth)
    db.session.flush()

    unauth_token = secrets.token_hex(32)
    unauth_sess = AdminSession(
        session_token=unauth_token,
        admin_id=unauth.id,
        role="OBSERVER",
        expires_at=now + timedelta(hours=8),
        revoked=False,
    )
    db.session.add(unauth_sess)

    db.session.commit()

    return {
        "officer": off,
        "officer_token": off_token,
        "auditor": aud,
        "auditor_token": aud_token,
        "unauth": unauth,
        "unauth_token": unauth_token,
    }


@pytest.fixture
def mock_results_provisional():
    """Provisional clean results payload matching ResultsService structure."""
    return {
        "election_id": "elec-prov-2026",
        "election_title": "Student Council President 2026",
        "status": "CLOSED",
        "is_finalized": False,
        "result_state": "PROVISIONAL_UNFINALIZED",
        "total_distinct_voters": 120,
        "turnout_percentage": 60.0,
        "total_valid_votes": 115,
        "total_null_votes": 5,
        "blockchain_verified": True,
        "tally_matches_blockchain": True,
        "is_tie": False,
        "open_reconciliation_issues": 0,
        "candidates": [
            {
                "candidate_index": 0,
                "name": "Candidate Alice",
                "department": "Computer Science",
                "votes": 75,
                "percentage": 65.22,
            },
            {
                "candidate_index": 1,
                "name": "Candidate Bob",
                "department": "Mechanical Eng",
                "votes": 40,
                "percentage": 34.78,
            },
        ],
        "winners": [
            {
                "candidate_index": 0,
                "name": "Candidate Alice",
                "department": "Computer Science",
                "votes": 75,
                "percentage": 65.22,
            }
        ],
    }


@pytest.fixture
def mock_results_finalized():
    """Finalized clean results payload matching ResultsService structure."""
    return {
        "election_id": "elec-fin-2026",
        "election_title": "Senate General Election 2026",
        "status": "FINALIZED",
        "is_finalized": True,
        "result_state": "FINALIZED_RESULTS",
        "total_distinct_voters": 200,
        "turnout_percentage": 80.0,
        "total_valid_votes": 195,
        "total_null_votes": 5,
        "blockchain_verified": True,
        "tally_matches_blockchain": True,
        "is_tie": False,
        "open_reconciliation_issues": 0,
        "candidates": [
            {
                "candidate_index": 0,
                "name": "Candidate Carol",
                "department": "Electrical Eng",
                "votes": 120,
                "percentage": 61.54,
            },
            {
                "candidate_index": 1,
                "name": "Candidate Dave",
                "department": "Civil Eng",
                "votes": 75,
                "percentage": 38.46,
            },
        ],
        "winners": [
            {
                "candidate_index": 0,
                "name": "Candidate Carol",
                "department": "Electrical Eng",
                "votes": 120,
                "percentage": 61.54,
            }
        ],
    }


# ==============================================================================
# TEST 1: Unauthenticated request rejected (401)
# ==============================================================================
def test_export_unauthenticated_rejected(client, db):
    res = client.get("/api/admin/elections/elec-101/export?format=csv")
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"] in ("AUTH_REQUIRED", "INVALID_SESSION")


# ==============================================================================
# TEST 2: Unauthorized role rejected (403)
# ==============================================================================
def test_export_unauthorized_role_rejected(client, officers):
    token = officers["unauth_token"]
    res = client.get(
        "/api/admin/elections/elec-101/export?format=csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "ROLE_UNAUTHORIZED"


# ==============================================================================
# TEST 3: Authorized OFFICER can export (200)
# ==============================================================================
def test_export_officer_authorized(client, officers, mock_results_provisional, db):
    # Seed election record
    e = Election(
        election_id="elec-prov-2026",
        title="Student Council President 2026",
        status="CLOSED",
        candidate_count=2,
        eligible_count=200,
        roll_hash="0x" + "a" * 64,
        candidates_hash="0x" + "b" * 64,
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert "text/csv" in res.content_type
        assert "PROVISIONAL" in res.data.decode("utf-8")


# ==============================================================================
# TEST 4: Authorized AUDITOR can export (200)
# ==============================================================================
def test_export_auditor_authorized(client, officers, mock_results_finalized, db):
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
        candidate_count=2,
        eligible_count=250,
        roll_hash="0x" + "a" * 64,
        candidates_hash="0x" + "b" * 64,
    )
    db.session.add(e)
    db.session.commit()

    token = officers["auditor_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert "openxmlformats-officedocument.spreadsheetml.sheet" in res.content_type


# ==============================================================================
# TEST 5: Unknown election returns 404
# ==============================================================================
def test_export_unknown_election_returns_404(client, officers):
    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(False, "ELECTION_NOT_FOUND", {"error": "ELECTION_NOT_FOUND"})):
        res = client.get(
            "/api/admin/elections/nonexistent-election/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404
        data = res.get_json()
        assert data["error"] == "ELECTION_NOT_FOUND"


# ==============================================================================
# TEST 6: Invalid format query parameter rejected (400)
# ==============================================================================
def test_export_invalid_format_rejected(client, officers, mock_results_provisional, db):
    e = Election(
        election_id="elec-prov-2026",
        title="Student Council President 2026",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)):
        # Format = json or xml or empty
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 400
        data = res.get_json()
        assert data["error"] == "INVALID_FORMAT"

        # Missing format defaults or checks
        res2 = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res2.status_code == 400


# ==============================================================================
# TEST 7: OPEN, SCHEDULED, and DRAFT elections return 403 (results withheld)
# ==============================================================================
@pytest.mark.parametrize("bad_status", ["OPEN", "SCHEDULED", "DRAFT"])
def test_export_open_scheduled_draft_withheld(client, officers, bad_status, db):
    e = Election(
        election_id=f"elec-{bad_status.lower()}",
        title=f"Election in {bad_status}",
        status=bad_status,
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    mock_withheld = {
        "error": "RESULTS_UNAVAILABLE",
        "message": f"Results remain withheld in status '{bad_status}'",
    }
    with patch.object(ResultsService, "get_election_results", return_value=(False, "RESULTS_UNAVAILABLE", mock_withheld)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"] in ("RESULTS_UNAVAILABLE", "RESULTS_WITHHELD")


# ==============================================================================
# TEST 8: PROCESSING_PENDING_BALLOTS returns 423
# ==============================================================================
def test_export_pending_ballots_returns_423(client, officers, db):
    e = Election(
        election_id="elec-pending-queue",
        title="Election with in-flight queue",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    mock_pending = {
        "result_state": "PROCESSING_PENDING_BALLOTS",
        "pending_ballots_count": 3,
        "message": "Queue is draining on blockchain",
    }
    with patch.object(ResultsService, "get_election_results", return_value=(False, "PROCESSING_PENDING_BALLOTS", mock_pending)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 423
        data = res.get_json()
        assert data["error"] == "PROCESSING_PENDING_BALLOTS"


# ==============================================================================
# TEST 9: RESULTS_UNDER_REVIEW returns 403 (withheld until resolved)
# ==============================================================================
def test_export_under_review_returns_403(client, officers, db):
    e = Election(
        election_id="elec-under-review",
        title="Election under review",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    mock_review = {
        "result_state": "RESULTS_UNDER_REVIEW",
        "open_reconciliation_issues": 2,
        "message": "Results withheld during active reconciliation review",
    }
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_review)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"] == "RESULTS_UNDER_REVIEW"


# ==============================================================================
# TEST 10: Unknown/missing result states fail closed (403)
# ==============================================================================
def test_export_unknown_result_state_fails_closed(client, officers, db):
    e = Election(
        election_id="elec-unknown-state",
        title="Election with unknown state",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    mock_corrupt = {
        "result_state": "CORRUPTED_OR_UNKNOWN_STATE",
        "total_distinct_voters": 50,
    }
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_corrupt)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"] in ("INVALID_RESULT_STATE", "EXPORT_NOT_PERMITTED")


# ==============================================================================
# TEST 11: Provisional results export generates CSV with 'PROVISIONAL — NOT CERTIFIED'
# ==============================================================================
def test_export_csv_provisional_label(client, officers, mock_results_provisional, db):
    e = Election(
        election_id="elec-prov-2026",
        title="Student Council President 2026",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        content = res.data.decode("utf-8")
        assert "PROVISIONAL — NOT CERTIFIED" in content
        assert "Candidate Alice" in content
        # Ensure CRLF terminators
        assert "\r\n" in content


# ==============================================================================
# TEST 12: Finalized results export generates CSV with 'OFFICIAL FINALIZED RESULTS'
# ==============================================================================
def test_export_csv_finalized_label(client, officers, mock_results_finalized, db):
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        content = res.data.decode("utf-8")
        assert "OFFICIAL FINALIZED RESULTS" in content
        assert "Candidate Carol" in content


# ==============================================================================
# TEST 13: XLSX export produces valid spreadsheet (zipfile inspection)
# ==============================================================================
def test_export_xlsx_produces_valid_spreadsheet(client, officers, mock_results_finalized, db):
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        # Valid XLSX must be an openable ZIP archive containing xl/workbook.xml
        buf = io.BytesIO(res.data)
        assert zipfile.is_zipfile(buf)
        with zipfile.ZipFile(buf, "r") as zf:
            namelist = zf.namelist()
            assert "xl/workbook.xml" in namelist
            assert "[Content_Types].xml" in namelist


# ==============================================================================
# TEST 14: XLSX contains all three required worksheets
# ==============================================================================
def test_export_xlsx_contains_three_worksheets(client, officers, mock_results_finalized, db):
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        buf = io.BytesIO(res.data)
        with zipfile.ZipFile(buf, "r") as zf:
            wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
            assert "Election Summary" in wb_xml
            assert "Candidate Tallies" in wb_xml
            assert "Audit Evidence" in wb_xml


# ==============================================================================
# TEST 15: CSV formula injection characters (=, +, -, @) safely escaped
# ==============================================================================
def test_csv_formula_injection_escaping():
    assert sanitize_cell("=1+1") == "'=1+1"
    assert sanitize_cell("+100") == "'+100"
    assert sanitize_cell("-50") == "'-50"
    assert sanitize_cell("@SUM(A1)") == "'@SUM(A1)"
    assert sanitize_cell("\tCMD") == "'\tCMD"
    assert sanitize_cell("  =cmd") == "'  =cmd"
    assert sanitize_cell("Alice Smith") == "Alice Smith"
    assert sanitize_cell(123) == "123"
    assert sanitize_cell(None) == ""


# ==============================================================================
# TEST 16: Untrusted text in XLSX written via write_string or sanitized
# ==============================================================================
def test_xlsx_formula_injection_sanitization(officers, mock_results_provisional, db):
    # Inject formula characters into candidate name and department
    malicious_results = dict(mock_results_provisional)
    malicious_results["candidates"] = [
        {
            "candidate_index": 0,
            "name": "=cmd|' /C calc'!A0",
            "department": "+SUM(1,2)",
            "votes": 10,
            "percentage": 100.0,
        }
    ]
    malicious_results["winners"] = malicious_results["candidates"]

    e = Election(
        election_id=malicious_results["election_id"],
        title="=HYPERLINK(\"http://evil.com\")",
        status="CLOSED",
    )
    db.session.add(e)
    db.session.commit()

    admin = officers["officer"]
    output = ExportService.generate_results_xlsx(malicious_results, admin)
    assert isinstance(output, io.BytesIO)

    with zipfile.ZipFile(output, "r") as zf:
        # Check that sheet xml contains escaped versions or strings
        for name in zf.namelist():
            if name.startswith("xl/worksheets/"):
                sheet_xml = zf.read(name).decode("utf-8")
                # Neither '=cmd' nor '+SUM' should be written as a formula element (<f>)
                assert "<f>=cmd" not in sheet_xml
                assert "<f>+SUM" not in sheet_xml


# ==============================================================================
# TEST 17: Sensitive fields strictly absent: no student names, USNs, emails,
# wallet addresses, biometric data, pseudonyms, receipt codes, raw roll hash, internal DB PKs
# ==============================================================================
def test_export_sensitive_fields_strictly_absent(client, officers, mock_results_finalized, db):
    raw_roll_hash = "0x" + "f" * 64
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
        roll_hash=raw_roll_hash,
    )
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        # 1. Inspect CSV
        res_csv = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_csv.status_code == 200
        csv_text = res_csv.data.decode("utf-8")

        # Must NOT leak raw roll hash
        assert raw_roll_hash not in csv_text
        # Must NOT leak internal integer database IDs (e.g. e.id or admin.id)
        assert f"Election.id: {e.id}" not in csv_text
        # Must NOT mention student private fields
        for forbidden in ["usn", "USN", "receipt_code", "pseudonym", "biometric", "wallet_address"]:
            assert forbidden not in csv_text

        # 2. Inspect XLSX
        res_xlsx = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_xlsx.status_code == 200
        buf = io.BytesIO(res_xlsx.data)
        with zipfile.ZipFile(buf, "r") as zf:
            for item in zf.namelist():
                if item.endswith(".xml"):
                    xml_content = zf.read(item).decode("utf-8", errors="ignore")
                    assert raw_roll_hash not in xml_content


# ==============================================================================
# TEST 18: No cross-election tally or candidate leakage
# ==============================================================================
def test_export_no_cross_election_leakage(client, officers, mock_results_provisional, db):
    e1 = Election(election_id="elec-01", title="Election One", status="CLOSED")
    e2 = Election(election_id="elec-02", title="Election Two", status="CLOSED")
    db.session.add_all([e1, e2])
    db.session.commit()

    token = officers["officer_token"]
    # Mock ResultsService verifying that the correct election_id is requested
    def mock_results_call(election_id):
        assert election_id == "elec-01"
        return True, "RESULTS_COMPUTED", dict(mock_results_provisional, election_id=election_id, election_title="Election One")

    with patch.object(ResultsService, "get_election_results", side_effect=mock_results_call):
        res = client.get(
            f"/api/admin/elections/{e1.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        content = res.data.decode("utf-8")
        assert "Election One" in content
        assert "Election Two" not in content


# ==============================================================================
# TEST 19: Successful export records ELECTION_RESULTS_EXPORTED audit event
# ==============================================================================
def test_export_records_audit_event_on_success(client, officers, mock_results_provisional, db):
    e = Election(election_id="elec-prov-2026", title="Election Audit Test", status="CLOSED")
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

        # Verify audit event in database
        event = (
            AuditEvent.query.filter_by(event_type="ELECTION_RESULTS_EXPORTED")
            .order_by(AuditEvent.id.desc())
            .first()
        )
        assert event is not None
        meta_str = getattr(event, 'event_metadata', None) or getattr(event, 'metadata_json', None) or getattr(event, 'metadata', None)
        payload = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
        assert payload["election_id"] == e.election_id
        assert "format" in payload
        assert "role" in payload
        assert "admin_id" in payload
        assert "result_state" in payload
        assert payload["officer_id"] == officers["officer"].admin_id
        assert payload["state"] == "PROVISIONAL_UNFINALIZED"
        assert payload["action"] == "EXPORT_CSV"
        # Ensure no secrets logged
        assert "ip" not in payload
        assert "user_agent" not in payload


# ==============================================================================
# TEST 20: Audit failure prevents export download (500)
# ==============================================================================
def test_export_audit_failure_prevents_download(client, officers, mock_results_provisional, db):
    e = Election(election_id="elec-prov-2026", title="Election Audit Fail Test", status="CLOSED")
    db.session.add(e)
    db.session.commit()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)), \
         patch.object(AuditLogger, "log", side_effect=RuntimeError("Audit disk full")):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Audit failure must abort export with 500
        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] in ("AUDIT_LOG_FAILED", "AUDIT_LOGGING_FAILED")


# ==============================================================================
# TEST 21: File generation failure does not record audit event
# ==============================================================================
def test_export_file_generation_failure_no_audit(client, officers, mock_results_provisional, db):
    e = Election(election_id="elec-prov-2026", title="Generation Fail Test", status="CLOSED")
    db.session.add(e)
    db.session.commit()

    initial_audit_count = AuditEvent.query.filter_by(event_type="ELECTION_RESULTS_EXPORTED").count()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_provisional)), \
         patch.object(ExportService, "generate_results_csv", side_effect=Exception("CSV serialization crash")):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] == "EXPORT_GENERATION_FAILED"

        # Verify no audit event was logged
        final_audit_count = AuditEvent.query.filter_by(event_type="ELECTION_RESULTS_EXPORTED").count()
        assert final_audit_count == initial_audit_count


# ==============================================================================
# TEST 22: Export operation does not mutate ballots, ballot queue, or election records
# ==============================================================================
def test_export_operation_is_strictly_read_only(client, officers, mock_results_finalized, db):
    e = Election(
        election_id="elec-fin-2026",
        title="Senate General Election 2026",
        status="FINALIZED",
    )
    db.session.add(e)
    db.session.commit()

    # Seed an unmutated state
    initial_e_status = e.status
    initial_ballots_count = Ballot.query.count()
    initial_queue_count = BallotQueue.query.count()
    initial_issues_count = ReconciliationIssue.query.count()

    token = officers["officer_token"]
    with patch.object(ResultsService, "get_election_results", return_value=(True, "RESULTS_COMPUTED", mock_results_finalized)):
        res = client.get(
            f"/api/admin/elections/{e.election_id}/export?format=xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    # Verify state remains completely unmutated
    db.session.refresh(e)
    assert e.status == initial_e_status
    assert Ballot.query.count() == initial_ballots_count
    assert BallotQueue.query.count() == initial_queue_count
    assert ReconciliationIssue.query.count() == initial_issues_count
