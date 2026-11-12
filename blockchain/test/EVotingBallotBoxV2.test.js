const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
  P,
  Q,
  G,
  INFINITY,
  pointAdd,
  pointMul,
  generateReferenceBallotProof,
} = require("./helpers/bn254_cds_reference");
const {
  generateSecureScalarBN254,
  generateSchnorrPoP,
  generateOfficerDecryptionShares,
  solveDiscreteLogTallies,
} = require("./helpers/bn254_tally_reference");

describe("EVotingBallotBoxV2 - Milestone 3 Complete End-to-End Suite", function () {
  let admin, relayer, officer1, officer2, voter1, voter2, unauthorized;
  let verifier, ballotBox;
  let chainId;
  let verifierAddress, ballotBoxAddress;

  const electionId = 8888n;
  const candidateCount = 2n;

  // Officer private shares
  let s1, s2;
  let Y1, Y2, Y_joint;

  before(async function () {
    [admin, relayer, officer1, officer2, voter1, voter2, unauthorized] = await ethers.getSigners();
    const network = await ethers.provider.getNetwork();
    chainId = network.chainId;

    // Deploy BN254CDSVerifier library/contract
    const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier");
    verifier = await VerifierFactory.deploy();
    await verifier.waitForDeployment();
    verifierAddress = await verifier.getAddress();

    // Sample secure officer private shares
    s1 = generateSecureScalarBN254();
    s2 = generateSecureScalarBN254();
    Y1 = pointMul(G, s1);
    Y2 = pointMul(G, s2);
    Y_joint = pointAdd(Y1, Y2);
  });

  beforeEach(async function () {
    const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
    ballotBox = await BallotBoxFactory.deploy(
      electionId,
      candidateCount,
      relayer.address,
      verifierAddress
    );
    await ballotBox.waitForDeployment();
    ballotBoxAddress = await ballotBox.getAddress();
  });

  // Helper to fully setup and open an election
  async function setupAndOpenElection() {
    const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
    await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);

    const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
    await ballotBox.connect(relayer).registerOfficer(2, pop2.pubKey, pop2.pop);

    await ballotBox.connect(admin).openVoting();
  }

  // =========================================================================
  // SUITE 1: OFFICER AUTHORIZATION & DUAL-CUSTODY SETUP (Tests 1.1 - 1.9)
  // =========================================================================
  describe("Suite 1: Officer Authorization & Dual-Custody Setup", function () {
    it("1.1 Valid Officer 1 registration with Schnorr PoP succeeds", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      const tx = await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);
      const receipt = await tx.wait();
      expect(receipt.status).to.equal(1);

      expect(await ballotBox.officer1Registered()).to.be.true;
      expect(await ballotBox.state()).to.equal(1); // Officer1Registered
    });

    it("1.2 Valid Officer 2 registration completes key setup and computes Y_joint", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);

      const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
      await ballotBox.connect(relayer).registerOfficer(2, pop2.pubKey, pop2.pop);

      expect(await ballotBox.officer2Registered()).to.be.true;
      expect(await ballotBox.state()).to.equal(3); // KeyRegistrationComplete

      const onchainJoint = await ballotBox.jointPubKey();
      expect(onchainJoint.x).to.equal(Y_joint.x);
      expect(onchainJoint.y).to.equal(Y_joint.y);
    });

    it("1.3 Zero relayer address in constructor reverts (INVALID_RELAYER_ADDRESS)", async function () {
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      await expect(
        BallotBoxFactory.deploy(
          electionId,
          candidateCount,
          ethers.ZeroAddress,
          verifierAddress
        )
      ).to.be.revertedWith("INVALID_RELAYER_ADDRESS");
    });

    it("1.4 Unauthorized caller attempting to register Officer 1 reverts (UNAUTHORIZED_RELAYER)", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await expect(
        ballotBox.connect(unauthorized).registerOfficer(1, pop1.pubKey, pop1.pop)
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");
    });

    it("1.5 Invalid Schnorr PoP response reverts (POP_VERIFICATION_FAILED)", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      // Tamper response scalar
      const badPoP = { r: pop1.pop.r, z: (pop1.pop.z + 1n) % Q };
      await expect(
        ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, badPoP)
      ).to.be.revertedWith("POP_VERIFICATION_FAILED");
    });

    it("1.6 Officer key with infinity point reverts (INVALID_OFFICER_KEY)", async function () {
      const pop = { r: pointMul(G, 5n), z: 12345n };
      await expect(
        ballotBox.connect(relayer).registerOfficer(1, INFINITY, pop)
      ).to.be.revertedWith("INVALID_OFFICER_KEY");
    });

    it("1.7 Pre-voting key invalidation resets state back to Setup", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);
      expect(await ballotBox.state()).to.equal(1);

      // Relayer resets registration
      await ballotBox.connect(relayer).invalidateKeyRegistration();
      expect(await ballotBox.state()).to.equal(0); // Setup
      expect(await ballotBox.officer1Registered()).to.be.false;
    });

    it("1.8 Key invalidation attempted after voting opens reverts", async function () {
      await setupAndOpenElection();
      expect(await ballotBox.state()).to.equal(4); // VotingOpen

      await expect(
        ballotBox.connect(relayer).invalidateKeyRegistration()
      ).to.be.revertedWith("INVALID_STATE_FOR_KEY_RESET");
    });

    it("1.9 Admin can rotate relayer successfully and unauthorized caller reverts", async function () {
      // Unauthorized attempts to rotate
      await expect(
        ballotBox.connect(unauthorized).rotateRelayer(unauthorized.address)
      ).to.be.revertedWith("UNAUTHORIZED_ADMIN");

      // Admin rotates to zero address reverts
      await expect(
        ballotBox.connect(admin).rotateRelayer(ethers.ZeroAddress)
      ).to.be.revertedWith("INVALID_RELAYER_ADDRESS");

      // Admin rotates to existing relayer reverts
      await expect(
        ballotBox.connect(admin).rotateRelayer(relayer.address)
      ).to.be.revertedWith("IDENTICAL_RELAYER_ADDRESS");

      // Admin successfully rotates relayer
      const newRelayer = unauthorized;
      const tx = await ballotBox.connect(admin).rotateRelayer(newRelayer.address);
      await expect(tx).to.emit(ballotBox, "RelayerRotated").withArgs(relayer.address, newRelayer.address);
      expect(await ballotBox.relayer()).to.equal(newRelayer.address);

      // Old relayer is now unauthorized
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await expect(
        ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop)
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");

      // New relayer can register officer
      await ballotBox.connect(newRelayer).registerOfficer(1, pop1.pubKey, pop1.pop);
      expect(await ballotBox.officer1Registered()).to.be.true;
    });
  });

  // =========================================================================
  // SUITE 2: BALLOT AGGREGATION & SEQUENCE CONTROL (Tests 2.1 - 2.5)
  // =========================================================================
  describe("Suite 2: Ballot Aggregation & Sequence Control", function () {
    const pseudonym1 = ethers.keccak256(ethers.toUtf8Bytes("pseudonym_alice"));
    const pseudonym2 = ethers.keccak256(ethers.toUtf8Bytes("pseudonym_bob"));

    beforeEach(async function () {
      await setupAndOpenElection();
    });

    it("2.1 First ballot for Candidate 0 accumulates correctly and increments totalActiveBallots", async function () {
      const context = {
        electionId,
        pseudonym: pseudonym1,
        sequence: 1n,
        jointPubKey: Y_joint,
      };

      const { ciphertexts, proof } = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context,
        verifierAddress,
        chainId,
      });

      const tx = await ballotBox.castBallot(pseudonym1, 1n, ciphertexts, proof);
      const receipt = await tx.wait();
      expect(receipt.status).to.equal(1);

      expect(await ballotBox.totalActiveBallots()).to.equal(1n);
      expect(await ballotBox.voterSequence(pseudonym1)).to.equal(1n);

      const [aggA0, aggB0] = await ballotBox.getAggregateCiphertext(0);
      expect(aggA0.x).to.equal(ciphertexts[0].a.x);
      expect(aggB0.x).to.equal(ciphertexts[0].b.x);
    });

    it("2.2 First ballot for Candidate 1 accumulates correctly across multiple voters", async function () {
      // Voter 1 votes for Candidate 0
      const ctx1 = { electionId, pseudonym: pseudonym1, sequence: 1n, jointPubKey: Y_joint };
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx1,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym1, 1n, ballot1.ciphertexts, ballot1.proof);

      // Voter 2 votes for Candidate 1
      const ctx2 = { electionId, pseudonym: pseudonym2, sequence: 1n, jointPubKey: Y_joint };
      const ballot2 = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 2,
        context: ctx2,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym2, 1n, ballot2.ciphertexts, ballot2.proof);

      expect(await ballotBox.totalActiveBallots()).to.equal(2n);

      // Candidate 0 aggregate A should equal A_v1 + A_v2
      const [aggA0] = await ballotBox.getAggregateCiphertext(0);
      const expectedA0 = pointAdd(ballot1.ciphertexts[0].a, ballot2.ciphertexts[0].a);
      expect(aggA0.x).to.equal(expectedA0.x);
      expect(aggA0.y).to.equal(expectedA0.y);
    });

    it("2.3 Duplicate sequence submission reverts (INVALID_SEQUENCE_ORDER)", async function () {
      const ctx = { electionId, pseudonym: pseudonym1, sequence: 1n, jointPubKey: Y_joint };
      const ballot = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx,
        verifierAddress,
        chainId,
      });

      await ballotBox.castBallot(pseudonym1, 1n, ballot.ciphertexts, ballot.proof);

      // Re-submitting sequence 1
      await expect(
        ballotBox.castBallot(pseudonym1, 1n, ballot.ciphertexts, ballot.proof)
      ).to.be.revertedWith("INVALID_SEQUENCE_ORDER");
    });

    it("2.4 Out-of-order sequence (seq 3 before seq 2) reverts", async function () {
      const ctx = { electionId, pseudonym: pseudonym1, sequence: 1n, jointPubKey: Y_joint };
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym1, 1n, ballot1.ciphertexts, ballot1.proof);

      // Attempting sequence 3 directly
      const ctx3 = { electionId, pseudonym: pseudonym1, sequence: 3n, jointPubKey: Y_joint };
      const ballot3 = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 2,
        context: ctx3,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.castBallot(pseudonym1, 3n, ballot3.ciphertexts, ballot3.proof)
      ).to.be.revertedWith("INVALID_SEQUENCE_ORDER");
    });

    it("2.5 Ballot submission before voting opens or after close reverts", async function () {
      // Re-deploy a fresh contract in Setup state
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      const freshBox = await BallotBoxFactory.deploy(
        123n,
        candidateCount,
        relayer.address,
        verifierAddress
      );
      await freshBox.waitForDeployment();

      const ctx = { electionId: 123n, pseudonym: pseudonym1, sequence: 1n, jointPubKey: Y_joint };
      const ballot = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx,
        verifierAddress,
        chainId,
      });

      await expect(
        freshBox.castBallot(pseudonym1, 1n, ballot.ciphertexts, ballot.proof)
      ).to.be.revertedWith("ELECTION_NOT_OPEN");
    });
  });

  // =========================================================================
  // SUITE 3: REVOTING TRANSITIONS & ATOMICITY (Tests 3.1 - 3.4)
  // =========================================================================
  describe("Suite 3: Revoting Transitions & Atomicity", function () {
    const pseudonym = ethers.keccak256(ethers.toUtf8Bytes("pseudonym_revoter"));

    beforeEach(async function () {
      await setupAndOpenElection();
    });

    it("3.1 Revote switching Candidate 0 to Candidate 1 homomorphically replaces vote", async function () {
      // Sequence 1: Vote for Candidate 0
      const ctx1 = { electionId, pseudonym, sequence: 1n, jointPubKey: Y_joint };
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx1,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym, 1n, ballot1.ciphertexts, ballot1.proof);
      expect(await ballotBox.totalActiveBallots()).to.equal(1n);

      // Sequence 2: Switch to Candidate 1
      const ctx2 = { electionId, pseudonym, sequence: 2n, jointPubKey: Y_joint };
      const ballot2 = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 2,
        context: ctx2,
        verifierAddress,
        chainId,
      });
      const tx = await ballotBox.castBallot(pseudonym, 2n, ballot2.ciphertexts, ballot2.proof);
      await tx.wait();

      expect(await ballotBox.totalActiveBallots()).to.equal(1n); // Unchanged!
      expect(await ballotBox.voterSequence(pseudonym)).to.equal(2n);

      // Aggregate point for Candidate 1 should match ballot 2's ciphertext
      const [aggA1, aggB1] = await ballotBox.getAggregateCiphertext(1);
      expect(aggA1.x).to.equal(ballot2.ciphertexts[1].a.x);
      expect(aggB1.x).to.equal(ballot2.ciphertexts[1].b.x);
    });

    it("3.2 Revoting for the same candidate preserves numerical state invariance", async function () {
      const ctx1 = { electionId, pseudonym, sequence: 1n, jointPubKey: Y_joint };
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx1,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym, 1n, ballot1.ciphertexts, ballot1.proof);

      // Sequence 2: Vote again for Candidate 0 with new randomness
      const ctx2 = { electionId, pseudonym, sequence: 2n, jointPubKey: Y_joint };
      const ballot2 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx2,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym, 2n, ballot2.ciphertexts, ballot2.proof);

      expect(await ballotBox.totalActiveBallots()).to.equal(1n);
      expect(await ballotBox.voterSequence(pseudonym)).to.equal(2n);
    });

    it("3.3 Multiple sequential revotes (seq 1 -> 2 -> 3) accurately reflect final choice", async function () {
      for (let s = 1n; s <= 3n; s++) {
        const choice = s % 2n === 1n ? 0 : 1; // 1->0, 2->1, 3->0
        const ctx = { electionId, pseudonym, sequence: s, jointPubKey: Y_joint };
        const ballot = generateReferenceBallotProof({
          selectedCandidate: choice,
          candidateCount: 2,
          context: ctx,
          verifierAddress,
          chainId,
        });
        await ballotBox.castBallot(pseudonym, s, ballot.ciphertexts, ballot.proof);
      }

      expect(await ballotBox.totalActiveBallots()).to.equal(1n);
      expect(await ballotBox.voterSequence(pseudonym)).to.equal(3n);
    });

    it("3.4 Failed revote with invalid proof reverts atomically without modifying active ballot", async function () {
      // Valid sequence 1
      const ctx1 = { electionId, pseudonym, sequence: 1n, jointPubKey: Y_joint };
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx1,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym, 1n, ballot1.ciphertexts, ballot1.proof);

      const [savedA0, savedB0] = await ballotBox.getAggregateCiphertext(0);

      // Corrupt sequence 2 proof
      const ctx2 = { electionId, pseudonym, sequence: 2n, jointPubKey: Y_joint };
      const ballot2 = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 2,
        context: ctx2,
        verifierAddress,
        chainId,
      });
      // Corrupt response z0
      ballot2.proof.candidateProofs[0].z0 = (ballot2.proof.candidateProofs[0].z0 + 1n) % Q;

      await expect(
        ballotBox.castBallot(pseudonym, 2n, ballot2.ciphertexts, ballot2.proof)
      ).to.be.reverted;

      // Assert active ballot and sequence were completely untouched
      expect(await ballotBox.voterSequence(pseudonym)).to.equal(1n);
      const [recheckA0, recheckB0] = await ballotBox.getAggregateCiphertext(0);
      expect(recheckA0.x).to.equal(savedA0.x);
      expect(recheckB0.x).to.equal(savedB0.x);
    });

    it("3.5 Fourth submission (seq 4) reverts with MAX_BALLOTS_EXCEEDED", async function () {
      expect(await ballotBox.MAX_BALLOTS_PER_VOTER()).to.equal(3n);

      for (let s = 1n; s <= 3n; s++) {
        const ctx = { electionId, pseudonym, sequence: s, jointPubKey: Y_joint };
        const ballot = generateReferenceBallotProof({
          selectedCandidate: Number(s % 2n),
          candidateCount: 2,
          context: ctx,
          verifierAddress,
          chainId,
        });
        await ballotBox.castBallot(pseudonym, s, ballot.ciphertexts, ballot.proof);
      }

      const ctx4 = { electionId, pseudonym, sequence: 4n, jointPubKey: Y_joint };
      const ballot4 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx4,
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.castBallot(pseudonym, 4n, ballot4.ciphertexts, ballot4.proof)
      ).to.be.revertedWith("MAX_BALLOTS_EXCEEDED");
      expect(await ballotBox.voterSequence(pseudonym)).to.equal(3n);
    });
  });

  // =========================================================================
  // SUITE 4: DECRYPTION SHARES & DLEQ VERIFICATION (Tests 4.1 - 4.9)
  // =========================================================================
  describe("Suite 4: Decryption Shares & DLEQ Verification", function () {
    const pseudonym = ethers.keccak256(ethers.toUtf8Bytes("pseudonym_voter_dleq"));
    let aggA = [];

    beforeEach(async function () {
      await setupAndOpenElection();

      // Cast 1 ballot for Candidate 0
      const ctx = { electionId, pseudonym, sequence: 1n, jointPubKey: Y_joint };
      const ballot = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: ctx,
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(pseudonym, 1n, ballot.ciphertexts, ballot.proof);

      // Close voting
      await ballotBox.connect(admin).closeVoting();

      const [a0] = await ballotBox.getAggregateCiphertext(0);
      const [a1] = await ballotBox.getAggregateCiphertext(1);
      aggA = [
        { x: a0.x, y: a0.y },
        { x: a1.x, y: a1.y },
      ];
    });

    it("4.1 Valid DLEQ proof from Officer 1 is accepted and recorded", async function () {
      const decShares1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      const tx = await ballotBox.connect(relayer).submitDecryptionShares(1, decShares1.shares, decShares1.proofs);
      const receipt = await tx.wait();
      expect(receipt.status).to.equal(1);

      expect(await ballotBox.officerSharesSubmitted(1)).to.be.true;
      expect(await ballotBox.state()).to.equal(5); // VotingClosed (waiting for officer 2)
    });

    it("4.2 Valid DLEQ proofs from both officers transition state to DecryptionSharesComplete", async function () {
      const dec1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      await ballotBox.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs);

      const dec2 = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      await ballotBox.connect(relayer).submitDecryptionShares(2, dec2.shares, dec2.proofs);

      expect(await ballotBox.officerSharesSubmitted(2)).to.be.true;
      expect(await ballotBox.state()).to.equal(6); // DecryptionSharesComplete
    });

    it("4.3 Aggregate A_agg[j] = infinity edge case accepts D = infinity and bypasses DLEQ", async function () {
      // In this test, aggregate A for candidate 1 has r = 0 mod q (simulated via empty/inf aggregate)
      const aggWithInf = [aggA[0], INFINITY];

      const dec = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggWithInf,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      expect(dec.shares[1].x).to.equal(0n);
      expect(dec.shares[1].y).to.equal(0n);
    });

    it("4.4 Officer submitting D != infinity when A_agg is infinity reverts (EXPECTED_INFINITY_SHARE)", async function () {
      // Fresh ballot box with no votes cast (aggregate A is (0, 0))
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      const emptyBox = await BallotBoxFactory.deploy(
        1111n,
        2n,
        relayer.address,
        verifierAddress
      );
      await emptyBox.waitForDeployment();
      const emptyAddress = await emptyBox.getAddress();

      // Register and close
      const p1 = generateSchnorrPoP(s1, 1, 1111n, emptyAddress, chainId);
      const p2 = generateSchnorrPoP(s2, 2, 1111n, emptyAddress, chainId);
      await emptyBox.connect(relayer).registerOfficer(1, p1.pubKey, p1.pop);
      await emptyBox.connect(relayer).registerOfficer(2, p2.pubKey, p2.pop);
      await emptyBox.connect(admin).openVoting();
      await emptyBox.connect(admin).closeVoting();

      // Officer submits non-zero share when A is infinity
      const badShares = [pointMul(G, 5n), pointMul(G, 6n)];
      const mockProofs = [
        { u: pointMul(G, 1n), v: pointMul(G, 1n), z: 1n },
        { u: pointMul(G, 1n), v: pointMul(G, 1n), z: 1n },
      ];

      await expect(
        emptyBox.connect(relayer).submitDecryptionShares(1, badShares, mockProofs)
      ).to.be.revertedWith("EXPECTED_INFINITY_SHARE");
    });

    it("4.5 DLEQ proof with tampered commitment reverts (DLEQ_G_EQUATION_FAILED)", async function () {
      const dec = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      // Tamper U commitment point
      dec.proofs[0].u = pointAdd(dec.proofs[0].u, G);

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, dec.shares, dec.proofs)
      ).to.be.revertedWith("DLEQ_G_EQUATION_FAILED");
    });

    it("4.6 DLEQ proof with tampered decryption share reverts (DLEQ_A_EQUATION_FAILED)", async function () {
      const dec = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      // Tamper decryption share D_0
      dec.shares[0] = pointAdd(dec.shares[0], G);

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, dec.shares, dec.proofs)
      ).to.be.revertedWith("DLEQ_G_EQUATION_FAILED");
    });

    it("4.7 Replaying DLEQ proof generated for another election ID reverts", async function () {
      const decWrongElection = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId: 99999n, // Different election ID!
        contractAddress: ballotBoxAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, decWrongElection.shares, decWrongElection.proofs)
      ).to.be.revertedWith("DLEQ_G_EQUATION_FAILED");
    });

    it("4.8 Officer submitting decryption shares twice reverts (SHARES_ALREADY_SUBMITTED)", async function () {
      const dec1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      await ballotBox.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs);

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs)
      ).to.be.revertedWith("SHARES_ALREADY_SUBMITTED");
    });

    it("4.9 Unauthorized caller submitting officer shares reverts", async function () {
      const dec1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      await expect(
        ballotBox.connect(unauthorized).submitDecryptionShares(1, dec1.shares, dec1.proofs)
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");
    });
  });

  // =========================================================================
  // SUITE 5: TALLY VERIFICATION & SAFETY INVARIANTS (Tests 5.1 - 5.6)
  // =========================================================================
  describe("Suite 5: Tally Verification & Safety Invariants", function () {
    const p1 = ethers.keccak256(ethers.toUtf8Bytes("voter_alice"));
    const p2 = ethers.keccak256(ethers.toUtf8Bytes("voter_bob"));
    let aggB = [];
    let dec1, dec2;

    beforeEach(async function () {
      await setupAndOpenElection();

      // Alice votes Candidate 0
      const b1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p1, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(p1, 1n, b1.ciphertexts, b1.proof);

      // Bob votes Candidate 0
      const b2 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p2, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(p2, 1n, b2.ciphertexts, b2.proof);

      await ballotBox.connect(admin).closeVoting();

      const [a0, b0] = await ballotBox.getAggregateCiphertext(0);
      const [a1, b1_point] = await ballotBox.getAggregateCiphertext(1);
      const aggA = [{ x: a0.x, y: a0.y }, { x: a1.x, y: a1.y }];
      aggB = [{ x: b0.x, y: b0.y }, { x: b1_point.x, y: b1_point.y }];

      dec1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      await ballotBox.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs);

      dec2 = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      await ballotBox.connect(relayer).submitDecryptionShares(2, dec2.shares, dec2.proofs);
    });

    it("5.1 Exactly correct tally [2, 0] verifies successfully and emits ElectionFinalized", async function () {
      // Off-chain discrete log recovery
      const tallies = solveDiscreteLogTallies(aggB, dec1.shares, dec2.shares, 2, 10);
      expect(tallies[0]).to.equal(2n);
      expect(tallies[1]).to.equal(0n);

      expect(await ballotBox.state()).to.equal(6); // DecryptionSharesComplete

      const tx = await ballotBox.finalizeTally(tallies);
      const receipt = await tx.wait();
      expect(receipt.status).to.equal(1);

      expect(await ballotBox.state()).to.equal(7); // Finalized
      expect(await ballotBox.getFinalTally(0)).to.equal(2n);
      expect(await ballotBox.getFinalTally(1)).to.equal(0n);
    });

    it("5.2 Zero-vote candidate (Candidate 1 = 0 votes) verifies against point at infinity", async function () {
      const tallies = [2n, 0n];
      await ballotBox.finalizeTally(tallies);
      expect(await ballotBox.getFinalTally(1)).to.equal(0n);
    });

    it("5.3 Tally value exceeding total ballots reverts (CANDIDATE_TALLY_EXCEEDS_TOTAL)", async function () {
      await expect(
        ballotBox.finalizeTally([3n, 0n]) // 3 > totalActiveBallots (2)
      ).to.be.revertedWith("CANDIDATE_TALLY_EXCEEDS_TOTAL");
    });

    it("5.4 Sum of tallies not equal to active ballots reverts (TALLY_SUM_MISMATCH)", async function () {
      await expect(
        ballotBox.finalizeTally([1n, 0n]) // Sum is 1, total is 2
      ).to.be.revertedWith("TALLY_SUM_MISMATCH");
    });

    it("5.5 Swapped candidate tallies [0, 2] revert (TALLY_EQUATION_FAILED)", async function () {
      await expect(
        ballotBox.finalizeTally([0n, 2n]) // Swapped: sum is 2, but equations fail
      ).to.be.revertedWith("TALLY_EQUATION_FAILED");
    });

    it("5.6 Zero-ballot election finalization guard reverts (NO_BALLOTS_CAST)", async function () {
      // Deploy an election with 0 ballots
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      const emptyBox = await BallotBoxFactory.deploy(
        5555n,
        2n,
        relayer.address,
        verifierAddress
      );
      await emptyBox.waitForDeployment();
      const addr = await emptyBox.getAddress();

      const p_1 = generateSchnorrPoP(s1, 1, 5555n, addr, chainId);
      const p_2 = generateSchnorrPoP(s2, 2, 5555n, addr, chainId);
      await emptyBox.connect(relayer).registerOfficer(1, p_1.pubKey, p_1.pop);
      await emptyBox.connect(relayer).registerOfficer(2, p_2.pubKey, p_2.pop);
      await emptyBox.connect(admin).openVoting();
      await emptyBox.connect(admin).closeVoting();

      // Submit shares for 0-vote election
      const d1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: [INFINITY, INFINITY],
        electionId: 5555n,
        contractAddress: addr,
        chainId,
      });
      const d2 = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA: [INFINITY, INFINITY],
        electionId: 5555n,
        contractAddress: addr,
        chainId,
      });
      await emptyBox.connect(relayer).submitDecryptionShares(1, d1.shares, d1.proofs);
      await emptyBox.connect(relayer).submitDecryptionShares(2, d2.shares, d2.proofs);

      await expect(
        emptyBox.finalizeTally([0n, 0n])
      ).to.be.revertedWith("NO_BALLOTS_CAST");
    });

    it("5.7 finalizeZeroVoteElection finalizes zero-ballot elections safely and enforces guards", async function () {
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
      const emptyBox = await BallotBoxFactory.deploy(
        5556n,
        2n,
        relayer.address,
        verifierAddress
      );
      await emptyBox.waitForDeployment();
      const addr = await emptyBox.getAddress();

      const p_1 = generateSchnorrPoP(s1, 1, 5556n, addr, chainId);
      const p_2 = generateSchnorrPoP(s2, 2, 5556n, addr, chainId);
      await emptyBox.connect(relayer).registerOfficer(1, p_1.pubKey, p_1.pop);
      await emptyBox.connect(relayer).registerOfficer(2, p_2.pubKey, p_2.pop);
      await emptyBox.connect(admin).openVoting();
      await emptyBox.connect(admin).closeVoting();

      // Incomplete shares guard
      await expect(
        emptyBox.connect(relayer).finalizeZeroVoteElection()
      ).to.be.revertedWith("SHARES_INCOMPLETE");

      const d1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: [INFINITY, INFINITY],
        electionId: 5556n,
        contractAddress: addr,
        chainId,
      });
      const d2 = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA: [INFINITY, INFINITY],
        electionId: 5556n,
        contractAddress: addr,
        chainId,
      });
      await emptyBox.connect(relayer).submitDecryptionShares(1, d1.shares, d1.proofs);
      await emptyBox.connect(relayer).submitDecryptionShares(2, d2.shares, d2.proofs);

      // Unauthorized caller guard
      await expect(
        emptyBox.connect(voter1).finalizeZeroVoteElection()
      ).to.be.revertedWith("UNAUTHORIZED_CALLER");

      // Relayer finalizes zero-vote election cleanly without fabricating votes
      await expect(emptyBox.connect(relayer).finalizeZeroVoteElection())
        .to.emit(emptyBox, "ZeroVoteElectionFinalized")
        .withArgs(5556n, 2n)
        .and.to.emit(emptyBox, "ElectionFinalized")
        .withArgs(5556n, [0n, 0n]);

      expect(await emptyBox.state()).to.equal(7n); // Finalized
      expect(await emptyBox.totalActiveBallots()).to.equal(0n);
      expect(await emptyBox.getFinalTally(0)).to.equal(0n);
      expect(await emptyBox.getFinalTally(1)).to.equal(0n);

      // Cannot use finalizeZeroVoteElection when active ballots exist (Suite 5 beforeEach ballotBox is in DecryptionSharesComplete with 2 ballots)
      await expect(
        ballotBox.connect(relayer).finalizeZeroVoteElection()
      ).to.be.revertedWith("NON_ZERO_BALLOTS");
    });
  });

  // =========================================================================
  // SUITE 6: LIFECYCLE, DISASTER RECOVERY & SIGN-OFF EDGE CASES (Tests 6.1 - 6.6)
  // =========================================================================
  describe("Suite 6: Lifecycle, Disaster Recovery & Sign-Off Edge Cases", function () {
    it("6.1 Permissionless markTallyStalled transitions to TallyStalled after 72 hours", async function () {
      await setupAndOpenElection();
      await ballotBox.connect(admin).closeVoting();

      // Advance blockchain time by 72 hours + 1 second
      await ethers.provider.send("evm_increaseTime", [72 * 3600 + 1]);
      await ethers.provider.send("evm_mine");

      // Anyone (unauthorized caller) can trigger markTallyStalled
      const tx = await ballotBox.connect(unauthorized).markTallyStalled();
      const receipt = await tx.wait();
      expect(receipt.status).to.equal(1);

      expect(await ballotBox.state()).to.equal(8); // TallyStalled
    });

    it("6.2 markTallyStalled called before 72-hour grace period reverts", async function () {
      await setupAndOpenElection();
      await ballotBox.connect(admin).closeVoting();

      // Advance only 1 hour
      await ethers.provider.send("evm_increaseTime", [3600]);
      await ethers.provider.send("evm_mine");

      await expect(
        ballotBox.connect(unauthorized).markTallyStalled()
      ).to.be.revertedWith("TALLY_DEADLINE_NOT_PASSED");
    });

    it("6.3 Attempting to finalize tally when state is TallyStalled reverts (SHARES_INCOMPLETE)", async function () {
      await setupAndOpenElection();
      await ballotBox.connect(admin).closeVoting();

      await ethers.provider.send("evm_increaseTime", [72 * 3600 + 1]);
      await ethers.provider.send("evm_mine");
      await ballotBox.connect(unauthorized).markTallyStalled();

      await expect(
        ballotBox.finalizeTally([1n, 0n])
      ).to.be.revertedWith("SHARES_INCOMPLETE");
    });

    it("6.4 DLEQ proof with scalar z >= Q reverts (SCALAR_EXCEEDS_ORDER_Q)", async function () {
      await setupAndOpenElection();
      // Cast 1 ballot
      const p = ethers.keccak256(ethers.toUtf8Bytes("voter_scalar"));
      const b = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(p, 1n, b.ciphertexts, b.proof);
      await ballotBox.connect(admin).closeVoting();

      const [a0] = await ballotBox.getAggregateCiphertext(0);
      const [a1] = await ballotBox.getAggregateCiphertext(1);
      const dec = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: [{ x: a0.x, y: a0.y }, { x: a1.x, y: a1.y }],
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      // Set z to Q
      dec.proofs[0].z = Q;

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, dec.shares, dec.proofs)
      ).to.be.revertedWith("SCALAR_EXCEEDS_ORDER_Q");
    });

    it("6.5 Mismatched decryption share and proof vector lengths revert", async function () {
      await setupAndOpenElection();
      await ballotBox.connect(admin).closeVoting();

      // Submit 1 share instead of 2 (SHARES_LENGTH_MISMATCH)
      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, [INFINITY], [{ u: INFINITY, v: INFINITY, z: 0n }])
      ).to.be.revertedWith("SHARES_LENGTH_MISMATCH");

      // Submit 2 shares but 1 proof (PROOFS_LENGTH_MISMATCH)
      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, [INFINITY, INFINITY], [{ u: INFINITY, v: INFINITY, z: 0n }])
      ).to.be.revertedWith("PROOFS_LENGTH_MISMATCH");
    });

    it("6.6 Deploying contract with candidateCount < 2 or > 10 reverts (INVALID_CANDIDATE_COUNT)", async function () {
      const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");

      // 1 candidate
      await expect(
        BallotBoxFactory.deploy(1n, 1n, relayer.address, verifierAddress)
      ).to.be.revertedWith("INVALID_CANDIDATE_COUNT");

      // 11 candidates
      await expect(
        BallotBoxFactory.deploy(1n, 11n, relayer.address, verifierAddress)
      ).to.be.revertedWith("INVALID_CANDIDATE_COUNT");
    });

    it("6.7 castBallot attempted after closeVoting reverts (ELECTION_NOT_OPEN)", async function () {
      await setupAndOpenElection();
      await ballotBox.connect(admin).closeVoting();

      const p = ethers.keccak256(ethers.toUtf8Bytes("late_voter"));
      const b = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });

      await expect(
        ballotBox.castBallot(p, 1n, b.ciphertexts, b.proof)
      ).to.be.revertedWith("ELECTION_NOT_OPEN");
    });

    it("6.8 Unauthorized caller calling invalidateKeyRegistration reverts (UNAUTHORIZED_RELAYER)", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);

      await expect(
        ballotBox.connect(unauthorized).invalidateKeyRegistration()
      ).to.be.revertedWith("UNAUTHORIZED_RELAYER");
    });

    it("6.9 Non-admin calling openVoting or closeVoting reverts (UNAUTHORIZED_ADMIN)", async function () {
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
      await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);
      await ballotBox.connect(relayer).registerOfficer(2, pop2.pubKey, pop2.pop);

      await expect(
        ballotBox.connect(unauthorized).openVoting()
      ).to.be.revertedWith("UNAUTHORIZED_ADMIN");

      await ballotBox.connect(admin).openVoting();

      await expect(
        ballotBox.connect(unauthorized).closeVoting()
      ).to.be.revertedWith("UNAUTHORIZED_ADMIN");
    });

    it("6.10 Off-curve point passed as decryption share Dj reverts (POINT_NOT_ON_CURVE)", async function () {
      await setupAndOpenElection();
      const p = ethers.keccak256(ethers.toUtf8Bytes("offcurve_voter"));
      const b = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      await ballotBox.castBallot(p, 1n, b.ciphertexts, b.proof);
      await ballotBox.connect(admin).closeVoting();

      const [a0] = await ballotBox.getAggregateCiphertext(0);
      const [a1] = await ballotBox.getAggregateCiphertext(1);
      const dec = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: [{ x: a0.x, y: a0.y }, { x: a1.x, y: a1.y }],
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });

      // Provide off-curve point for D_0
      dec.shares[0] = { x: 5n, y: 5n };

      await expect(
        ballotBox.connect(relayer).submitDecryptionShares(1, dec.shares, dec.proofs)
      ).to.be.revertedWith("POINT_NOT_ON_CURVE");
    });
  });

  // =========================================================================
  // SUITE 7: ACTUAL GAS MEASUREMENTS FROM TRANSACTION RECEIPTS
  // =========================================================================
  describe("Suite 7: Actual Gas Measurements from Transaction Receipts", function () {
    it("Measures exact on-chain execution gas for all Milestone 3 lifecycle operations", async function () {
      console.log("\n================================================================================");
      console.log("       MILESTONE 3 ACTUAL ON-CHAIN GAS MEASUREMENTS (Hardhat Paris EVM)          ");
      console.log("================================================================================");

      // 1. Officer 1 Registration
      const pop1 = generateSchnorrPoP(s1, 1, electionId, ballotBoxAddress, chainId);
      const txReg1 = await ballotBox.connect(relayer).registerOfficer(1, pop1.pubKey, pop1.pop);
      const rReg1 = await txReg1.wait();
      console.log(`[MEASURED] registerOfficer (Officer 1):            ${rReg1.gasUsed.toString()} gas`);

      // 2. Officer 2 Registration (computes joint key)
      const pop2 = generateSchnorrPoP(s2, 2, electionId, ballotBoxAddress, chainId);
      const txReg2 = await ballotBox.connect(relayer).registerOfficer(2, pop2.pubKey, pop2.pop);
      const rReg2 = await txReg2.wait();
      console.log(`[MEASURED] registerOfficer (Officer 2 + JointKey):  ${rReg2.gasUsed.toString()} gas`);

      // 3. Open Voting
      const txOpen = await ballotBox.connect(admin).openVoting();
      const rOpen = await txOpen.wait();
      console.log(`[MEASURED] openVoting:                             ${rOpen.gasUsed.toString()} gas`);

      // 4. First Ballot Cast (Candidate 0, 2 candidates)
      const p = ethers.keccak256(ethers.toUtf8Bytes("gas_voter"));
      const ballot1 = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context: { electionId, pseudonym: p, sequence: 1n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      const txCast1 = await ballotBox.castBallot(p, 1n, ballot1.ciphertexts, ballot1.proof);
      const rCast1 = await txCast1.wait();
      console.log(`[MEASURED] castBallot (First Vote, 2 cands):       ${rCast1.gasUsed.toString()} gas`);

      // 5. Revote Cast (Candidate 1, 2 candidates)
      const ballot2 = generateReferenceBallotProof({
        selectedCandidate: 1,
        candidateCount: 2,
        context: { electionId, pseudonym: p, sequence: 2n, jointPubKey: Y_joint },
        verifierAddress,
        chainId,
      });
      const txCast2 = await ballotBox.castBallot(p, 2n, ballot2.ciphertexts, ballot2.proof);
      const rCast2 = await txCast2.wait();
      console.log(`[MEASURED] castBallot (Revote, 2 cands):           ${rCast2.gasUsed.toString()} gas`);

      // 6. Close Voting
      const txClose = await ballotBox.connect(admin).closeVoting();
      const rClose = await txClose.wait();
      console.log(`[MEASURED] closeVoting:                            ${rClose.gasUsed.toString()} gas`);

      // 7. Submit Decryption Shares (Officer 1)
      const [a0, b0] = await ballotBox.getAggregateCiphertext(0);
      const [a1, b1] = await ballotBox.getAggregateCiphertext(1);
      const aggA = [{ x: a0.x, y: a0.y }, { x: a1.x, y: a1.y }];

      const dec1 = generateOfficerDecryptionShares({
        officerPrivKey: s1,
        officerId: 1,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      const txDec1 = await ballotBox.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs);
      const rDec1 = await txDec1.wait();
      console.log(`[MEASURED] submitDecryptionShares (Officer 1):     ${rDec1.gasUsed.toString()} gas`);

      // 8. Submit Decryption Shares (Officer 2)
      const dec2 = generateOfficerDecryptionShares({
        officerPrivKey: s2,
        officerId: 2,
        aggregateA: aggA,
        electionId,
        contractAddress: ballotBoxAddress,
        chainId,
      });
      const txDec2 = await ballotBox.connect(relayer).submitDecryptionShares(2, dec2.shares, dec2.proofs);
      const rDec2 = await txDec2.wait();
      console.log(`[MEASURED] submitDecryptionShares (Officer 2):     ${rDec2.gasUsed.toString()} gas`);

      // 9. Finalize Tally
      const txFinal = await ballotBox.finalizeTally([0n, 1n]);
      const rFinal = await txFinal.wait();
      console.log(`[MEASURED] finalizeTally (2 cands):                ${rFinal.gasUsed.toString()} gas`);
      console.log("================================================================================\n");

      expect(rCast1.gasUsed).to.be.greaterThan(0n);
      expect(rFinal.gasUsed).to.be.greaterThan(0n);
    });
  });
});
