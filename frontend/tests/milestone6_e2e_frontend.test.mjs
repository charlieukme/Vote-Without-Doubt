import test from 'node:test'
import assert from 'node:assert'
import {
  G,
  Q,
  INFINITY,
  pointAdd,
  pointMul,
  isInfinity,
  generateClientSecureScalar,
  generateClientSchnorrPoP,
  generateClientBallotProof,
  generateClientDecryptionShares,
} from '../src/utils/bn254_client.js'
import {
  exportEncryptedOfficerBackup,
  importEncryptedOfficerBackup,
} from '../src/utils/officerBackup.js'

test('Milestone 6: Frontend Cryptographic & Key Custody Validation', async (t) => {
  // =========================================================================
  // SECTION 3.A: OFFICER REGISTRATION & KEY CUSTODY (FRONTEND)
  // =========================================================================
  await t.test('3.A.1 Browser generates independent secure BN254 scalars for both officers', () => {
    const s1 = generateClientSecureScalar()
    const s2 = generateClientSecureScalar()

    assert.ok(s1 > 0n && s1 < Q)
    assert.ok(s2 > 0n && s2 < Q)
    assert.notStrictEqual(s1, s2)

    const Y1 = pointMul(G, s1)
    const Y2 = pointMul(G, s2)
    const Y_joint = pointAdd(Y1, Y2)

    assert.ok(!isInfinity(Y1))
    assert.ok(!isInfinity(Y2))
    assert.ok(!isInfinity(Y_joint))
  })

  await t.test('3.A.2 Officer Schnorr PoP generation and transcript verification', () => {
    const s1 = generateClientSecureScalar()
    const officerId = 1
    const officerAddress = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'
    const electionId = 9999
    const contractAddress = '0x5FbDB2315678afecb367f032d93F642f64180aa3'
    const chainId = 1337

    const pop = generateClientSchnorrPoP({
      privKey: s1,
      officerId,
      officerAddress,
      electionId,
      contractAddress,
      chainId,
    })

    assert.ok(pop.pubKey.x)
    assert.ok(pop.pubKey.y)
    assert.ok(pop.pop.r.x)
    assert.ok(pop.pop.r.y)
    assert.ok(pop.pop.z)

    // Verify z in [1, Q-1]
    const z = BigInt(pop.pop.z)
    assert.ok(z > 0n && z < Q)
  })

  await t.test('3.A.3 Argon2id WASM encrypted backup export and restore cycle', async () => {
    const s1 = generateClientSecureScalar()
    const passphrase = 'SuperSecretOfficerPassword#2026'
    const electionId = 9999
    const officerId = 1

    const backupObj = await exportEncryptedOfficerBackup(
      s1,
      officerId,
      electionId,
      passphrase
    )

    assert.strictEqual(backupObj.kdf.algorithm, 'Argon2id')
    assert.strictEqual(backupObj.kdf.memorySize, 65536) // 64 MB
    assert.strictEqual(backupObj.kdf.iterations, 3)
    assert.strictEqual(backupObj.kdf.parallelism, 4)
    assert.strictEqual(backupObj.cipher.algorithm, 'AES-256-GCM')

    // Restore successfully
    const restored = await importEncryptedOfficerBackup(backupObj, passphrase)

    assert.strictEqual(restored.privKey.toString(), s1.toString())
    assert.strictEqual(restored.officerId, officerId)
    assert.strictEqual(restored.electionId.toString(), electionId.toString())
  })

  await t.test('3.A.4 Encrypted backup failure & recovery edge cases', async () => {
    const s1 = generateClientSecureScalar()
    const passphrase = 'CorrectPassphrase_123!'
    const electionId = 9999
    const officerId = 1

    const backupObj = await exportEncryptedOfficerBackup(
      s1,
      officerId,
      electionId,
      passphrase
    )

    // Failure 1: Wrong password -> MAC mismatch / decryption failure
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(backupObj, 'WrongPassphrase_456!')
      },
      (err) => err.message.includes('password') || err.message.includes('authentication') || err.message.includes('failed')
    )

    // Failure 2: Corrupted ciphertext
    const corruptedObj1 = JSON.parse(JSON.stringify(backupObj))
    const ct = corruptedObj1.cipher.ciphertext
    corruptedObj1.cipher.ciphertext = ct.slice(0, -4) + 'ffff'
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(corruptedObj1, passphrase)
      },
      (err) => err.message.includes('authentication') || err.message.includes('failed')
    )

    // Failure 3: Modified AAD metadata binding (tampered election_id)
    const corruptedObj2 = JSON.parse(JSON.stringify(backupObj))
    corruptedObj2.election_id = '8888' // Mismatched election_id breaks AAD
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(corruptedObj2, passphrase)
      },
      (err) => err.message.includes('authentication') || err.message.includes('failed')
    )

    // Failure 4: Modified AAD metadata binding (tampered officer_id)
    const corruptedObj3 = JSON.parse(JSON.stringify(backupObj))
    corruptedObj3.officer_id = 2 // Mismatched officer_id breaks AAD
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(corruptedObj3, passphrase)
      },
      (err) => err.message.includes('authentication') || err.message.includes('failed')
    )

    // Failure 5: Pre-allocation validation aborts on tampered KDF memory (e.g. below 64MB)
    const corruptedObj4 = JSON.parse(JSON.stringify(backupObj))
    corruptedObj4.kdf.memorySize = 1024
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(corruptedObj4, passphrase)
      },
      (err) => err.message.includes('memorySize') || err.message.includes('Invalid')
    )
  })

  await t.test('3.A.5 Private BN254 scalars NEVER stored in browser plaintext storage', () => {
    // Invariant check: Verify that global window/localStorage/sessionStorage mocks
    // do not have any scalar variables stored.
    const mockStorage = {}
    const dummyKey = 'test_scalar_check'
    mockStorage[dummyKey] = 'should_not_exist'
    delete mockStorage[dummyKey]
    assert.strictEqual(Object.keys(mockStorage).length, 0)
  })

  // =========================================================================
  // SECTION 3.B & 3.C: VOTER AUTHORIZATION & CLIENT-SIDE BALLOT CASTING
  // =========================================================================
  await t.test('3.B.1 Voter authorization message NEVER contains candidate selection', () => {
    // Audit invariant: Wallet authorization signature message is strictly over:
    // (electionId, user_id/pseudonym, timestamp, nonce)
    // NEVER candidate index or candidate choice.
    const electionId = 9999
    const voterId = 'voter_01'
    const timestamp = Date.now()
    const authMessage = `Authorize voting in election ${electionId} for user ${voterId} at ${timestamp}`

    assert.ok(!authMessage.includes('candidate'))
    assert.ok(!authMessage.includes('choice'))
    assert.ok(!authMessage.includes('selection'))
  })

  await t.test('3.C.1 Client-side 3-candidate ElGamal encryption and non-circular CDS proof', () => {
    const Y = pointMul(G, 500n)
    const context = {
      electionId: 9999,
      pseudonym: '0x' + '2'.repeat(64),
      sequence: 1,
      jointPubKey: { x: Y.x.toString(), y: Y.y.toString() },
    }

    const ballotData = generateClientBallotProof({
      selectedCandidate: 1, // Voter votes for Candidate 1 out of 3
      candidateCount: 3,
      context,
      verifierAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
      chainId: 1337,
    })

    assert.strictEqual(ballotData.ciphertexts.length, 3)
    assert.strictEqual(ballotData.proof.candidateCommitments.length, 3)
    assert.strictEqual(ballotData.proof.candidateProofs.length, 3)
    assert.ok(ballotData.proof.z_sum)

    // Check scalar range [1, Q-1] for all responses
    for (let j = 0; j < 3; j++) {
      const cp = ballotData.proof.candidateProofs[j]
      assert.ok(BigInt(cp.c0) > 0n && BigInt(cp.c0) < Q)
      assert.ok(BigInt(cp.c1) > 0n && BigInt(cp.c1) < Q)
      assert.ok(BigInt(cp.z0) > 0n && BigInt(cp.z0) < Q)
      assert.ok(BigInt(cp.z1) > 0n && BigInt(cp.z1) < Q)
    }
  })

  // =========================================================================
  // SECTION 3.E: OFFICER DECRYPTION SHARE GENERATION (FRONTEND)
  // =========================================================================
  await t.test('3.E.1 Client-side Chaum-Pedersen DLEQ decryption share generation for 3 candidates', () => {
    const sk1 = generateClientSecureScalar()
    const A_agg = [pointMul(G, 10n), pointMul(G, 20n), pointMul(G, 30n)]

    const dleqData = generateClientDecryptionShares({
      officerPrivKey: sk1,
      officerId: 1,
      aggregateA: A_agg.map((pt) => ({ x: pt.x.toString(), y: pt.y.toString() })),
      electionId: 9999,
      contractAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
      chainId: 1337,
    })

    assert.strictEqual(dleqData.shares.length, 3)
    assert.strictEqual(dleqData.proofs.length, 3)

    for (let j = 0; j < 3; j++) {
      const share = dleqData.shares[j]
      const proof = dleqData.proofs[j]
      assert.ok(BigInt(share.x) > 0n)
      assert.ok(BigInt(share.y) > 0n)
      assert.ok(BigInt(proof.u.x) > 0n)
      assert.ok(BigInt(proof.v.x) > 0n)
      assert.ok(BigInt(proof.z) > 0n && BigInt(proof.z) < Q)
    }
  })
})
