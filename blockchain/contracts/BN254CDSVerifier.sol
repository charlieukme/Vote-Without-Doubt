// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./BN254.sol";

/**
 * @title BN254CDSVerifier
 * @dev Milestone 2 (Non-Circular): High-assurance zero-knowledge verifier for
 * Cramer-Damgard-Schoenmakers (CDS) 1-of-2 disjunctive proofs and vector sum-to-one
 * proofs over the BN254 G1 curve.
 *
 * Implements canonical, non-circular Fiat-Shamir transformation:
 * Prover explicitly commits T points first -> Transcript computes challenge -> Prover solves responses.
 * Verifier evaluates challenge from transmitted T points and verifies forward linear equations.
 */
contract BN254CDSVerifier {
    using BN254 for BN254.G1Point;

    bytes32 public constant DOMAIN_SEPARATOR = keccak256("VWD_BN254_CDS_NIZK_NONCIRCULAR_V2");
    uint256 public constant MIN_CANDIDATES = 2;
    uint256 public constant MAX_CANDIDATES = 10;

    struct Ciphertext {
        BN254.G1Point a;
        BN254.G1Point b;
    }

    struct CandidateCommitments {
        BN254.G1Point t_a_0;
        BN254.G1Point t_b_0;
        BN254.G1Point t_a_1;
        BN254.G1Point t_b_1;
    }

    struct CandidateProof {
        uint256 c0;
        uint256 c1;
        uint256 z0;
        uint256 z1;
    }

    struct SumCommitments {
        BN254.G1Point t_a_sum;
        BN254.G1Point t_b_sum;
    }

    struct BallotProof {
        CandidateCommitments[] candidateCommitments;
        CandidateProof[] candidateProofs;
        SumCommitments sumCommitments;
        uint256 z_sum;
    }

    struct BallotContext {
        uint256 electionId;
        bytes32 pseudonym;
        uint256 sequence;
        BN254.G1Point jointPubKey;
    }

    struct TranscriptHeader {
        bytes32 domainSeparator;
        uint256 chainId;
        address verifier;
        uint256 electionId;
        bytes32 pseudonym;
        uint256 sequence;
        uint256 jointPubKeyX;
        uint256 jointPubKeyY;
        uint256 candidateCount;
    }

    function _pointsEqual(BN254.G1Point memory p1, BN254.G1Point memory p2) internal pure returns (bool) {
        return (p1.x == p2.x && p1.y == p2.y);
    }

    /**
     * @notice Verifies linear response equations for Candidate j Branch 0 (v_j = 0):
     * z0 * G == T_A_0 + c0 * A
     * z0 * Y == T_B_0 + c0 * B
     */
    function _verifyBranch0(
        Ciphertext calldata ct,
        CandidateCommitments calldata comm,
        CandidateProof calldata cp,
        BN254.G1Point memory G,
        BN254.G1Point memory Y
    ) internal view {
        BN254.G1Point memory lhsA = BN254.mul(G, cp.z0);
        BN254.G1Point memory rhsA = BN254.add(comm.t_a_0, BN254.mul(ct.a, cp.c0));
        require(_pointsEqual(lhsA, rhsA), "BRANCH_0_A_EQUATION_FAILED");

        BN254.G1Point memory lhsB = BN254.mul(Y, cp.z0);
        BN254.G1Point memory rhsB = BN254.add(comm.t_b_0, BN254.mul(ct.b, cp.c0));
        require(_pointsEqual(lhsB, rhsB), "BRANCH_0_B_EQUATION_FAILED");
    }

    /**
     * @notice Verifies linear response equations for Candidate j Branch 1 (v_j = 1):
     * z1 * G == T_A_1 + c1 * A
     * z1 * Y == T_B_1 + c1 * (B - G)
     */
    function _verifyBranch1(
        Ciphertext calldata ct,
        CandidateCommitments calldata comm,
        CandidateProof calldata cp,
        BN254.G1Point memory G,
        BN254.G1Point memory Y
    ) internal view {
        BN254.G1Point memory lhsA = BN254.mul(G, cp.z1);
        BN254.G1Point memory rhsA = BN254.add(comm.t_a_1, BN254.mul(ct.a, cp.c1));
        require(_pointsEqual(lhsA, rhsA), "BRANCH_1_A_EQUATION_FAILED");

        BN254.G1Point memory B_minus_G = BN254.sub(ct.b, G);
        BN254.G1Point memory lhsB = BN254.mul(Y, cp.z1);
        BN254.G1Point memory rhsB = BN254.add(comm.t_b_1, BN254.mul(B_minus_G, cp.c1));
        require(_pointsEqual(lhsB, rhsB), "BRANCH_1_B_EQUATION_FAILED");
    }

    /**
     * @notice Verifies vector sum-to-one linear response equations:
     * z_sum * G == T_A_sum + c_sum * A_sum
     * z_sum * Y == T_B_sum + c_sum * (B_sum - G)
     */
    function _verifySumProof(
        BN254.G1Point memory A_sum,
        BN254.G1Point memory B_sum,
        SumCommitments calldata sumComm,
        uint256 z_sum,
        uint256 c_sum,
        BN254.G1Point memory G,
        BN254.G1Point memory Y
    ) internal view {
        BN254.G1Point memory lhsA = BN254.mul(G, z_sum);
        BN254.G1Point memory rhsA = BN254.add(sumComm.t_a_sum, BN254.mul(A_sum, c_sum));
        require(_pointsEqual(lhsA, rhsA), "SUM_A_EQUATION_FAILED");

        BN254.G1Point memory B_sum_minus_G = BN254.sub(B_sum, G);
        BN254.G1Point memory lhsB = BN254.mul(Y, z_sum);
        BN254.G1Point memory rhsB = BN254.add(sumComm.t_b_sum, BN254.mul(B_sum_minus_G, c_sum));
        require(_pointsEqual(lhsB, rhsB), "SUM_B_EQUATION_FAILED");
    }

    /**
     * @notice Verifies that an encrypted candidate vector is strictly binary (each v_j in {0, 1})
     * and that the sum of votes is exactly 1 (sum(v_j) == 1).
     * Non-circular: The Fiat-Shamir challenge is computed strictly from the commitments.
     */
    function verifyBallotProof(
        BallotContext calldata context,
        Ciphertext[] calldata ciphertexts,
        BallotProof calldata proof
    ) external view returns (bool) {
        uint256 M = ciphertexts.length;
        require(M > 0, "EMPTY_CIPHERTEXTS");
        require(M >= MIN_CANDIDATES, "CANDIDATE_COUNT_BELOW_MINIMUM");
        require(M <= MAX_CANDIDATES, "CANDIDATE_COUNT_EXCEEDS_MAXIMUM");
        require(proof.candidateCommitments.length == M, "COMMITMENTS_LENGTH_MISMATCH");
        require(proof.candidateProofs.length == M, "PROOFS_LENGTH_MISMATCH");

        // Validate joint public key
        BN254.validatePoint(context.jointPubKey);
        require(!BN254.isInfinity(context.jointPubKey), "INVALID_JOINT_KEY");

        // Context bounds
        require(context.electionId > 0, "INVALID_ELECTION_ID");
        require(context.pseudonym != bytes32(0), "INVALID_PSEUDONYM");
        require(context.sequence > 0, "INVALID_SEQUENCE");

        BN254.G1Point memory G = BN254.generator();
        BN254.G1Point memory Y = context.jointPubKey;

        BN254.G1Point memory A_sum = BN254.infinity();
        BN254.G1Point memory B_sum = BN254.infinity();

        // 1. Validate points, scalars, and accumulate sums
        for (uint256 j = 0; j < M; j++) {
            Ciphertext calldata ct = ciphertexts[j];
            CandidateCommitments calldata comm = proof.candidateCommitments[j];
            CandidateProof calldata cp = proof.candidateProofs[j];

            BN254.validatePoint(ct.a);
            BN254.validatePoint(ct.b);
            require(!BN254.isInfinity(ct.a), "CIPHERTEXT_A_IS_INFINITY");

            BN254.validatePoint(comm.t_a_0);
            BN254.validatePoint(comm.t_b_0);
            BN254.validatePoint(comm.t_a_1);
            BN254.validatePoint(comm.t_b_1);

            // Canonical scalar range checks [0, q-1]
            BN254.validateScalar(cp.c0);
            BN254.validateScalar(cp.c1);
            BN254.validateScalar(cp.z0);
            BN254.validateScalar(cp.z1);

            A_sum = BN254.add(A_sum, ct.a);
            B_sum = BN254.add(B_sum, ct.b);
        }

        BN254.validatePoint(proof.sumCommitments.t_a_sum);
        BN254.validatePoint(proof.sumCommitments.t_b_sum);
        BN254.validateScalar(proof.z_sum);

        // 2. Compute Non-Circular Fiat-Shamir Transcript Challenge from explicit commitments
        bytes32 transcriptHash = computeTranscriptHash(
            context,
            ciphertexts,
            proof.candidateCommitments,
            proof.sumCommitments
        );
        uint256 c_master = uint256(transcriptHash) % BN254.Q;

        // 3. Verify coordinate challenge splits and linear response equations
        for (uint256 j = 0; j < M; j++) {
            uint256 expected_c_j = uint256(keccak256(abi.encode(c_master, j))) % BN254.Q;
            uint256 actual_sum_c = addmod(proof.candidateProofs[j].c0, proof.candidateProofs[j].c1, BN254.Q);
            require(actual_sum_c == expected_c_j, "INVALID_CDS_CHALLENGE_SUM");

            _verifyBranch0(ciphertexts[j], proof.candidateCommitments[j], proof.candidateProofs[j], G, Y);
            _verifyBranch1(ciphertexts[j], proof.candidateCommitments[j], proof.candidateProofs[j], G, Y);
        }

        // 4. Verify sum challenge and sum linear response equations
        uint256 expected_c_sum = uint256(keccak256(abi.encode(c_master, "SUM"))) % BN254.Q;
        _verifySumProof(A_sum, B_sum, proof.sumCommitments, proof.z_sum, expected_c_sum, G, Y);

        return true;
    }

    /**
     * @notice Canonical Non-Circular Fiat-Shamir transcript hash computation.
     * Derived exclusively from context, ciphertexts, and explicitly transmitted commitments.
     */
    function computeTranscriptHash(
        BallotContext calldata context,
        Ciphertext[] calldata ciphertexts,
        CandidateCommitments[] calldata candidateCommitments,
        SumCommitments calldata sumCommitments
    ) public view returns (bytes32) {
        require(ciphertexts.length > 0, "EMPTY_CIPHERTEXTS");
        require(ciphertexts.length >= MIN_CANDIDATES, "CANDIDATE_COUNT_BELOW_MINIMUM");
        require(ciphertexts.length <= MAX_CANDIDATES, "CANDIDATE_COUNT_EXCEEDS_MAXIMUM");

        TranscriptHeader memory header = TranscriptHeader({
            domainSeparator: DOMAIN_SEPARATOR,
            chainId: block.chainid,
            verifier: address(this),
            electionId: context.electionId,
            pseudonym: context.pseudonym,
            sequence: context.sequence,
            jointPubKeyX: context.jointPubKey.x,
            jointPubKeyY: context.jointPubKey.y,
            candidateCount: ciphertexts.length
        });

        bytes32 headerHash = keccak256(abi.encode(header));
        bytes32 ctHash = keccak256(abi.encode(ciphertexts));
        bytes32 commHash = keccak256(abi.encode(candidateCommitments));
        bytes32 sumCommHash = keccak256(abi.encode(sumCommitments));

        return keccak256(abi.encode(headerHash, ctHash, commHash, sumCommHash));
    }
}
