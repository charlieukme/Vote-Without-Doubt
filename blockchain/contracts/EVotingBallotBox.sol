// SPDX-License-Identifier: MIT
/**
 * @title EVotingBallotBox (LEGACY / INSECURE — DEPRECATED)
 * @notice LEGACY V1 IMPLEMENTATION: Retained strictly for historical audit and backwards-compatible records.
 * @dev CRITICAL SECURITY NOTICE (SEC-001):
 * This legacy contract stores unencrypted candidate choices on-chain and emits them in cleartext
 * in the public BallotCast event log (castBallot / ballots / tally mappings).
 * DO NOT USE FOR ACTIVE ELECTIONS.
 * Active elections must exclusively use EVotingBallotBoxV2.sol, which enforces threshold ElGamal
 * encryption over the BN254 elliptic curve with non-interactive zero-knowledge CDS proofs.
 */
pragma solidity ^0.8.19;

contract EVotingBallotBox {
    enum ElectionState {
        DRAFT,
        OPEN,
        CLOSED,
        CANCELLED
    }

    struct Election {
        uint256 start;
        uint256 end;
        uint256 candidateCount;
        bytes32 candidatesHash;
        uint256 eligibleCount;
        bytes32 rollHash;
        uint256 maxBallots;
        uint256 distinctVoters;
        bool cancelled;
    }

    struct BallotInfo {
        uint256 sequence;
        uint256 lastCandidate;
        bool isNull;
    }

    mapping(uint256 => Election) public elections;
    mapping(uint256 => mapping(uint256 => uint256)) public tally;
    mapping(uint256 => mapping(bytes32 => BallotInfo)) public ballots;
    mapping(uint256 => mapping(bytes32 => bool)) public hasBallot;
    mapping(uint256 => bytes32) public auditAnchors;
    mapping(uint256 => uint256) public auditAnchorBlocks;
    mapping(uint256 => uint256) public auditAnchorCount;
    mapping(uint256 => bytes32) public ballotMerkleRoots;
    mapping(uint256 => uint256) public ballotMerkleRootBlocks;

    address public officer;
    address public relayer;

    event ElectionCreated(uint256 indexed electionId, uint256 start, uint256 end, uint256 candidateCount, uint256 eligibleCount, uint256 maxBallots);
    event ElectionCancelled(uint256 indexed electionId);
    event BallotCast(uint256 indexed electionId, bytes32 indexed pseudonym, uint256 candidate, uint256 sequence);
    event NullBallotCast(uint256 indexed electionId, bytes32 indexed pseudonym, uint256 sequence);
    event AuditAnchored(uint256 indexed electionId, bytes32 indexed auditHash, uint256 blockNumber);
    event BallotMerkleRootAnchored(uint256 indexed electionId, bytes32 indexed merkleRoot, uint256 blockNumber);
    event RelayerChanged(address indexed oldRelayer, address indexed newRelayer);

    modifier onlyOfficer() {
        require(msg.sender == officer, "UNAUTHORIZED_OFFICER");
        _;
    }

    modifier onlyRelayer() {
        require(msg.sender == relayer, "UNAUTHORIZED_RELAYER");
        _;
    }

    constructor() {
        officer = msg.sender;
        relayer = address(0);
    }

    function setRelayer(address _relayer) public onlyOfficer {
        require(_relayer != address(0), "INVALID_RELAYER");
        require(_relayer != relayer, "RELAYER_UNCHANGED");
        emit RelayerChanged(relayer, _relayer);
        relayer = _relayer;
    }

    function createElection(
        uint256 electionId,
        uint256 _start,
        uint256 _end,
        uint256 _candidateCount,
        bytes32 _candidatesHash,
        uint256 _eligibleCount,
        bytes32 _rollHash,
        uint256 _maxBallots
    ) public onlyOfficer {
        require(_start < _end, "INVALID_TIMING");
        require(_candidateCount > 0, "INVALID_CANDIDATES");
        require(_eligibleCount > 0, "INVALID_ELIGIBLE");
        require(_maxBallots > 0, "INVALID_MAXBALLOTS");
        require(!elections[electionId].cancelled, "ELECTION_EXISTS");
        require(elections[electionId].end == 0 || elections[electionId].cancelled, "ELECTION_EXISTS");
        elections[electionId] = Election({
            start: _start,
            end: _end,
            candidateCount: _candidateCount,
            candidatesHash: _candidatesHash,
            eligibleCount: _eligibleCount,
            rollHash: _rollHash,
            maxBallots: _maxBallots,
            distinctVoters: 0,
            cancelled: false
        });
        emit ElectionCreated(electionId, _start, _end, _candidateCount, _eligibleCount, _maxBallots);
    }

    function cancelElection(uint256 electionId) public onlyOfficer {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        require(!elections[electionId].cancelled, "ALREADY_CANCELLED");
        elections[electionId].cancelled = true;
        emit ElectionCancelled(electionId);
    }

    function castBallot(uint256 electionId, bytes32 pseudonym, uint256 candidate, uint256 sequence) public onlyRelayer {
        Election storage e = elections[electionId];
        require(e.end > 0, "ELECTION_NOT_EXISTS");
        require(!e.cancelled, "ELECTION_CANCELLED");
        require(block.timestamp >= e.start && block.timestamp <= e.end, "ELECTION_NOT_OPEN");
        require(pseudonym != bytes32(0), "INVALID_PSEUDONYM");
        require(candidate < e.candidateCount, "INVALID_CANDIDATE");
        if (hasBallot[electionId][pseudonym] && e.maxBallots == 1) {
            revert("BALLOT_ALREADY_CAST");
        }
        require(sequence > 0, "INVALID_SEQUENCE");
        require(sequence <= e.maxBallots, "SEQUENCE_TOO_LARGE");
        BallotInfo storage prev = ballots[electionId][pseudonym];

        if (!hasBallot[electionId][pseudonym]) {
            require(sequence == 1, "INVALID_SEQUENCE");
            require(e.distinctVoters < e.eligibleCount, "ELIGIBLE_CAP_REACHED");

            ballots[electionId][pseudonym] = BallotInfo({sequence: 1, lastCandidate: candidate, isNull: false});
            hasBallot[electionId][pseudonym] = true;
            e.distinctVoters += 1;
            tally[electionId][candidate] += 1;
        } else {
            require(sequence == prev.sequence + 1, "INVALID_SEQUENCE");

            if (!prev.isNull) {
                tally[electionId][prev.lastCandidate] -= 1;
            }
            tally[electionId][candidate] += 1;
            ballots[electionId][pseudonym] = BallotInfo({sequence: sequence, lastCandidate: candidate, isNull: false});
        }

        emit BallotCast(electionId, pseudonym, candidate, sequence);
    }

    function castNullBallot(uint256 electionId, bytes32 pseudonym, uint256 sequence) public onlyRelayer {
        Election storage e = elections[electionId];
        require(e.end > 0, "ELECTION_NOT_EXISTS");
        require(!e.cancelled, "ELECTION_CANCELLED");
        require(block.timestamp >= e.start && block.timestamp <= e.end, "ELECTION_NOT_OPEN");
        require(pseudonym != bytes32(0), "INVALID_PSEUDONYM");
        require(hasBallot[electionId][pseudonym], "NO_PRIOR_BALLOT");
        if (e.maxBallots == 1) {
            revert("BALLOT_ALREADY_CAST");
        }
        require(sequence > 0, "INVALID_SEQUENCE");
        require(sequence <= e.maxBallots, "SEQUENCE_TOO_LARGE");

        BallotInfo storage prev = ballots[electionId][pseudonym];
        require(sequence == prev.sequence + 1, "INVALID_SEQUENCE");

        if (!prev.isNull) {
            tally[electionId][prev.lastCandidate] -= 1;
        }
        ballots[electionId][pseudonym] = BallotInfo({sequence: sequence, lastCandidate: 0, isNull: true});

        emit NullBallotCast(electionId, pseudonym, sequence);
    }

    function getBallot(uint256 electionId, bytes32 pseudonym) external view returns (uint256 sequence, uint256 lastCandidate, bool isNull, bool hasCast) {
        return (ballots[electionId][pseudonym].sequence, ballots[electionId][pseudonym].lastCandidate, ballots[electionId][pseudonym].isNull, hasBallot[electionId][pseudonym]);
    }

    function getTally(uint256 electionId, uint256 candidate) public view returns (uint256) {
        return tally[electionId][candidate];
    }

    function electionInfo(uint256 electionId) public view returns (Election memory) {
        return elections[electionId];
    }

    function anchorAudit(uint256 electionId, bytes32 auditHash) public onlyOfficer {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        require(auditHash != bytes32(0), "INVALID_AUDIT_HASH");
        auditAnchors[electionId] = auditHash;
        auditAnchorBlocks[electionId] = block.number;
        auditAnchorCount[electionId] += 1;
        emit AuditAnchored(electionId, auditHash, block.number);
    }

    function getAuditAnchor(uint256 electionId) external view returns (bytes32 anchor, uint256 blockNumber, uint256 updateCount) {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        return (auditAnchors[electionId], auditAnchorBlocks[electionId], auditAnchorCount[electionId]);
    }

    function anchorBallotMerkleRoot(uint256 electionId, bytes32 merkleRoot) public onlyOfficer {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        require(merkleRoot != bytes32(0), "INVALID_MERKLE_ROOT");
        ballotMerkleRoots[electionId] = merkleRoot;
        ballotMerkleRootBlocks[electionId] = block.number;
        emit BallotMerkleRootAnchored(electionId, merkleRoot, block.number);
    }

    function getBallotMerkleRoot(uint256 electionId) external view returns (bytes32 root, uint256 blockNumber) {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        return (ballotMerkleRoots[electionId], ballotMerkleRootBlocks[electionId]);
    }
}
