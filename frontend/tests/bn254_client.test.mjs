import test from 'node:test'
import assert from 'node:assert/strict'
import {
  P,
  Q,
  G,
  INFINITY,
  isOnCurve,
  isInfinity,
  pointAdd,
  pointSub,
  pointMul,
  pointNeg,
  keccak256,
  generateClientSecureScalar,
  generateClientSchnorrPoP,
  computeClientTranscriptHash,
  generateClientBallotProof,
  generateClientDecryptionShares,
} from '../src/utils/bn254_client.js'

test('1. BN254 G1 Generator G=(1, 2) is on curve and finite', () => {
  assert.equal(isOnCurve(G), true)
  assert.equal(isInfinity(G), false)
})

test('2. Point addition identity G + O = G and O + G = G', () => {
  assert.deepEqual(pointAdd(G, INFINITY), G)
  assert.deepEqual(pointAdd(INFINITY, G), G)
})

test('3. Point negation and subtraction G + (-G) = O', () => {
  const negG = pointNeg(G)
  assert.equal(isOnCurve(negG), true)
  assert.equal(negG.x, 1n)
  assert.equal(negG.y, P - 2n)
  assert.deepEqual(pointAdd(G, negG), INFINITY)
  assert.deepEqual(pointSub(G, G), INFINITY)
})

test('4. Subgroup order identity q * G = O', () => {
  const res = pointMul(G, Q)
  assert.equal(isInfinity(res), true)
})

test('5. Keccak-256 standard test vectors match EVM', () => {
  // Empty string keccak256
  assert.equal(
    keccak256(''),
    '0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
  )
  // "hello" keccak256
  assert.equal(
    keccak256('hello'),
    '0x1c8aff950685c2ed4bc3174f3472287b56d9517b9c948127319a09a7a36deac8'
  )
})

test('6. Client-Side Schnorr PoP produces on-curve keys and valid response', () => {
  const privKey = generateClientSecureScalar()
  const electionId = 8888
  const officerAddr = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'
  const contractAddr = '0x5FbDB2315678afecb367f032d93F642f64180aa3'

  const popData = generateClientSchnorrPoP({
    privKey,
    officerId: 1,
    officerAddress: officerAddr,
    electionId,
    contractAddress: contractAddr,
    chainId: 1337,
  })

  const Y = { x: BigInt(popData.pubKey.x), y: BigInt(popData.pubKey.y) }
  const R = { x: BigInt(popData.pop.r.x), y: BigInt(popData.pop.r.y) }

  assert.equal(isOnCurve(Y), true)
  assert.equal(isOnCurve(R), true)
  assert.ok(BigInt(popData.pop.z) > 0n)
  assert.ok(BigInt(popData.pop.z) < Q)
})

test('7. Client-Side Non-Circular CDS Ballot Proof generates correct vector lengths', () => {
  const s1 = generateClientSecureScalar()
  const s2 = generateClientSecureScalar()
  const Y_joint = pointAdd(pointMul(G, s1), pointMul(G, s2))

  const context = {
    electionId: 8888,
    pseudonym: '0x' + '1'.repeat(64),
    sequence: 1,
    jointPubKey: { x: Y_joint.x.toString(), y: Y_joint.y.toString() },
  }

  const ballot = generateClientBallotProof({
    selectedCandidate: 0,
    candidateCount: 2,
    context,
    verifierAddress: '0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512',
    chainId: 1337,
  })

  assert.equal(ballot.ciphertexts.length, 2)
  assert.equal(ballot.proof.candidateCommitments.length, 2)
  assert.equal(ballot.proof.candidateProofs.length, 2)
  assert.ok(BigInt(ballot.proof.z_sum) > 0n)
  assert.ok(BigInt(ballot.c_master) > 0n)
})

test('8. Client-Side DLEQ Decryption Shares handles infinity branch', () => {
  const s1 = generateClientSecureScalar()
  const A0 = pointMul(G, 12345n)
  const A1 = INFINITY // Zero-vote coordinate

  const decData = generateClientDecryptionShares({
    officerPrivKey: s1,
    officerId: 1,
    aggregateA: [A0, A1],
    electionId: 8888,
    contractAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
    chainId: 1337,
  })

  assert.equal(decData.shares.length, 2)
  assert.equal(decData.proofs.length, 2)

  // Coordinate 0 (finite)
  assert.notEqual(decData.shares[0].x, '0')
  assert.notEqual(decData.proofs[0].z, '0')

  // Coordinate 1 (infinity)
  assert.equal(decData.shares[1].x, '0')
  assert.equal(decData.shares[1].y, '0')
  assert.equal(decData.proofs[1].u.x, '0')
  assert.equal(decData.proofs[1].v.x, '0')
  assert.equal(decData.proofs[1].z, '0')
})

test('9. computeClientTranscriptHash requires explicit numeric election ID (no Election 12 fallback)', () => {
  const s1 = generateClientSecureScalar()
  const Y_joint = pointMul(G, s1)
  const verifierAddress = '0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512'
  const chainId = 1337
  const pseudonym = '0x' + '2'.repeat(64)

  const sampleVectors = {
    ciphertexts: [
      { a: G, b: G },
      { a: G, b: G },
    ],
    candidateCommitments: [
      { t_a_0: G, t_b_0: G, t_a_1: G, t_b_1: G },
      { t_a_0: G, t_b_0: G, t_a_1: G, t_b_1: G },
    ],
    sumCommitments: { t_a_sum: G, t_b_sum: G },
    verifierAddress,
    chainId,
  }

  // Distinct transcript hashes across Elections 9, 11, 12, and a new election ID (13)
  const hashFor = (idOrCtx) =>
    computeClientTranscriptHash({
      context: {
        pseudonym,
        sequence: 1,
        jointPubKey: { x: Y_joint.x.toString(), y: Y_joint.y.toString() },
        ...(typeof idOrCtx === 'object' ? idOrCtx : { electionId: idOrCtx }),
      },
      ...sampleVectors,
    })

  const h9 = hashFor(9)
  const h11 = hashFor(11)
  const h12 = hashFor(12)
  const h13 = hashFor(13)

  assert.equal(new Set([h9, h11, h12, h13]).size, 4)

  // Public string election_id with explicit numericElectionId must match numeric electionId exactly
  assert.equal(hashFor({ electionId: 'ELEC_20261110140216_75CE', numericElectionId: 9 }), h9)
  assert.equal(hashFor({ electionId: 'ELEC_20261111105119_3BFD', numericElectionId: 11 }), h11)
  assert.equal(hashFor({ electionId: 'ELEC_20261111140652_38E2', numericElectionId: 12 }), h12)
  assert.equal(hashFor({ electionId: 'ELEC_NEW_13', numeric_election_id: 13 }), h13)

  // Missing or non-numeric electionId without valid numeric fallback must throw descriptively (never fall back to 12)
  const invalidContexts = [
    { electionId: 'ELEC_20261111105119_3BFD' },
    { electionId: 'ELEC_NEW_ELECTION' },
    { electionId: '' },
    { electionId: null },
    { electionId: undefined },
    { electionId: 0 },
    { electionId: -1 },
    { electionId: 12.5 },
    { electionId: 'ELEC_BAD', numericElectionId: 0 },
  ]

  for (const invalidCtx of invalidContexts) {
    assert.throws(
      () => hashFor(invalidCtx),
      /Invalid or missing numeric election ID/
    )
    assert.throws(
      () =>
        generateClientBallotProof({
          selectedCandidate: 0,
          candidateCount: 2,
          context: {
            pseudonym,
            sequence: 1,
            jointPubKey: { x: Y_joint.x.toString(), y: Y_joint.y.toString() },
            ...invalidCtx,
          },
          verifierAddress,
          chainId,
        }),
      /Invalid or missing numeric election ID/
    )
  }
})
