import assert from 'node:assert'
import {
  computeClientCommitment,
  computeLeafHash,
  computeNodeHash,
  verifyClientInclusionProof,
  canonicalJson,
  computeAuditEventHash,
  verifyAuditChainAndMerkleRootAuthority,
  verifyReceiptOpeningAndInclusionWithAudit,
  bytesToHex,
  hexToBytes,
} from './src/utils/clientCommitment.js'

async function runTests() {
  console.log('=== FIX 1B: INDEPENDENT MERKLE ROOT AUTHORITY VERIFICATION TEST SUITE ===\n')

  const electionId = 'ELEC_TEST_2026'
  const onChainId = 1
  const contractAddress = '0x5FbDB2315678afecb367f032d93F642f64180aa3'
  const candidateIndex = 1
  const nonceHex = 'a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00'

  // 1. Compute client commitment
  const commitment = await computeClientCommitment(electionId, candidateIndex, nonceHex)
  const leaf0 = await computeClientCommitment(electionId, 0, '1111111111111111111111111111111111111111111111111111111111111111')
  const leaf1 = commitment // voter's leaf

  // Compute canonical Merkle root for a 2-leaf tree
  const h0 = await computeLeafHash(leaf0)
  const h1 = await computeLeafHash(leaf1)
  const rootBytes = await computeNodeHash(h0, h1)
  const authenticMerkleRoot = '0x' + bytesToHex(rootBytes)

  // Voter's inclusion proof: sibling is leaf0 on the left
  const auditPath = [{ direction: 'left', hash: '0x' + bytesToHex(h0) }]

  // Verify inclusion locally
  const localProof = await verifyClientInclusionProof(leaf1, authenticMerkleRoot, auditPath)
  assert.strictEqual(localProof.valid, true, 'Local proof reconstruction must be valid')

  // Construct a valid 3-event audit chain
  // Event 1: Genesis / Election Created
  const event1 = {
    id: 1,
    event_type: 'ELECTION_CREATED',
    created_at: '2026-10-31T12:00:00.000000Z',
    metadata: { election_id: electionId, title: 'Presidential Election' },
    previous_hash: null,
  }
  event1.current_hash = await computeAuditEventHash(event1)

  // Event 2: Merkle Root Finalized
  const event2 = {
    id: 2,
    event_type: 'ELECTION_MERKLE_ROOT_FINALIZED',
    created_at: '2026-10-31T12:05:00.000000Z',
    metadata: {
      election_id: electionId,
      merkle_root: authenticMerkleRoot,
      leaf_count: 2,
    },
    previous_hash: event1.current_hash,
  }
  event2.current_hash = await computeAuditEventHash(event2)

  // Event 3: Checkpoint Anchored (Head of the anchored segment)
  const event3 = {
    id: 3,
    event_type: 'AUDIT_CHECKPOINT_ANCHORED',
    created_at: '2026-10-31T12:10:00.000000Z',
    metadata: {
      election_id: electionId,
      checkpoint_event_id: 3,
      checkpoint_hash: event2.current_hash,
    },
    previous_hash: event2.current_hash,
  }
  event3.current_hash = await computeAuditEventHash(event3)

  const authenticChain = [event1, event2, event3]
  const onChainCheckpointAnchor = '0x' + event3.current_hash

  // Mock RPC handler for simulating responses
  function createMockFetch(anchorResponse, chainId = 1337) {
    return async (url, options) => {
      const body = JSON.parse(options.body)
      if (body.method === 'eth_chainId') {
        return {
          ok: true,
          json: async () => ({ jsonrpc: '2.0', id: body.id, result: '0x' + chainId.toString(16) }),
        }
      }
      if (body.method === 'eth_call') {
        if (!anchorResponse.success) {
          return {
            ok: true,
            json: async () => ({ jsonrpc: '2.0', id: body.id, error: { message: anchorResponse.error } }),
          }
        }
        // abi decode for (bytes32 anchor, uint256 blockNumber, uint256 updateCount)
        const anchorClean = anchorResponse.anchor.replace(/^0x/, '').padStart(64, '0')
        const blockHex = BigInt(anchorResponse.blockNumber).toString(16).padStart(64, '0')
        const countHex = BigInt(anchorResponse.updateCount).toString(16).padStart(64, '0')
        return {
          ok: true,
          json: async () => ({ jsonrpc: '2.0', id: body.id, result: '0x' + anchorClean + blockHex + countHex }),
        }
      }
      throw new Error(`Unexpected RPC call: ${body.method}`)
    }
  }

  // Save original fetch
  const originalFetch = globalThis.fetch

  try {
    // -------------------------------------------------------------
    // TEST 1: Correct audit chain and checkpoint accepted
    // -------------------------------------------------------------
    console.log('[TEST 1] Correct audit chain and checkpoint accepted...')
    globalThis.fetch = createMockFetch({
      success: true,
      anchor: onChainCheckpointAnchor,
      blockNumber: 42,
      updateCount: 1,
    })

    const test1Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: authenticChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test1Result.verified, true, 'Test 1 must pass overall verification')
    assert.strictEqual(test1Result.status, 'VALID_BALLOT_CERTIFIED')
    assert.strictEqual(test1Result.authenticatedMerkleRoot.toLowerCase(), authenticMerkleRoot.toLowerCase())
    console.log('✓ PASS: Valid chain and on-chain checkpoint certified!\n')

    // -------------------------------------------------------------
    // TEST 2: Modified audit event rejected
    // -------------------------------------------------------------
    console.log('[TEST 2] Modified audit event rejected (tampered event metadata)...')
    const tamperedChain = JSON.parse(JSON.stringify(authenticChain))
    // Tamper event 2 metadata (e.g. attacker changes root or timestamp)
    tamperedChain[1].metadata.merkle_root = '0xbad0000000000000000000000000000000000000000000000000000000000000'

    const test2Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: tamperedChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test2Result.verified, false, 'Tampered audit chain must NOT verify')
    assert.strictEqual(test2Result.status, 'AUDIT_CHAIN_INTEGRITY_COMPROMISED')
    console.log('✓ PASS: Modified audit event cleanly rejected!\n')

    // -------------------------------------------------------------
    // TEST 3: Incorrect checkpoint rejected
    // -------------------------------------------------------------
    console.log('[TEST 3] Incorrect checkpoint rejected (contract anchor does not match chain head)...')
    globalThis.fetch = createMockFetch({
      success: true,
      anchor: '0x' + 'ff'.repeat(32), // wrong anchor
      blockNumber: 43,
      updateCount: 1,
    })

    const test3Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: authenticChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test3Result.verified, false, 'Mismatched checkpoint must fail verification')
    assert.strictEqual(test3Result.status, 'CHECKPOINT_MISMATCH')
    console.log('✓ PASS: Incorrect on-chain checkpoint anchor rejected!\n')

    // -------------------------------------------------------------
    // TEST 4: Backend-supplied fabricated root rejected
    // -------------------------------------------------------------
    console.log('[TEST 4] Backend-supplied fabricated root rejected...')
    // In this case, say backend returns an audit path that reconstructs a fabricated root,
    // but the on-chain audit chain authenticated a different root!
    globalThis.fetch = createMockFetch({
      success: true,
      anchor: onChainCheckpointAnchor,
      blockNumber: 42,
      updateCount: 1,
    })

    // Sibling modified so reconstructed root != authenticMerkleRoot
    const fabricatedAuditPath = [{ direction: 'left', hash: '0x' + '99'.repeat(32) }]

    const test4Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath: fabricatedAuditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: authenticChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test4Result.verified, false, 'Fabricated root must be rejected')
    assert.strictEqual(test4Result.status, 'FABRICATED_ROOT_REJECTED')
    console.log('✓ PASS: Fabricated root rejected against authenticated audit chain!\n')

    // -------------------------------------------------------------
    // TEST 5: RPC unavailable does not produce a green verification result
    // -------------------------------------------------------------
    console.log('[TEST 5] RPC unavailable does not produce a green verification result...')
    globalThis.fetch = async () => {
      throw new Error('Connection refused (ECONNREFUSED 127.0.0.1:8545)')
    }

    const test5Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: authenticChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test5Result.verified, false, 'Must fail when RPC is unreachable')
    assert.strictEqual(test5Result.status, 'RPC_UNAVAILABLE')
    console.log('✓ PASS: Unavailable RPC fails closed and never produces green result!\n')

    // -------------------------------------------------------------
    // TEST 6: Incorrect Chain ID rejected
    // -------------------------------------------------------------
    console.log('[TEST 6] Incorrect Chain ID rejected...')
    globalThis.fetch = createMockFetch(
      { success: true, anchor: onChainCheckpointAnchor, blockNumber: 42, updateCount: 1 },
      1 // mainnet instead of 1337
    )

    const test6Result = await verifyReceiptOpeningAndInclusionWithAudit({
      electionId,
      candidateIndex,
      nonceHex,
      expectedCommitment: commitment,
      auditPath,
      onChainId,
      contractAddress,
      rpcUrl: 'http://mock-rpc',
      auditEvents: authenticChain,
      expectedChainId: 1337,
    })

    assert.strictEqual(test6Result.verified, false, 'Wrong chain ID must fail')
    assert.strictEqual(test6Result.status, 'CHAIN_ID_MISMATCH')
    console.log('✓ PASS: Chain ID mismatch detected and rejected!\n')

    console.log('=================================================================')
    console.log('ALL FIX 1B CLIENT CRYPTOGRAPHIC TESTS PASSED (6/6)!')
    console.log('=================================================================')
  } finally {
    globalThis.fetch = originalFetch
  }
}

runTests().catch((err) => {
  console.error('Test suite failed:', err)
  process.exit(1)
})
