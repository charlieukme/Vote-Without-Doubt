// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./BN254.sol";
import "./BN254CDSVerifier.sol";

/**
 * @title EVotingBallotBoxV2
 * @dev FIX 3 V2 Milestone 3: Privacy-preserving electronic voting ballot box
 * supporting two-officer threshold ElGamal encryption over BN254 G1, non-circular
 * CDS zero-knowledge ballot validity verification, homomorphic aggregation,
 * secure revoting, Chaum-Pedersen DLEQ decryption verification, and bounded tally verification.
 */
contract EVotingBallotBoxV2 {
    using BN254 for BN254.G1Point;

    enum ElectionState {
        Setup,
        Officer1Registered,
        Officer2Registered,
        KeyRegistrationComplete,
        VotingOpen,
        VotingClosed,
        DecryptionSharesComplete,
        Finalized,
        TallyStalled
    }

    uint256 public constant TALLY_GRACE_PERIOD = 72 hours;
    uint256 public constant MAX_ELECTION_VOTERS = 100000;
    uint256 public constant MAX_BALLOTS_PER_VOTER = 3;
    uint256 public constant MIN_CANDIDATES = 2;
    uint256 public constant MAX_CANDIDATES = 10;

    // Election Immutable Configuration
    uint256 public immutable electionId;
    uint256 public immutable candidateCount;
    address public immutable admin;
    address public relayer;
    BN254CDSVerifier public immutable verifier;

    // Election State
    ElectionState public state;
    uint256 public totalActiveBallots;
    uint256 public votingClosedTimestamp;
    uint256 public tallyDeadline;

    // Officer Keys and PoP State
    bool public officer1Registered;
    bool public officer2Registered;
    BN254.G1Point public officerKey1;
    BN254.G1Point public officerKey2;
    BN254.G1Point public jointPubKey;

    // Encrypted Aggregate State per Candidate
    mapping(uint256 => BN254.G1Point) public aggregateA;
    mapping(uint256 => BN254.G1Point) public aggregateB;

    // Active Voter Records for Homomorphic Revoting
    mapping(bytes32 => uint256) public voterSequence;
    mapping(bytes32 => mapping(uint256 => BN254CDSVerifier.Ciphertext)) private activeBallots;

    // Officer Decryption Shares per Candidate
    mapping(uint256 => bool) public officerSharesSubmitted;
    mapping(uint256 => mapping(uint256 => BN254.G1Point)) public officerDecryptionShares;

    // Verified Final Tallies
    mapping(uint256 => uint256) public finalTallies;

    // Structs
    struct SchnorrPoP {
        BN254.G1Point r;
        uint256 z;
    }

    struct DLEQProof {
        BN254.G1Point u;
        BN254.G1Point v;
        uint256 z;
    }

    // Events
    event OfficerRegistered(uint256 indexed electionId, uint256 indexed officerId, uint256 pubKeyX, uint256 pubKeyY);
    event KeyRegistrationComplete(uint256 indexed electionId, uint256 jointPubKeyX, uint256 jointPubKeyY);
    event KeyRegistrationReset(uint256 indexed electionId, address indexed caller);
    event RelayerRotated(address indexed oldRelayer, address indexed newRelayer);
    event VotingOpened(uint256 indexed electionId, uint256 timestamp);
    event VotingClosed(uint256 indexed electionId, uint256 timestamp, uint256 deadline);
    event BallotCastV2(uint256 indexed electionId, bytes32 indexed pseudonym, uint256 sequence, uint256 activeBallotCount);
    event DecryptionSharesSubmitted(uint256 indexed electionId, uint256 indexed officerId);
    event DecryptionSharesCompleted(uint256 indexed electionId);
    event ElectionFinalized(uint256 indexed electionId, uint256[] tallies);
    event ZeroVoteElectionFinalized(uint256 indexed electionId, uint256 candidateCount);
    event ElectionStalled(uint256 indexed electionId, uint256 timestamp);

    constructor(
        uint256 _electionId,
        uint256 _candidateCount,
        address _relayer,
        address _verifier
    ) {
        require(_electionId > 0, "INVALID_ELECTION_ID");
        require(
            _candidateCount >= MIN_CANDIDATES &&
            _candidateCount <= MAX_CANDIDATES,
            "INVALID_CANDIDATE_COUNT"
        );
        require(_relayer != address(0), "INVALID_RELAYER_ADDRESS");
        require(_verifier != address(0), "INVALID_VERIFIER_ADDRESS");

        electionId = _electionId;
        candidateCount = _candidateCount;
        admin = msg.sender;
        relayer = _relayer;
        verifier = BN254CDSVerifier(_verifier);

        state = ElectionState.Setup;
    }

    /**
     * @notice Admin can rotate the authorized relayer address without affecting election state or officer keys.
     */
    function rotateRelayer(address _newRelayer) external {
        require(msg.sender == admin, "UNAUTHORIZED_ADMIN");
        require(_newRelayer != address(0), "INVALID_RELAYER_ADDRESS");
        require(_newRelayer != relayer, "IDENTICAL_RELAYER_ADDRESS");
        emit RelayerRotated(relayer, _newRelayer);
        relayer = _newRelayer;
    }

    // ==========================================
    // 1. OFFICER REGISTRATION & KEY LIFECYCLE
    // ==========================================

    /**
     * @notice Registers an officer's public key with a Schnorr Proof-of-Possession.
     */
    function registerOfficer(
        uint256 officerId,
        BN254.G1Point calldata pubKey,
        SchnorrPoP calldata pop
    ) external {
        require(msg.sender == relayer, "UNAUTHORIZED_RELAYER");
        require(
            state == ElectionState.Setup ||
            state == ElectionState.Officer1Registered ||
            state == ElectionState.Officer2Registered,
            "INVALID_STATE_FOR_KEY_REGISTRATION"
        );
        require(officerId == 1 || officerId == 2, "INVALID_OFFICER_ID");

        if (officerId == 1) {
            require(!officer1Registered, "OFFICER_1_ALREADY_REGISTERED");
        } else {
            require(!officer2Registered, "OFFICER_2_ALREADY_REGISTERED");
        }

        // Validate public key and proof
        BN254.validatePoint(pubKey);
        require(!BN254.isInfinity(pubKey), "INVALID_OFFICER_KEY");
        BN254.validatePoint(pop.r);
        require(!BN254.isInfinity(pop.r), "INVALID_POP_COMMITMENT");
        BN254.validateScalar(pop.z);

        // Verify Schnorr Proof-of-Possession: z * G == R + e * Y
        bytes32 eHash = keccak256(abi.encode(
            keccak256("VWD_BN254_POP_V1"),
            block.chainid,
            address(this),
            electionId,
            officerId,
            pubKey.x, pubKey.y,
            pop.r.x, pop.r.y
        ));
        uint256 e = uint256(eHash) % BN254.Q;
        require(e != 0, "INVALID_CHALLENGE");

        BN254.G1Point memory lhs = BN254.mul(BN254.generator(), pop.z);
        BN254.G1Point memory rhs = BN254.add(pop.r, BN254.mul(pubKey, e));
        require(lhs.x == rhs.x && lhs.y == rhs.y, "POP_VERIFICATION_FAILED");

        // Save public key
        if (officerId == 1) {
            officerKey1 = pubKey;
            officer1Registered = true;
            if (officer2Registered) {
                state = ElectionState.KeyRegistrationComplete;
                jointPubKey = BN254.add(officerKey1, officerKey2);
                emit KeyRegistrationComplete(electionId, jointPubKey.x, jointPubKey.y);
            } else {
                state = ElectionState.Officer1Registered;
            }
        } else {
            officerKey2 = pubKey;
            officer2Registered = true;
            if (officer1Registered) {
                state = ElectionState.KeyRegistrationComplete;
                jointPubKey = BN254.add(officerKey1, officerKey2);
                emit KeyRegistrationComplete(electionId, jointPubKey.x, jointPubKey.y);
            } else {
                state = ElectionState.Officer2Registered;
            }
        }

        emit OfficerRegistered(electionId, officerId, pubKey.x, pubKey.y);
    }

    /**
     * @notice Allows an officer to reset key registration before voting begins.
     */
    function invalidateKeyRegistration() external {
        require(
            state == ElectionState.Officer1Registered ||
            state == ElectionState.Officer2Registered ||
            state == ElectionState.KeyRegistrationComplete,
            "INVALID_STATE_FOR_KEY_RESET"
        );
        require(msg.sender == relayer, "UNAUTHORIZED_RELAYER");

        officer1Registered = false;
        officer2Registered = false;
        officerKey1 = BN254.infinity();
        officerKey2 = BN254.infinity();
        jointPubKey = BN254.infinity();

        state = ElectionState.Setup;
        emit KeyRegistrationReset(electionId, msg.sender);
    }

    /**
     * @notice Admin opens voting once both officer keys are registered.
     */
    function openVoting() external {
        require(msg.sender == admin, "UNAUTHORIZED_ADMIN");
        require(state == ElectionState.KeyRegistrationComplete, "KEYS_NOT_READY");

        state = ElectionState.VotingOpen;
        emit VotingOpened(electionId, block.timestamp);
    }

    /**
     * @notice Admin closes voting, starting the 72-hour tally countdown.
     */
    function closeVoting() external {
        require(msg.sender == admin, "UNAUTHORIZED_ADMIN");
        require(state == ElectionState.VotingOpen, "VOTING_NOT_OPEN");

        state = ElectionState.VotingClosed;
        votingClosedTimestamp = block.timestamp;
        tallyDeadline = block.timestamp + TALLY_GRACE_PERIOD;

        emit VotingClosed(electionId, block.timestamp, tallyDeadline);
    }

    // ==========================================
    // 2. BALLOT CASTING & HOMOMORPHIC REVOTING
    // ==========================================

    /**
     * @notice Casts an encrypted ballot vector with a non-circular CDS validity proof.
     */
    function castBallot(
        bytes32 pseudonym,
        uint256 sequence,
        BN254CDSVerifier.Ciphertext[] calldata ciphertexts,
        BN254CDSVerifier.BallotProof calldata proof
    ) external {
        require(state == ElectionState.VotingOpen, "ELECTION_NOT_OPEN");
        require(ciphertexts.length == candidateCount, "CANDIDATE_COUNT_MISMATCH");

        uint256 currentSeq = voterSequence[pseudonym];
        require(sequence == currentSeq + 1, "INVALID_SEQUENCE_ORDER");
        require(sequence <= MAX_BALLOTS_PER_VOTER, "MAX_BALLOTS_EXCEEDED");

        // Verify Non-Circular CDS Ballot Validity Proof
        BN254CDSVerifier.BallotContext memory ctx = BN254CDSVerifier.BallotContext({
            electionId: electionId,
            pseudonym: pseudonym,
            sequence: sequence,
            jointPubKey: jointPubKey
        });

        bool valid = verifier.verifyBallotProof(ctx, ciphertexts, proof);
        require(valid, "BALLOT_PROOF_INVALID");

        // Homomorphic Accumulation
        if (currentSeq == 0) {
            // First ballot
            require(totalActiveBallots + 1 <= MAX_ELECTION_VOTERS, "MAX_VOTERS_EXCEEDED");
            for (uint256 j = 0; j < candidateCount; j++) {
                aggregateA[j] = BN254.add(aggregateA[j], ciphertexts[j].a);
                aggregateB[j] = BN254.add(aggregateB[j], ciphertexts[j].b);
                activeBallots[pseudonym][j] = ciphertexts[j];
            }
            totalActiveBallots += 1;
        } else {
            // Revote: homomorphically subtract previous ballot, add new ballot
            for (uint256 j = 0; j < candidateCount; j++) {
                BN254CDSVerifier.Ciphertext memory prevCt = activeBallots[pseudonym][j];
                aggregateA[j] = BN254.add(BN254.sub(aggregateA[j], prevCt.a), ciphertexts[j].a);
                aggregateB[j] = BN254.add(BN254.sub(aggregateB[j], prevCt.b), ciphertexts[j].b);
                activeBallots[pseudonym][j] = ciphertexts[j];
            }
        }

        voterSequence[pseudonym] = sequence;
        emit BallotCastV2(electionId, pseudonym, sequence, totalActiveBallots);
    }

    // ==========================================
    // 3. DECRYPTION SHARES & DLEQ VERIFICATION
    // ==========================================

    /**
     * @notice Submits an officer's decryption shares and verifies their Chaum-Pedersen DLEQ proofs.
     */
    function submitDecryptionShares(
        uint256 officerId,
        BN254.G1Point[] calldata shares,
        DLEQProof[] calldata proofs
    ) external {
        require(msg.sender == relayer, "UNAUTHORIZED_RELAYER");
        require(state == ElectionState.VotingClosed, "VOTING_NOT_CLOSED");
        require(officerId == 1 || officerId == 2, "INVALID_OFFICER_ID");

        if (officerId == 1) {
            require(!officerSharesSubmitted[1], "SHARES_ALREADY_SUBMITTED");
        } else {
            require(!officerSharesSubmitted[2], "SHARES_ALREADY_SUBMITTED");
        }

        require(shares.length == candidateCount, "SHARES_LENGTH_MISMATCH");
        require(proofs.length == candidateCount, "PROOFS_LENGTH_MISMATCH");

        BN254.G1Point memory Y_i = (officerId == 1) ? officerKey1 : officerKey2;

        for (uint256 j = 0; j < candidateCount; j++) {
            BN254.G1Point memory A_j = aggregateA[j];
            BN254.G1Point memory D_j = shares[j];

            BN254.validatePoint(D_j);

            // Handle aggregate point at infinity
            if (BN254.isInfinity(A_j)) {
                require(BN254.isInfinity(D_j), "EXPECTED_INFINITY_SHARE");
                // When A_j is infinity, D_j = s_i * inf = inf. DLEQ is trivially satisfied.
            } else {
                require(!BN254.isInfinity(D_j), "UNEXPECTED_INFINITY_SHARE");
                _verifyDLEQ(officerId, j, Y_i, A_j, D_j, proofs[j]);
            }

            officerDecryptionShares[officerId][j] = D_j;
        }

        officerSharesSubmitted[officerId] = true;
        emit DecryptionSharesSubmitted(electionId, officerId);

        if (officerSharesSubmitted[1] && officerSharesSubmitted[2]) {
            state = ElectionState.DecryptionSharesComplete;
            emit DecryptionSharesCompleted(electionId);
        }
    }

    // ==========================================
    // 4. ON-CHAIN TALLY VERIFICATION
    // ==========================================

    /**
     * @notice Finalizes the election by verifying proposed tallies against aggregate ciphertexts.
     */
    function finalizeTally(uint256[] calldata tallies) external {
        require(state == ElectionState.DecryptionSharesComplete, "SHARES_INCOMPLETE");
        require(tallies.length == candidateCount, "TALLIES_LENGTH_MISMATCH");
        require(totalActiveBallots > 0, "NO_BALLOTS_CAST");

        uint256 runningSum = 0;
        for (uint256 j = 0; j < candidateCount; j++) {
            uint256 tj = tallies[j];
            require(tj <= totalActiveBallots, "CANDIDATE_TALLY_EXCEEDS_TOTAL");
            runningSum += tj;
        }
        require(runningSum == totalActiveBallots, "TALLY_SUM_MISMATCH");

        BN254.G1Point memory G = BN254.generator();

        for (uint256 j = 0; j < candidateCount; j++) {
            uint256 tj = tallies[j];

            // D_joint = D_1 + D_2
            BN254.G1Point memory D_joint = BN254.add(
                officerDecryptionShares[1][j],
                officerDecryptionShares[2][j]
            );

            // B_agg - D_joint == T_j * G
            BN254.G1Point memory decryptedPoint = BN254.sub(aggregateB[j], D_joint);
            BN254.G1Point memory expectedPoint = BN254.mul(G, tj);

            require(
                decryptedPoint.x == expectedPoint.x && decryptedPoint.y == expectedPoint.y,
                "TALLY_EQUATION_FAILED"
            );

            finalTallies[j] = tj;
        }

        state = ElectionState.Finalized;
        emit ElectionFinalized(electionId, tallies);
    }

    /**
     * @notice Finalize a zero-ballot election safely without fabricating votes.
     * Requires both officers' decryption shares to be submitted, zero active ballots,
     * and point-at-infinity aggregate ciphertexts across all candidates.
     */
    function finalizeZeroVoteElection() external {
        require(msg.sender == admin || msg.sender == relayer, "UNAUTHORIZED_CALLER");
        require(state == ElectionState.DecryptionSharesComplete, "SHARES_INCOMPLETE");
        require(totalActiveBallots == 0, "NON_ZERO_BALLOTS");

        uint256[] memory zeroTallies = new uint256[](candidateCount);
        for (uint256 j = 0; j < candidateCount; j++) {
            require(BN254.isInfinity(aggregateA[j]), "NON_EMPTY_AGGREGATE_A");
            require(BN254.isInfinity(aggregateB[j]), "NON_EMPTY_AGGREGATE_B");
            finalTallies[j] = 0;
            zeroTallies[j] = 0;
        }

        state = ElectionState.Finalized;
        emit ZeroVoteElectionFinalized(electionId, candidateCount);
        emit ElectionFinalized(electionId, zeroTallies);
    }

    /**
     * @notice Permissionless transition to TallyStalled if 72-hour grace period expires without completion.
     */
    function markTallyStalled() external {
        require(
            state == ElectionState.VotingClosed,
            "INVALID_STATE_FOR_STALL"
        );
        require(block.timestamp >= tallyDeadline, "TALLY_DEADLINE_NOT_PASSED");

        state = ElectionState.TallyStalled;
        emit ElectionStalled(electionId, block.timestamp);
    }

    function _computeDLEQChallenge(
        uint256 officerId,
        uint256 j,
        BN254.G1Point memory Y_i,
        BN254.G1Point memory A_j,
        BN254.G1Point memory D_j,
        DLEQProof calldata proof
    ) internal view returns (uint256) {
        bytes32 headHash = keccak256(abi.encode(
            keccak256("VWD_BN254_DLEQ_V1"),
            block.chainid,
            address(this),
            electionId,
            officerId,
            j
        ));
        bytes32 pointsHash = keccak256(abi.encode(
            Y_i.x, Y_i.y,
            A_j.x, A_j.y,
            D_j.x, D_j.y,
            proof.u.x, proof.u.y,
            proof.v.x, proof.v.y
        ));
        return uint256(keccak256(abi.encode(headHash, pointsHash))) % BN254.Q;
    }

    function _verifyDLEQ(
        uint256 officerId,
        uint256 j,
        BN254.G1Point memory Y_i,
        BN254.G1Point memory A_j,
        BN254.G1Point memory D_j,
        DLEQProof calldata proof
    ) internal view {
        BN254.validatePoint(proof.u);
        BN254.validatePoint(proof.v);
        require(!BN254.isInfinity(proof.u), "INVALID_DLEQ_U");
        require(!BN254.isInfinity(proof.v), "INVALID_DLEQ_V");
        BN254.validateScalar(proof.z);

        uint256 c = _computeDLEQChallenge(officerId, j, Y_i, A_j, D_j, proof);

        BN254.G1Point memory lhs1 = BN254.mul(BN254.generator(), proof.z);
        BN254.G1Point memory rhs1 = BN254.add(proof.u, BN254.mul(Y_i, c));
        require(lhs1.x == rhs1.x && lhs1.y == rhs1.y, "DLEQ_G_EQUATION_FAILED");

        BN254.G1Point memory lhs2 = BN254.mul(A_j, proof.z);
        BN254.G1Point memory rhs2 = BN254.add(proof.v, BN254.mul(D_j, c));
        require(lhs2.x == rhs2.x && lhs2.y == rhs2.y, "DLEQ_A_EQUATION_FAILED");
    }

    // ==========================================
    // 5. HELPER VIEW FUNCTIONS
    // ==========================================

    function getAggregateCiphertext(uint256 j) external view returns (BN254.G1Point memory a, BN254.G1Point memory b) {
        require(j < candidateCount, "INVALID_CANDIDATE_INDEX");
        return (aggregateA[j], aggregateB[j]);
    }

    function getActiveBallot(bytes32 pseudonym, uint256 j) external view returns (BN254.G1Point memory a, BN254.G1Point memory b) {
        require(j < candidateCount, "INVALID_CANDIDATE_INDEX");
        BN254CDSVerifier.Ciphertext memory ct = activeBallots[pseudonym][j];
        return (ct.a, ct.b);
    }

    function getFinalTally(uint256 j) external view returns (uint256) {
        require(state == ElectionState.Finalized, "ELECTION_NOT_FINALIZED");
        require(j < candidateCount, "INVALID_CANDIDATE_INDEX");
        return finalTallies[j];
    }
}
