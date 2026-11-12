"""
Cryptographic Merkle Tree & Ballot Commitment Module
Vote Without Doubt - System Verification

Implements:
1. High-Entropy 256-bit Ballot Commitments:
   C = SHA256(b"VWD_BALLOT_COMMITMENT_V1:" || election_id || ":" || candidate_index || ":" || nonce)
   Protects candidate choice against brute-force / dictionary enumeration over small candidate domains.

2. RFC 6962-Derived Binary Merkle Tree:
   - Leaf Hash: H(0x00 || commitment_bytes)
   - Internal Node: H(0x01 || left_child || right_child)
   - Odd-Node Rule (RFC 6962 Section 2.1): Subtrees split at largest power of 2 less than N.
     Never duplicates leaves (immune to CVE-2012-2459 duplication attacks).
   - Empty Tree (RFC 6962 Section 2.1): SHA256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
   - Audit Path: Sibling hashes with direction ('left' | 'right').
   - Leaf Ordering: Lexicographically sorted (project-specific choice for voter privacy).

3. Self-Verifying Inclusion Proofs:
   Verifies that a ballot commitment is anchored in the finalized Merkle root.
   Output: 'VALID INCLUSION PROOF' or 'INVALID INCLUSION PROOF'.
"""

from __future__ import annotations

import hashlib
import math
import secrets
from typing import Any, Dict, List, Optional, Tuple, Union


DOMAIN_BALLOT_COMMITMENT = b"VWD_BALLOT_COMMITMENT_V1:"
RFC6962_LEAF_PREFIX = b"\x00"
RFC6962_NODE_PREFIX = b"\x01"
EMPTY_TREE_ROOT = hashlib.sha256(b"").digest()


def generate_commitment_nonce() -> bytes:
    """Generate 256 bits (32 bytes) of cryptographically secure random entropy."""
    return secrets.token_bytes(32)


def compute_ballot_commitment(
    election_id: Union[str, int],
    candidate_index: int,
    nonce: bytes,
) -> str:
    """
    Compute a domain-separated, brute-force resistant commitment for a ballot.

    Inputs:
    - election_id: identifier of the election.
    - candidate_index: integer index of candidate choice (or 0 for null ballot).
    - nonce: exactly 32 bytes of high-entropy randomness.

    Output:
    - 64-character lowercase hex SHA-256 digest.
    """
    if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != 32:
        raise ValueError("Nonce must be exactly 32 cryptographically secure bytes (256 bits).")

    eid_bytes = str(election_id).strip().encode("utf-8")
    cand_bytes = str(int(candidate_index)).encode("utf-8")
    payload = DOMAIN_BALLOT_COMMITMENT + eid_bytes + b":" + cand_bytes + b":" + bytes(nonce)
    return hashlib.sha256(payload).hexdigest()


def _largest_power_of_two_less_than(n: int) -> int:
    """Return largest power of 2 strictly less than n (for n > 1)."""
    if n <= 1:
        raise ValueError("n must be greater than 1")
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _leaf_hash(commitment_hex: str) -> bytes:
    """Compute RFC 6962 leaf hash: H(0x00 || commitment_bytes)."""
    commitment_bytes = bytes.fromhex(commitment_hex.strip().lower())
    if len(commitment_bytes) != 32:
        raise ValueError("Commitment must be a 32-byte (64 hex char) digest.")
    return hashlib.sha256(RFC6962_LEAF_PREFIX + commitment_bytes).digest()


def _node_hash(left_bytes: bytes, right_bytes: bytes) -> bytes:
    """Compute RFC 6962 internal node hash: H(0x01 || left || right)."""
    if len(left_bytes) != 32 or len(right_bytes) != 32:
        raise ValueError("Child nodes must be 32 bytes each.")
    return hashlib.sha256(RFC6962_NODE_PREFIX + left_bytes + right_bytes).digest()


class MerkleTree:
    """
    RFC 6962 Compliant Binary Merkle Tree for Ballot Commitments.
    """

    def __init__(self, commitments: Optional[List[str]] = None, sort_leaves: bool = True):
        """
        Initialize tree with ballot commitments.
        If sort_leaves is True (default), leaves are lexicographically sorted to eliminate
        temporal/sequence correlation between casting order and tree position.
        """
        raw_commitments = [c.strip().lower() for c in (commitments or []) if c and c.strip()]
        if sort_leaves:
            self.commitments = sorted(raw_commitments)
        else:
            self.commitments = list(raw_commitments)

        self._leaf_hashes: List[bytes] = [_leaf_hash(c) for c in self.commitments]
        self.root_bytes = self._compute_mth(self._leaf_hashes)

    @property
    def root(self) -> str:
        """Return 0x-prefixed 64-character hex Merkle root."""
        return "0x" + self.root_bytes.hex()

    @property
    def leaf_count(self) -> int:
        """Number of leaves in the tree."""
        return len(self.commitments)

    def _compute_mth(self, leaves: List[bytes]) -> bytes:
        """
        Recursive Merkle Tree Hash (MTH) calculation per RFC 6962 Section 2.1.
        """
        n = len(leaves)
        if n == 0:
            return EMPTY_TREE_ROOT
        if n == 1:
            return leaves[0]

        k = _largest_power_of_two_less_than(n)
        left_mth = self._compute_mth(leaves[:k])
        right_mth = self._compute_mth(leaves[k:])
        return _node_hash(left_mth, right_mth)

    def get_audit_proof(self, commitment_hex: str) -> Optional[Dict[str, Any]]:
        """
        Generate inclusion proof (audit path) for a specific commitment.
        Returns None if commitment is not in this tree.
        """
        target = commitment_hex.strip().lower()
        try:
            m = self.commitments.index(target)
        except ValueError:
            return None

        path: List[Dict[str, str]] = []
        self._build_audit_path(m, self._leaf_hashes, path)

        return {
            "commitment": target,
            "leaf_index": m,
            "total_leaves": len(self.commitments),
            "merkle_root": self.root,
            "audit_path": path,
        }

    def _build_audit_path(
        self,
        m: int,
        leaves: List[bytes],
        path: List[Dict[str, str]],
    ) -> None:
        """
        Recursively construct RFC 6962 audit path for index m in leaves.
        """
        n = len(leaves)
        if n <= 1:
            return

        k = _largest_power_of_two_less_than(n)
        if m < k:
            self._build_audit_path(m, leaves[:k], path)
            sibling = self._compute_mth(leaves[k:])
            path.append({"hash": "0x" + sibling.hex(), "direction": "right"})
        else:
            self._build_audit_path(m - k, leaves[k:], path)
            sibling = self._compute_mth(leaves[:k])
            path.append({"hash": "0x" + sibling.hex(), "direction": "left"})


def verify_inclusion_proof(
    commitment_hex: str,
    merkle_root_hex: str,
    audit_path: List[Dict[str, str]],
) -> Tuple[bool, str]:
    """
    Verify an RFC 6962 Merkle inclusion proof.

    Returns:
    - (True, "VALID INCLUSION PROOF") if cryptographically verified.
    - (False, "INVALID INCLUSION PROOF: <reason>") if verification fails.
    """
    try:
        clean_commitment = commitment_hex.strip().lower()
        if clean_commitment.startswith("0x"):
            clean_commitment = clean_commitment[2:]

        clean_root = merkle_root_hex.strip().lower()
        if clean_root.startswith("0x"):
            clean_root = clean_root[2:]

        expected_root_bytes = bytes.fromhex(clean_root)
        if len(expected_root_bytes) != 32:
            return False, "INVALID INCLUSION PROOF: Malformed expected root"

        # 1. Compute leaf hash from commitment
        current = _leaf_hash(clean_commitment)

        # 2. Iterate up through the audit path
        for step in audit_path:
            sib_hex = step.get("hash", "").strip().lower()
            if sib_hex.startswith("0x"):
                sib_hex = sib_hex[2:]
            sib_bytes = bytes.fromhex(sib_hex)
            if len(sib_bytes) != 32:
                return False, "INVALID INCLUSION PROOF: Malformed sibling hash in audit path"

            direction = step.get("direction", "").lower()
            if direction == "right":
                current = _node_hash(current, sib_bytes)
            elif direction == "left":
                current = _node_hash(sib_bytes, current)
            else:
                return False, f"INVALID INCLUSION PROOF: Invalid direction '{direction}' in audit path"

        # 3. Final root comparison
        if current == expected_root_bytes:
            return True, "VALID INCLUSION PROOF"
        return False, "INVALID INCLUSION PROOF: Recomputed root does not match published root"

    except Exception as err:
        return False, f"INVALID INCLUSION PROOF: Verification error ({err})"
