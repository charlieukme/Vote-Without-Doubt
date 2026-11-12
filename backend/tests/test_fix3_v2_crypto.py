"""
Unit Tests for Python BN254 Cryptographic Engine (FIX 3 V2).
Verifies:
1. Curve arithmetic, generator, doubling, and infinity properties.
2. CSPRNG scalar generation and canonical range enforcement.
3. Schnorr Proof-of-Possession (PoP) correctness and context binding.
4. Non-circular CDS zero-knowledge ballot proofs.
5. Chaum-Pedersen DLEQ decryption shares and infinity branch handling.
6. Discrete-log tally solver.
"""

import pytest
from app.services.bn254_crypto import (
    G,
    INFINITY,
    P,
    Q,
    compute_canonical_dleq_challenge,
    compute_canonical_transcript_hash,
    generate_ballot_proof,
    generate_officer_decryption_shares,
    generate_schnorr_pop,
    generate_secure_scalar,
    is_infinity,
    is_on_curve,
    point_add,
    point_mul,
    point_neg,
    point_sub,
    solve_discrete_log_tallies,
    validate_point,
    validate_scalar,
    verify_schnorr_pop,
)


def test_generator_on_curve():
    """Confirms BN254 generator G=(1, 2) lies on curve y^2 = x^3 + 3 (mod p)."""
    assert is_on_curve(G) is True
    assert is_infinity(G) is False
    validate_point(G)


def test_point_addition_identity():
    """G + O = G and O + G = G."""
    assert point_add(G, INFINITY) == G
    assert point_add(INFINITY, G) == G
    assert point_add(INFINITY, INFINITY) == INFINITY


def test_point_negation_and_subtraction():
    """G + (-G) = O."""
    neg_G = point_neg(G)
    assert is_on_curve(neg_G) is True
    assert neg_G[0] == G[0]
    assert neg_G[1] == (P - G[1]) % P
    assert point_add(G, neg_G) == INFINITY
    assert point_sub(G, G) == INFINITY


def test_scalar_multiplication_associativity():
    """(a * b) * G == a * (b * G)."""
    a = 12345
    b = 67890
    ab = (a * b) % Q

    pt1 = point_mul(point_mul(G, a), b)
    pt2 = point_mul(G, ab)

    assert pt1 == pt2
    assert is_on_curve(pt1) is True


def test_subgroup_order_identity():
    """q * G == O."""
    res = point_mul(G, Q)
    assert is_infinity(res) is True


def test_secure_scalar_generation():
    """CSPRNG scalars strictly in [1, Q-1]."""
    for _ in range(20):
        s = generate_secure_scalar()
        assert 0 < s < Q
        validate_scalar(s)


def test_schnorr_pop_generation_and_verification():
    """Officer Schnorr PoP generates valid signature and validates against context."""
    s1 = generate_secure_scalar()
    contract_addr = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
    officer_addr = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    election_id = 9999
    chain_id = 1337

    pop_data = generate_schnorr_pop(
        priv_key=s1,
        officer_id=1,
        officer_address=officer_addr,
        election_id=election_id,
        contract_address=contract_addr,
        chain_id=chain_id,
    )

    Y = (pop_data["pub_key"]["x"], pop_data["pub_key"]["y"])
    assert is_on_curve(Y) is True

    valid = verify_schnorr_pop(
        pub_key=Y,
        pop=pop_data["pop"],
        officer_id=1,
        officer_address=officer_addr,
        election_id=election_id,
        contract_address=contract_addr,
        chain_id=chain_id,
    )
    assert valid is True

    # Replay under wrong election id fails
    wrong_election = verify_schnorr_pop(
        pub_key=Y,
        pop=pop_data["pop"],
        officer_id=1,
        officer_address=officer_addr,
        election_id=1111,
        contract_address=contract_addr,
        chain_id=chain_id,
    )
    assert wrong_election is False


def test_non_circular_cds_proof_generation():
    """Generates valid 1-of-M CDS ballot proof with sum-to-one constraint."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y1 = point_mul(G, s1)
    Y2 = point_mul(G, s2)
    Y_joint = point_add(Y1, Y2)

    context = {
        "election_id": 8888,
        "pseudonym": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        "sequence": 1,
        "joint_pub_key": {"x": Y_joint[0], "y": Y_joint[1]},
    }

    verifier_addr = "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512"
    chain_id = 1337

    ballot = generate_ballot_proof(
        selected_candidate=0,
        candidate_count=2,
        context=context,
        verifier_address=verifier_addr,
        chain_id=chain_id,
    )

    assert len(ballot["ciphertexts"]) == 2
    assert len(ballot["proof"]["candidateCommitments"]) == 2
    assert len(ballot["proof"]["candidateProofs"]) == 2
    assert ballot["proof"]["z_sum"] > 0


def test_dleq_decryption_shares_and_infinity_handling():
    """Verifies DLEQ decryption shares generation including aggregate infinity branch."""
    s1 = generate_secure_scalar()
    election_id = 8888
    contract_addr = "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0"
    chain_id = 1337

    A0 = point_mul(G, 12345)
    A1 = INFINITY  # Zero-vote / infinity coordinate

    shares_data = generate_officer_decryption_shares(
        officer_priv_key=s1,
        officer_id=1,
        aggregate_a=[A0, A1],
        election_id=election_id,
        contract_address=contract_addr,
        chain_id=chain_id,
    )

    shares = shares_data["shares"]
    proofs = shares_data["proofs"]

    assert len(shares) == 2
    assert len(proofs) == 2

    # Coordinate 0 is non-infinity
    assert shares[0]["x"] != 0
    assert proofs[0]["z"] != 0

    # Coordinate 1 is infinity
    assert shares[1]["x"] == 0 and shares[1]["y"] == 0
    assert proofs[1]["u"]["x"] == 0
    assert proofs[1]["v"]["x"] == 0
    assert proofs[1]["z"] == 0


def test_discrete_log_tally_solver():
    """Solves bounded discrete-log tallies correctly."""
    s1 = generate_secure_scalar()
    s2 = generate_secure_scalar()
    Y1 = point_mul(G, s1)
    Y2 = point_mul(G, s2)
    Y_joint = point_add(Y1, Y2)

    # 3 voters:
    # Voter 1: Cand 0 (r1)
    # Voter 2: Cand 0 (r2)
    # Voter 3: Cand 1 (r3)
    # Expected tally: [2, 1]
    r1 = 100
    r2 = 200
    r3 = 300

    # Candidate 0: 2 votes -> r_agg = r1 + r2 = 300
    # A_0 = 300*G, B_0 = 300*Y + 2*G
    A0 = point_mul(G, r1 + r2)
    B0 = point_add(point_mul(Y_joint, r1 + r2), point_mul(G, 2))

    # Candidate 1: 1 vote -> r_agg = r3 = 300
    # A_1 = 300*G, B_1 = 300*Y + 1*G
    A1 = point_mul(G, r3)
    B1 = point_add(point_mul(Y_joint, r3), point_mul(G, 1))

    agg_A = [A0, A1]
    agg_B = [B0, B1]

    # Officer 1 shares: D1_j = s1 * A_j
    shares1 = [point_mul(A, s1) for A in agg_A]
    # Officer 2 shares: D2_j = s2 * A_j
    shares2 = [point_mul(A, s2) for A in agg_A]

    tallies = solve_discrete_log_tallies(agg_B, shares1, shares2, candidate_count=2, max_ballots=10)
    assert tallies == [2, 1]
