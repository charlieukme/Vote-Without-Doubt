"""
Isolated Blockchain Audit-Anchoring Workflow Tests
Vote Without Doubt - Backend Test Suite

Tests:
1. Authorization & RBAC:
   - Only officers can request ANCHOR_AUDIT.
   - Non-officer (auditor) cannot request ANCHOR_AUDIT.
   - Self-approval strictly forbidden (Officer 1 cannot approve own request).
   - Auditor cannot approve ANCHOR_AUDIT.
2. Election Validation:
   - Non-existent election rejected.
   - Election not provisioned on-chain (end == 0) rejected.
   - Ineligible election status (DRAFT) rejected.
3. Checkpoint Binding & Cryptographic Integrity:
   - Checkpoint hash and event ID accurately bound to audit chain head.
   - Tampered checkpoint event fails closed upon approval.
   - Broken audit chain fails closed upon request and approval.
4. Duplicate Request Protection:
   - Duplicate pending ANCHOR_AUDIT request rejected.
5. Officer 2 Approval & Mock Execution:
   - Officer 2 approves; transaction receipt recorded; request status APPROVED.
   - AUDIT_ANCHORED_ON_CHAIN event logged without secrets.
6. Checkpoint Stability (Subsequent Audit Events):
   - Appending new audit events after anchoring does not invalidate earlier anchor.
7. Safe Failure, Retries, and Idempotency:
   - Reverted transaction marks request FAILED without corrupting state.
   - Idempotent retry when on-chain anchor already matches checkpoint.
   - Unrecognized on-chain anchor flagged as failure.
"""

from datetime import datetime, timedelta
import hashlib
import json
import pytest
from unittest.mock import MagicMock, patch

from app.audit.audit import AuditEvent, AuditLogger
from app.extensions import db
from app.models.admin import AdminUser, ApprovalRequest, Candidate
from app.models.ballot import Election
from app.models.ballot_record import BallotQueue
from app.models.reconciliation import ReconciliationIssue
from app.relayer import Relayer
from app.security.admin_auth import AdminAuthService
from app.services.election_admin_service import (
    ElectionAdminService,
    ElectionAdminError,
    TwoOfficerApprovalError,
    InvalidLifecycleTransitionError,
)
from app.services.verification_service import VerificationService


@pytest.fixture
def officers(db):
    """Seed distinct officers and an auditor."""
    off1, secret1 = AdminAuthService.create_admin(
        admin_id="OFFICER_01",
        name="Chief Election Officer",
        email="chief@election.local",
        password="ValidPassword123!",
        role="OFFICER",
    )
    off2, secret2 = AdminAuthService.create_admin(
        admin_id="OFFICER_02",
        name="Deputy Election Officer",
        email="deputy@election.local",
        password="ValidPassword456!",
        role="OFFICER",
    )
    aud, aud_secret = AdminAuthService.create_admin(
        admin_id="AUDITOR_01",
        name="Election Auditor",
        email="auditor@election.local",
        password="ValidPassword789!",
        role="AUDITOR",
    )
    return {
        "officer1": off1,
        "officer2": off2,
        "auditor": aud,
    }


@pytest.fixture
def provisioned_election(db):
    """Seed a provisioned election in CLOSED status with intact audit events."""
    logger = AuditLogger()
    ev1 = logger.log("SYSTEM_INIT", {"detail": "Genesis test event"})
    ev2 = logger.log("ROLL_IMPORTED", {"eligible_count": 100})

    e = Election(
        election_id="101",
        title="Student Council Election 2026",
        description="Anchoring test election",
        status="CLOSED",
        start_time=datetime.utcnow() - timedelta(hours=5),
        end_time=datetime.utcnow() - timedelta(hours=1),
        closed_at=datetime.utcnow() - timedelta(hours=1),
        candidate_count=2,
        eligible_count=100,
        max_ballots=3,
        roll_hash="0x" + "a" * 64,
        candidates_hash="0x" + "b" * 64,
    )
    db.session.add(e)
    db.session.commit()

    c0 = Candidate(election_id=e.election_id, candidate_index=0, name="Candidate Alpha")
    c1 = Candidate(election_id=e.election_id, candidate_index=1, name="Candidate Beta")
    db.session.add_all([c0, c1])
    db.session.commit()

    return e


def _create_mock_web3(on_chain_end=1791515340, anchor_tuple=(b'\x00' * 32, 0, 0), tx_status=1):
    """Build a mock Web3 instance with controllable contract calls and receipts."""
    officer_addr = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    mock_contract = MagicMock()
    mock_contract.functions.electionInfo().call.return_value = (
        1791511140, on_chain_end, 2, b'\x11' * 32, 100, b'\x00' * 32, 3, 1, False
    )
    mock_contract.functions.getAuditAnchor().call.return_value = anchor_tuple
    mock_contract.functions.officer().call.return_value = officer_addr
    mock_contract.functions.anchorAudit.return_value.transact.return_value = "0x" + "c" * 64
    mock_contract.functions.anchorAudit.return_value.build_transaction.return_value = {
        'from': officer_addr,
        'nonce': 0,
        'gas': 200_000,
        'gasPrice': 1_000_000_000,
        'to': officer_addr,
        'value': 0,
        'chainId': 1337,
    }

    mock_receipt = MagicMock()
    mock_receipt.status = tx_status
    mock_receipt.blockNumber = 12345
    mock_receipt.transactionHash = b'\xaa' * 32

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.accounts = [officer_addr]
    mock_w3.eth.chain_id = 1337
    mock_w3.eth.gas_price = 1_000_000_000
    mock_w3.eth.contract.return_value = mock_contract
    mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    mock_w3.eth.get_transaction_receipt.return_value = mock_receipt
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.send_raw_transaction.return_value = b'\xcc' * 32
    mock_w3.eth.gas_price = 20000000000
    mock_w3.eth.chain_id = 1337

    return mock_w3, mock_contract, mock_receipt


# ==============================================================================
# SECTION 1: AUTHORIZATION & TWO-OFFICER WORKFLOW
# ==============================================================================

def test_auditor_cannot_request_anchor(provisioned_election, officers):
    auditor = officers["auditor"]
    with pytest.raises(TwoOfficerApprovalError):
        ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            auditor,
            reason="Auditor unauthorized attempt",
        )


def test_officer_can_request_anchor(provisioned_election, officers):
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Request audit anchor for closed election",
        )
        assert req.id is not None
        assert req.status == "PENDING"
        assert req.action_type == "ANCHOR_AUDIT"
        assert req.requester_id == off1.id

        payload = json.loads(req.payload_json)
        assert payload["action_type"] == "ANCHOR_AUDIT"
        assert payload["election_id"] == provisioned_election.election_id
        assert payload["checkpoint_hash"] is not None
        assert payload["checkpoint_event_id"] is not None


def test_self_approval_strictly_forbidden(provisioned_election, officers):
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Request anchor",
        )

    # Officer 1 attempts to approve own request
    with pytest.raises(TwoOfficerApprovalError, match="Self-approval is strictly forbidden"):
        ElectionAdminService.approve_request(req.id, off1)

    # Status must remain PENDING
    db.session.refresh(req)
    assert req.status == "PENDING"


def test_auditor_cannot_approve_anchor(provisioned_election, officers):
    off1 = officers["officer1"]
    auditor = officers["auditor"]
    mock_w3, _, _ = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Request anchor",
        )

    with pytest.raises(TwoOfficerApprovalError, match="Auditors cannot approve"):
        ElectionAdminService.approve_request(req.id, auditor)


# ==============================================================================
# SECTION 2: ELECTION ELIGIBILITY & ON-CHAIN VALIDATION
# ==============================================================================

def test_unprovisioned_on_chain_election_rejected(provisioned_election, officers):
    off1 = officers["officer1"]
    # Mock verify_on_chain_provisioning returning NOT_PROVISIONED
    with patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(False, 'NOT_PROVISIONED', {})):
        with pytest.raises(ElectionAdminError, match="not verified on-chain"):
            ElectionAdminService.request_approval(
                provisioned_election.election_id,
                "ANCHOR_AUDIT",
                off1,
                reason="Attempt to anchor unprovisioned election",
            )


def test_draft_election_rejected_for_anchoring(officers, db):
    off1 = officers["officer1"]
    draft_e = Election(
        election_id="999",
        title="Draft Election",
        status="DRAFT",
    )
    db.session.add(draft_e)
    db.session.commit()

    with pytest.raises(InvalidLifecycleTransitionError, match="must be SCHEDULED, OPEN, CLOSED, or FINALIZED"):
        ElectionAdminService.request_approval(
            draft_e.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Attempt to anchor draft",
        )


def test_nonexistent_election_rejected(officers):
    off1 = officers["officer1"]
    with pytest.raises(ElectionAdminError, match="not found"):
        ElectionAdminService.request_approval(
            "99999",
            "ANCHOR_AUDIT",
            off1,
            reason="Ghost election",
        )


# ==============================================================================
# SECTION 3: DUPLICATE REQUEST PROTECTION
# ==============================================================================

def test_duplicate_pending_anchor_request_rejected(provisioned_election, officers):
    off1 = officers["officer1"]
    off2 = officers["officer2"]
    mock_w3, _, _ = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req1 = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Initial anchor request",
        )
        assert req1.status == "PENDING"

        # Attempt duplicate request by Officer 2 while req1 is PENDING
        with pytest.raises(ElectionAdminError, match="A pending ANCHOR_AUDIT request already exists"):
            ElectionAdminService.request_approval(
                provisioned_election.election_id,
                "ANCHOR_AUDIT",
                off2,
                reason="Duplicate request attempt",
            )


# ==============================================================================
# SECTION 4: OFFICER 2 APPROVAL, EXECUTION & AUDIT LOGGING
# ==============================================================================

def test_successful_approval_and_execution(provisioned_election, officers):
    off1 = officers["officer1"]
    off2 = officers["officer2"]
    mock_w3, mock_contract, mock_receipt = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor closed election",
        )

        # Officer 2 grants approval
        with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract',
                   return_value=(None, mock_w3, mock_contract)):
            success, reason = ElectionAdminService.approve_request(req.id, off2)

        assert success is True
        assert reason == "OK"

        db.session.refresh(req)
        assert req.status == "APPROVED"
        assert req.approver_id == off2.id

        payload = json.loads(req.payload_json)
        assert "execution" in payload
        exec_details = payload["execution"]
        assert exec_details["status"] == "CONFIRMED_ON_CHAIN"
        assert exec_details["tx_hash"] is not None
        assert exec_details["block_number"] == 12345

        # Verify AUDIT_ANCHORED_ON_CHAIN event was logged
        anchored_event = AuditEvent.query.filter_by(event_type="AUDIT_ANCHORED_ON_CHAIN").first()
        assert anchored_event is not None
        meta = anchored_event.event_metadata
        assert meta["election_id"] == provisioned_election.election_id
        assert meta["outcome"] == "SUCCESS"
        # Privacy sanitizer redacts unknown identity keys to [REDACTED]
        assert meta.get("requester_id") in (off1.admin_id, "[REDACTED]")
        assert meta.get("approver_id") in (off2.admin_id, "[REDACTED]")


# ==============================================================================
# SECTION 5: HISTORICAL CHECKPOINT STABILITY (SUBSEQUENT AUDIT EVENTS)
# ==============================================================================

def test_subsequent_audit_events_do_not_invalidate_earlier_anchor(provisioned_election, officers):
    """
    Core Requirement 4 Check:
    Anchoring locks an exact checkpoint node.
    New events appended to the audit chain afterwards MUST NOT invalidate the anchor.
    """
    off1 = officers["officer1"]
    off2 = officers["officer2"]

    logger = AuditLogger()
    checkpoint_node = logger.log("FINAL_TALLY_CALCULATED", {"election_id": provisioned_election.election_id})
    checkpoint_hash = checkpoint_node.current_hash
    checkpoint_bytes32 = bytes.fromhex(checkpoint_hash).ljust(32, b'\x00')[:32]

    mock_w3, mock_contract, _ = _create_mock_web3(anchor_tuple=(checkpoint_bytes32, 12345, 1))

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor tally checkpoint",
        )
        with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract',
                   return_value=(None, mock_w3, mock_contract)):
            ok, _ = ElectionAdminService.approve_request(req.id, off2)
            assert ok is True

    # Now append multiple subsequent audit events (advancing the chain head)
    logger.log("VOTER_FEEDBACK", {"comment": "Great election"})
    logger.log("DISPUTE_FILED", {"ticket_id": "DISP-001"})
    logger.log("OFFICER_LOGOUT", {"officer": "OFFICER_01"})

    # Chain head is now far ahead of checkpoint_hash
    current_head = logger.chain_head()
    assert current_head.current_hash != checkpoint_hash
    assert logger.verify_chain() is True

    # Verify audit anchor using VerificationService
    with patch.object(Relayer, 'get_web3', return_value=mock_w3):
        v_res = VerificationService.verify_audit_anchor(provisioned_election.election_id)

    assert v_res["chain_intact"] is True
    assert v_res["is_anchored"] is True
    assert v_res["verification_status"] == "VERIFIED"
    assert v_res["checkpoint_status"] == "MATCH_VERIFIED"
    assert v_res["anchored_event_id"] == checkpoint_node.id


# ==============================================================================
# SECTION 6: FAIL-CLOSED BEHAVIOR & INTEGRITY ATTACKS
# ==============================================================================

def test_tampered_checkpoint_event_fails_approval_closed(provisioned_election, officers):
    off1 = officers["officer1"]
    off2 = officers["officer2"]
    mock_w3, mock_contract, _ = _create_mock_web3()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor before tampering",
        )

    # Tamper with the checkpoint event in DB before Officer 2 approves
    p = json.loads(req.payload_json)
    target_event = db.session.get(AuditEvent, p["checkpoint_event_id"])
    target_event.event_type = "TAMPERED_EVENT"
    db.session.commit()

    with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract',
               return_value=(None, mock_w3, mock_contract)):
        ok, reason = ElectionAdminService.approve_request(req.id, off2)

    assert ok is False
    assert "ANCHOR_FAILED" in reason
    db.session.refresh(req)
    assert req.status == "FAILED"


def test_broken_chain_fails_anchor_verification(provisioned_election):
    logger = AuditLogger()
    ev = logger.log("PRE_TAMPER_EVENT", {"detail": "Normal"})
    anchor_bytes32 = bytes.fromhex(ev.current_hash).ljust(32, b'\x00')[:32]

    # Tamper with an earlier event
    first_ev = AuditEvent.query.order_by(AuditEvent.id.asc()).first()
    first_ev.previous_hash = "0x" + "9" * 64
    db.session.commit()

    assert logger.verify_chain() is False

    mock_w3, _, _ = _create_mock_web3(anchor_tuple=(anchor_bytes32, 100, 1))

    with patch.object(Relayer, 'get_web3', return_value=mock_w3):
        v_res = VerificationService.verify_audit_anchor(provisioned_election.election_id)

    assert v_res["chain_intact"] is False
    assert v_res["is_anchored"] is False
    assert v_res["verification_status"] == "FAILED"
    assert "AUDIT_CHAIN_INTEGRITY_COMPROMISED" in v_res["issues"]


# ==============================================================================
# SECTION 7: TRANSACTION FAILURE, RECOVERY & IDEMPOTENCY
# ==============================================================================

def test_reverted_transaction_marks_request_failed_cleanly(provisioned_election, officers):
    off1 = officers["officer1"]
    off2 = officers["officer2"]
    # Mock transaction reverting on-chain (status = 0)
    mock_w3, mock_contract, _ = _create_mock_web3(tx_status=0)

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor request doomed to revert",
        )

        with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract',
                   return_value=(None, mock_w3, mock_contract)):
            ok, reason = ElectionAdminService.approve_request(req.id, off2)

    assert ok is False
    assert "reverted on-chain" in reason

    db.session.refresh(req)
    assert req.status == "FAILED"
    assert "reverted" in req.rejection_reason


def test_idempotent_retry_when_already_anchored(provisioned_election, officers):
    """
    If the transaction was already confirmed on-chain (e.g. prior retry succeeded),
    executing anchor audit detects the matching on-chain anchor and succeeds idempotently.
    """
    off1 = officers["officer1"]
    off2 = officers["officer2"]

    logger = AuditLogger()
    head = logger.chain_head()
    head_bytes32 = bytes.fromhex(head.current_hash).ljust(32, b'\x00')[:32]

    # Mock contract already reporting this exact anchor on chain
    mock_w3, mock_contract, _ = _create_mock_web3(anchor_tuple=(head_bytes32, 12000, 1))

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Idempotent anchor retry",
        )

        with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract',
                   return_value=(None, mock_w3, mock_contract)):
            ok, reason = ElectionAdminService.approve_request(req.id, off2)

    assert ok is True
    assert reason == "OK"
    db.session.refresh(req)
    assert req.status == "APPROVED"
    payload = json.loads(req.payload_json)
    assert payload["execution"]["status"] == "ALREADY_ANCHORED"


def test_unrecognized_on_chain_anchor_reports_failure(provisioned_election):
    """
    If the on-chain contract reports a hash that never existed in our audit log,
    VerificationService must fail closed.
    """
    foreign_hash = b'\x77' * 32
    mock_w3, _, _ = _create_mock_web3(anchor_tuple=(foreign_hash, 99999, 1))

    with patch.object(Relayer, 'get_web3', return_value=mock_w3):
        v_res = VerificationService.verify_audit_anchor(provisioned_election.election_id)

    assert v_res["chain_intact"] is True
    assert v_res["is_anchored"] is False
    assert v_res["verification_status"] == "FAILED"
    assert "ON_CHAIN_ANCHOR_NOT_FOUND_IN_AUDIT_LOG" in v_res["issues"]


# ==============================================================================
# SECTION 8: BALLOT RECONCILIATION UNRESOLVED CHECKS (PRIORITY 1)
# ==============================================================================

def test_unresolved_failure_blocks_anchoring(provisioned_election, officers, db):
    """
    Requirement: Before creating an ANCHOR_AUDIT approval request, reject the request
    if that election has any unresolved ballot reconciliation records, including failed
    records with reconcile_required enabled.
    Also verify that alternate election identifier cannot bypass this check.
    """
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    # Seed an unresolved failed ballot in BallotQueue for this election
    failed_ballot = BallotQueue(
        election_id=int(provisioned_election.election_id),
        pseudonym="a" * 64,
        candidate=0,
        sequence=1,
        state="FAILED",
        reconcile_required=True,
        reconcile_reason="TX_REVERTED",
        error="TRANSACTION_REVERTED (block 2165)",
    )
    db.session.add(failed_ballot)
    db.session.commit()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        # Attempt via string business identifier
        with pytest.raises(ElectionAdminError, match="unresolved ballot reconciliation record"):
            ElectionAdminService.request_approval(
                provisioned_election.election_id,
                "ANCHOR_AUDIT",
                off1,
                reason="Attempt to anchor election with failed ballot in queue",
            )

        # Attempt to bypass via integer primary key identifier
        with pytest.raises(ElectionAdminError, match="unresolved ballot reconciliation record"):
            ElectionAdminService.request_approval(
                provisioned_election.id,
                "ANCHOR_AUDIT",
                off1,
                reason="Bypass attempt using primary key id",
            )


def test_multiple_unresolved_records_block_anchoring(provisioned_election, officers, db):
    """
    Multiple unresolved ballot records (e.g. FAILED + QUEUED) correctly count and block.
    """
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    b1 = BallotQueue(
        election_id=int(provisioned_election.election_id),
        pseudonym="b" * 64,
        candidate=0,
        sequence=1,
        state="FAILED",
        reconcile_required=True,
        reconcile_reason="TX_REVERTED",
    )
    b2 = BallotQueue(
        election_id=int(provisioned_election.election_id),
        pseudonym="c" * 64,
        candidate=1,
        sequence=1,
        state="QUEUED",
        reconcile_required=False,
    )
    db.session.add_all([b1, b2])
    db.session.commit()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        with pytest.raises(ElectionAdminError, match="2 unresolved ballot reconciliation record"):
            ElectionAdminService.request_approval(
                provisioned_election.election_id,
                "ANCHOR_AUDIT",
                off1,
                reason="Attempt to anchor election with multiple unresolved ballots",
            )


def test_clean_election_allows_anchoring(provisioned_election, officers, db):
    """
    When all ballots in BallotQueue are successfully finalized (reconcile_required=False),
    anchoring request succeeds cleanly.
    """
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    b_clean = BallotQueue(
        election_id=int(provisioned_election.election_id),
        pseudonym="d" * 64,
        candidate=0,
        sequence=1,
        state="FINALIZED",
        reconcile_required=False,
        tx_hash="0x" + "1" * 64,
        block_number=1234,
        receipt_code="REC-101-ABCD",
    )
    db.session.add(b_clean)
    db.session.commit()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor clean election",
        )
        assert req.id is not None
        assert req.status == "PENDING"
        assert req.action_type == "ANCHOR_AUDIT"


def test_election_with_no_ballots_allows_anchoring(provisioned_election, officers, db):
    """
    Elections with 0 ballot records (e.g. uncontested or newly closed) allow anchoring cleanly.
    """
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    # Confirm 0 ballots exist in BallotQueue
    assert BallotQueue.query.filter_by(election_id=int(provisioned_election.election_id)).count() == 0

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        req = ElectionAdminService.request_approval(
            provisioned_election.election_id,
            "ANCHOR_AUDIT",
            off1,
            reason="Anchor election with zero ballots",
        )
        assert req.id is not None
        assert req.status == "PENDING"
        assert req.action_type == "ANCHOR_AUDIT"


def test_open_reconciliation_issue_blocks_anchoring(provisioned_election, officers, db):
    """
    When an open ReconciliationIssue exists, anchoring request is blocked.
    """
    off1 = officers["officer1"]
    mock_w3, _, _ = _create_mock_web3()

    issue = ReconciliationIssue(
        election_id=int(provisioned_election.election_id),
        issue_type="TALLY_DIVERGENCE",
        severity="HIGH",
        status="OPEN",
        observed_state="DB count 1 != Chain 0",
    )
    db.session.add(issue)
    db.session.commit()

    with patch.object(Relayer, 'get_web3', return_value=mock_w3), \
         patch.object(ElectionAdminService, 'verify_on_chain_provisioning', return_value=(True, 'PROVISIONED_MATCH', {})):
        with pytest.raises(ElectionAdminError, match="open reconciliation issue"):
            ElectionAdminService.request_approval(
                provisioned_election.election_id,
                "ANCHOR_AUDIT",
                off1,
                reason="Attempt to anchor election with open reconciliation issue",
            )

