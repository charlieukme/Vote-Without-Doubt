const { ethers } = require("hardhat");

/**
 * BN254 Curve Constants and Order
 */
const P = 21888242871839275222246405745257275088696311157297823662689037894645226208583n;
const Q = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const GX = 1n;
const GY = 2n;

const G = { x: GX, y: GY };
const INFINITY = { x: 0n, y: 0n };

const DOMAIN_SEPARATOR = ethers.keccak256(ethers.toUtf8Bytes("VWD_BN254_CDS_NIZK_NONCIRCULAR_V2"));
const MIN_CANDIDATES = 2;
const MAX_CANDIDATES = 10;

/**
 * Extended Euclidean Algorithm for Modular Inverse
 */
function modInverse(a, m = P) {
  let [old_r, r] = [BigInt(a) % m, m];
  let [old_s, s] = [1n, 0n];

  while (r !== 0n) {
    const quotient = old_r / r;
    [old_r, r] = [r, old_r - quotient * r];
    [old_s, s] = [s, old_s - quotient * s];
  }

  if (old_r !== 1n) {
    throw new Error("MODULAR_INVERSE_DOES_NOT_EXIST");
  }

  return ((old_s % m) + m) % m;
}

function modP(val) {
  return ((BigInt(val) % P) + P) % P;
}

function modQ(val) {
  return ((BigInt(val) % Q) + Q) % Q;
}

function isInfinity(point) {
  return point.x === 0n && point.y === 0n;
}

function pointsEqual(p1, p2) {
  return p1.x === p2.x && p1.y === p2.y;
}

function isOnCurve(point) {
  if (isInfinity(point)) return true;
  if (point.x >= P || point.y >= P) return false;

  const y2 = modP(point.y * point.y);
  const x3_plus_3 = modP(point.x * point.x * point.x + 3n);
  return y2 === x3_plus_3;
}

function pointNeg(point) {
  if (isInfinity(point)) return INFINITY;
  return { x: point.x, y: modP(P - point.y) };
}

function pointAdd(p1, p2) {
  if (isInfinity(p1)) return { x: p2.x, y: p2.y };
  if (isInfinity(p2)) return { x: p1.x, y: p1.y };

  if (p1.x === p2.x) {
    if (modP(p1.y + p2.y) === 0n) {
      return INFINITY;
    }
    // Point doubling: lambda = (3 * x1^2) / (2 * y1)
    const num = modP(3n * p1.x * p1.x);
    const den = modP(2n * p1.y);
    const lambda = modP(num * modInverse(den, P));

    const x3 = modP(lambda * lambda - 2n * p1.x);
    const y3 = modP(lambda * (p1.x - x3) - p1.y);
    return { x: x3, y: y3 };
  } else {
    // Point addition: lambda = (y2 - y1) / (x2 - x1)
    const num = modP(p2.y - p1.y);
    const den = modP(p2.x - p1.x);
    const lambda = modP(num * modInverse(den, P));

    const x3 = modP(lambda * lambda - p1.x - p2.x);
    const y3 = modP(lambda * (p1.x - x3) - p1.y);
    return { x: x3, y: y3 };
  }
}

function pointSub(p1, p2) {
  return pointAdd(p1, pointNeg(p2));
}

function pointMul(point, scalar) {
  let s = modQ(scalar);
  if (s === 0n || isInfinity(point)) return INFINITY;

  let current = { x: point.x, y: point.y };
  let result = INFINITY;

  while (s > 0n) {
    if (s & 1n) {
      result = pointAdd(result, current);
    }
    current = pointAdd(current, current);
    s >>= 1n;
  }

  return result;
}

/**
 * Off-Chain Canonical Transcript Computation matching BN254CDSVerifier.computeTranscriptHash exactly.
 */
function computeCanonicalTranscriptHash(context, ciphertexts, candidateCommitments, sumCommitments, verifierAddress, chainId) {
  const M = ciphertexts.length;
  if (M === 0) throw new Error("EMPTY_CIPHERTEXTS");
  if (M < MIN_CANDIDATES) throw new Error("CANDIDATE_COUNT_BELOW_MINIMUM");
  if (M > MAX_CANDIDATES) throw new Error("CANDIDATE_COUNT_EXCEEDS_MAXIMUM");

  const header = [
    DOMAIN_SEPARATOR,
    BigInt(chainId),
    verifierAddress,
    BigInt(context.electionId),
    context.pseudonym,
    BigInt(context.sequence),
    BigInt(context.jointPubKey.x),
    BigInt(context.jointPubKey.y),
    BigInt(ciphertexts.length),
  ];

  const headerHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["tuple(bytes32,uint256,address,uint256,bytes32,uint256,uint256,uint256,uint256)"],
      [header]
    )
  );

  const ctHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["tuple(tuple(uint256,uint256),tuple(uint256,uint256))[]"],
      [ciphertexts.map((ct) => [[ct.a.x, ct.a.y], [ct.b.x, ct.b.y]])]
    )
  );

  const commHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["tuple(tuple(uint256,uint256),tuple(uint256,uint256),tuple(uint256,uint256),tuple(uint256,uint256))[]"],
      [
        candidateCommitments.map((c) => [
          [c.t_a_0.x, c.t_a_0.y],
          [c.t_b_0.x, c.t_b_0.y],
          [c.t_a_1.x, c.t_a_1.y],
          [c.t_b_1.x, c.t_b_1.y],
        ]),
      ]
    )
  );

  const sumCommHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["tuple(tuple(uint256,uint256),tuple(uint256,uint256))"],
      [[[sumCommitments.t_a_sum.x, sumCommitments.t_a_sum.y], [sumCommitments.t_b_sum.x, sumCommitments.t_b_sum.y]]]
    )
  );

  return ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["bytes32", "bytes32", "bytes32", "bytes32"],
      [headerHash, ctHash, commHash, sumCommHash]
    )
  );
}

/**
 * Independent Reference Prover:
 * Creates valid ElGamal ciphertexts, non-circular commitments, derives master challenge,
 * computes branch splits and responses.
 */
function generateReferenceBallotProof({
  selectedCandidate,
  candidateCount,
  context,
  verifierAddress,
  chainId,
  customNonces = null,
}) {
  const M = candidateCount;
  const Y = context.jointPubKey;

  const ciphertexts = [];
  const candidateCommitments = [];
  const rValues = [];
  const simChallenges = [];
  const simResponses = [];
  const realWitnesses = [];

  for (let j = 0; j < M; j++) {
    const v_j = j === selectedCandidate ? 1n : 0n;
    const r_j = customNonces ? customNonces.r[j] : modQ(BigInt(j + 1) * 1013n + 17n);
    rValues.push(r_j);

    // ElGamal encryption: A = r * G, B = r * Y + v * G
    const A = pointMul(G, r_j);
    let B = pointMul(Y, r_j);
    if (v_j === 1n) {
      B = pointAdd(B, G);
    }
    ciphertexts.push({ a: A, b: B });

    const w_j = customNonces ? customNonces.w[j] : modQ(BigInt(j + 1) * 2029n + 31n);
    const sim_c = customNonces ? customNonces.simC[j] : modQ(BigInt(j + 1) * 3041n + 47n);
    const sim_z = customNonces ? customNonces.simZ[j] : modQ(BigInt(j + 1) * 4057n + 61n);

    realWitnesses.push(w_j);
    simChallenges.push(sim_c);
    simResponses.push(sim_z);

    let t_a_0, t_b_0, t_a_1, t_b_1;

    if (v_j === 0n) {
      // Real branch is 0
      t_a_0 = pointMul(G, w_j);
      t_b_0 = pointMul(Y, w_j);

      // Simulated branch is 1: T = z*Point - c*Diff
      t_a_1 = pointSub(pointMul(G, sim_z), pointMul(A, sim_c));
      const B_minus_G = pointSub(B, G);
      t_b_1 = pointSub(pointMul(Y, sim_z), pointMul(B_minus_G, sim_c));
    } else {
      // Simulated branch is 0: T = z*Point - c*Diff
      t_a_0 = pointSub(pointMul(G, sim_z), pointMul(A, sim_c));
      t_b_0 = pointSub(pointMul(Y, sim_z), pointMul(B, sim_c));

      // Real branch is 1
      t_a_1 = pointMul(G, w_j);
      t_b_1 = pointMul(Y, w_j);
    }

    candidateCommitments.push({ t_a_0, t_b_0, t_a_1, t_b_1 });
  }

  // Sum commitments: sum(v_j) = 1, sum(A_j) = sum(r_j)*G, sum(B_j) = sum(r_j)*Y + 1*G
  const w_sum = customNonces ? customNonces.w_sum : modQ(998877n);
  const t_a_sum = pointMul(G, w_sum);
  const t_b_sum = pointMul(Y, w_sum);
  const sumCommitments = { t_a_sum, t_b_sum };

  // Compute canonical Fiat-Shamir master challenge from context + ciphertexts + commitments
  const transcriptHash = computeCanonicalTranscriptHash(
    context,
    ciphertexts,
    candidateCommitments,
    sumCommitments,
    verifierAddress,
    chainId
  );
  const c_master = modQ(BigInt(transcriptHash));

  // Compute challenges and responses
  const candidateProofs = [];
  for (let j = 0; j < M; j++) {
    const v_j = j === selectedCandidate ? 1n : 0n;
    const c_j_hash = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(["uint256", "uint256"], [c_master, j])
    );
    const c_j = modQ(BigInt(c_j_hash));

    let c0, c1, z0, z1;
    if (v_j === 0n) {
      c1 = simChallenges[j];
      z1 = simResponses[j];
      c0 = modQ(c_j - c1);
      z0 = modQ(realWitnesses[j] + c0 * rValues[j]);
    } else {
      c0 = simChallenges[j];
      z0 = simResponses[j];
      c1 = modQ(c_j - c0);
      z1 = modQ(realWitnesses[j] + c1 * rValues[j]);
    }

    candidateProofs.push({ c0, c1, z0, z1 });
  }

  // Sum challenge and response
  let sumR = 0n;
  for (const r of rValues) {
    sumR = modQ(sumR + r);
  }
  const c_sum_hash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(["uint256", "string"], [c_master, "SUM"])
  );
  const c_sum = modQ(BigInt(c_sum_hash));
  const z_sum = modQ(w_sum + c_sum * sumR);

  const proof = {
    candidateCommitments,
    candidateProofs,
    sumCommitments,
    z_sum,
  };

  return { context, ciphertexts, proof, c_master };
}

/**
 * Independent Reference Verifier:
 * Pure JS verification of CDS zero-knowledge ballot proof without contacting Solidity.
 */
function verifyBallotProofOffchain(context, ciphertexts, proof, verifierAddress, chainId) {
  const M = ciphertexts.length;
  if (M === 0) throw new Error("EMPTY_CIPHERTEXTS");
  if (M < MIN_CANDIDATES) throw new Error("CANDIDATE_COUNT_BELOW_MINIMUM");
  if (M > MAX_CANDIDATES) throw new Error("CANDIDATE_COUNT_EXCEEDS_MAXIMUM");
  if (proof.candidateCommitments.length !== M) throw new Error("COMMITMENTS_LENGTH_MISMATCH");
  if (proof.candidateProofs.length !== M) throw new Error("PROOFS_LENGTH_MISMATCH");

  // Validate context
  if (BigInt(context.electionId) === 0n) throw new Error("INVALID_ELECTION_ID");
  if (!context.pseudonym || context.pseudonym === ethers.ZeroHash) throw new Error("INVALID_PSEUDONYM");
  if (BigInt(context.sequence) === 0n) throw new Error("INVALID_SEQUENCE");

  const Y = context.jointPubKey;
  if (!isOnCurve(Y) || isInfinity(Y)) throw new Error("INVALID_JOINT_KEY");

  let A_sum = INFINITY;
  let B_sum = INFINITY;

  // Validate all coordinates and scalars
  for (let j = 0; j < M; j++) {
    const ct = ciphertexts[j];
    const comm = proof.candidateCommitments[j];
    const cp = proof.candidateProofs[j];

    if (!isOnCurve(ct.a) || isInfinity(ct.a)) throw new Error(`CT_A_INVALID_AT_${j}`);
    if (!isOnCurve(ct.b)) throw new Error(`CT_B_INVALID_AT_${j}`);

    if (!isOnCurve(comm.t_a_0)) throw new Error(`TA0_INVALID_AT_${j}`);
    if (!isOnCurve(comm.t_b_0)) throw new Error(`TB0_INVALID_AT_${j}`);
    if (!isOnCurve(comm.t_a_1)) throw new Error(`TA1_INVALID_AT_${j}`);
    if (!isOnCurve(comm.t_b_1)) throw new Error(`TB1_INVALID_AT_${j}`);

    if (cp.c0 >= Q || cp.c0 < 0n) throw new Error(`C0_OUT_OF_RANGE_AT_${j}`);
    if (cp.c1 >= Q || cp.c1 < 0n) throw new Error(`C1_OUT_OF_RANGE_AT_${j}`);
    if (cp.z0 >= Q || cp.z0 < 0n) throw new Error(`Z0_OUT_OF_RANGE_AT_${j}`);
    if (cp.z1 >= Q || cp.z1 < 0n) throw new Error(`Z1_OUT_OF_RANGE_AT_${j}`);

    A_sum = pointAdd(A_sum, ct.a);
    B_sum = pointAdd(B_sum, ct.b);
  }

  if (!isOnCurve(proof.sumCommitments.t_a_sum)) throw new Error("TA_SUM_INVALID");
  if (!isOnCurve(proof.sumCommitments.t_b_sum)) throw new Error("TB_SUM_INVALID");
  if (proof.z_sum >= Q || proof.z_sum < 0n) throw new Error("Z_SUM_OUT_OF_RANGE");

  // Compute canonical Fiat-Shamir master challenge
  const transcriptHash = computeCanonicalTranscriptHash(
    context,
    ciphertexts,
    proof.candidateCommitments,
    proof.sumCommitments,
    verifierAddress,
    chainId
  );
  const c_master = modQ(BigInt(transcriptHash));

  // Verify branch proofs
  for (let j = 0; j < M; j++) {
    const ct = ciphertexts[j];
    const comm = proof.candidateCommitments[j];
    const cp = proof.candidateProofs[j];

    const c_j_hash = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(["uint256", "uint256"], [c_master, j])
    );
    const expected_c_j = modQ(BigInt(c_j_hash));
    const actual_sum_c = modQ(cp.c0 + cp.c1);
    if (actual_sum_c !== expected_c_j) {
      throw new Error(`INVALID_CDS_CHALLENGE_SUM_AT_${j}`);
    }

    // Branch 0 linear equations:
    // z0 * G == T_A_0 + c0 * A
    // z0 * Y == T_B_0 + c0 * B
    const lhs0A = pointMul(G, cp.z0);
    const rhs0A = pointAdd(comm.t_a_0, pointMul(ct.a, cp.c0));
    if (!pointsEqual(lhs0A, rhs0A)) throw new Error(`BRANCH_0_A_EQUATION_FAILED_AT_${j}`);

    const lhs0B = pointMul(Y, cp.z0);
    const rhs0B = pointAdd(comm.t_b_0, pointMul(ct.b, cp.c0));
    if (!pointsEqual(lhs0B, rhs0B)) throw new Error(`BRANCH_0_B_EQUATION_FAILED_AT_${j}`);

    // Branch 1 linear equations:
    // z1 * G == T_A_1 + c1 * A
    // z1 * Y == T_B_1 + c1 * (B - G)
    const lhs1A = pointMul(G, cp.z1);
    const rhs1A = pointAdd(comm.t_a_1, pointMul(ct.a, cp.c1));
    if (!pointsEqual(lhs1A, rhs1A)) throw new Error(`BRANCH_1_A_EQUATION_FAILED_AT_${j}`);

    const B_minus_G = pointSub(ct.b, G);
    const lhs1B = pointMul(Y, cp.z1);
    const rhs1B = pointAdd(comm.t_b_1, pointMul(B_minus_G, cp.c1));
    if (!pointsEqual(lhs1B, rhs1B)) throw new Error(`BRANCH_1_B_EQUATION_FAILED_AT_${j}`);
  }

  // Sum linear equations:
  // z_sum * G == T_A_sum + c_sum * A_sum
  // z_sum * Y == T_B_sum + c_sum * (B_sum - G)
  const c_sum_hash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(["uint256", "string"], [c_master, "SUM"])
  );
  const expected_c_sum = modQ(BigInt(c_sum_hash));

  const lhsSumA = pointMul(G, proof.z_sum);
  const rhsSumA = pointAdd(proof.sumCommitments.t_a_sum, pointMul(A_sum, expected_c_sum));
  if (!pointsEqual(lhsSumA, rhsSumA)) throw new Error("SUM_A_EQUATION_FAILED");

  const B_sum_minus_G = pointSub(B_sum, G);
  const lhsSumB = pointMul(Y, proof.z_sum);
  const rhsSumB = pointAdd(proof.sumCommitments.t_b_sum, pointMul(B_sum_minus_G, expected_c_sum));
  if (!pointsEqual(lhsSumB, rhsSumB)) throw new Error("SUM_B_EQUATION_FAILED");

  return true;
}

module.exports = {
  P,
  Q,
  G,
  INFINITY,
  DOMAIN_SEPARATOR,
  MIN_CANDIDATES,
  MAX_CANDIDATES,
  modInverse,
  modP,
  modQ,
  isOnCurve,
  isInfinity,
  pointsEqual,
  pointNeg,
  pointAdd,
  pointSub,
  pointMul,
  computeCanonicalTranscriptHash,
  generateReferenceBallotProof,
  verifyBallotProofOffchain,
};
