"""
Tests for RFC 6962 Merkle Tree & Ballot Commitment Module
"""

import pytest
import secrets

from app.security.merkle import (
    compute_ballot_commitment,
    generate_commitment_nonce,
    MerkleTree,
    verify_inclusion_proof,
    EMPTY_TREE_ROOT,
)


def test_ballot_commitment_determinism_and_hiding():
    nonce = generate_commitment_nonce()
    assert len(nonce) == 32

    c1 = compute_ballot_commitment("ELEC_1", 1, nonce)
    c2 = compute_ballot_commitment("ELEC_1", 1, nonce)
    assert c1 == c2
    assert len(c1) == 64

    # Different candidate produces completely different commitment
    c3 = compute_ballot_commitment("ELEC_1", 2, nonce)
    assert c1 != c3

    # Different election produces different commitment
    c4 = compute_ballot_commitment("ELEC_2", 1, nonce)
    assert c1 != c4

    # Invalid nonce raises ValueError
    with pytest.raises(ValueError):
        compute_ballot_commitment("ELEC_1", 1, b"short_nonce")


def test_empty_merkle_tree():
    tree = MerkleTree([])
    assert tree.leaf_count == 0
    # Strict RFC 6962 Section 2.1: MTH({}) = SHA-256("")
    expected_empty_hex = "0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert tree.root == expected_empty_hex
    assert tree.root == "0x" + EMPTY_TREE_ROOT.hex()

    # Empty tree proof behavior
    fake_commitment = compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce())
    proof = tree.get_audit_proof(fake_commitment)
    assert proof is None

    # Verifying against empty root must fail
    valid, msg = verify_inclusion_proof(fake_commitment, tree.root, [])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_single_leaf_merkle_tree():
    nonce = generate_commitment_nonce()
    c = compute_ballot_commitment("ELEC_1", 1, nonce)

    tree = MerkleTree([c])
    assert tree.leaf_count == 1
    assert tree.root.startswith("0x")

    proof = tree.get_audit_proof(c)
    assert proof is not None
    assert proof["audit_path"] == []

    valid, msg = verify_inclusion_proof(c, tree.root, proof["audit_path"])
    assert valid is True
    assert msg == "VALID INCLUSION PROOF"


def test_two_leaf_merkle_tree():
    c1 = compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce())
    c2 = compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce())
    tree = MerkleTree([c1, c2], sort_leaves=True)
    assert tree.leaf_count == 2
    for c in [c1, c2]:
        proof = tree.get_audit_proof(c)
        assert proof is not None
        assert len(proof["audit_path"]) == 1
        valid, msg = verify_inclusion_proof(c, tree.root, proof["audit_path"])
        assert valid is True
        assert msg == "VALID INCLUSION PROOF"


def test_three_leaf_merkle_tree():
    c1 = compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce())
    c2 = compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce())
    c3 = compute_ballot_commitment("ELEC_1", 2, generate_commitment_nonce())
    tree = MerkleTree([c1, c2, c3], sort_leaves=True)
    assert tree.leaf_count == 3
    for c in [c1, c2, c3]:
        proof = tree.get_audit_proof(c)
        assert proof is not None
        valid, msg = verify_inclusion_proof(c, tree.root, proof["audit_path"])
        assert valid is True
        assert msg == "VALID INCLUSION PROOF"


@pytest.mark.parametrize("leaf_count", [2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17])
def test_merkle_tree_various_leaf_counts_odd_and_even(leaf_count):
    commitments = []
    for i in range(leaf_count):
        nonce = generate_commitment_nonce()
        c = compute_ballot_commitment("ELEC_1", i % 3, nonce)
        commitments.append(c)

    tree = MerkleTree(commitments, sort_leaves=True)
    assert tree.leaf_count == leaf_count

    # Verify inclusion proof for every single leaf
    for c in commitments:
        proof = tree.get_audit_proof(c)
        assert proof is not None
        valid, msg = verify_inclusion_proof(c, tree.root, proof["audit_path"])
        assert valid is True
        assert msg == "VALID INCLUSION PROOF"


def test_tampered_leaf_rejected():
    commitments = [
        compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 2, generate_commitment_nonce()),
    ]
    tree = MerkleTree(commitments)
    proof = tree.get_audit_proof(commitments[0])

    # Tamper with the leaf commitment
    tampered_c = commitments[0][:-4] + "ffff"
    valid, msg = verify_inclusion_proof(tampered_c, tree.root, proof["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_tampered_sibling_rejected():
    commitments = [
        compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 2, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce()),
    ]
    tree = MerkleTree(commitments)
    proof = tree.get_audit_proof(commitments[0])

    # Tamper with first sibling hash in audit path
    tampered_path = list(proof["audit_path"])
    tampered_path[0] = {
        "hash": "0x" + "a" * 64,
        "direction": tampered_path[0]["direction"],
    }
    valid, msg = verify_inclusion_proof(commitments[0], tree.root, tampered_path)
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_tampered_root_rejected():
    commitments = [
        compute_ballot_commitment("ELEC_1", 0, generate_commitment_nonce()),
        compute_ballot_commitment("ELEC_1", 1, generate_commitment_nonce()),
    ]
    tree = MerkleTree(commitments)
    proof = tree.get_audit_proof(commitments[0])

    tampered_root = "0x" + "0" * 64
    valid, msg = verify_inclusion_proof(commitments[0], tampered_root, proof["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg


def test_cross_election_proof_substitution_rejected():
    # Tree A for Election A
    cA = compute_ballot_commitment("ELEC_A", 1, generate_commitment_nonce())
    treeA = MerkleTree([cA, compute_ballot_commitment("ELEC_A", 2, generate_commitment_nonce())])

    # Tree B for Election B
    cB = compute_ballot_commitment("ELEC_B", 1, generate_commitment_nonce())
    treeB = MerkleTree([cB, compute_ballot_commitment("ELEC_B", 2, generate_commitment_nonce())])

    proofA = treeA.get_audit_proof(cA)

    # Attempt to verify cA against Root B
    valid, msg = verify_inclusion_proof(cA, treeB.root, proofA["audit_path"])
    assert valid is False
    assert "INVALID INCLUSION PROOF" in msg
