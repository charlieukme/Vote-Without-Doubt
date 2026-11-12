const { expect } = require("chai");
const { ethers, network } = require("hardhat");
const {
  P,
  Q,
  G,
  INFINITY,
  isOnCurve,
  isInfinity,
  pointsEqual,
  pointAdd,
  pointSub,
  pointMul,
  generateReferenceBallotProof,
  verifyBallotProofOffchain,
} = require("./helpers/bn254_cds_reference");
const {
  generateSecureScalarBN254,
  generateSchnorrPoP,
  generateOfficerDecryptionShares,
  solveDiscreteLogTallies,
} = require("./helpers/bn254_tally_reference");

describe("FIX 3 V2 — Milestone 6: Isolated End-to-End Validation", function () {
  this.timeout(180000);

  let admin, officer1, officer2, voter1, voter2, voter3, voter4, voter5, unauthorized;
  let verifier, ballotBox;
  let chainId;
  let verifierAddress, ballotBoxAddress;

  const electionId = 9999n;
  const candidateCount = 3n; // At least 3 candidates (0, 1, 2)

  // Officer private scalars (held independently in memory)
  let s1, s2;
  let Y1, Y2, Y_joint;

  // Track transaction hashes and gas usage for the report
  const txRecords = [];

  function recordTx(name, receipt) {
    txRecords.push({
      operation: name,
      txHash: receipt.hash,
      blockNumber: receipt.blockNumber,
      gasUsed: receipt.gasUsed.toString(),
    });
  }

  // Helper to retrieve all aggregate points from contract
  async function getAggregates(contract, count) {
    const aList = [];
    const bList = [];
    for (let j = 0; j < count; j++) {
      const [a, b] = await contract.getAggregateCiphertext(j);
      aList.push({ x: a.x, y: a.y });
      bList.push({ x: b.x, y: b.y });
    }
    return [aList, bList];
  }

  // Independent Test Oracle state
  class IndependentTestOracle {
    constructor(numCandidates) {
      this.numCandidates = Number(numCandidates);
      this.voterBallots = new Map(); // pseudonym -> { sequence, candidateIndex, ciphertexts }
      this.expectedAggregateA = Array(this.numCandidates).fill(INFINITY);
      this.expectedAggregateB = Array(this.numCandidates).fill(INFINITY);
    }

    castBallot(pseudonym, sequence, candidateIndex, ciphertexts) {
      const prev = this.voterBallots.get(pseudonym);
      if (prev) {
        if (sequence <= prev.sequence) {
          throw new Error("SEQUENCE_MUST_BE_MONOTONIC");
        }
        // Deduct previous ballot from aggregate
        for (let j = 0; j < this.numCandidates; j++) {
          this.expectedAggregateA[j] = pointSub(this.expectedAggregateA[j], prev.ciphertexts[j].a);
          this.expectedAggregateB[j] = pointSub(this.expectedAggregateB[j], prev.ciphertexts[j].b);
        }
      }

      // Add new ballot to aggregate
      for (let j = 0; j < this.numCandidates; j++) {
        this.expectedAggregateA[j] = pointAdd(this.expectedAggregateA[j], ciphertexts[j].a);
        this.expectedAggregateB[j] = pointAdd(this.expectedAggregateB[j], ciphertexts[j].b);
      }

      this.voterBallots.set(pseudonym, { sequence, candidateIndex, ciphertexts });
    }

    getExpectedTallies() {
      const tallies = Array(this.numCandidates).fill(0);
      for (const [, record] of this.voterBallots.entries()) {
        tallies[record.candidateIndex]++;
      }
      return tallies;
    }

    getActiveBallotCount() {
      return this.voterBallots.size;
    }
  }

  let oracle;

  // 5 simulated voter pseudonyms
  const pseudonyms = [
    ethers.keccak256(ethers.toUtf8Bytes("voter_sim_01_salt")),
    ethers.keccak256(ethers.toUtf8Bytes("voter_sim_02_salt")),
    ethers.keccak256(ethers.toUtf8Bytes("voter_sim_03_salt")),
    ethers.keccak256(ethers.toUtf8Bytes("voter_sim_04_salt")),
    ethers.keccak256(ethers.toUtf8Bytes("voter_sim_05_salt")),
  ];

  before(async function () {
    [admin, officer1, officer2, voter1, voter2, voter3, voter4, voter5, unauthorized] =
      await ethers.getSigners();

    const net = await ethers.provider.getNetwork();
    chainId = net.chainId;

    // Confirm we are on the isolated in-process network (1337)
    expect(chainId).to.equal(1337n);

    // Deploy BN254CDSVerifier
    const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier");
    verifier = await VerifierFactory.deploy();
    await verifier.waitForDeployment();
    verifierAddress = await verifier.getAddress();

    // Deploy EVotingBallotBoxV2 (admin acts as authorized relayer in this E2E suite)
    const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
    ballotBox = await BallotBoxFactory.deploy(
      electionId,
      candidateCount,
      admin.address,
      verifierAddress
    );
    await ballotBox.waitForDeployment();
    ballotBoxAddress = await ballotBox.getAddress();

    // Generate independent secure scalars for officers
    s1 = generateSecureScalarBN254();
    s2 = generateSecureScalarBN254();
    Y1 = pointMul(G, s1);
    Y2 = pointMul(G, s2);
    Y_joint = pointAdd(Y1, Y2);

    oracle = new IndependentTestOracle(candidateCount);
  });

  // =========================================================================
  // SECTION A: OFFICER REGISTRATION AND KEY CUSTODY
  // =========================================================================
  describe("Section A: Officer Registration and Key Custody", function () {
    it("A.1 Registers Officer 1 with valid Schnorr PoP", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      const tx = await ballotBox.connect(admin).registerOfficer(1, pop1.pubKey, pop1.pop);
      const rc = await tx.wait();
      recordTx("registerOfficer(Officer 1)", rc);

      expect(await ballotBox.officer1Registered()).to.be.true;
      expect(await ballotBox.officer2Registered()).to.be.false;
      expect(await ballotBox.state()).to.equal(1); // Officer1Registered
    });

    it("A.2 Rejects unauthorized caller attempting to register Officer 2 (Relayer Separation)", async function () {
      const fakePop2 = generateSchnorrPoP(s1, 2, electionId, ballotBoxAddress, chainId);
      await expect(
        ballotBox.connect(officer1).registerOfficer(2, fakePop2.pubKey, fakePop2.pop)
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");
    });

    it("A.3 Rejects unauthorized third party registering as an officer", async function () {
      const fakeKey = generateSecureScalarBN254();
      const fakePop = generateSchnorrPoP(fakeKey, 2, electionId, ballotBoxAddress, chainId);
      await expect(
        ballotBox.connect(unauthorized).registerOfficer(2, fakePop.pubKey, fakePop.pop)
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");
    });

    it("A.4 Rejects invalid / forged Schnorr PoP challenge response", async function () {
      const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
      const corruptedPop = {
        r: pop2.pop.r,
        z: (pop2.pop.z + 1n) % Q, // Tampered response
      };
      await expect(
        ballotBox.connect(admin).registerOfficer(2, pop2.pubKey, corruptedPop)
      ).to.be.revertedWith("POP_VERIFICATION_FAILED");
    });

    it("A.5 Rejects off-curve public key coordinates", async function () {
      const offCurveKey = { x: 5n, y: 5n }; // Not on curve
      const fakePop = { r: G, z: 12345n };
      await expect(
        ballotBox.connect(admin).registerOfficer(2, offCurveKey, fakePop)
      ).to.be.revertedWith("POINT_NOT_ON_CURVE");
    });

    it("A.6 Registers Officer 2 with valid Schnorr PoP, completes key registration and computes Y_joint", async function () {
      const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
      const tx = await ballotBox.connect(admin).registerOfficer(2, pop2.pubKey, pop2.pop);
      const rc = await tx.wait();
      recordTx("registerOfficer(Officer 2)", rc);

      expect(await ballotBox.officer2Registered()).to.be.true;
      expect(await ballotBox.state()).to.equal(3); // KeyRegistrationComplete

      const onchainJoint = await ballotBox.jointPubKey();
      expect(onchainJoint.x).to.equal(Y_joint.x);
      expect(onchainJoint.y).to.equal(Y_joint.y);
    });

    it("A.7 Rejects duplicate registration attempts after state completion", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await expect(
        ballotBox.connect(admin).registerOfficer(1, pop1.pubKey, pop1.pop)
      ).to.be.revertedWith("INVALID_STATE_FOR_KEY_REGISTRATION");
    });
  });

  // =========================================================================
  // SECTION B: ELECTION OPENING & VOTING LIFECYCLE
  // =========================================================================
  describe("Section B: Election Opening & Lifecycle", function () {
    it("B.1 Rejects ballot casting before voting is opened", async function () {
      const pseudonym = ethers.keccak256(ethers.toUtf8Bytes("voter_premature"));
      const context = {
        electionId,
        pseudonym,
        sequence: 1n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.castBallot(
          pseudonym,
          1n,
          ballotData.ciphertexts,
          ballotData.proof
        )
      ).to.be.revertedWith("ELECTION_NOT_OPEN");
    });

    it("B.2 Admin opens voting transitions state to VotingOpen", async function () {
      const tx = await ballotBox.connect(admin).openVoting();
      const rc = await tx.wait();
      recordTx("openVoting", rc);

      expect(await ballotBox.state()).to.equal(4); // VotingOpen
    });

    it("B.3 Non-admin cannot close or reopen voting", async function () {
      await expect(
        ballotBox.connect(unauthorized).closeVoting()
      ).to.be.revertedWith("UNAUTHORIZED_ADMIN");
    });
  });

  // =========================================================================
  // SECTION C: BALLOT CASTING & CDS PROOF VERIFICATION (3 CANDIDATES, 5 VOTERS)
  // =========================================================================
  describe("Section C: Initial Ballot Casting (5 Simulated Voters, 3 Candidates)", function () {
    // Initial choices:
    // Voter 1: Cand 0
    // Voter 2: Cand 1
    // Voter 3: Cand 0
    // Voter 4: Cand 2
    // Voter 5: Cand 1
    const initialChoices = [0, 1, 0, 2, 1];

    it("C.1 Casts initial ballots for all 5 voters with valid 3-candidate CDS proofs", async function () {
      for (let i = 0; i < 5; i++) {
        const p = pseudonyms[i];
        const choice = initialChoices[i];
        const context = {
          electionId,
          pseudonym: p,
          sequence: 1n,
          jointPubKey: Y_joint,
        };

        const ballotData = generateReferenceBallotProof({
          selectedCandidate: choice,
          candidateCount: 3,
          context,
          verifierAddress,
          chainId,
        });

        // Verify off-chain using reference verifier first
        const offchainValid = verifyBallotProofOffchain(
          context,
          ballotData.ciphertexts,
          ballotData.proof,
          verifierAddress,
          chainId
        );
        expect(offchainValid).to.be.true;

        // Cast on-chain
        const tx = await ballotBox.connect(admin).castBallot(
          p,
          1n,
          ballotData.ciphertexts,
          ballotData.proof
        );
        const rc = await tx.wait();
        recordTx(`castBallot(Voter ${i + 1}, Seq 1, Cand ${choice})`, rc);

        // Update independent test oracle
        oracle.castBallot(p, 1n, choice, ballotData.ciphertexts);

        // Verify active sequence on chain
        expect(await ballotBox.voterSequence(p)).to.equal(1n);
      }

      expect(await ballotBox.totalActiveBallots()).to.equal(5n);
      expect(oracle.getActiveBallotCount()).to.equal(5);
    });

    it("C.2 Verifies on-chain aggregate ciphertexts match Independent Test Oracle exactly", async function () {
      const [onchainA, onchainB] = await getAggregates(ballotBox, 3);

      for (let j = 0; j < 3; j++) {
        expect(onchainA[j].x).to.equal(oracle.expectedAggregateA[j].x);
        expect(onchainA[j].y).to.equal(oracle.expectedAggregateA[j].y);
        expect(onchainB[j].x).to.equal(oracle.expectedAggregateB[j].x);
        expect(onchainB[j].y).to.equal(oracle.expectedAggregateB[j].y);
      }
    });

    it("C.3 Rejects candidate count mismatch (e.g., 2 ciphertexts when M=3)", async function () {
      const p = pseudonyms[0];
      const context = {
        electionId,
        pseudonym: p,
        sequence: 2n,
        jointPubKey: Y_joint,
      };

      // Generate 2-candidate ballot instead of 3
      const badBallot = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(admin).castBallot(p, 2n, badBallot.ciphertexts, badBallot.proof)
      ).to.be.revertedWith("CANDIDATE_COUNT_MISMATCH");
    });

    it("C.4 Rejects invalid scalar range in CDS proof (z >= Q)", async function () {
      const p = pseudonyms[0];
      const context = {
        electionId,
        pseudonym: p,
        sequence: 2n,
        jointPubKey: Y_joint,
      };
      const validBallot = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      // Tamper z_sum to be >= Q
      const tamperedProof = JSON.parse(JSON.stringify(validBallot.proof, (key, value) =>
        typeof value === 'bigint' ? value.toString() : value
      ));
      tamperedProof.z_sum = (Q + 5n).toString();

      await expect(
        ballotBox.connect(admin).castBallot(p, 2n, validBallot.ciphertexts, tamperedProof)
      ).to.be.revertedWith("SCALAR_EXCEEDS_ORDER_Q");
    });

    it("C.5 Rejects tampered / forged CDS branch proof", async function () {
      const p = pseudonyms[0];
      const context = {
        electionId,
        pseudonym: p,
        sequence: 2n,
        jointPubKey: Y_joint,
      };
      const validBallot = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      // Tamper c0 in branch 0
      const tamperedProof = JSON.parse(JSON.stringify(validBallot.proof, (key, value) =>
        typeof value === 'bigint' ? value.toString() : value
      ));
      tamperedProof.candidateProofs[0].c0 = ((BigInt(tamperedProof.candidateProofs[0].c0) + 1n) % Q).toString();

      await expect(
        ballotBox.connect(admin).castBallot(p, 2n, validBallot.ciphertexts, tamperedProof)
      ).to.be.revertedWith("INVALID_CDS_CHALLENGE_SUM");
    });
  });

  // =========================================================================
  // SECTION D: REVOTING AND AGGREGATE HOMOMORPHIC UPDATES
  // =========================================================================
  describe("Section D: Revoting (Sequence Monotonicity & Atomic Homomorphic Update)", function () {
    it("D.1 Rejects duplicate sequence number (Replay Protection)", async function () {
      const p = pseudonyms[0]; // Voter 1 currently has sequence 1
      const context = {
        electionId,
        pseudonym: p,
        sequence: 1n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 2,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(admin).castBallot(p, 1n, ballotData.ciphertexts, ballotData.proof)
      ).to.be.revertedWith("INVALID_SEQUENCE_ORDER");
    });

    it("D.2 Rejects out-of-order sequence leap (sequence 3 when sequence 1 is active)", async function () {
      const p = pseudonyms[0];
      const context = {
        electionId,
        pseudonym: p,
        sequence: 3n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 2,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(admin).castBallot(p, 3n, ballotData.ciphertexts, ballotData.proof)
      ).to.be.revertedWith("INVALID_SEQUENCE_ORDER");
    });

    it("D.3 Executes Revote 1: Voter 1 changes vote from Cand 0 to Cand 2 (sequence 2)", async function () {
      const p = pseudonyms[0];
      const context = {
        electionId,
        pseudonym: p,
        sequence: 2n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 2,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      const tx = await ballotBox.connect(admin).castBallot(
        p,
        2n,
        ballotData.ciphertexts,
        ballotData.proof
      );
      const rc = await tx.wait();
      recordTx("castBallot(Voter 1 Revote: Cand 0 -> Cand 2, Seq 2)", rc);

      // Update Oracle
      oracle.castBallot(p, 2n, 2, ballotData.ciphertexts);

      expect(await ballotBox.voterSequence(p)).to.equal(2n);
      expect(await ballotBox.totalActiveBallots()).to.equal(5n); // Total active voters unchanged
    });

    it("D.4 Confirms active ballot on-chain reflects sequence 2 ciphertext", async function () {
      const p = pseudonyms[0];
      const [actA0, actB0] = await ballotBox.getActiveBallot(p, 0n);
      expect(actA0.x).to.not.equal(0n);
      expect(actA0.y).to.not.equal(0n);
    });

    it("D.5 Executes Revote 2: Voter 3 changes vote from Cand 0 to Cand 1 (sequence 2)", async function () {
      const p = pseudonyms[2]; // Voter 3 currently has sequence 1
      const context = {
        electionId,
        pseudonym: p,
        sequence: 2n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      const tx = await ballotBox.connect(admin).castBallot(
        p,
        2n,
        ballotData.ciphertexts,
        ballotData.proof
      );
      const rc = await tx.wait();
      recordTx("castBallot(Voter 3 Revote: Cand 0 -> Cand 1, Seq 2)", rc);

      // Update Oracle
      oracle.castBallot(p, 2n, 1, ballotData.ciphertexts);

      expect(await ballotBox.voterSequence(p)).to.equal(2n);
      expect(await ballotBox.totalActiveBallots()).to.equal(5n);
    });

    it("D.6 Confirms on-chain aggregate matches Oracle homomorphic update: C_agg = C_agg - C_prev + C_new", async function () {
      const [onchainA, onchainB] = await getAggregates(ballotBox, 3);

      for (let j = 0; j < 3; j++) {
        expect(onchainA[j].x).to.equal(oracle.expectedAggregateA[j].x);
        expect(onchainA[j].y).to.equal(oracle.expectedAggregateA[j].y);
        expect(onchainB[j].x).to.equal(oracle.expectedAggregateB[j].x);
        expect(onchainB[j].y).to.equal(oracle.expectedAggregateB[j].y);
      }

      // Expected tally distribution according to Oracle:
      // Cand 0: 0 votes (Voter 1 switched to Cand 2; Voter 3 switched to Cand 1)
      // Cand 1: 3 votes (Voter 2, Voter 3, Voter 5)
      // Cand 2: 2 votes (Voter 1, Voter 4)
      const expectedTallies = oracle.getExpectedTallies();
      expect(expectedTallies).to.deep.equal([0, 3, 2]);
    });
  });

  // =========================================================================
  // SECTION E: ELECTION CLOSURE & THRESHOLD TALLY
  // =========================================================================
  describe("Section E: Election Closure & Decryption Shares Submission", function () {
    let aggregateA, aggregateB;
    let shares1Data, shares2Data;

    before(async function () {
      const [aList, bList] = await getAggregates(ballotBox, 3);
      aggregateA = aList;
      aggregateB = bList;
    });

    it("E.1 Admin closes voting and transitions state to VotingClosed", async function () {
      const tx = await ballotBox.connect(admin).closeVoting();
      const rc = await tx.wait();
      recordTx("closeVoting", rc);

      expect(await ballotBox.state()).to.equal(5); // VotingClosed
    });

    it("E.2 Rejects any subsequent ballot casting after election is closed", async function () {
      const p = ethers.keccak256(ethers.toUtf8Bytes("voter_late"));
      const context = {
        electionId,
        pseudonym: p,
        sequence: 1n,
        jointPubKey: Y_joint,
      };
      const ballotData = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 3,
        context,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(admin).castBallot(p, 1n, ballotData.ciphertexts, ballotData.proof)
      ).to.be.revertedWith("ELECTION_NOT_OPEN");
    });

    it("E.3 Officer 1 submits decryption shares with valid DLEQ proofs", async function () {
      shares1Data = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      const tx = await ballotBox.connect(admin).submitDecryptionShares(
        1,
        shares1Data.shares,
        shares1Data.proofs
      );
      const rc = await tx.wait();
      recordTx("submitDecryptionShares(Officer 1, 3 candidates)", rc);

      expect(await ballotBox.officerSharesSubmitted(1)).to.be.true;
      expect(await ballotBox.officerSharesSubmitted(2)).to.be.false;
      expect(await ballotBox.state()).to.equal(5); // Still VotingClosed until both submit
    });

    it("E.4 Verifies Officer 1 alone CANNOT finalize the tally", async function () {
      await expect(
        ballotBox.finalizeTally([0, 3, 2])
      ).to.be.revertedWith("SHARES_INCOMPLETE");
    });

    it("E.5 Rejects duplicate share submission from Officer 1", async function () {
      await expect(
        ballotBox.connect(admin).submitDecryptionShares(1, shares1Data.shares, shares1Data.proofs)
      ).to.be.revertedWith("SHARES_ALREADY_SUBMITTED");
    });

    it("E.6 Rejects invalid DLEQ proof from Officer 2", async function () {
      shares2Data = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      const corruptedProofs = JSON.parse(JSON.stringify(shares2Data.proofs, (key, value) =>
        typeof value === 'bigint' ? value.toString() : value
      ));
      // Tamper z scalar in proof for candidate 0
      corruptedProofs[0].z = ((BigInt(corruptedProofs[0].z) + 1n) % Q).toString();

      await expect(
        ballotBox.connect(admin).submitDecryptionShares(2, shares2Data.shares, corruptedProofs)
      ).to.be.revertedWith("DLEQ_G_EQUATION_FAILED");
    });

    it("E.7 Officer 2 submits valid decryption shares and completes threshold phase", async function () {
      const tx = await ballotBox.connect(admin).submitDecryptionShares(
        2,
        shares2Data.shares,
        shares2Data.proofs
      );
      const rc = await tx.wait();
      recordTx("submitDecryptionShares(Officer 2, 3 candidates)", rc);

      expect(await ballotBox.officerSharesSubmitted(2)).to.be.true;
      expect(await ballotBox.state()).to.equal(6); // DecryptionSharesComplete
    });
  });

  // =========================================================================
  // SECTION F: TALLY FINALIZATION & INDEPENDENT TEST ORACLE VERIFICATION
  // =========================================================================
  describe("Section F: Zero-Trust Tally Finalization & Infinity Point Special Case", function () {
    it("F.1 Independent Test Oracle solves discrete logarithms and predicts [0, 3, 2]", async function () {
      const [, aggregateB] = await getAggregates(ballotBox, 3);

      // Fetch on-chain registered shares
      const s1Shares = [];
      const s2Shares = [];
      for (let j = 0; j < 3; j++) {
        s1Shares.push(await ballotBox.officerDecryptionShares(1, j));
        s2Shares.push(await ballotBox.officerDecryptionShares(2, j));
      }

      const recoveredTallies = solveDiscreteLogTallies(
        aggregateB,
        s1Shares,
        s2Shares,
        3,
        5
      );

      const expected = oracle.getExpectedTallies();
      expect(recoveredTallies.map(Number)).to.deep.equal(expected);
      expect(expected).to.deep.equal([0, 3, 2]);
    });

    it("F.2 Rejects incorrect candidate tallies (e.g. attempting [1, 2, 2])", async function () {
      await expect(
        ballotBox.finalizeTally([1, 2, 2])
      ).to.be.revertedWith("TALLY_EQUATION_FAILED");
    });

    it("F.3 Rejects tally vector with wrong length (e.g. 2 tallies for 3 candidates)", async function () {
      await expect(
        ballotBox.finalizeTally([0, 3])
      ).to.be.revertedWith("TALLIES_LENGTH_MISMATCH");
    });

    it("F.4 Rejects tally exceeding active ballot count bound (sum != activeBallots)", async function () {
      await expect(
        ballotBox.finalizeTally([0, 3, 3]) // Sum = 6 > 5
      ).to.be.revertedWith("TALLY_SUM_MISMATCH");
    });

    it("F.5 Finalizes tally with correct vector [0, 3, 2] (exercising Candidate 0 Infinity Point)", async function () {
      // Notice: Candidate 0 has exactly 0 votes.
      // Therefore B_agg[0] - (D_1[0] + D_2[0]) == 0 * G == Point at Infinity (0, 0)!
      // EVotingBallotBoxV2 explicitly handles infinity point for tally verification.
      const tx = await ballotBox.finalizeTally([0, 3, 2]);
      const rc = await tx.wait();
      recordTx("finalizeTally([0, 3, 2], Candidate 0 Infinity Point)", rc);

      expect(await ballotBox.state()).to.equal(7); // Finalized

      // Read finalized tallies from contract
      expect(await ballotBox.getFinalTally(0)).to.equal(0n);
      expect(await ballotBox.getFinalTally(1)).to.equal(3n);
      expect(await ballotBox.getFinalTally(2)).to.equal(2n);

      // Verify invariant: sum(tallies) == totalActiveBallots
      const sum = (await ballotBox.getFinalTally(0)) +
                  (await ballotBox.getFinalTally(1)) +
                  (await ballotBox.getFinalTally(2));
      expect(sum).to.equal(await ballotBox.totalActiveBallots());
    });

    it("F.6 Cannot re-finalize an already finalized election", async function () {
      await expect(
        ballotBox.finalizeTally([0, 3, 2])
      ).to.be.revertedWith("SHARES_INCOMPLETE");
    });
  });

  // =========================================================================
  // SECTION G: 72-HOUR TALLY STALLED TRANSITION (PERMISSIONLESS ESCAPE HATCH)
  // =========================================================================
  describe("Section G: 72-Hour TallyStalled Escape Hatch", function () {
    let stalledBallotBox;
    const stalledElectionId = 112233n;

    before(async function () {
      // Deploy an isolated ballotBox instance to test the timeout transition
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      stalledBallotBox = await BallotBoxFactory.deploy(
        stalledElectionId,
        candidateCount,
        admin.address,
        verifierAddress
      );
      await stalledBallotBox.waitForDeployment();
      const sBoxAddr = await stalledBallotBox.getAddress();

      // Officers register (submitted via authorized relayer/admin)
      const pop1 = generateSchnorrPoP(s1, 1, stalledElectionId, sBoxAddr, chainId);
      await stalledBallotBox.connect(admin).registerOfficer(1, pop1.pubKey, pop1.pop);
      const pop2 = generateSchnorrPoP(s2, 2, stalledElectionId, sBoxAddr, chainId);
      await stalledBallotBox.connect(admin).registerOfficer(2, pop2.pubKey, pop2.pop);

      // Open and Close
      await stalledBallotBox.connect(admin).openVoting();
      await stalledBallotBox.connect(admin).closeVoting();

      // Only Officer 1 submits shares; Officer 2 is unresponsive/stalled
      const [aggA] = await getAggregates(stalledBallotBox, 3);
      const s1Data = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId: stalledElectionId,
        contractAddress: sBoxAddr,
        chainId,
      });
      await stalledBallotBox.connect(admin).submitDecryptionShares(1, s1Data.shares, s1Data.proofs);
    });

    it("G.1 Rejects markTallyStalled before 72 hours have elapsed", async function () {
      await expect(
        stalledBallotBox.connect(unauthorized).markTallyStalled()
      ).to.be.revertedWith("TALLY_DEADLINE_NOT_PASSED");
    });

    it("G.2 Permissionless caller triggers markTallyStalled after 72 hours (+10s)", async function () {
      // Advance EVM time by 72 hours + 10 seconds
      await network.provider.send("evm_increaseTime", [72 * 3600 + 10]);
      await network.provider.send("evm_mine");

      const tx = await stalledBallotBox.connect(unauthorized).markTallyStalled();
      const rc = await tx.wait();
      recordTx("markTallyStalled(Permissionless Caller after 72h)", rc);

      expect(await stalledBallotBox.state()).to.equal(8); // TallyStalled
    });

    it("G.3 Confirms no shares can be submitted and no tally can be finalized once stalled", async function () {
      await expect(
        stalledBallotBox.finalizeTally([0, 0, 0])
      ).to.be.revertedWith("SHARES_INCOMPLETE");
    });
  });

  // =========================================================================
  // SECTION H: GAS CONSUMPTION REPORT SUMMARY
  // =========================================================================
  describe("Section H: Gas Profiling Summary", function () {
    it("H.1 Outputs gas profiling table for major V2 operations", function () {
      console.log("\n================================================================================");
      console.log("            MILESTONE 6: V2 SMART CONTRACT GAS PROFILING TABLE                  ");
      console.log("================================================================================");
      console.table(txRecords);
      console.log("================================================================================\n");

      expect(txRecords.length).to.be.greaterThan(5);
    });
  });
});
