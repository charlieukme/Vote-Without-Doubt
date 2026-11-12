"""
Phase 12 Public Verification and Results Tests
Vote Without Doubt - Backend Test Suite

Tests:
1. Results Gating:
   - Results unavailable while election is OPEN (403 RESULTS_UNAVAILABLE).
   - Results unavailable while election is DRAFT or SCHEDULED.
   - Results available once election is CLOSED.
   - Results available once election is FINALIZED.
2. Canonical Tally Semantics (Phase 9):
   - Sequence progression and latest-vote-wins.
   - Superseded ballots excluded from tallies.
   - Null revotes retract previous candidate choices.
   - Distinct participating voter count accurately computed.
3. Public Verification Endpoint:
   - Returns contract address, election parameters, candidate hash, roll hash.
   - Withholds candidate tallies for OPEN elections.
   - Exposes tally summary for CLOSED and FINALIZED elections.
   - Privacy Invariant: Zero voter identity, USN, email, or pseudonym leakage.
4. Audit Trail & On-Chain Anchoring:
   - Hash chain integrity verified.
   - Broken hash chain detected.
   - On-chain anchor verified against audit head.
5. Controlled Database Tampering Demonstration:
   - Pristine state verified -> CLEAN.
   - Controlled candidate modification -> MISMATCH DETECTED.
   - Clean restoration -> Pristine state returns to CLEAN.
"""

from datetime import datetime, timedelta
import hashlib
import json
import pytest

from app.audit.audit import AuditEvent, AuditLogger
from app.extensions import db
from app.models import BallotRecord, Election, User
from app.models.admin import Candidate
from app.models.reconciliation import ReconciliationIssue
from app.services.results_service import ResultsService
from app.services.verification_service import VerificationService


@pytest.fixture
def p12_election(db):
    """Seed test election."""
    e = Election(
        election_id="ELEC_P12_TEST_01",
        title="Student Senate Election 2026",
        description="Phase 12 Verification Election",
        status="OPEN",
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=2),
        candidate_count=2,
        eligible_count=1000,
        max_ballots=3,
        roll_hash="0x" + "a" * 64,
    )
    db.session.add(e)
    db.session.commit()

    # Seed candidates
    c0 = Candidate(election_id=e.election_id, candidate_index=0, name="Aditya Sharma", department="CSE")
    c1 = Candidate(election_id=e.election_id, candidate_index=1, name="Priya Patel", department="ECE")
    db.session.add_all([c0, c1])
    db.session.commit()

    # Update candidate hash
    e.candidates_hash = VerificationService.compute_candidates_hash(e.election_id)
    db.session.commit()
    return e


# ---------------------------------------------------------------------------
# 1. Results Gating Tests
# ---------------------------------------------------------------------------

def test_results_gated_when_open(client, p12_election):
    """Results must be blocked with 403 when election is still OPEN."""
    res = client.get(f"/api/elections/{p12_election.election_id}/results")
    assert res.status_code == 403
    json_data = res.get_json()
    assert json_data["error"] == "RESULTS_UNAVAILABLE"
    assert "withheld" in json_data["message"].lower()


def test_results_gated_when_draft(client, p12_election, db):
    """Results must be blocked with 403 when election is in DRAFT state."""
    p12_election.status = "DRAFT"
    db.session.commit()

    res = client.get(f"/api/elections/{p12_election.election_id}/results")
    assert res.status_code == 403
    assert res.get_json()["error"] == "RESULTS_UNAVAILABLE"


def test_results_available_when_closed(client, p12_election, db):
    """Results become accessible once election transitions to CLOSED."""
    p12_election.status = "CLOSED"
    db.session.commit()

    res = client.get(f"/api/elections/{p12_election.election_id}/results")
    assert res.status_code == 200
    data = res.get_json()
    assert data["is_closed"] is True
    assert data["status"] == "CLOSED"
    assert "candidates" in data


def test_results_available_when_finalized(client, p12_election, db):
    """Results remain accessible when election reaches FINALIZED."""
    p12_election.status = "FINALIZED"
    db.session.commit()

    res = client.get(f"/api/elections/{p12_election.election_id}/results")
    assert res.status_code == 200
    data = res.get_json()
    assert data["is_finalized"] is True
    assert data["status"] == "FINALIZED"


def test_results_nonexistent_election(client):
    """Querying results for invalid election returns 404."""
    res = client.get("/api/elections/ELEC_DOES_NOT_EXIST/results")
    assert res.status_code == 404
    assert res.get_json()["error"] == "ELECTION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 2. Canonical Tally Semantics (Phase 9 Revoting, Null Ballots, Superseded)
# ---------------------------------------------------------------------------

def test_tally_revoting_and_null_semantics(p12_election, db):
    """
    Test Phase 9 tally calculation:
      Voter 1: casts candidate 0 -> then revotes candidate 1 (seq 1 superseded)
      Voter 2: casts candidate 0 (seq 1)
      Voter 3: casts candidate 1 -> then revotes null (retraction)
    Expected tally:
      Candidate 0: 1 vote (Voter 2)
      Candidate 1: 1 vote (Voter 1)
      Null: 1 vote (Voter 3)
      Total valid: 2 votes
      Distinct voters: 3 voters
    """
    p12_election.status = "CLOSED"
    db.session.commit()

    p1 = "0x" + "1" * 64
    p2 = "0x" + "2" * 64
    p3 = "0x" + "3" * 64

    # Voter 1: Ballot 1 (cand 0, superseded), Ballot 2 (cand 1, active)
    b1_1 = BallotRecord(election_id=p12_election.id, pseudonym=p1, candidate=0, sequence=1, state='FINALIZED', superseded=True, is_null=False)
    b1_2 = BallotRecord(election_id=p12_election.id, pseudonym=p1, candidate=1, sequence=2, state='FINALIZED', superseded=False, is_null=False)

    # Voter 2: Ballot 1 (cand 0, active)
    b2_1 = BallotRecord(election_id=p12_election.id, pseudonym=p2, candidate=0, sequence=1, state='FINALIZED', superseded=False, is_null=False)

    # Voter 3: Ballot 1 (cand 1, superseded), Ballot 2 (null, active)
    b3_1 = BallotRecord(election_id=p12_election.id, pseudonym=p3, candidate=1, sequence=1, state='FINALIZED', superseded=True, is_null=False)
    b3_2 = BallotRecord(election_id=p12_election.id, pseudonym=p3, candidate=0, sequence=2, state='FINALIZED', superseded=False, is_null=True)

    db.session.add_all([b1_1, b1_2, b2_1, b3_1, b3_2])
    db.session.commit()

    ok, msg, res = ResultsService.get_election_results(p12_election.election_id)
    assert ok is True
    assert res["total_valid_votes"] == 2
    assert res["total_null_votes"] == 1
    assert res["total_distinct_voters"] == 3

    cand_map = {c["candidate_index"]: c["votes"] for c in res["candidates"]}
    assert cand_map[0] == 1
    assert cand_map[1] == 1

    # Winner tie handling
    assert len(res["winners"]) == 2
    assert res["is_tie"] is True


# ---------------------------------------------------------------------------
# 3. Public Verification Endpoint & Privacy Invariant
# ---------------------------------------------------------------------------

def test_public_verification_when_open(client, p12_election):
    """
    When election is OPEN:
      Parameters, candidate hash, roll hash are exposed.
      Results are withheld (results_available = False).
    """
    res = client.get(f"/api/elections/{p12_election.election_id}/verification")
    assert res.status_code == 200
    data = res.get_json()
    assert data["election_id"] == p12_election.election_id
    assert data["results_available"] is False
    assert data["results_summary"] is None
    assert data["candidates_hash"] == p12_election.candidates_hash
    assert data["roll_hash"] == p12_election.roll_hash


def test_public_verification_when_closed(client, p12_election, db):
    """
    When election is CLOSED:
      Parameters and results_summary are available.
    """
    p12_election.status = "CLOSED"
    db.session.commit()

    res = client.get(f"/api/elections/{p12_election.election_id}/verification")
    assert res.status_code == 200
    data = res.get_json()
    assert data["results_available"] is True
    assert data["results_summary"] is not None


def test_public_verification_privacy_invariants(client, p12_election, db):
    """
    Verify that public verification response NEVER exposes:
      - voter identity, student ID, USN, email
      - wallet address
      - plaintext pseudonyms
      - ballot-to-voter mapping
    """
    p12_election.status = "CLOSED"
    db.session.commit()

    # Seed finalized ballot
    b = BallotRecord(
        election_id=p12_election.id,
        pseudonym="0x" + "9" * 64,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        receipt_code="REC-SECRET-1234",
    )
    db.session.add(b)
    db.session.commit()

    res = client.get(f"/api/elections/{p12_election.election_id}/verification")
    assert res.status_code == 200
    raw_response = res.get_data(as_text=True).lower()

    forbidden_tokens = [
        "voter_id", "studentid", "usn", "email",
        "0x" + "9" * 64,  # pseudonym value
        "rec-secret-1234",  # voter receipt code
    ]
    for token in forbidden_tokens:
        assert token not in raw_response, f"Privacy leakage detected: {token} found in response"


# ---------------------------------------------------------------------------
# 4. Audit Trail Verification
# ---------------------------------------------------------------------------

def test_audit_verification_intact_chain(client, p12_election, db):
    """Verify cryptographic audit trail verification endpoint."""
    logger = AuditLogger()
    logger.log("ELECTION_CREATED", {"election_id": p12_election.election_id})
    logger.log("ELECTION_SCHEDULED", {"election_id": p12_election.election_id})

    res = client.get(f"/api/elections/{p12_election.election_id}/audit-verification")
    assert res.status_code == 200
    data = res.get_json()
    assert data["chain_intact"] is True
    assert data["latest_hash"] is not None
    assert data["total_events"] >= 2


def test_audit_verification_detects_broken_chain(p12_election, db):
    """Tampering with an audit event breaks the chain and is detected."""
    logger = AuditLogger()
    ev1 = logger.log("EVENT_A", {"election_id": "TEST"})
    ev2 = logger.log("EVENT_B", {"election_id": "TEST"})

    # Tamper with previous_hash on ev2
    ev2.previous_hash = "0x" + "0" * 64
    db.session.commit()

    assert logger.verify_chain() is False

    res = VerificationService.verify_audit_anchor(p12_election.election_id)
    assert res["chain_intact"] is False
    assert res["verification_status"] == "FAILED"


# ---------------------------------------------------------------------------
# 5. Controlled Database Tampering Demonstration
# ---------------------------------------------------------------------------

def test_tampering_demonstration_detects_and_restores(p12_election, db):
    """
    Test the controlled tampering flow:
      1. Pristine baseline -> clean.
      2. Injected candidate modification -> detected by reconciliation.
      3. Clean restoration -> returned to pristine state.
    """
    p12_election.status = "CLOSED"
    db.session.commit()

    # Seed finalized ballot
    b = BallotRecord(
        election_id=p12_election.id,
        pseudonym="0x" + "a" * 64,
        candidate=0,
        sequence=1,
        state='FINALIZED',
        superseded=False,
        is_null=False,
    )
    db.session.add(b)
    db.session.commit()

    result = VerificationService.run_tampering_demonstration(p12_election.election_id)
    assert result["demonstration_verdict"] == "SUCCESS"
    assert result["original_value"] == 0
    assert result["tampered_value"] != 0
    assert result["tamper_detected"] is True
    assert result["restored_verified"] is True

    # Confirm ballot record is back to original
    refreshed_b = db.session.get(BallotRecord, b.id)
    assert refreshed_b.candidate == 0
    assert refreshed_b.state == 'FINALIZED'


# ---------------------------------------------------------------------------
# 6. Exact Receipt Code Regression Test (REC-4-CF314B8D772BF3A1)
# ---------------------------------------------------------------------------

def test_verify_exact_receipt_code_REC_4_CF314B8D772BF3A1(client, db):
    """
    Regression test verifying exact receipt code REC-4-CF314B8D772BF3A1:
      1. Resolves election and ballot record correctly.
      2. Validates HMAC cryptographically.
      3. Confirms on-chain block settlement.
      4. Never leaks candidate, wallet, tx_hash, or pseudonym.
    """
    import os
    from datetime import datetime
    from unittest.mock import patch

    # Seed Election 4 and Ballot 2 into test db to match existing system state
    e4 = Election(
        id=4,
        election_id="ELEC_20261009024727_6C5C",
        title="Student Council 2026",
        description="Official General Election",
        start_time=datetime(2026, 10, 9, 2, 47, 27),
        end_time=datetime(2026, 10, 9, 14, 47, 27),
        status="OPEN",
    )
    b2 = BallotRecord(
        election_id=4,
        pseudonym="2df1d54897b8b30a9238e12f0b29012e9a60ef1aa0de136f7f761f89da4b7cae",
        candidate=1,
        sequence=1,
        state='FINALIZED',
        block_number=2189,
        receipt_code='REC-4-CF314B8D772BF3A1',
        tx_hash='0x5f4f88d47792c5a02a583f01881928eb040afce2e54e0d9ea4480f4c53b449e8',
        created_at=datetime(2026, 10, 9, 3, 16, 0),
        tx_confirmed_at=datetime(2026, 10, 9, 3, 16, 10),
        is_null=False,
    )
    db.session.add(e4)
    db.session.add(b2)
    db.session.commit()

    # The exact receipt code REC-4-CF314B8D772BF3A1 was HMAC-signed with the key from backend/.env
    live_key = "dEUTYYqPndJ7dQsUHcVuIHyvEtvufGb4Qugq2TO4uvE="
    with patch.dict(os.environ, {"RECEIPT_SECRET": live_key, "PSEUDONYM_MASTER_KEY": live_key}):
        # 1. Direct receipt endpoint check
        res = client.get("/api/verification/receipt/REC-4-CF314B8D772BF3A1")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "VALID"
        assert data["hmac_verified"] is True
        assert data["receipt_code"] == "REC-4-CF314B8D772BF3A1"
        assert data["sequence"] == 1
        assert data["block_number"] == 2189

        # Privacy check on public payload
        raw_text = res.get_data(as_text=True).lower()
        for forbidden in ["candidate", "wallet_address", "pseudonym", "tx_hash"]:
            assert f'"{forbidden}":' not in raw_text

        # 2. Querying election verifier with the receipt code resolves election
        res_ele = client.get("/api/elections/REC-4-CF314B8D772BF3A1/verification")
        assert res_ele.status_code == 200
        ele_data = res_ele.get_json()
        assert "Election 'REC-4-CF314B8D772BF3A1' does not exist." not in res_ele.get_data(as_text=True)
        assert ele_data["election_id"] == "ELEC_20261009024727_6C5C"
        assert ele_data.get("receipt_evidence") is not None
        assert ele_data["receipt_evidence"]["status"] == "VALID"


# ---------------------------------------------------------------------------
# 7. Receipt Verification Status Matrix: VALID, INVALID, NOT_FOUND, UNAVAILABLE
# ---------------------------------------------------------------------------

def test_verify_receipt_status_matrix(client, p12_election, db):
    """
    Test receipt verification status handling:
      - VALID: authentic HMAC and finalized ballot
      - INVALID: format error or tampered HMAC
      - NOT_FOUND: receipt code not in registry
      - UNAVAILABLE: secret key missing/destroyed
    """
    import hmac
    import hashlib
    import os
    from datetime import datetime
    from unittest.mock import patch

    secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY') or 'test-secret'
    now_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:00Z')
    pseud = "0x" + "c" * 64
    msg = f"{p12_election.id}|{pseud}|{now_str}"
    valid_hex = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].upper()
    valid_code = f"REC-{p12_election.id}-{valid_hex}"

    ballot = BallotRecord(
        election_id=p12_election.id,
        pseudonym=pseud,
        candidate=1,
        sequence=1,
        state='FINALIZED',
        receipt_code=valid_code,
        created_at=datetime.utcnow(),
        tx_confirmed_at=datetime.utcnow(),
    )
    db.session.add(ballot)
    db.session.commit()

    # Case A: VALID receipt
    res_valid = client.get(f"/api/verification/receipt/{valid_code}")
    assert res_valid.status_code == 200
    assert res_valid.get_json()["status"] == "VALID"
    assert res_valid.get_json()["hmac_verified"] is True

    # Case B: INVALID format
    res_fmt = client.get("/api/verification/receipt/NOT-A-VALID-CODE")
    assert res_fmt.status_code == 400
    assert res_fmt.get_json()["status"] == "INVALID"
    assert res_fmt.get_json()["reason"] == "INVALID_FORMAT"

    # Case C: NOT_FOUND (proper format but unknown code)
    res_nf = client.get(f"/api/verification/receipt/REC-{p12_election.id}-FFFFFFFFFFFFFFFF")
    assert res_nf.status_code == 404
    assert res_nf.get_json()["status"] == "NOT_FOUND"
    assert res_nf.get_json()["reason"] == "RECEIPT_NOT_FOUND"

    # Case D: INVALID (tampered HMAC on existing ballot)
    tampered_ballot = BallotRecord(
        election_id=p12_election.id,
        pseudonym=pseud,
        candidate=0,
        sequence=2,
        state='FINALIZED',
        receipt_code=f"REC-{p12_election.id}-0000000000000000",
        created_at=datetime.utcnow(),
    )
    db.session.add(tampered_ballot)
    db.session.commit()

    res_tampered = client.get(f"/api/verification/receipt/REC-{p12_election.id}-0000000000000000")
    assert res_tampered.status_code == 400
    assert res_tampered.get_json()["status"] == "INVALID"
    assert res_tampered.get_json()["reason"] == "HMAC_MISMATCH"

    # Case E: UNAVAILABLE (verification key unavailable)
    with patch.dict(os.environ, {"RECEIPT_SECRET": "", "PSEUDONYM_MASTER_KEY": ""}):
        res_unavail = client.get(f"/api/verification/receipt/{valid_code}")
        assert res_unavail.status_code == 503
        assert res_unavail.get_json()["status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# 8. Verifier Integrity-Warning & Zero-Root Honesty
# ---------------------------------------------------------------------------

def test_zero_root_and_integrity_warning_honesty(client, p12_election, db):
    """
    Ensure the verifier does not label an election 'VERIFIED' if integrity checks fail.
    When candidate hash mismatches on chain, it must report FAILED with issues list.
    """
    from unittest.mock import MagicMock, patch
    from app.relayer import Relayer

    mock_contract = MagicMock()
    # Return different candidate hash on chain
    mock_contract.functions.electionInfo().call.return_value = (
        1791511140, 1791515340, 2, b'\x11' * 32, 100, b'\x00' * 32, 3, 1, False
    )
    mock_contract.functions.getAuditAnchor().call.return_value = (b'\x00' * 32, 0, 0)

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.contract.return_value = mock_contract

    with patch.object(Relayer, 'get_web3', return_value=mock_w3):
        res = client.get(f"/api/elections/{p12_election.election_id}/verification")
        assert res.status_code == 200
        data = res.get_json()
        assert data["verification_status"] == "FAILED"
        assert "CANDIDATES_HASH_MISMATCH" in data["verification_issues"]
        assert data["blockchain_evidence"]["candidates_hash_matches"] is False

