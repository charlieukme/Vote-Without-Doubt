/**
 * Pure JavaScript High-Assurance BN254 Cryptographic Engine for Vote Without Doubt (FIX 3 V2).
 *
 * Implements:
 * 1. BN254 G1 curve arithmetic using native BigInt (EIP-196/197 compliant).
 * 2. Pure JavaScript Keccak-256 hash function (matching EVM keccak256 byte-for-byte).
 * 3. Canonical ABI tuple and array serialization.
 * 4. CSPRNG scalar generation via window.crypto.getRandomValues.
 * 5. Client-Side Schnorr Proof-of-Possession (PoP).
 * 6. Client-Side Non-Circular CDS 1-of-2 and vector sum-to-one ballot proof generator.
 * 7. Client-Side Chaum-Pedersen DLEQ decryption share generator with aggregate infinity handling.
 *
 * Zero external npm dependencies.
 */

// ==============================================================================
// 1. BN254 Curve Constants
// Curve over F_p: Y^2 = X^3 + 3 (mod p)
// ==============================================================================
export const P = 21888242871839275222246405745257275088696311157297823662689037894645226208583n
export const Q = 21888242871839275222246405745257275088548364400416034343698204186575808495617n

export const GX = 1n
export const GY = 2n
export const G = { x: GX, y: GY }
export const INFINITY = { x: 0n, y: 0n }

export const MIN_CANDIDATES = 2
export const MAX_CANDIDATES = 10

// ==============================================================================
// 2. Pure JavaScript Keccak-256 Implementation
// ==============================================================================
const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n,
  0x000000000000808bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
  0x000000000000008an, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000an,
  0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n, 0x8000000000008003n,
  0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
]

const ROTC = [
  [0, 36, 3, 41, 18],
  [1, 44, 10, 45, 2],
  [62, 6, 43, 15, 61],
  [28, 55, 25, 21, 56],
  [27, 20, 39, 8, 14],
]

function rotl64(x, n) {
  const s = BigInt(n % 64)
  return ((x << s) | (x >> (64n - s))) & 0xffffffffffffffffn
}

export function keccak256(data) {
  let bytes
  if (typeof data === 'string') {
    if (data.startsWith('0x') && data.length % 2 === 0) {
      const clean = data.slice(2)
      bytes = new Uint8Array(clean.length / 2)
      for (let i = 0; i < clean.length; i += 2) {
        bytes[i / 2] = parseInt(clean.substring(i, i + 2), 16)
      }
    } else {
      bytes = new TextEncoder().encode(data)
    }
  } else if (data instanceof Uint8Array) {
    bytes = data
  } else {
    throw new Error('Unsupported data type for keccak256')
  }

  // Padding for Keccak-256 (rate = 1088 bits = 136 bytes, delim = 0x01)
  const rate = 136
  const len = bytes.length
  const padLen = rate - (len % rate)
  const padded = new Uint8Array(len + padLen)
  padded.set(bytes)
  padded[len] = 0x01
  padded[padded.length - 1] |= 0x80

  // 5x5 state stored as 25 BigUint64 lanes
  const state = new BigUint64Array(25)

  for (let offset = 0; offset < padded.length; offset += rate) {
    for (let i = 0; i < 17; i++) {
      const idx = offset + i * 8
      let lane = 0n
      for (let b = 0; b < 8; b++) {
        lane |= BigInt(padded[idx + b]) << BigInt(b * 8)
      }
      state[i] ^= lane
    }

    // 24 rounds of Keccak-f[1600]
    for (let round = 0; round < 24; round++) {
      // Theta
      const C = new BigUint64Array(5)
      for (let x = 0; x < 5; x++) {
        C[x] = state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
      }
      const D = new BigUint64Array(5)
      for (let x = 0; x < 5; x++) {
        D[x] = C[(x + 4) % 5] ^ rotl64(C[(x + 1) % 5], 1)
      }
      for (let i = 0; i < 25; i++) {
        state[i] ^= D[i % 5]
      }

      // Rho and Pi
      const B = new BigUint64Array(25)
      for (let x = 0; x < 5; x++) {
        for (let y = 0; y < 5; y++) {
          const newX = y
          const newY = (2 * x + 3 * y) % 5
          B[newX + newY * 5] = rotl64(state[x + y * 5], ROTC[x][y])
        }
      }

      // Chi
      for (let x = 0; x < 5; x++) {
        for (let y = 0; y < 5; y++) {
          const idx = x + y * 5
          const idx1 = ((x + 1) % 5) + y * 5
          const idx2 = ((x + 2) % 5) + y * 5
          state[idx] = B[idx] ^ (~B[idx1] & B[idx2])
        }
      }

      // Iota
      state[0] ^= RC[round]
    }
  }

  // Squeeze 32 bytes (256 bits)
  const out = new Uint8Array(32)
  for (let i = 0; i < 4; i++) {
    const lane = state[i]
    for (let b = 0; b < 8; b++) {
      out[i * 8 + b] = Number((lane >> BigInt(b * 8)) & 0xffn)
    }
  }

  return '0x' + Array.from(out).map(b => b.toString(16).padStart(2, '0')).join('')
}

export const DOMAIN_SEPARATOR = keccak256('VWD_BN254_CDS_NIZK_NONCIRCULAR_V2')
export const POP_DOMAIN_SEPARATOR = keccak256('VWD_BN254_POP_V1')
export const DLEQ_DOMAIN_SEPARATOR = keccak256('VWD_BN254_DLEQ_V1')

// ==============================================================================
// 3. BN254 Field & Elliptic Curve Arithmetic
// ==============================================================================
export function modInverse(a, m = P) {
  let [old_r, r] = [BigInt(a) % m, m]
  let [old_s, s] = [1n, 0n]

  while (r !== 0n) {
    const quotient = old_r / r
    ;[old_r, r] = [r, old_r - quotient * r]
    ;[old_s, s] = [s, old_s - quotient * s]
  }

  if (old_r !== 1n) {
    throw new Error('MODULAR_INVERSE_DOES_NOT_EXIST')
  }

  return ((old_s % m) + m) % m
}

export function modP(val) {
  return ((BigInt(val) % P) + P) % P
}

export function modQ(val) {
  return ((BigInt(val) % Q) + Q) % Q
}

export function isInfinity(pt) {
  return BigInt(pt.x) === 0n && BigInt(pt.y) === 0n
}

export function isOnCurve(pt) {
  if (isInfinity(pt)) return true
  const x = BigInt(pt.x)
  const y = BigInt(pt.y)
  if (x >= P || y >= P || x < 0n || y < 0n) return false

  const y2 = modP(y * y)
  const x3_plus_3 = modP(x * x * x + 3n)
  return y2 === x3_plus_3
}

export function validatePoint(pt) {
  if (!isOnCurve(pt)) {
    throw new Error('Point is not on BN254 G1 curve')
  }
}

export function validateScalar(s) {
  const val = BigInt(s)
  if (val < 0n || val >= Q) {
    throw new Error('Scalar exceeds subgroup order Q')
  }
}

export function pointNeg(pt) {
  if (isInfinity(pt)) return { x: 0n, y: 0n }
  return { x: BigInt(pt.x), y: modP(P - BigInt(pt.y)) }
}

export function pointAdd(p1, p2) {
  if (isInfinity(p1)) return { x: BigInt(p2.x), y: BigInt(p2.y) }
  if (isInfinity(p2)) return { x: BigInt(p1.x), y: BigInt(p1.y) }

  const x1 = BigInt(p1.x)
  const y1 = BigInt(p1.y)
  const x2 = BigInt(p2.x)
  const y2 = BigInt(p2.y)

  if (x1 === x2) {
    if (modP(y1 + y2) === 0n) {
      return { x: 0n, y: 0n }
    }
    // Point doubling: lambda = (3 * x1^2) / (2 * y1)
    const num = modP(3n * x1 * x1)
    const den = modP(2n * y1)
    const lambda = modP(num * modInverse(den, P))

    const x3 = modP(lambda * lambda - 2n * x1)
    const y3 = modP(lambda * (x1 - x3) - y1)
    return { x: x3, y: y3 }
  } else {
    // Point addition: lambda = (y2 - y1) / (x2 - x1)
    const num = modP(y2 - y1)
    const den = modP(x2 - x1)
    const lambda = modP(num * modInverse(den, P))

    const x3 = modP(lambda * lambda - x1 - x2)
    const y3 = modP(lambda * (x1 - x3) - y1)
    return { x: x3, y: y3 }
  }
}

export function pointSub(p1, p2) {
  return pointAdd(p1, pointNeg(p2))
}

export function pointMul(pt, scalar) {
  let s = modQ(BigInt(scalar))
  if (s === 0n || isInfinity(pt)) return { x: 0n, y: 0n }

  let current = { x: BigInt(pt.x), y: BigInt(pt.y) }
  let result = { x: 0n, y: 0n }

  while (s > 0n) {
    if (s & 1n) {
      result = pointAdd(result, current)
    }
    current = pointAdd(current, current)
    s >>= 1n
  }

  return result
}

export function pointsEqual(p1, p2) {
  return BigInt(p1.x) === BigInt(p2.x) && BigInt(p1.y) === BigInt(p2.y)
}

/**
 * Generates a cryptographically secure scalar in [1, Q-1] using CSPRNG rejection sampling.
 */
export function generateClientSecureScalar() {
  const cryptoObj = (typeof window !== 'undefined' ? window.crypto : null) || globalThis.crypto
  if (!cryptoObj || !cryptoObj.getRandomValues) {
    throw new Error('Web Crypto API (crypto.getRandomValues) is required')
  }

  const bytes = new Uint8Array(32)
  while (true) {
    cryptoObj.getRandomValues(bytes)
    let s = 0n
    for (let i = 0; i < 32; i++) {
      s = (s << 8n) | BigInt(bytes[i])
    }
    if (s > 0n && s < Q) {
      return s
    }
  }
}

// ==============================================================================
// 4. Canonical ABI Encoding Helpers
// ==============================================================================
function pad32(val) {
  if (typeof val === 'bigint' || typeof val === 'number') {
    return val.toString(16).padStart(64, '0')
  }
  let clean = String(val).toLowerCase().replace(/^0x/, '')
  return clean.padStart(64, '0')
}

// ==============================================================================
// 5. Client-Side Schnorr Proof-of-Possession
// ==============================================================================
export function generateClientSchnorrPoP({
  privKey,
  officerId,
  officerAddress = null,
  electionId,
  contractAddress,
  chainId,
  customWitness = null,
}) {
  const k = customWitness ? BigInt(customWitness) : generateClientSecureScalar()
  const s = BigInt(privKey)
  validateScalar(s)

  const Y = pointMul(G, s)
  const R = pointMul(G, k)

  // Canonical V2 PoP transcript: bound to contractAddress, electionId, and officerId
  const encodedHex =
    pad32(POP_DOMAIN_SEPARATOR) +
    pad32(BigInt(chainId)) +
    pad32(contractAddress || officerAddress || '0x0000000000000000000000000000000000000000') +
    pad32(BigInt(electionId)) +
    pad32(BigInt(officerId)) +
    pad32(Y.x) +
    pad32(Y.y) +
    pad32(R.x) +
    pad32(R.y)

  const eHash = keccak256('0x' + encodedHex)
  const e = modQ(BigInt(eHash))
  const z = modQ(k + e * s)

  return {
    pubKey: { x: Y.x.toString(), y: Y.y.toString() },
    pop: {
      r: { x: R.x.toString(), y: R.y.toString() },
      z: z.toString(),
    },
    c: e,
  }
}

// ==============================================================================
// 6. Client-Side Non-Circular CDS Ballot Proof Generator
// ==============================================================================
function parsePositiveNumericElectionId(value) {
  if (typeof value === 'bigint') {
    return value > 0n ? value : null
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) && value > 0 ? BigInt(value) : null
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (/^\d+$/.test(trimmed)) {
      const parsed = BigInt(trimmed)
      return parsed > 0n ? parsed : null
    }
  }
  return null
}

function resolveNumericElectionId(context) {
  if (!context || typeof context !== 'object') {
    throw new Error('Missing voting context: a valid numeric electionId is required for transcript hashing.')
  }

  const direct = parsePositiveNumericElectionId(context.electionId)
  if (direct !== null) {
    return direct
  }

  const isEmptyOrNonDigitString =
    context.electionId === undefined ||
    context.electionId === null ||
    typeof context.electionId === 'string'

  if (isEmptyOrNonDigitString) {
    const numericCandidate =
      context.numericElectionId !== undefined && context.numericElectionId !== null
        ? context.numericElectionId
        : context.numeric_election_id
    const resolvedFallback = parsePositiveNumericElectionId(numericCandidate)
    if (resolvedFallback !== null) {
      return resolvedFallback
    }
  }

  throw new Error(
    `Invalid or missing numeric election ID (electionId=${String(context.electionId)}, ` +
      `numericElectionId=${String(context.numericElectionId ?? context.numeric_election_id)}). ` +
      'A positive integer numeric election ID is required for Fiat-Shamir transcript generation.'
  )
}

export function computeClientTranscriptHash({
  context,
  ciphertexts,
  candidateCommitments,
  sumCommitments,
  verifierAddress,
  chainId,
}) {
  const M = ciphertexts.length

  // 1. Header Hash
  const safeElectionId = resolveNumericElectionId(context)

  const headerHex =
    pad32(DOMAIN_SEPARATOR) +
    pad32(BigInt(chainId)) +
    pad32(verifierAddress) +
    pad32(safeElectionId) +
    pad32(context.pseudonym) +
    pad32(BigInt(context.sequence)) +
    pad32(BigInt(context.jointPubKey.x)) +
    pad32(BigInt(context.jointPubKey.y)) +
    pad32(BigInt(M))

  const headerHash = keccak256('0x' + headerHex)

  // 2. Ciphertext Array Hash: encode tuple(G1Point a, G1Point b)[]
  let ctHex = pad32(32n) + pad32(BigInt(M)) // offset + length
  for (const ct of ciphertexts) {
    ctHex += pad32(BigInt(ct.a.x)) + pad32(BigInt(ct.a.y)) + pad32(BigInt(ct.b.x)) + pad32(BigInt(ct.b.y))
  }
  const ctHash = keccak256('0x' + ctHex)

  // 3. Commitments Array Hash
  let commHex = pad32(32n) + pad32(BigInt(M))
  for (const c of candidateCommitments) {
    commHex +=
      pad32(BigInt(c.t_a_0.x)) + pad32(BigInt(c.t_a_0.y)) +
      pad32(BigInt(c.t_b_0.x)) + pad32(BigInt(c.t_b_0.y)) +
      pad32(BigInt(c.t_a_1.x)) + pad32(BigInt(c.t_a_1.y)) +
      pad32(BigInt(c.t_b_1.x)) + pad32(BigInt(c.t_b_1.y))
  }
  const commHash = keccak256('0x' + commHex)

  // 4. Sum Commitments Hash
  const sumCommHex =
    pad32(BigInt(sumCommitments.t_a_sum.x)) + pad32(BigInt(sumCommitments.t_a_sum.y)) +
    pad32(BigInt(sumCommitments.t_b_sum.x)) + pad32(BigInt(sumCommitments.t_b_sum.y))
  const sumCommHash = keccak256('0x' + sumCommHex)

  // Final Master Challenge Hash
  const finalHex = pad32(headerHash) + pad32(ctHash) + pad32(commHash) + pad32(sumCommHash)
  return keccak256('0x' + finalHex)
}

export function generateClientBallotProof({
  selectedCandidate,
  candidateCount,
  context,
  verifierAddress,
  chainId,
  customNonces = null,
}) {
  const M = candidateCount
  const Y = { x: BigInt(context.jointPubKey.x), y: BigInt(context.jointPubKey.y) }
  validatePoint(Y)

  const ciphertexts = []
  const candidateCommitments = []
  const rValues = []
  const simChallenges = []
  const simResponses = []
  const realWitnesses = []

  for (let j = 0; j < M; j++) {
    const v_j = j === selectedCandidate ? 1n : 0n
    const r_j = customNonces ? BigInt(customNonces.r[j]) : generateClientSecureScalar()
    rValues.push(r_j)

    // ElGamal: A = r * G, B = r * Y + v * G
    const A = pointMul(G, r_j)
    let B = pointMul(Y, r_j)
    if (v_j === 1n) {
      B = pointAdd(B, G)
    }

    ciphertexts.push({
      a: { x: A.x.toString(), y: A.y.toString() },
      b: { x: B.x.toString(), y: B.y.toString() },
    })

    const w_j = customNonces ? BigInt(customNonces.w[j]) : generateClientSecureScalar()
    const sim_c = customNonces ? BigInt(customNonces.simC[j]) : generateClientSecureScalar()
    const sim_z = customNonces ? BigInt(customNonces.simZ[j]) : generateClientSecureScalar()

    realWitnesses.push(w_j)
    simChallenges.push(sim_c)
    simResponses.push(sim_z)

    let t_a_0, t_b_0, t_a_1, t_b_1

    if (v_j === 0n) {
      // Real branch 0
      t_a_0 = pointMul(G, w_j)
      t_b_0 = pointMul(Y, w_j)

      // Simulated branch 1
      t_a_1 = pointSub(pointMul(G, sim_z), pointMul(A, sim_c))
      const B_minus_G = pointSub(B, G)
      t_b_1 = pointSub(pointMul(Y, sim_z), pointMul(B_minus_G, sim_c))
    } else {
      // Simulated branch 0
      t_a_0 = pointSub(pointMul(G, sim_z), pointMul(A, sim_c))
      t_b_0 = pointSub(pointMul(Y, sim_z), pointMul(B, sim_c))

      // Real branch 1
      t_a_1 = pointMul(G, w_j)
      t_b_1 = pointMul(Y, w_j)
    }

    candidateCommitments.push({
      t_a_0: { x: t_a_0.x.toString(), y: t_a_0.y.toString() },
      t_b_0: { x: t_b_0.x.toString(), y: t_b_0.y.toString() },
      t_a_1: { x: t_a_1.x.toString(), y: t_a_1.y.toString() },
      t_b_1: { x: t_b_1.x.toString(), y: t_b_1.y.toString() },
    })
  }

  // Sum commitments
  const w_sum = customNonces ? BigInt(customNonces.w_sum) : generateClientSecureScalar()
  const t_a_sum = pointMul(G, w_sum)
  const t_b_sum = pointMul(Y, w_sum)
  const sumCommitments = {
    t_a_sum: { x: t_a_sum.x.toString(), y: t_a_sum.y.toString() },
    t_b_sum: { x: t_b_sum.x.toString(), y: t_b_sum.y.toString() },
  }

  // Master Fiat-Shamir Challenge
  const transcriptHash = computeClientTranscriptHash({
    context,
    ciphertexts,
    candidateCommitments,
    sumCommitments,
    verifierAddress,
    chainId,
  })
  const c_master = modQ(BigInt(transcriptHash))

  const candidateProofs = []
  for (let j = 0; j < M; j++) {
    const v_j = j === selectedCandidate ? 1n : 0n
    const c_j_hash = keccak256('0x' + pad32(c_master) + pad32(BigInt(j)))
    const c_j = modQ(BigInt(c_j_hash))

    let c0, c1, z0, z1
    if (v_j === 0n) {
      c1 = simChallenges[j]
      z1 = simResponses[j]
      c0 = modQ(c_j - c1)
      z0 = modQ(realWitnesses[j] + c0 * rValues[j])
    } else {
      c0 = simChallenges[j]
      z0 = simResponses[j]
      c1 = modQ(c_j - c0)
      z1 = modQ(realWitnesses[j] + c1 * rValues[j])
    }

    candidateProofs.push({
      c0: c0.toString(),
      c1: c1.toString(),
      z0: z0.toString(),
      z1: z1.toString(),
    })
  }

  let sumR = 0n
  for (const r of rValues) {
    sumR = modQ(sumR + r)
  }

  // Sum challenge with string "SUM"
  // abi.encode(uint256, string): uint256 + offset(0x40) + len(3) + "SUM" padded
  const sumStrHex = pad32(c_master) + pad32(64n) + pad32(3n) + '53554d' + '0'.repeat(58)
  const c_sum_hash = keccak256('0x' + sumStrHex)
  const c_sum = modQ(BigInt(c_sum_hash))
  const z_sum = modQ(w_sum + c_sum * sumR)

  const proof = {
    candidateCommitments,
    candidateProofs,
    sumCommitments,
    z_sum: z_sum.toString(),
  }

  return {
    ciphertexts,
    proof,
    c_master: c_master.toString(),
  }
}

// ==============================================================================
// 7. Client-Side Chaum-Pedersen DLEQ Decryption Share Generator
// ==============================================================================
export function computeClientDLEQChallenge({
  officerId,
  j,
  Y_i,
  A_j,
  D_j,
  proof_u,
  proof_v,
  electionId,
  contractAddress,
  chainId,
}) {
  const headHex =
    pad32(DLEQ_DOMAIN_SEPARATOR) +
    pad32(BigInt(chainId)) +
    pad32(contractAddress) +
    pad32(BigInt(electionId)) +
    pad32(BigInt(officerId)) +
    pad32(BigInt(j))
  const headHash = keccak256('0x' + headHex)

  const pointsHex =
    pad32(BigInt(Y_i.x)) + pad32(BigInt(Y_i.y)) +
    pad32(BigInt(A_j.x)) + pad32(BigInt(A_j.y)) +
    pad32(BigInt(D_j.x)) + pad32(BigInt(D_j.y)) +
    pad32(BigInt(proof_u.x)) + pad32(BigInt(proof_u.y)) +
    pad32(BigInt(proof_v.x)) + pad32(BigInt(proof_v.y))
  const pointsHash = keccak256('0x' + pointsHex)

  const finalHex = pad32(headHash) + pad32(pointsHash)
  return modQ(BigInt(keccak256('0x' + finalHex)))
}

export function generateClientDecryptionShares({
  officerPrivKey,
  officerId,
  aggregateA,
  electionId,
  contractAddress,
  chainId,
  customWitnesses = null,
}) {
  const s = BigInt(officerPrivKey)
  validateScalar(s)
  const Y = pointMul(G, s)

  const shares = []
  const proofs = []

  for (let j = 0; j < aggregateA.length; j++) {
    const A_j = { x: BigInt(aggregateA[j].x), y: BigInt(aggregateA[j].y) }

    if (isInfinity(A_j)) {
      shares.push({ x: '0', y: '0' })
      proofs.push({
        u: { x: '0', y: '0' },
        v: { x: '0', y: '0' },
        z: '0',
      })
    } else {
      validatePoint(A_j)
      const D_j = pointMul(A_j, s)
      shares.push({ x: D_j.x.toString(), y: D_j.y.toString() })

      const t_j = customWitnesses ? BigInt(customWitnesses[j]) : generateClientSecureScalar()
      const U_j = pointMul(G, t_j)
      const V_j = pointMul(A_j, t_j)

      const c = computeClientDLEQChallenge({
        officerId,
        j,
        Y_i: Y,
        A_j,
        D_j,
        proof_u: U_j,
        proof_v: V_j,
        electionId,
        contractAddress,
        chainId,
      })
      const z_j = modQ(t_j + c * s)

      proofs.push({
        u: { x: U_j.x.toString(), y: U_j.y.toString() },
        v: { x: V_j.x.toString(), y: V_j.y.toString() },
        z: z_j.toString(),
      })
    }
  }

  return { shares, proofs }
}
