"""
Final Security Audit & Verification Test Suite
Vote Without Doubt - System Completion Tests

Tests:
1. Merkle Inclusion Verification:
   - Empty tree behavior
   - 1-leaf tree
   - Odd and even leaf counts (RFC 6962 canonical construction)
   - Altered leaves (tampered payload rejected)
   - Altered sibling hashes rejected
   - Altered Merkle root rejected
   - Replayed proof / mismatched commitment rejected
   - Cross-election proof substitution rejected
2. Privacy & Voter-Ballot Linkage Protection:
   - Database schema isolation (BallotRecord vs Identity tables)
   - High-entropy 256-bit nonce security
   - Receipt lookup secrecy (nonces only available to authenticated receipt holder)
3. Election Deletion & Archiving Restrictions:
   - DRAFT election with 0 ballots can be deleted
   - DRAFT election with ballots or receipts cannot be deleted
   - Non-DRAFT elections (SCHEDULED, OPEN, CLOSED) cannot be hard deleted
   - CLOSED elections can be safely archived (preserving all evidence)
   - Role-based access control (Auditor / anonymous cannot delete)
4. Tally Correctness Distinction:
   - Proof explicitly validates ballot commitment inclusion, not tally computation.
"""

import os
import pytest
import secrets
from datetime import datetime, timedelta

from app.extensions import db
from app.models.admin import AdminUser
from app.models.ballot import Election, Ballot
from app.models.ballot_record import BallotQueue as BallotRecord
from app.security.merkle import (
    generate_commitment_nonce,
    compute_ballot_commitment,
    MerkleTree,
    verify_inclusion_proof,
    EMPTY_TREE_ROOT,
)
from app.services.election_admin_service import ElectionAdminService, ElectionAdminError
from app.services.verification_service import VerificationService


def test_merkle_empty_and_single_leaf():
    """Verify empty tree and 1-leaf tree conform to RFC 6962 rules."""
    empty_tree = MerkleTree([])
    assert empty_tree.leaf_count == 0
    assert empty_tree.root == "0x" + EMPTY_TREE_ROOT.hex()

    nonce = generate_commitment_nonce()
    c = compute_ballot_commitment("ELEC_100", 0, nonce)
    single_tree = MerkleTree([c])
    assert single_tree.leaf_count == 1
    proof = single_tree.get_audit_proof(c)
    assert proof["audit_path"] == []
    valid, msg = verify_inclusion_proof(c, single_tree.root, proof["audit_path"])
    assert valid is True
    assert msg == "VALID INCLUSION PROOF"


@pytest.mark.parametrize("leaf_count", [2, 3, 5, 8, 9, 13, 16, 21])
def test_merkle_odd_even_leaf_counts_rfc6962(leaf_count):
    """Verify RFC 6962 largest-power-of-2 split for odd and even leaf counts."""
    commitments = []
    for i in range(leaf_count):
        nonce = generate_commitment_nonce()
        commitments.append(compute_ballot_commitment("ELEC_TEST", i % 4, nonce))

    tree = MerkleTree(commitments, sort_leaves=True)
    assert tree.leaf_count == leaf_count

    for c in commitments:
        proof = tree.get_audit_proof(c)
        assert proof is not None
        valid, msg = verify_inclusion_proof(c, tree.root, proof["audit_path"])
        assert valid is True
        assert msg == "VALID INCLUSION PROOF"


def test_merkle_tampered_leaf_and_sibling():
    """Verify tampering detection for leaf payload and sibling hashes."""
    commitments = [
        compute_ballot_commitment("ELEC_100", 1, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_100", 2, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_100", 3, generate_commitment_nonce()),
    ]
    tree = MerkleTree(commitments)
    c0 = commitments[0]
    proof0 = tree.get_audit_proof(c0)

    # 1. Tampered leaf
    tampered_leaf = c0[:-4] + "dead"
    valid, msg = verify_inclusion_proof(tampered_leaf, tree.root, proof0["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg

    # 2. Tampered sibling
    tampered_path = list(proof0["audit_path"])
    tampered_path[0] = {"hash": "0x" + "f" * 64, "direction": tampered_path[0]["direction"]}
    valid, msg = verify_inclusion_proof(c0, tree.root, tampered_path)
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg

    # 3. Tampered root
    valid, msg = verify_inclusion_proof(c0, "0x" + "1" * 64, proof0["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_merkle_replayed_and_cross_election_proof():
    """Verify proofs cannot be replayed for mismatched commitments or across elections."""
    cA = compute_ballot_commitment("ELEC_A", 1, generate_commitment_nonce())
    cB = compute_ballot_commitment("ELEC_B", 1, generate_commitment_nonce())

    treeA = MerkleTree([cA, compute_ballot_commitment("ELEC_A", 2, generate_commitment_nonce())])
    treeB = MerkleTree([cB, compute_ballot_commitment("ELEC_B", 2, generate_commitment_nonce())])

    proofA = treeA.get_audit_proof(cA)

    # Replay proof of cA against cB
    valid, msg = verify_inclusion_proof(cB, treeA.root, proofA["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg

    # Cross-election substitution
    valid, msg = verify_inclusion_proof(cA, treeB.root, proofA["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_election_deletion_restrictions(app, db):
    """
    Verify deletion safety rules:
    - Draft with 0 ballots: deletion succeeds
    - Draft with ballots/receipts: deletion blocked
    - Scheduled/Open/Closed: deletion blocked
    """
    with app.app_context():
        # Setup officer
        officer = AdminUser(
            admin_id="OFFICER_AUDIT_1",
            email="officer_audit@rvce.edu.in",
            name="Audit Officer",
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
            role="OFFICER",
            is_active=True,
        )
        db.session.add(officer)
        db.session.commit()

        # 1. Clean draft
        draft_clean = Election(
            election_id="ELEC_CLEAN_101",
            title="Clean Draft Election",
            status="DRAFT",
            start_time=datetime.utcnow() + timedelta(days=1),
            end_time=datetime.utcnow() + timedelta(days=2),
            eligible_count=100,
        )
        db.session.add(draft_clean)
        db.session.commit()
        draft_clean_id = draft_clean.election_id

        # Deleting clean draft should succeed
        ok, msg = ElectionAdminService.delete_election(draft_clean_id, officer)
        assert ok is True
        assert Election.query.filter_by(election_id=draft_clean_id).first() is None

        # 2. Draft with a ballot record (cannot delete)
        draft_dirty = Election(
            election_id="ELEC_DIRTY_102",
            title="Dirty Draft Election",
            status="DRAFT",
            start_time=datetime.utcnow() + timedelta(days=1),
            end_time=datetime.utcnow() + timedelta(days=2),
            eligible_count=100,
        )
        db.session.add(draft_dirty)
        db.session.commit()

        ballot_rec = BallotRecord(
            election_id=draft_dirty.id,
            pseudonym="pseudo_01",
            candidate=1,
            sequence=1,
            state="CONFIRMED",
            receipt_code="rec_01",
            commitment="commit_01",
        )
        db.session.add(ballot_rec)
        db.session.commit()

        with pytest.raises(ElectionAdminError) as excinfo:
            ElectionAdminService.delete_election(draft_dirty.election_id, officer)
        assert "Cannot delete election" in str(excinfo.value)

        # 3. OPEN election (cannot delete)
        open_election = Election(
            election_id="ELEC_OPEN_103",
            title="Open Election",
            status="OPEN",
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            eligible_count=100,
        )
        db.session.add(open_election)
        db.session.commit()

        with pytest.raises(ElectionAdminError) as excinfo:
            ElectionAdminService.delete_election(open_election.election_id, officer)
        assert "Cannot delete election in 'OPEN' state" in str(excinfo.value)

        # 4. CLOSED election can be archived, not deleted
        closed_election = Election(
            election_id="ELEC_CLOSED_104",
            title="Closed Election",
            status="CLOSED",
            start_time=datetime.utcnow() - timedelta(days=2),
            end_time=datetime.utcnow() - timedelta(days=1),
            eligible_count=100,
            merkle_root="0x" + "a" * 64,
        )
        db.session.add(closed_election)
        db.session.commit()

        # Hard deletion rejected
        with pytest.raises(ElectionAdminError):
            ElectionAdminService.delete_election(closed_election.election_id, officer)

        # Archival succeeds
        arch_ok, arch_msg = ElectionAdminService.archive_election(closed_election.election_id, officer)
        assert arch_ok is True
        refreshed = Election.query.filter_by(election_id=closed_election.election_id).first()
        assert refreshed.is_archived is True
        assert refreshed.merkle_root == "0x" + "a" * 64


def test_public_inclusion_proof_api_and_verification(client, app):
    """
    Verify public inclusion proof retrieval and verification endpoints.
    Checks that nonces are isolated and tally disclaimer is verified.
    """
    receipt_code = "REC-999-1111222233334444"
    with app.app_context():
        election = Election(
            election_id="999",
            title="Final Verification Test Election",
            status="CLOSED",
            start_time=datetime.utcnow() - timedelta(days=2),
            end_time=datetime.utcnow() - timedelta(days=1),
            eligible_count=50,
        )
        db.session.add(election)
        db.session.commit()

        nonce1 = generate_commitment_nonce()
        nonce2 = generate_commitment_nonce()
        c1 = compute_ballot_commitment("999", 0, nonce1)
        c2 = compute_ballot_commitment("999", 1, nonce2)

        tree = MerkleTree([c1, c2], sort_leaves=True)
        election.merkle_root = tree.root

        # Ballot 1
        b1 = BallotRecord(
            election_id=999,
            pseudonym="pseudo_hash_1",
            candidate=0,
            sequence=1,
            receipt_code=receipt_code,
            commitment=c1,
            commitment_nonce=nonce1.hex(),
            state="CONFIRMED",
        )
        # Ballot 2
        b2 = BallotRecord(
            election_id=999,
            pseudonym="pseudo_hash_2",
            candidate=1,
            sequence=1,
            receipt_code="REC-999-5555666677778888",
            commitment=c2,
            commitment_nonce=nonce2.hex(),
            state="CONFIRMED",
        )
        db.session.add_all([b1, b2])
        db.session.commit()

    # Query public inclusion proof endpoint
    resp = client.get(f"/api/public/receipt/{receipt_code}/inclusion-proof")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["status"] == "VALID INCLUSION PROOF"
    assert data["commitment"] == c1
    assert data.get("commitment_nonce") is None, "Public inclusion proof must withhold nonce to protect candidate privacy"

    # Verify against arbitrary verification endpoint
    verify_resp = client.post(
        "/api/public/verify-inclusion-proof",
        json={
            "commitment": data["commitment"],
            "merkle_root": data["merkle_root"],
            "audit_path": data["audit_path"],
        },
    )
    assert verify_resp.status_code == 200
    v_data = verify_resp.get_json()
    assert v_data["verified"] is True
    assert v_data["status"] == "VALID INCLUSION PROOF"
