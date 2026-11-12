const { ethers } = require("hardhat");
const crypto = require("crypto");
const {
  P,
  Q,
  G,
  INFINITY,
  modQ,
  pointAdd,
  pointSub,
  pointMul,
  isInfinity,
  pointsEqual,
} = require("./bn254_cds_reference");

/**
 * Generates a cryptographically secure scalar in [1, Q-1] using CSPRNG rejection sampling.
 */
function generateSecureScalarBN254() {
  while (true) {
    const bytes = crypto.randomBytes(32);
    const s = BigInt("0x" + bytes.toString("hex"));
    if (s > 0n && s < Q) {
      return s;
    }
  }
}

/**
 * Computes canonical Schnorr Proof-of-Possession for an officer public key.
 */
function generateSchnorrPoP(privKey, officerId, electionId, contractAddress, chainId, customWitness = null) {
  const k = customWitness ? customWitness : generateSecureScalarBN254();
  const Y = pointMul(G, privKey);
  const R = pointMul(G, k);

  const eHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["bytes32", "uint256", "address", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
      [
        ethers.keccak256(ethers.toUtf8Bytes("VWD_BN254_POP_V1")),
        BigInt(chainId),
        contractAddress,
        BigInt(electionId),
        BigInt(officerId),
        Y.x,
        Y.y,
        R.x,
        R.y,
      ]
    )
  );
  const e = modQ(BigInt(eHash));
  const z = modQ(k + e * privKey);

  return { pubKey: Y, pop: { r: R, z } };
}

/**
 * Computes canonical DLEQ challenge matching EVotingBallotBoxV2._computeDLEQChallenge exactly.
 */
function computeCanonicalDLEQChallenge(officerId, j, Y_i, A_j, D_j, proof, electionId, contractAddress, chainId) {
  const headHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["bytes32", "uint256", "address", "uint256", "uint256", "uint256"],
      [
        ethers.keccak256(ethers.toUtf8Bytes("VWD_BN254_DLEQ_V1")),
        BigInt(chainId),
        contractAddress,
        BigInt(electionId),
        BigInt(officerId),
        BigInt(j),
      ]
    )
  );

  const pointsHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256"],
      [
        Y_i.x,
        Y_i.y,
        A_j.x,
        A_j.y,
        D_j.x,
        D_j.y,
        proof.u.x,
        proof.u.y,
        proof.v.x,
        proof.v.y,
      ]
    )
  );

  const finalHash = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(["bytes32", "bytes32"], [headHash, pointsHash])
  );

  return modQ(BigInt(finalHash));
}

/**
 * Generates Chaum-Pedersen DLEQ decryption shares and proofs for an officer.
 */
function generateOfficerDecryptionShares({
  officerPrivKey,
  officerId,
  aggregateA,
  electionId,
  contractAddress,
  chainId,
  customWitnesses = null,
}) {
  const M = aggregateA.length;
  const Y = pointMul(G, officerPrivKey);

  const shares = [];
  const proofs = [];

  for (let j = 0; j < M; j++) {
    const A_j = aggregateA[j];

    if (isInfinity(A_j)) {
      // Degenerate infinity coordinate
      shares.push(INFINITY);
      proofs.push({ u: INFINITY, v: INFINITY, z: 0n });
    } else {
      const D_j = pointMul(A_j, officerPrivKey);
      shares.push(D_j);

      const t_j = customWitnesses ? customWitnesses[j] : generateSecureScalarBN254();
      const U_j = pointMul(G, t_j);
      const V_j = pointMul(A_j, t_j);

      const partialProof = { u: U_j, v: V_j, z: 0n };
      const c = computeCanonicalDLEQChallenge(
        officerId,
        j,
        Y,
        A_j,
        D_j,
        partialProof,
        electionId,
        contractAddress,
        chainId
      );
      const z_j = modQ(t_j + c * officerPrivKey);

      proofs.push({ u: U_j, v: V_j, z: z_j });
    }
  }

  return { shares, proofs };
}

/**
 * Off-chain discrete-log solver for bounded tallies: 0 <= T_j <= maxBallots.
 * Recovers integer tally vector from decrypted points M_j = B_agg[j] - (D_1[j] + D_2[j]).
 */
function solveDiscreteLogTallies(aggregateB, shares1, shares2, candidateCount, maxBallots) {
  // Precompute lookup table up to maxBallots
  const table = new Map();
  let current = INFINITY;
  table.set(`${current.x},${current.y}`, 0n);

  for (let k = 1n; k <= BigInt(maxBallots); k++) {
    current = pointAdd(current, G);
    table.set(`${current.x},${current.y}`, k);
  }

  const tallies = [];

  for (let j = 0; j < candidateCount; j++) {
    const D_joint = pointAdd(shares1[j], shares2[j]);
    const decryptedPoint = pointSub(aggregateB[j], D_joint);
    const key = `${decryptedPoint.x},${decryptedPoint.y}`;

    if (!table.has(key)) {
      throw new Error(`DISCRETE_LOG_NOT_FOUND_FOR_CANDIDATE_${j}`);
    }

    tallies.push(table.get(key));
  }

  return tallies;
}

module.exports = {
  generateSecureScalarBN254,
  generateSchnorrPoP,
  computeCanonicalDLEQChallenge,
  generateOfficerDecryptionShares,
  solveDiscreteLogTallies,
};
