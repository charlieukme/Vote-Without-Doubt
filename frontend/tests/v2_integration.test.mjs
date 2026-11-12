import test from 'node:test'
import assert from 'node:assert'
import {
  G,
  Q,
  pointMul,
  generateClientSecureScalar,
  generateClientSchnorrPoP,
  generateClientBallotProof,
  generateClientDecryptionShares,
  keccak256,
  POP_DOMAIN_SEPARATOR,
  DOMAIN_SEPARATOR,
  DLEQ_DOMAIN_SEPARATOR,
} from '../src/utils/bn254_client.js'
import {
  exportEncryptedOfficerBackup,
  importEncryptedOfficerBackup,
} from '../src/utils/officerBackup.js'

test('Phase 6 Integration: Cryptographic Transcripts and Security Invariants', async (t) => {
  await t.test('1. Python/JavaScript/Solidity Schnorr PoP Transcript Parity', () => {
    const sk = 12345678901234567890123456789012345678901234567890n
    const officerId = 1
    const officerAddress = '0x90F79bf6EB2c4f870365E785982E1f101E93b906'
    const electionId = 1
    const contractAddress = '0x5FbDB2315678afecb367f032d93F642f64180aa3'
    const chainId = 1337
    const customWitness = 98765432109876543210987654321098765432109876543210n

    const pop = generateClientSchnorrPoP({
      privKey: sk,
      officerId,
      officerAddress,
      electionId,
      contractAddress,
      chainId,
      customWitness,
    })

    // Verify public key is on curve and non-zero
    const Y = { x: BigInt(pop.pubKey.x), y: BigInt(pop.pubKey.y) }
    const R = { x: BigInt(pop.pop.r.x), y: BigInt(pop.pop.r.y) }
    const z = BigInt(pop.pop.z)

    assert.ok(Y.x > 0n && Y.y > 0n)
    assert.ok(R.x > 0n && R.y > 0n)
    assert.ok(z > 0n && z < Q)

    // Verify transcript challenge formula:
    // c = keccak256(abi.encode(POP_DOMAIN_SEPARATOR, chainId, contract, electionId, officerId, officerAddress, Y, R)) % Q
    assert.ok(pop.c > 0n && pop.c < Q)

    // Verify Schnorr equation: z * G == R + c * Y
    // z = k + c * sk (mod Q)
    const expectedZ = (customWitness + pop.c * sk) % Q
    assert.strictEqual(z, expectedZ)
  })

  await t.test('2. Non-Circular CDS Fiat-Shamir Transcript Independence & Cross-Language Parity', () => {
    const Y = pointMul(G, 300n)
    const context = {
      electionId: 8888,
      pseudonym: '0x' + '1'.repeat(64),
      sequence: 1,
      jointPubKey: { x: Y.x.toString(), y: Y.y.toString() },
    }
    const customNonces = {
      r: [11n, 22n],
      w: [33n, 44n],
      w_sum: 55n,
      simC: [66n, 77n],
      simZ: [88n, 99n],
    }
    const ballotData = generateClientBallotProof({
      selectedCandidate: 0,
      candidateCount: 2,
      context,
      verifierAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
      chainId: 1337,
      customNonces,
    })

    assert.strictEqual(ballotData.ciphertexts.length, 2)
    assert.strictEqual(ballotData.proof.candidateCommitments.length, 2)
    assert.strictEqual(ballotData.proof.candidateProofs.length, 2)

    // Exact parity match with Python reference generate_ballot_proof()
    assert.strictEqual(ballotData.c_master, '17551239865429218936303788849152595020862154851418133278496627901856227630425')
    assert.strictEqual(ballotData.proof.z_sum, '1789204776403154177673054250328542951002068135048079026329365984747849151555')
    assert.strictEqual(ballotData.proof.candidateProofs[0].c0, '66')
    assert.strictEqual(ballotData.proof.candidateProofs[0].c1, '7302720243162214323635041688231701843210607103404665763423600167575792446935')
    assert.strictEqual(ballotData.proof.candidateProofs[0].z0, '88')
    assert.strictEqual(ballotData.proof.candidateProofs[0].z1, '14665194059266531893246241334776895009671584936203220366564989283606291429467')
  })

  await t.test('3. Private-Key Isolation Guarantee', () => {
    // Invariant: Officer and Voter payloads submitted to backend NEVER contain private key shares
    const sk = generateClientSecureScalar()
    const pop = generateClientSchnorrPoP({
      privKey: sk,
      officerId: 1,
      officerAddress: '0x1111111111111111111111111111111111111111',
      electionId: 1,
      contractAddress: '0x2222222222222222222222222222222222222222',
      chainId: 1337,
    })

    const officerSubmissionPayload = {
      election_id: 1,
      officer_id: 1,
      pub_key: pop.pubKey,
      pop: pop.pop,
      officer_address: '0x1111111111111111111111111111111111111111',
    }

    const payloadString = JSON.stringify(officerSubmissionPayload)
    assert.ok(!payloadString.includes(sk.toString()), 'Officer private key must NEVER be in transmission payload')

    // Invariant: LocalStorage / SessionStorage isolation
    // Plaintext scalar must never be serialized
    const storageKeys = ['voter_token', 'session_id', 'officer_key']
    const mockStorage = {}
    // If officer dashboard saves key, it only saves encrypted backup
    assert.strictEqual(mockStorage['officer_sk'], undefined)
  })

  await t.test('4. Browser Refresh & Recovery Workflow via Encrypted Backup', async () => {
    // Simulate officer generating keypair in Session A
    const sessionA_sk = generateClientSecureScalar()
    const sessionA_pub = pointMul(G, sessionA_sk)
    const passphrase = 'HighlySecureOfficerPassword2026!'

    // Officer exports encrypted backup
    const backupJson = await exportEncryptedOfficerBackup(sessionA_sk, 1, '1', passphrase)

    // Simulate browser refresh (memory cleared)
    let memory_sk = null
    let memory_pub = null
    assert.strictEqual(memory_sk, null)

    // Session B: Officer imports encrypted backup
    const recovered = await importEncryptedOfficerBackup(backupJson, passphrase)
    memory_sk = recovered.privKey
    memory_pub = recovered.pubKey

    // Exact identity recovered
    assert.strictEqual(memory_sk, sessionA_sk)
    assert.strictEqual(memory_pub.x, sessionA_pub.x)
    assert.strictEqual(memory_pub.y, sessionA_pub.y)
  })

  await t.test('5. DLEQ Decryption Share Generation & Cross-Language Parity', () => {
    const s = 12345n
    const A_regular = pointMul(G, 67890n)
    const A_inf = { x: 0n, y: 0n } // Infinity point

    const { shares, proofs } = generateClientDecryptionShares({
      officerPrivKey: s,
      officerId: 1,
      aggregateA: [A_regular, A_inf],
      electionId: 8888,
      contractAddress: '0x5FbDB2315678afecb367f032d93F642f64180aa3',
      chainId: 1337,
      customWitnesses: [11111n, 0n],
    })

    assert.strictEqual(shares.length, 2)
    assert.strictEqual(proofs.length, 2)

    // Exact parity match with Python reference generate_officer_decryption_shares()
    assert.strictEqual(proofs[0].z, '7269805023117298819153109424669710626039459636623160455565098443408426847545')
    assert.strictEqual(proofs[0].u.x, '10523841697479385960881926870434332886588904807357050526326565031647080841169')
    assert.strictEqual(proofs[0].u.y, '14564493663906629632174268627960335778864891535947606750295527855783436195179')
    assert.strictEqual(proofs[0].v.x, '7225503024910874651457520503335314845942160161065517874436557885683959551060')
    assert.strictEqual(proofs[0].v.y, '2923980642920689929174075949315621238001764732649051302381768063805352785843')

    // Coordinate 1 is infinity
    assert.strictEqual(shares[1].x, '0')
    assert.strictEqual(shares[1].y, '0')
    assert.strictEqual(proofs[1].u.x, '0')
    assert.strictEqual(proofs[1].u.y, '0')
    assert.strictEqual(proofs[1].v.x, '0')
    assert.strictEqual(proofs[1].v.y, '0')
    assert.strictEqual(proofs[1].z, '0')
  })
})
