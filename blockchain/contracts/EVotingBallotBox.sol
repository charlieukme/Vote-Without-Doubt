/**
 * @title EVotingBallotBox
 * @dev Phase 6 - Blockchain foundation (Vote Without Doubt)
 * @notice Supports multiple elections. Receives pseudonymous ballots from relayer.
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
    }

    mapping(uint256 => Election) public elections;
    mapping(uint256 => mapping(uint256 => uint256)) public tally;
    mapping(uint256 => mapping(bytes32 => BallotInfo)) public ballots;
    mapping(uint256 => mapping(bytes32 => bool)) public hasBallot;

    address public officer;
    address public relayer;

    event ElectionCreated(uint256 indexed electionId, uint256 start, uint256 end, uint256 candidateCount, uint256 eligibleCount, uint256 maxBallots);
    event ElectionCancelled(uint256 indexed electionId);
    event BallotCast(uint256 indexed electionId, bytes32 indexed pseudonym, uint256 candidate, uint256 sequence);
    event AuditAnchored(uint256 indexed electionId, bytes32 indexed auditHash, uint256 blockNumber);
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
        require(candidate < e.candidateCount, "INVALID_CANDIDATE");
        require(sequence > 0, "INVALID_SEQUENCE");
        require(sequence <= e.maxBallots, "SEQUENCE_TOO_LARGE");
        if (!hasBallot[electionId][pseudonym]) {
            require(e.distinctVoters < e.eligibleCount, "ELIGIBLE_CAP_REACHED");
            require(sequence == 1, "INVALID_SEQUENCE");
            ballots[electionId][pseudonym] = BallotInfo({sequence: 1, lastCandidate: candidate});
            hasBallot[electionId][pseudonym] = true;
            e.distinctVoters += 1;
            tally[electionId][candidate] += 1;
            emit BallotCast(electionId, pseudonym, candidate, sequence);
        } else {
            BallotInfo storage b = ballots[electionId][pseudonym];
            require(sequence == b.sequence + 1, "INVALID_SEQUENCE");
            require(sequence <= e.maxBallots, "SEQUENCE_TOO_LARGE");
            tally[electionId][b.lastCandidate] -= 1;
            b.lastCandidate = candidate;
            b.sequence = sequence;
            tally[electionId][candidate] += 1;
            emit BallotCast(electionId, pseudonym, candidate, sequence);
        }
    }

    function getTally(uint256 electionId, uint256 candidate) public view returns (uint256) {
        return tally[electionId][candidate];
    }

    function electionInfo(uint256 electionId) public view returns (Election memory) {
        return elections[electionId];
    }

    function anchorAudit(uint256 electionId, bytes32 auditHash) public onlyOfficer {
        require(elections[electionId].end > 0, "ELECTION_NOT_EXISTS");
        emit AuditAnchored(electionId, auditHash, block.number);
    }
}
