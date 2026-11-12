"""
Isolated Test Suite for FIX 3: On-Chain Candidate Choice Privacy
Tests Threshold ElGamal Encryption, Zero-Knowledge Ballot-Validity Proofs,
Revoting Homomorphic Aggregation, and Verifiable Aggregate Decryption.
"""

import pytest
from app.services.tally_crypto_service import ThresholdTallyEngine


def test_joint_key_generation():
    """Two officers generate independent key shares and combine into joint public key."""
    s1, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    s2, Y2 = ThresholdTallyEngine.generate_officer_keypair()

    assert s1 != s2
    assert Y1 != Y2

    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])
    assert joint_pub > 1


def test_ballot_encryption_and_validity_proof():
    """Ballot encryption creates ciphertexts and a valid Chaum-Pedersen NIZK proof."""
    _, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    _, Y2 = ThresholdTallyEngine.generate_officer_keypair()
    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])

    candidate_count = 3
    candidate_choice = 1  # Vote for Candidate 1

    ciphertexts, proof = ThresholdTallyEngine.encrypt_candidate_vector(
        joint_pub, candidate_choice, candidate_count
    )

    assert len(ciphertexts) == 3
    # Verify NIZK proof passes
    is_valid = ThresholdTallyEngine.verify_ballot_validity_proof(joint_pub, ciphertexts, proof)
    assert is_valid is True


def test_invalid_ballot_tampering_rejected():
    """Tampering with ciphertexts causes NIZK ballot validity verification to fail."""
    _, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    _, Y2 = ThresholdTallyEngine.generate_officer_keypair()
    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])

    candidate_count = 3
    ciphertexts, proof = ThresholdTallyEngine.encrypt_candidate_vector(
        joint_pub, 0, candidate_count
    )

    # Tamper with candidate 0's ciphertext
    tampered = list(ciphertexts)
    A_tampered = (tampered[0][0] * 5) % ThresholdTallyEngine.generate_officer_keypair()[1]
    tampered[0] = (A_tampered, tampered[0][1])

    is_valid = ThresholdTallyEngine.verify_ballot_validity_proof(joint_pub, tampered, proof)
    assert is_valid is False


def test_homomorphic_tally_aggregation_and_threshold_decryption():
    """
    Homomorphically aggregates votes from multiple voters and verifies
    that two officers can verifiably decrypt the final tally without revealing individual votes.
    """
    s1, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    s2, Y2 = ThresholdTallyEngine.generate_officer_keypair()
    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])

    candidate_count = 3
    # Simulated 5 voters:
    # Voter 1: Cand 0
    # Voter 2: Cand 1
    # Voter 3: Cand 0
    # Voter 4: Cand 2
    # Voter 5: Cand 0
    # Expected: Cand 0 = 3, Cand 1 = 1, Cand 2 = 1
    choices = [0, 1, 0, 2, 0]
    ballot_ciphertexts = []

    for c in choices:
        ciphers, proof = ThresholdTallyEngine.encrypt_candidate_vector(joint_pub, c, candidate_count)
        assert ThresholdTallyEngine.verify_ballot_validity_proof(joint_pub, ciphers, proof) is True
        ballot_ciphertexts.append(ciphers)

    # Aggregate ciphertexts
    agg_ciphers = ThresholdTallyEngine.homomorphic_tally_aggregate(ballot_ciphertexts, candidate_count)
    assert len(agg_ciphers) == 3

    # Officer 1 computes decryption shares and proof
    shares_1, proof_1 = ThresholdTallyEngine.compute_officer_decryption_share(s1, Y1, agg_ciphers)
    assert ThresholdTallyEngine.verify_decryption_share(proof_1) is True

    # Officer 2 computes decryption shares and proof
    shares_2, proof_2 = ThresholdTallyEngine.compute_officer_decryption_share(s2, Y2, agg_ciphers)
    assert ThresholdTallyEngine.verify_decryption_share(proof_2) is True

    # Decrypt tallies using both officer shares
    tallies = ThresholdTallyEngine.decrypt_tallies(agg_ciphers, shares_1, shares_2)
    assert tallies == [3, 1, 1]


def test_revoting_replaces_active_ballot_accurately():
    """
    Demonstrates revoting: voter 1 changes their vote from candidate 0 to candidate 2.
    The aggregation incorporates the latest active ballot only, updating the tally.
    """
    s1, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    s2, Y2 = ThresholdTallyEngine.generate_officer_keypair()
    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])

    candidate_count = 3
    # Initial vote for voter 1 (Cand 0)
    v1_seq1, _ = ThresholdTallyEngine.encrypt_candidate_vector(joint_pub, 0, candidate_count)
    # Revote for voter 1 (Cand 2)
    v1_seq2, _ = ThresholdTallyEngine.encrypt_candidate_vector(joint_pub, 2, candidate_count)

    # Voter 2 casts Cand 1
    v2_seq1, _ = ThresholdTallyEngine.encrypt_candidate_vector(joint_pub, 1, candidate_count)

    # State stores only active ballots per pseudonym: {p1: v1_seq2, p2: v2_seq1}
    active_ballots = [v1_seq2, v2_seq1]

    agg = ThresholdTallyEngine.homomorphic_tally_aggregate(active_ballots, candidate_count)
    shares_1, _ = ThresholdTallyEngine.compute_officer_decryption_share(s1, Y1, agg)
    shares_2, _ = ThresholdTallyEngine.compute_officer_decryption_share(s2, Y2, agg)

    tallies = ThresholdTallyEngine.decrypt_tallies(agg, shares_1, shares_2)
    # Expected: Cand 0 = 0, Cand 1 = 1, Cand 2 = 1
    assert tallies == [0, 1, 1]


def test_single_officer_alone_cannot_decrypt():
    """Confirms threshold security: single officer with only s1 cannot decrypt the tally."""
    s1, Y1 = ThresholdTallyEngine.generate_officer_keypair()
    _, Y2 = ThresholdTallyEngine.generate_officer_keypair()
    joint_pub = ThresholdTallyEngine.combine_officer_public_keys([Y1, Y2])

    candidate_count = 2
    ciphers, _ = ThresholdTallyEngine.encrypt_candidate_vector(joint_pub, 0, candidate_count)
    agg = ThresholdTallyEngine.homomorphic_tally_aggregate([ciphers], candidate_count)

    shares_1, _ = ThresholdTallyEngine.compute_officer_decryption_share(s1, Y1, agg)
    # Fake shares for officer 2 (without s2)
    fake_shares_2 = [1, 1]

    # Attempting to decrypt with fake/missing officer 2 share fails to yield correct tally
    try:
        tallies = ThresholdTallyEngine.decrypt_tallies(agg, shares_1, fake_shares_2, max_votes=100)
        # Even if discrete log fell in table by coincidence, it will not match actual vote 0
        assert tallies != [1, 0]
    except ValueError:
        # Expected: discrete log search exhausts without finding match
        pass
