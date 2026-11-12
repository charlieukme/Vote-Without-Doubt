const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
  P,
  Q,
  G,
  INFINITY,
  modQ,
  pointAdd,
  pointMul,
  generateReferenceBallotProof,
  verifyBallotProofOffchain,
  computeCanonicalTranscriptHash,
} = require("./helpers/bn254_cds_reference");

describe("BN254CDSVerifier - Milestone 2 (Non-Circular Transcript Correction)", function () {
  let verifier, bn254Wrapper;
  let deployer;
  let chainId;
  let verifierAddress;

  // Joint public key setup: privKey = 123456789n, pubKey = privKey * G
  const privKey = 123456789n;
  const jointPubKey = pointMul(G, privKey);

  before(async function () {
    [deployer] = await ethers.getSigners();
    const network = await ethers.provider.getNetwork();
    chainId = network.chainId;

    const WrapperFactory = await ethers.getContractFactory("BN254TestWrapper");
    bn254Wrapper = await WrapperFactory.deploy();
    await bn254Wrapper.waitForDeployment();

    const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier");
    verifier = await VerifierFactory.deploy();
    await verifier.waitForDeployment();
    verifierAddress = await verifier.getAddress();
  });

  function createValidContext(electionId = 101, sequence = 1) {
    return {
      electionId: BigInt(electionId),
      pseudonym: ethers.keccak256(ethers.toUtf8Bytes("voter_anon_pseudonym_1")),
      sequence: BigInt(sequence),
      jointPubKey: { x: jointPubKey.x, y: jointPubKey.y },
    };
  }

  // --- TRANSCRIPT HASH MATCHING VERIFICATION ---
  it("0. Transcript encoding: Off-chain hash matches on-chain computeTranscriptHash exactly", async function () {
    const context = createValidContext(500, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const offchainHash = computeCanonicalTranscriptHash(
      context,
      ciphertexts,
      proof.candidateCommitments,
      proof.sumCommitments,
      verifierAddress,
      chainId
    );

    const onchainHash = await verifier.computeTranscriptHash(
      context,
      ciphertexts,
      proof.candidateCommitments,
      proof.sumCommitments
    );

    expect(offchainHash).to.equal(onchainHash);
  });

  // --- 20 REQUIRED AUDIT TEST CONDITIONS ---

  it("1. Valid zero encryption (Candidate 0 in 2-candidate ballot where Candidate 1 is selected)", async function () {
    const context = createValidContext(1001, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 1, // Candidate 0 is 0, Candidate 1 is 1
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Pure off-chain independent verifier
    const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
    expect(offchainValid).to.be.true;

    // Solidity verifier
    const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
    expect(onchainValid).to.be.true;
  });

  it("2. Valid one encryption (Candidate 0 in 2-candidate ballot where Candidate 0 is selected)", async function () {
    const context = createValidContext(1002, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0, // Candidate 0 is 1, Candidate 1 is 0
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
    expect(offchainValid).to.be.true;

    const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
    expect(onchainValid).to.be.true;
  });

  it("3. Valid 2-candidate ballot verifies successfully", async function () {
    const context = createValidContext(2001, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
    expect(offchainValid).to.be.true;

    const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
    expect(onchainValid).to.be.true;
  });

  it("4. Valid 5-candidate ballot verifies successfully", async function () {
    const context = createValidContext(5001, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 3, // vote for 4th candidate: [0, 0, 0, 1, 0]
      candidateCount: 5,
      context,
      verifierAddress,
      chainId,
    });

    const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
    expect(offchainValid).to.be.true;

    const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
    expect(onchainValid).to.be.true;
  });

  it("5. Invalid binary coordinate (vote coordinate encrypts 2 instead of 0 or 1)", async function () {
    const context = createValidContext(1005, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Corrupt ciphertext 0 to encrypt 2: B0 = B0 + G
    const tamperedCt = JSON.parse(JSON.stringify(ciphertexts, (k, v) => (typeof v === "bigint" ? v.toString() : v)));
    // parse BigInt back
    tamperedCt[0].b = pointAdd({ x: BigInt(tamperedCt[0].b.x), y: BigInt(tamperedCt[0].b.y) }, G);
    tamperedCt[0].a = { x: BigInt(tamperedCt[0].a.x), y: BigInt(tamperedCt[0].a.y) };
    tamperedCt[1].a = { x: BigInt(tamperedCt[1].a.x), y: BigInt(tamperedCt[1].a.y) };
    tamperedCt[1].b = { x: BigInt(tamperedCt[1].b.x), y: BigInt(tamperedCt[1].b.y) };

    // Off-chain verifier rejects
    expect(() => verifyBallotProofOffchain(context, tamperedCt, proof, verifierAddress, chainId)).to.throw();

    // On-chain verifier reverts
    await expect(verifier.verifyBallotProof(context, tamperedCt, proof)).to.be.reverted;
  });

  it("6. Invalid sum-to-one vector (all zeros: [0, 0])", async function () {
    const context = createValidContext(1006, 1);
    // Build proof where both candidates encrypt 0
    const M = 2;
    const rValues = [11n, 22n];
    const ciphertexts = [
      { a: pointMul(G, rValues[0]), b: pointMul(jointPubKey, rValues[0]) }, // encrypts 0
      { a: pointMul(G, rValues[1]), b: pointMul(jointPubKey, rValues[1]) }, // encrypts 0
    ];

    // Attempting sum-to-one proof when sum is 0 fails
    const { proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    expect(() => verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, proof)).to.be.reverted;
  });

  it("7. Tampered commitment point (tampered T_A_0)", async function () {
    const context = createValidContext(1007, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Deep clone and tamper T_A_0 of candidate 0
    const tamperedProof = JSON.parse(JSON.stringify(proof, (k, v) => (typeof v === "bigint" ? v.toString() : v)));
    // Change t_a_0 to 2*G
    const newTA0 = pointMul(G, 2n);
    tamperedProof.candidateCommitments[0].t_a_0 = { x: newTA0.x.toString(), y: newTA0.y.toString() };

    // Convert all BigInts back
    const reconstructedProof = {
      candidateCommitments: tamperedProof.candidateCommitments.map((c) => ({
        t_a_0: { x: BigInt(c.t_a_0.x), y: BigInt(c.t_a_0.y) },
        t_b_0: { x: BigInt(c.t_b_0.x), y: BigInt(c.t_b_0.y) },
        t_a_1: { x: BigInt(c.t_a_1.x), y: BigInt(c.t_a_1.y) },
        t_b_1: { x: BigInt(c.t_b_1.x), y: BigInt(c.t_b_1.y) },
      })),
      candidateProofs: tamperedProof.candidateProofs.map((cp) => ({
        c0: BigInt(cp.c0),
        c1: BigInt(cp.c1),
        z0: BigInt(cp.z0),
        z1: BigInt(cp.z1),
      })),
      sumCommitments: {
        t_a_sum: { x: BigInt(tamperedProof.sumCommitments.t_a_sum.x), y: BigInt(tamperedProof.sumCommitments.t_a_sum.y) },
        t_b_sum: { x: BigInt(tamperedProof.sumCommitments.t_b_sum.x), y: BigInt(tamperedProof.sumCommitments.t_b_sum.y) },
      },
      z_sum: BigInt(tamperedProof.z_sum),
    };

    expect(() => verifyBallotProofOffchain(context, ciphertexts, reconstructedProof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, reconstructedProof)).to.be.reverted;
  });

  it("8. Tampered ciphertext (tampered B_j)", async function () {
    const context = createValidContext(1008, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const tamperedCt = [
      { a: ciphertexts[0].a, b: pointMul(G, 999n) }, // Tampered
      ciphertexts[1],
    ];

    expect(() => verifyBallotProofOffchain(context, tamperedCt, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, tamperedCt, proof)).to.be.reverted;
  });

  it("9. Tampered challenge split (c0 + c1 != c_j mod q)", async function () {
    const context = createValidContext(1009, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const tamperedProof = {
      ...proof,
      candidateProofs: proof.candidateProofs.map((cp, idx) =>
        idx === 0 ? { ...cp, c0: modQ(cp.c0 + 1n) } : cp
      ),
    };

    expect(() => verifyBallotProofOffchain(context, ciphertexts, tamperedProof, verifierAddress, chainId)).to.throw(
      /INVALID_CDS_CHALLENGE_SUM/
    );
    await expect(verifier.verifyBallotProof(context, ciphertexts, tamperedProof)).to.be.revertedWith(
      "INVALID_CDS_CHALLENGE_SUM"
    );
  });

  it("10. Tampered response (z0 altered)", async function () {
    const context = createValidContext(1010, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const tamperedProof = {
      ...proof,
      candidateProofs: proof.candidateProofs.map((cp, idx) =>
        idx === 0 ? { ...cp, z0: modQ(cp.z0 + 1n) } : cp
      ),
    };

    expect(() => verifyBallotProofOffchain(context, ciphertexts, tamperedProof, verifierAddress, chainId)).to.throw(
      /BRANCH_0_A_EQUATION_FAILED/
    );
    await expect(verifier.verifyBallotProof(context, ciphertexts, tamperedProof)).to.be.revertedWith(
      "BRANCH_0_A_EQUATION_FAILED"
    );
  });

  it("11. Reordered candidates without re-generating proof", async function () {
    const context = createValidContext(1011, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Swap candidates 0 and 1
    const reorderedCt = [ciphertexts[1], ciphertexts[0]];
    const reorderedProof = {
      ...proof,
      candidateCommitments: [proof.candidateCommitments[1], proof.candidateCommitments[0]],
      candidateProofs: [proof.candidateProofs[1], proof.candidateProofs[0]],
    };

    // Both verifiers reject because candidate index is part of c_j derivation
    expect(() => verifyBallotProofOffchain(context, reorderedCt, reorderedProof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, reorderedCt, reorderedProof)).to.be.reverted;
  });

  it("12. Changed election ID", async function () {
    const context = createValidContext(1012, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const alteredContext = { ...context, electionId: 9999n };

    expect(() => verifyBallotProofOffchain(alteredContext, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(alteredContext, ciphertexts, proof)).to.be.reverted;
  });

  it("13. Changed pseudonym", async function () {
    const context = createValidContext(1013, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const alteredContext = {
      ...context,
      pseudonym: ethers.keccak256(ethers.toUtf8Bytes("different_pseudonym")),
    };

    expect(() => verifyBallotProofOffchain(alteredContext, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(alteredContext, ciphertexts, proof)).to.be.reverted;
  });

  it("14. Changed sequence", async function () {
    const context = createValidContext(1014, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    const alteredContext = { ...context, sequence: 2n };

    expect(() => verifyBallotProofOffchain(alteredContext, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(alteredContext, ciphertexts, proof)).to.be.reverted;
  });

  it("15. Changed public key", async function () {
    const context = createValidContext(1015, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Different key: 999 * G
    const alteredContext = { ...context, jointPubKey: pointMul(G, 999n) };

    expect(() => verifyBallotProofOffchain(alteredContext, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(alteredContext, ciphertexts, proof)).to.be.reverted;
  });

  it("16. Changed chain ID", async function () {
    const context = createValidContext(1016, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId: 31338, // Different chain ID
    });

    // Verifying against current chainId (31337) must fail
    expect(() => verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, proof)).to.be.reverted;
  });

  it("17. Changed verifier address", async function () {
    const context = createValidContext(1017, 1);
    const otherVerifierAddress = "0x0000000000000000000000000000000000000001";
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress: otherVerifierAddress, // Generated for different address
      chainId,
    });

    // On-chain verifier using address(this) will compute a different transcript hash
    expect(() => verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, proof)).to.be.reverted;
  });

  it("18. Zero-valued challenge and response edge cases (allowed in [0, q-1])", async function () {
    const context = createValidContext(1018, 1);

    // Specifically test that simulated challenge or response being 0 does not cause verifier rejection
    // when generated with 0-value nonces
    const customNonces = {
      r: [100n, 200n],
      w: [300n, 400n],
      simC: [0n, 0n], // Zero challenge in simulated branch!
      simZ: [0n, 0n], // Zero response in simulated branch!
      w_sum: 500n,
    };

    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
      customNonces,
    });

    // Candidate 0 (v=1, simulated branch is 0) has c0 = 0 and z0 = 0
    expect(proof.candidateProofs[0].c0).to.equal(0n);
    expect(proof.candidateProofs[0].z0).to.equal(0n);
    // Candidate 1 (v=0, simulated branch is 1) has c1 = 0 and z1 = 0
    expect(proof.candidateProofs[1].c1).to.equal(0n);
    expect(proof.candidateProofs[1].z1).to.equal(0n);

    // Both off-chain and on-chain verifiers accept zero challenge and zero response
    const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
    expect(offchainValid).to.be.true;

    const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
    expect(onchainValid).to.be.true;
  });

  it("19. Scalar values >= q are rejected", async function () {
    const context = createValidContext(1019, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // Test c0 >= Q
    const proofBadScalar = {
      ...proof,
      candidateProofs: proof.candidateProofs.map((cp, idx) =>
        idx === 0 ? { ...cp, c0: Q } : cp
      ),
    };

    expect(() => verifyBallotProofOffchain(context, ciphertexts, proofBadScalar, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, proofBadScalar)).to.be.revertedWith(
      "SCALAR_EXCEEDS_ORDER_Q"
    );

    // Test z_sum >= Q
    const proofBadSumScalar = {
      ...proof,
      z_sum: Q + 1n,
    };
    expect(() => verifyBallotProofOffchain(context, ciphertexts, proofBadSumScalar, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ciphertexts, proofBadSumScalar)).to.be.revertedWith(
      "SCALAR_EXCEEDS_ORDER_Q"
    );
  });

  it("20. Infinity and malformed point cases are rejected", async function () {
    const context = createValidContext(1020, 1);
    const { ciphertexts, proof } = generateReferenceBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress,
      chainId,
    });

    // A) Ciphertext A is infinity (0, 0)
    const ctWithInfA = [{ a: INFINITY, b: ciphertexts[0].b }, ciphertexts[1]];
    expect(() => verifyBallotProofOffchain(context, ctWithInfA, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ctWithInfA, proof)).to.be.revertedWith(
      "CIPHERTEXT_A_IS_INFINITY"
    );

    // B) Point off-curve: (1, 1) does not satisfy y^2 = x^3 + 3 (mod p)
    const offCurvePoint = { x: 1n, y: 1n };
    const ctOffCurve = [{ a: offCurvePoint, b: ciphertexts[0].b }, ciphertexts[1]];
    expect(() => verifyBallotProofOffchain(context, ctOffCurve, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(context, ctOffCurve, proof)).to.be.revertedWith(
      "POINT_NOT_ON_CURVE"
    );

    // C) Coordinate >= P
    const outOfFieldPoint = { x: P + 5n, y: 2n };
    const ctOutOfField = [{ a: outOfFieldPoint, b: ciphertexts[0].b }, ciphertexts[1]];
    await expect(verifier.verifyBallotProof(context, ctOutOfField, proof)).to.be.revertedWith(
      "COORDINATE_EXCEEDS_FIELD_P"
    );

    // D) Joint public key is infinity (0, 0)
    const contextInfKey = { ...context, jointPubKey: INFINITY };
    expect(() => verifyBallotProofOffchain(contextInfKey, ciphertexts, proof, verifierAddress, chainId)).to.throw();
    await expect(verifier.verifyBallotProof(contextInfKey, ciphertexts, proof)).to.be.revertedWith(
      "INVALID_JOINT_KEY"
    );
  });

  // --- PART D: CANDIDATE-COUNT LIMIT ENFORCEMENT ---
  describe("Candidate-Count Limits Enforcement", function () {
    it("21. Minimum valid candidate count (2 candidates) verifies successfully", async function () {
      const context = createValidContext(4001, 1);
      const { ciphertexts, proof } = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context,
        verifierAddress,
        chainId,
      });

      const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
      expect(offchainValid).to.be.true;

      const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
      expect(onchainValid).to.be.true;
    });

    it("22. Maximum supported candidate count (10 candidates) verifies successfully", async function () {
      const context = createValidContext(4002, 1);
      const { ciphertexts, proof } = generateReferenceBallotProof({
        selectedCandidate: 7,
        candidateCount: 10,
        context,
        verifierAddress,
        chainId,
      });

      const offchainValid = verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId);
      expect(offchainValid).to.be.true;

      const onchainValid = await verifier.verifyBallotProof(context, ciphertexts, proof);
      expect(onchainValid).to.be.true;
    });

    it("23. One candidate above the limit (11 candidates) is rejected", async function () {
      const context = createValidContext(4003, 1);
      expect(() =>
        generateReferenceBallotProof({
          selectedCandidate: 0,
          candidateCount: 11,
          context,
          verifierAddress,
          chainId,
        })
      ).to.throw(/CANDIDATE_COUNT_EXCEEDS_MAXIMUM/);

      const mockCiphertexts = Array(11).fill({ a: G, b: G });
      const mockCommitments = Array(11).fill({ t_a_0: G, t_b_0: G, t_a_1: G, t_b_1: G });
      const mockProofs = Array(11).fill({ c0: 1n, c1: 1n, z0: 1n, z1: 1n });
      const mockBallotProof = {
        candidateCommitments: mockCommitments,
        candidateProofs: mockProofs,
        sumCommitments: { t_a_sum: G, t_b_sum: G },
        z_sum: 1n,
      };

      await expect(
        verifier.verifyBallotProof(context, mockCiphertexts, mockBallotProof)
      ).to.be.revertedWith("CANDIDATE_COUNT_EXCEEDS_MAXIMUM");
    });

    it("24. Empty ciphertext array (0 candidates) is rejected", async function () {
      const context = createValidContext(4004, 1);
      const emptyProof = {
        candidateCommitments: [],
        candidateProofs: [],
        sumCommitments: { t_a_sum: G, t_b_sum: G },
        z_sum: 1n,
      };

      expect(() => verifyBallotProofOffchain(context, [], emptyProof, verifierAddress, chainId)).to.throw(
        /EMPTY_CIPHERTEXTS/
      );
      await expect(verifier.verifyBallotProof(context, [], emptyProof)).to.be.revertedWith(
        "EMPTY_CIPHERTEXTS"
      );
    });

    it("25. Below minimum candidate count (1 candidate) is rejected", async function () {
      const context = createValidContext(4005, 1);
      const mockCiphertexts = [{ a: G, b: G }];
      const mockCommitments = [{ t_a_0: G, t_b_0: G, t_a_1: G, t_b_1: G }];
      const mockProofs = [{ c0: 1n, c1: 1n, z0: 1n, z1: 1n }];
      const mockBallotProof = {
        candidateCommitments: mockCommitments,
        candidateProofs: mockProofs,
        sumCommitments: { t_a_sum: G, t_b_sum: G },
        z_sum: 1n,
      };

      expect(() =>
        verifyBallotProofOffchain(context, mockCiphertexts, mockBallotProof, verifierAddress, chainId)
      ).to.throw(/CANDIDATE_COUNT_BELOW_MINIMUM/);
      await expect(
        verifier.verifyBallotProof(context, mockCiphertexts, mockBallotProof)
      ).to.be.revertedWith("CANDIDATE_COUNT_BELOW_MINIMUM");
    });
  });

  // --- GAS MEASUREMENTS ---
  describe("Verification Gas Measurements", function () {
    it("Measures exact verification gas for 2 candidates", async function () {
      const context = createValidContext(3001, 1);
      const { ciphertexts, proof } = generateReferenceBallotProof({
        selectedCandidate: 0,
        candidateCount: 2,
        context,
        verifierAddress,
        chainId,
      });

      const gasEstimate = await verifier.verifyBallotProof.estimateGas(context, ciphertexts, proof);
      console.log(`\n==================================================`);
      console.log(`[MEASURED GAS] 2 Candidates Ballot Proof Verification:`);
      console.log(`Measured Gas Units: ${gasEstimate.toString()}`);
      console.log(`==================================================\n`);

      expect(gasEstimate).to.be.greaterThan(0n);
      expect(gasEstimate).to.be.lessThan(400000n);
    });

    it("Measures exact verification gas for 5 candidates", async function () {
      const context = createValidContext(3002, 1);
      const { ciphertexts, proof } = generateReferenceBallotProof({
        selectedCandidate: 2,
        candidateCount: 5,
        context,
        verifierAddress,
        chainId,
      });

      const gasEstimate = await verifier.verifyBallotProof.estimateGas(context, ciphertexts, proof);
      console.log(`\n==================================================`);
      console.log(`[MEASURED GAS] 5 Candidates Ballot Proof Verification:`);
      console.log(`Measured Gas Units: ${gasEstimate.toString()}`);
      console.log(`==================================================\n`);

      expect(gasEstimate).to.be.greaterThan(0n);
      expect(gasEstimate).to.be.lessThan(800000n);
    });
  });
});
