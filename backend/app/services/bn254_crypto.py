"""
FIX 3 V2: High-Assurance BN254 Cryptographic Engine for Vote Without Doubt.
Implements:
1. Pure Python BN254 G1 curve arithmetic (EIP-196 compliant: P, Q, G, ecAdd, ecMul).
2. CSPRNG scalar generation via Python `secrets`.
3. Schnorr Proof-of-Possession (PoP) matching EVotingBallotBoxV2.
4. Non-circular Cramer-Damgård-Schoenmakers (CDS) 1-of-2 and vector sum-to-one zero-knowledge prover.
5. Chaum-Pedersen DLEQ decryption-share generator with aggregate point-at-infinity handling.
6. Bounded discrete-log tally solver.
7. Exact Solidity ABI and Keccak256 transcript encoding parity.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional, Tuple
from eth_abi import encode
from eth_utils import keccak

# ==============================================================================
# BN254 G1 Curve Constants
# Base field F_p: Y^2 = X^3 + 3 (mod p)
# ==============================================================================
P: int = 21888242871839275222246405745257275088696311157297823662689037894645226208583
Q: int = 21888242871839275222246405745257275088548364400416034343698204186575808495617

GX: int = 1
GY: int = 2

# Generator and Infinity
G: Tuple[int, int] = (GX, GY)
INFINITY: Tuple[int, int] = (0, 0)

DOMAIN_SEPARATOR: bytes = keccak(b"VWD_BN254_CDS_NIZK_NONCIRCULAR_V2")
POP_DOMAIN_SEPARATOR: bytes = keccak(b"VWD_BN254_POP_V1")
DLEQ_DOMAIN_SEPARATOR: bytes = keccak(b"VWD_BN254_DLEQ_V1")

MIN_CANDIDATES: int = 2
MAX_CANDIDATES: int = 10


def mod_inv(a: int, m: int = P) -> int:
    """Computes modular inverse using extended Euclidean algorithm."""
    if a % m == 0:
        raise ZeroDivisionError("Modular inverse does not exist")
    return pow(a % m, -1, m)


def mod_p(val: int) -> int:
    """Reduces integer modulo base field prime P."""
    return val % P


def mod_q(val: int) -> int:
    """Reduces integer modulo subgroup order prime Q."""
    return val % Q


def is_infinity(pt: Tuple[int, int]) -> bool:
    """Returns True if point is the group identity (0, 0)."""
    return pt[0] == 0 and pt[1] == 0


def is_on_curve(pt: Tuple[int, int]) -> bool:
    """Verifies whether (x, y) is on BN254 G1: y^2 = x^3 + 3 (mod p)."""
    if is_infinity(pt):
        return True
    x, y = pt
    if x >= P or y >= P or x < 0 or y < 0:
        return False
    lhs = (y * y) % P
    rhs = (pow(x, 3, P) + 3) % P
    return lhs == rhs


def validate_point(pt: Tuple[int, int]) -> None:
    """Raises ValueError if point is not valid on BN254 G1."""
    if not is_on_curve(pt):
        raise ValueError("Point is not on BN254 G1 curve")


def validate_scalar(s: int) -> None:
    """Raises ValueError if scalar is not in canonical range [0, Q-1]."""
    if s < 0 or s >= Q:
        raise ValueError("Scalar exceeds subgroup order Q")


def point_neg(pt: Tuple[int, int]) -> Tuple[int, int]:
    """Computes point negation -P = (x, -y mod p)."""
    if is_infinity(pt):
        return INFINITY
    return (pt[0], (P - pt[1]) % P)


def point_add(p1: Tuple[int, int], p2: Tuple[int, int]) -> Tuple[int, int]:
    """Adds two G1 points using affine group addition formulas."""
    if is_infinity(p1):
        return p2
    if is_infinity(p2):
        return p1

    x1, y1 = p1
    x2, y2 = p2

    if x1 == x2:
        if (y1 + y2) % P == 0:
            return INFINITY
        # Point doubling: lambda = (3 * x1^2) / (2 * y1)
        num = (3 * x1 * x1) % P
        den = (2 * y1) % P
        lam = (num * mod_inv(den, P)) % P
        x3 = (lam * lam - 2 * x1) % P
        y3 = (lam * (x1 - x3) - y1) % P
        return (x3, y3)
    else:
        # Point addition: lambda = (y2 - y1) / (x2 - x1)
        num = (y2 - y1) % P
        den = (x2 - x1) % P
        lam = (num * mod_inv(den, P)) % P
        x3 = (lam * lam - x1 - x2) % P
        y3 = (lam * (x1 - x3) - y1) % P
        return (x3, y3)


def point_sub(p1: Tuple[int, int], p2: Tuple[int, int]) -> Tuple[int, int]:
    """Subtracts point p2 from p1: p1 - p2 = p1 + (-p2)."""
    return point_add(p1, point_neg(p2))


def point_mul(pt: Tuple[int, int], scalar: int) -> Tuple[int, int]:
    """Multiplies point by scalar using double-and-add algorithm."""
    s = mod_q(scalar)
    if s == 0 or is_infinity(pt):
        return INFINITY

    current = pt
    result = INFINITY

    while s > 0:
        if s & 1:
            result = point_add(result, current)
        current = point_add(current, current)
        s >>= 1

    return result


def generate_secure_scalar() -> int:
    """Generates a cryptographically secure scalar in [1, Q-1] using CSPRNG rejection sampling."""
    while True:
        s = secrets.randbelow(Q)
        if s > 0:
            return s


# ==============================================================================
# Schnorr Proof-of-Possession (PoP)
# ==============================================================================

def generate_schnorr_pop(
    priv_key: int,
    officer_id: int,
    officer_address: Optional[str] = None,
    election_id: int = 1,
    contract_address: str = "0x0000000000000000000000000000000000000000",
    chain_id: int = 1337,
    custom_witness: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Computes Schnorr Proof-of-Possession matching EVotingBallotBoxV2.registerOfficer:
    Public Key: Y = s * G
    Commitment: R = k * G
    Challenge: e = keccak256(POP_DOMAIN, chainId, contract, electionId, officerId, Y_x, Y_y, R_x, R_y) mod Q
    Response: z = k + e * s mod Q
    """
    validate_scalar(priv_key)
    k = custom_witness if custom_witness is not None else generate_secure_scalar()
    validate_scalar(k)

    Y = point_mul(G, priv_key)
    R = point_mul(G, k)

    # Clean addresses
    c_addr = bytes.fromhex(contract_address[2:].lower() if contract_address.startswith("0x") else contract_address.lower())

    if officer_address:
        o_addr = bytes.fromhex(officer_address[2:].lower() if officer_address.startswith("0x") else officer_address.lower())
        encoded_bytes = encode(
            ["bytes32", "uint256", "address", "uint256", "uint256", "address", "uint256", "uint256", "uint256", "uint256"],
            [
                POP_DOMAIN_SEPARATOR,
                int(chain_id),
                "0x" + c_addr.hex(),
                int(election_id),
                int(officer_id),
                "0x" + o_addr.hex(),
                Y[0],
                Y[1],
                R[0],
                R[1],
            ],
        )
    else:
        encoded_bytes = encode(
            ["bytes32", "uint256", "address", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
            [
                POP_DOMAIN_SEPARATOR,
                int(chain_id),
                "0x" + c_addr.hex(),
                int(election_id),
                int(officer_id),
                Y[0],
                Y[1],
                R[0],
                R[1],
            ],
        )
    e = mod_q(int.from_bytes(keccak(encoded_bytes), "big"))
    z = mod_q(k + e * priv_key)

    return {
        "pub_key": {"x": Y[0], "y": Y[1]},
        "pop": {
            "r": {"x": R[0], "y": R[1]},
            "z": z,
        },
    }


def verify_schnorr_pop(
    pub_key: Tuple[int, int],
    pop: Dict[str, Any],
    officer_id: int,
    officer_address: Optional[str] = None,
    election_id: int = 1,
    contract_address: str = "0x0000000000000000000000000000000000000000",
    chain_id: int = 1337,
) -> bool:
    """Verifies a Schnorr Proof-of-Possession off-chain."""
    if is_infinity(pub_key) or not is_on_curve(pub_key):
        return False

    try:
        rx = int(pop["r"]["x"], 0) if isinstance(pop["r"]["x"], str) else int(pop["r"]["x"])
        ry = int(pop["r"]["y"], 0) if isinstance(pop["r"]["y"], str) else int(pop["r"]["y"])
        R = (rx, ry)
        z = int(pop["z"], 0) if isinstance(pop["z"], str) else int(pop["z"])
    except (KeyError, ValueError, TypeError):
        return False

    if is_infinity(R) or not is_on_curve(R):
        return False

    if z < 0 or z >= Q:
        return False

    c_addr = bytes.fromhex(contract_address[2:].lower() if contract_address.startswith("0x") else contract_address.lower())

    # 1. Canonical V2 PoP Transcript (9 fields, independent of officer wallet address)
    encoded_canonical = encode(
        ["bytes32", "uint256", "address", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
        [
            POP_DOMAIN_SEPARATOR,
            int(chain_id),
            "0x" + c_addr.hex(),
            int(election_id),
            int(officer_id),
            pub_key[0],
            pub_key[1],
            R[0],
            R[1],
        ],
    )
    e = mod_q(int.from_bytes(keccak(encoded_canonical), "big"))
    lhs = point_mul(G, z)
    rhs = point_add(R, point_mul(pub_key, e))
    if lhs[0] == rhs[0] and lhs[1] == rhs[1]:
        return True

    # 2. Backward-compatibility: legacy 10-field transcript with officer_address
    if officer_address:
        o_addr = bytes.fromhex(officer_address[2:].lower() if officer_address.startswith("0x") else officer_address.lower())
        encoded_legacy = encode(
            ["bytes32", "uint256", "address", "uint256", "uint256", "address", "uint256", "uint256", "uint256", "uint256"],
            [
                POP_DOMAIN_SEPARATOR,
                int(chain_id),
                "0x" + c_addr.hex(),
                int(election_id),
                int(officer_id),
                "0x" + o_addr.hex(),
                pub_key[0],
                pub_key[1],
                R[0],
                R[1],
            ],
        )
        e_leg = mod_q(int.from_bytes(keccak(encoded_legacy), "big"))
        rhs_leg = point_add(R, point_mul(pub_key, e_leg))
        if lhs[0] == rhs_leg[0] and lhs[1] == rhs_leg[1]:
            return True

    return False


# ==============================================================================
# Non-Circular CDS Zero-Knowledge Ballot Validity Prover
# ==============================================================================

def compute_canonical_transcript_hash(
    context: Dict[str, Any],
    ciphertexts: List[Dict[str, Any]],
    candidate_commitments: List[Dict[str, Any]],
    sum_commitments: Dict[str, Any],
    verifier_address: str,
    chain_id: int,
) -> bytes:
    """
    Computes canonical Fiat-Shamir transcript hash matching BN254CDSVerifier.computeTranscriptHash exactly.
    """
    M = len(ciphertexts)
    if M < MIN_CANDIDATES or M > MAX_CANDIDATES:
        raise ValueError(f"Candidate count {M} out of range [{MIN_CANDIDATES}, {MAX_CANDIDATES}]")

    v_addr = verifier_address if verifier_address.startswith("0x") else "0x" + verifier_address
    pseudonym_bytes = bytes.fromhex(context["pseudonym"][2:] if context["pseudonym"].startswith("0x") else context["pseudonym"])

    header = [
        DOMAIN_SEPARATOR,
        int(chain_id),
        v_addr,
        int(context["election_id"]),
        pseudonym_bytes,
        int(context["sequence"]),
        int(context["joint_pub_key"]["x"]),
        int(context["joint_pub_key"]["y"]),
        M,
    ]

    header_hash = keccak(
        encode(
            ["(bytes32,uint256,address,uint256,bytes32,uint256,uint256,uint256,uint256)"],
            [tuple(header)],
        )
    )

    ct_tuples = [
        ((int(ct["a"]["x"]), int(ct["a"]["y"])), (int(ct["b"]["x"]), int(ct["b"]["y"])))
        for ct in ciphertexts
    ]
    ct_hash = keccak(
        encode(
            ["((uint256,uint256),(uint256,uint256))[]"],
            [ct_tuples],
        )
    )

    comm_tuples = [
        (
            (int(c["t_a_0"]["x"]), int(c["t_a_0"]["y"])),
            (int(c["t_b_0"]["x"]), int(c["t_b_0"]["y"])),
            (int(c["t_a_1"]["x"]), int(c["t_a_1"]["y"])),
            (int(c["t_b_1"]["x"]), int(c["t_b_1"]["y"])),
        )
        for c in candidate_commitments
    ]
    comm_hash = keccak(
        encode(
            ["((uint256,uint256),(uint256,uint256),(uint256,uint256),(uint256,uint256))[]"],
            [comm_tuples],
        )
    )

    sum_comm_tuple = (
        (int(sum_commitments["t_a_sum"]["x"]), int(sum_commitments["t_a_sum"]["y"])),
        (int(sum_commitments["t_b_sum"]["x"]), int(sum_commitments["t_b_sum"]["y"])),
    )
    sum_comm_hash = keccak(
        encode(
            ["((uint256,uint256),(uint256,uint256))"],
            [sum_comm_tuple],
        )
    )

    return keccak(
        encode(
            ["bytes32", "bytes32", "bytes32", "bytes32"],
            [header_hash, ct_hash, comm_hash, sum_comm_hash],
        )
    )


def generate_ballot_proof(
    selected_candidate: int,
    candidate_count: int,
    context: Dict[str, Any],
    verifier_address: str,
    chain_id: int,
    custom_nonces: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates valid ElGamal encrypted ballot vector and non-circular CDS proof.
    """
    M = candidate_count
    if selected_candidate < 0 or selected_candidate >= M:
        raise ValueError(f"Selected candidate {selected_candidate} out of bounds")

    Y = (context["joint_pub_key"]["x"], context["joint_pub_key"]["y"])
    validate_point(Y)
    if is_infinity(Y):
        raise ValueError("Joint public key cannot be infinity")

    ciphertexts = []
    candidate_commitments = []
    r_values = []
    sim_challenges = []
    sim_responses = []
    real_witnesses = []

    for j in range(M):
        v_j = 1 if j == selected_candidate else 0
        r_j = custom_nonces["r"][j] if custom_nonces else generate_secure_scalar()
        validate_scalar(r_j)
        r_values.append(r_j)

        # ElGamal encryption: A = r * G, B = r * Y + v * G
        A = point_mul(G, r_j)
        B = point_mul(Y, r_j)
        if v_j == 1:
            B = point_add(B, G)

        ciphertexts.append({
            "a": {"x": A[0], "y": A[1]},
            "b": {"x": B[0], "y": B[1]},
        })

        w_j = custom_nonces["w"][j] if custom_nonces else generate_secure_scalar()
        sim_c = custom_nonces["sim_c"][j] if custom_nonces else generate_secure_scalar()
        sim_z = custom_nonces["sim_z"][j] if custom_nonces else generate_secure_scalar()

        real_witnesses.append(w_j)
        sim_challenges.append(sim_c)
        sim_responses.append(sim_z)

        if v_j == 0:
            # Real branch is 0
            t_a_0 = point_mul(G, w_j)
            t_b_0 = point_mul(Y, w_j)

            # Simulated branch is 1: T = z*Point - c*Diff
            t_a_1 = point_sub(point_mul(G, sim_z), point_mul(A, sim_c))
            B_minus_G = point_sub(B, G)
            t_b_1 = point_sub(point_mul(Y, sim_z), point_mul(B_minus_G, sim_c))
        else:
            # Simulated branch is 0: T = z*Point - c*Diff
            t_a_0 = point_sub(point_mul(G, sim_z), point_mul(A, sim_c))
            t_b_0 = point_sub(point_mul(Y, sim_z), point_mul(B, sim_c))

            # Real branch is 1
            t_a_1 = point_mul(G, w_j)
            t_b_1 = point_mul(Y, w_j)

        candidate_commitments.append({
            "t_a_0": {"x": t_a_0[0], "y": t_a_0[1]},
            "t_b_0": {"x": t_b_0[0], "y": t_b_0[1]},
            "t_a_1": {"x": t_a_1[0], "y": t_a_1[1]},
            "t_b_1": {"x": t_b_1[0], "y": t_b_1[1]},
        })

    # Sum commitments
    w_sum = custom_nonces["w_sum"] if custom_nonces else generate_secure_scalar()
    validate_scalar(w_sum)
    t_a_sum = point_mul(G, w_sum)
    t_b_sum = point_mul(Y, w_sum)
    sum_commitments = {
        "t_a_sum": {"x": t_a_sum[0], "y": t_a_sum[1]},
        "t_b_sum": {"x": t_b_sum[0], "y": t_b_sum[1]},
    }

    # Master Fiat-Shamir challenge
    transcript_hash = compute_canonical_transcript_hash(
        context, ciphertexts, candidate_commitments, sum_commitments, verifier_address, chain_id
    )
    c_master = mod_q(int.from_bytes(transcript_hash, "big"))

    candidate_proofs = []
    for j in range(M):
        v_j = 1 if j == selected_candidate else 0
        c_j_hash = keccak(encode(["uint256", "uint256"], [c_master, j]))
        c_j = mod_q(int.from_bytes(c_j_hash, "big"))

        if v_j == 0:
            c1 = sim_challenges[j]
            z1 = sim_responses[j]
            c0 = mod_q(c_j - c1)
            z0 = mod_q(real_witnesses[j] + c0 * r_values[j])
        else:
            c0 = sim_challenges[j]
            z0 = sim_responses[j]
            c1 = mod_q(c_j - c0)
            z1 = mod_q(real_witnesses[j] + c1 * r_values[j])

        candidate_proofs.append({
            "c0": c0,
            "c1": c1,
            "z0": z0,
            "z1": z1,
        })

    sum_r = mod_q(sum(r_values))
    c_sum_hash = keccak(encode(["uint256", "string"], [c_master, "SUM"]))
    c_sum = mod_q(int.from_bytes(c_sum_hash, "big"))
    z_sum = mod_q(w_sum + c_sum * sum_r)

    proof = {
        "candidateCommitments": candidate_commitments,
        "candidateProofs": candidate_proofs,
        "sumCommitments": sum_commitments,
        "z_sum": z_sum,
    }

    return {
        "ciphertexts": ciphertexts,
        "proof": proof,
        "c_master": c_master,
    }


# ==============================================================================
# Chaum-Pedersen DLEQ Decryption Shares & Proofs
# ==============================================================================

def compute_canonical_dleq_challenge(
    officer_id: int,
    j: int,
    Y_i: Tuple[int, int],
    A_j: Tuple[int, int],
    D_j: Tuple[int, int],
    proof_u: Tuple[int, int],
    proof_v: Tuple[int, int],
    election_id: int,
    contract_address: str,
    chain_id: int,
) -> int:
    """Computes canonical DLEQ challenge matching EVotingBallotBoxV2._computeDLEQChallenge."""
    c_addr = contract_address if contract_address.startswith("0x") else "0x" + contract_address

    head_hash = keccak(
        encode(
            ["bytes32", "uint256", "address", "uint256", "uint256", "uint256"],
            [
                DLEQ_DOMAIN_SEPARATOR,
                int(chain_id),
                c_addr,
                int(election_id),
                int(officer_id),
                int(j),
            ],
        )
    )

    points_hash = keccak(
        encode(
            ["uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
            [
                Y_i[0],
                Y_i[1],
                A_j[0],
                A_j[1],
                D_j[0],
                D_j[1],
                proof_u[0],
                proof_u[1],
                proof_v[0],
                proof_v[1],
            ],
        )
    )

    final_hash = keccak(encode(["bytes32", "bytes32"], [head_hash, points_hash]))
    return mod_q(int.from_bytes(final_hash, "big"))


def generate_officer_decryption_shares(
    officer_priv_key: int,
    officer_id: int,
    aggregate_a: List[Tuple[int, int]],
    election_id: int,
    contract_address: str,
    chain_id: int,
    custom_witnesses: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Computes decryption shares and DLEQ proofs for an officer.
    Handles aggregate point at infinity: A_agg[j] = infinity -> D_j = infinity, proof = (inf, inf, 0).
    """
    validate_scalar(officer_priv_key)
    Y = point_mul(G, officer_priv_key)

    shares = []
    proofs = []

    for j, A_j in enumerate(aggregate_a):
        if is_infinity(A_j):
            shares.append({"x": 0, "y": 0})
            proofs.append({"u": {"x": 0, "y": 0}, "v": {"x": 0, "y": 0}, "z": 0})
        else:
            validate_point(A_j)
            D_j = point_mul(A_j, officer_priv_key)
            shares.append({"x": D_j[0], "y": D_j[1]})

            t_j = custom_witnesses[j] if custom_witnesses else generate_secure_scalar()
            validate_scalar(t_j)
            U_j = point_mul(G, t_j)
            V_j = point_mul(A_j, t_j)

            c = compute_canonical_dleq_challenge(
                officer_id,
                j,
                Y,
                A_j,
                D_j,
                U_j,
                V_j,
                election_id,
                contract_address,
                chain_id,
            )
            z_j = mod_q(t_j + c * officer_priv_key)

            proofs.append({
                "u": {"x": U_j[0], "y": U_j[1]},
                "v": {"x": V_j[0], "y": V_j[1]},
                "z": z_j,
            })

    return {
        "shares": shares,
        "proofs": proofs,
    }


# ==============================================================================
# Bounded Discrete-Log Tally Solver
# ==============================================================================

def solve_discrete_log_tallies(
    aggregate_b: List[Tuple[int, int]],
    shares1: List[Tuple[int, int]],
    shares2: List[Tuple[int, int]],
    candidate_count: int,
    max_ballots: int = 100000,
) -> List[int]:
    """
    Recovers candidate vote tallies T_j by solving:
    B_agg[j] - (D_1[j] + D_2[j]) == T_j * G.
    Precomputes lookup table in O(max_ballots).
    """
    table: Dict[Tuple[int, int], int] = {}
    curr = INFINITY
    table[curr] = 0

    for k in range(1, max_ballots + 1):
        curr = point_add(curr, G)
        table[curr] = k

    tallies = []
    for j in range(candidate_count):
        D_joint = point_add(shares1[j], shares2[j])
        decrypted_point = point_sub(aggregate_b[j], D_joint)

        if decrypted_point not in table:
            raise ValueError(f"Discrete log search failed for candidate {j}")
        tallies.append(table[decrypted_point])

    return tallies
