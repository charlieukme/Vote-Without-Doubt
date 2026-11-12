/**
 * Client-Side Cryptographic Commitment & Merkle Proof Verifier
 * Vote Without Doubt - Phase 1 Remediation
 *
 * Implements:
 * 1. Client-Side CSPRNG Nonce Generation via window.crypto.getRandomValues
 * 2. Canonical Ballot Commitment computation matching backend:
 *    SHA256("VWD_BALLOT_COMMITMENT_V1:" + election_id + ":" + candidate_index + ":" + nonce)
 * 3. Client-Side Merkle Inclusion Proof verification per RFC 6962:
 *    Leaf Hash: H(0x00 || commitment)
 *    Node Hash: H(0x01 || left || right)
 * 4. Independent Receipt Opening and Cryptographic Certification
 */

const DOMAIN_BALLOT_COMMITMENT = 'VWD_BALLOT_COMMITMENT_V1:'
const RFC6962_LEAF_PREFIX = new Uint8Array([0x00])
const RFC6962_NODE_PREFIX = new Uint8Array([0x01])

/**
 * Convert Uint8Array to lowercase hex string.
 */
export function bytesToHex(bytes) {
  return Array.from(bytes)
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Convert hex string to Uint8Array.
 */
export function hexToBytes(hex) {
  const clean = hex.trim().toLowerCase().replace(/^0x/, '')
  if (clean.length % 2 !== 0) {
    throw new Error('Hex string must have an even length.')
  }
  const bytes = new Uint8Array(clean.length / 2)
  for (let i = 0; i < clean.length; i += 2) {
    bytes[i / 2] = parseInt(clean.substring(i, i + 2), 16)
  }
  return bytes
}

/**
 * Generate 256 bits (32 bytes) of cryptographically secure random entropy in browser or runtime.
 */
export function generateClientNonce() {
  const c = (typeof window !== 'undefined' ? window.crypto : null) || globalThis.crypto
  if (!c || !c.getRandomValues) {
    throw new Error('Web Crypto API (crypto.getRandomValues) is required.')
  }
  const nonceBytes = new Uint8Array(32)
  c.getRandomValues(nonceBytes)
  return {
    bytes: nonceBytes,
    hex: bytesToHex(nonceBytes),
  }
}

/**
 * Compute SHA-256 hash using Web Crypto API.
 */
export async function sha256(data) {
  const c = (typeof window !== 'undefined' ? window.crypto : null) || globalThis.crypto
  if (!c || !c.subtle || !c.subtle.digest) {
    throw new Error('Web Crypto API (crypto.subtle.digest) is required.')
  }
  const hashBuffer = await c.subtle.digest('SHA-256', data)
  return new Uint8Array(hashBuffer)
}

/**
 * Compute canonical ballot commitment in the browser.
 *
 * Formula:
 * SHA256("VWD_BALLOT_COMMITMENT_V1:" + election_id + ":" + candidate_index + ":" + nonceBytes)
 */
export async function computeClientCommitment(electionId, candidateIndex, nonce) {
  const nonceBytes = typeof nonce === 'string' ? hexToBytes(nonce) : nonce
  if (!nonceBytes || nonceBytes.length !== 32) {
    throw new Error('Nonce must be exactly 32 bytes (256 bits).')
  }

  const prefixBytes = new TextEncoder().encode(DOMAIN_BALLOT_COMMITMENT)
  const eidBytes = new TextEncoder().encode(String(electionId).trim())
  const colon = new TextEncoder().encode(':')
  const candBytes = new TextEncoder().encode(String(parseInt(candidateIndex, 10)))

  const totalLen = prefixBytes.length + eidBytes.length + 1 + candBytes.length + 1 + 32
  const payload = new Uint8Array(totalLen)
  let offset = 0

  payload.set(prefixBytes, offset); offset += prefixBytes.length
  payload.set(eidBytes, offset); offset += eidBytes.length
  payload.set(colon, offset); offset += colon.length
  payload.set(candBytes, offset); offset += candBytes.length
  payload.set(colon, offset); offset += colon.length
  payload.set(nonceBytes, offset)

  const digestBytes = await sha256(payload)
  return bytesToHex(digestBytes)
}

/**
 * Compute RFC 6962 leaf hash: H(0x00 || commitmentBytes)
 */
export async function computeLeafHash(commitmentHex) {
  const commitmentBytes = hexToBytes(commitmentHex)
  if (commitmentBytes.length !== 32) {
    throw new Error('Commitment must be 32 bytes.')
  }
  const payload = new Uint8Array(1 + 32)
  payload.set(RFC6962_LEAF_PREFIX, 0)
  payload.set(commitmentBytes, 1)
  return await sha256(payload)
}

/**
 * Compute RFC 6962 node hash: H(0x01 || left || right)
 */
export async function computeNodeHash(leftBytes, rightBytes) {
  if (leftBytes.length !== 32 || rightBytes.length !== 32) {
    throw new Error('Child nodes must be 32 bytes each.')
  }
  const payload = new Uint8Array(1 + 64)
  payload.set(RFC6962_NODE_PREFIX, 0)
  payload.set(leftBytes, 1)
  payload.set(rightBytes, 33)
  return await sha256(payload)
}

/**
 * Verify an RFC 6962 Merkle inclusion proof in Javascript.
 * Returns { valid: boolean, reconstructedRoot: string, expectedRoot: string, error?: string }
 */
export async function verifyClientInclusionProof(commitmentHex, merkleRootHex, auditPath) {
  try {
    const cleanCommitment = commitmentHex.trim().toLowerCase().replace(/^0x/, '')
    const cleanExpectedRoot = merkleRootHex.trim().toLowerCase().replace(/^0x/, '')

    if (cleanExpectedRoot.length !== 64) {
      return { valid: false, error: 'Malformed expected Merkle root.' }
    }

    let current = await computeLeafHash(cleanCommitment)

    for (let i = 0; i < (auditPath || []).length; i++) {
      const step = auditPath[i]
      const siblingHex = (step.hash || '').trim().toLowerCase().replace(/^0x/, '')
      const siblingBytes = hexToBytes(siblingHex)
      if (siblingBytes.length !== 32) {
        return { valid: false, error: `Malformed sibling hash at index ${i}.` }
      }

      const direction = (step.direction || '').toLowerCase()
      if (direction === 'right') {
        current = await computeNodeHash(current, siblingBytes)
      } else if (direction === 'left') {
        current = await computeNodeHash(siblingBytes, current)
      } else {
        return { valid: false, error: `Invalid direction '${direction}' at index ${i}.` }
      }
    }

    const reconstructedRoot = '0x' + bytesToHex(current)
    const expectedRootFormatted = '0x' + cleanExpectedRoot
    const valid = reconstructedRoot.toLowerCase() === expectedRootFormatted.toLowerCase()

    return {
      valid,
      reconstructedRoot,
      expectedRoot: expectedRootFormatted,
      error: valid ? null : 'Recomputed root does not match published election root.',
    }
  } catch (err) {
    return { valid: false, error: err.message }
  }
}

/**
 * End-to-end receipt opening and inclusion certification.
 *
 * Checks:
 * 1. Nonce and candidate choice recompute the exact commitment.
 * 2. Commitment connects through audit path to the authoritative on-chain Merkle root.
 */
export async function verifyReceiptOpeningAndInclusion({
  electionId,
  candidateIndex,
  nonceHex,
  expectedCommitment,
  merkleRootHex,
  auditPath,
}) {
  const steps = []

  // Step 1: Recompute commitment
  let recomputedCommitment
  try {
    recomputedCommitment = await computeClientCommitment(electionId, candidateIndex, nonceHex)
    const match = recomputedCommitment.toLowerCase() === expectedCommitment.trim().toLowerCase().replace(/^0x/, '')
    steps.push({
      step: 'COMMITMENT_RECOMPUTATION',
      passed: match,
      recomputedCommitment,
      expectedCommitment,
      message: match
        ? '✓ Opening Nonce and Candidate Choice match the official ballot commitment.'
        : '✗ Recomputed commitment does not match receipt commitment (tampered candidate or nonce).',
    })
    if (!match) {
      return {
        verified: false,
        status: 'COMMITMENT_MISMATCH',
        message: 'Commitment opening failed: Candidate choice or nonce does not match the submitted ballot.',
        steps,
      }
    }
  } catch (err) {
    return {
      verified: false,
      status: 'OPENING_ERROR',
      message: `Failed to open commitment: ${err.message}`,
      steps,
    }
  }

  // Step 2: Verify Merkle inclusion of recomputed commitment
  const proofResult = await verifyClientInclusionProof(recomputedCommitment, merkleRootHex, auditPath)
  steps.push({
    step: 'MERKLE_INCLUSION_VERIFICATION',
    passed: proofResult.valid,
    reconstructedRoot: proofResult.reconstructedRoot,
    expectedRoot: proofResult.expectedRoot,
    message: proofResult.valid
      ? '✓ Merkle inclusion proof verified client-side against the election root.'
      : `✗ Inclusion verification failed: ${proofResult.error}`,
  })

  return {
    verified: proofResult.valid,
    status: proofResult.valid ? 'VALID_BALLOT_CERTIFIED' : 'PROOF_VERIFICATION_FAILED',
    recomputedCommitment,
    merkleRoot: proofResult.expectedRoot,
    message: proofResult.valid
      ? '✓ SUCCESS: Your ballot choice is certified to be mathematically included in the election Merkle root.'
      : proofResult.error,
    steps,
  }
}

/**
 * Deterministic canonical JSON formatting with sorted keys and no whitespace.
 */
export function canonicalJson(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj)
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(canonicalJson).join(',') + ']'
  }
  const keys = Object.keys(obj).sort()
  const entries = keys.map(k => JSON.stringify(k) + ':' + canonicalJson(obj[k]))
  return '{' + entries.join(',') + '}'
}

/**
 * Deterministic SHA-256 over an audit event's canonical payload.
 */
export async function computeAuditEventHash(event) {
  const payload = {
    algorithm: 'sha256',
    created_at: event.created_at,
    event_type: event.event_type,
    metadata: event.metadata || {},
    previous_hash: event.previous_hash || null,
  }
  const canonicalString = canonicalJson(payload)
  const encoded = new TextEncoder().encode(canonicalString)
  const digest = await sha256(encoded)
  return bytesToHex(digest)
}

/**
 * Query on-chain audit anchor via direct Ethereum JSON-RPC eth_call to getAuditAnchor(uint256).
 */
export async function queryOnChainAuditAnchor({
  rpcUrl = '',
  contractAddress,
  onChainId,
  expectedChainId = 1337,
}) {
  if (!rpcUrl) {
    return { success: false, status: 'RPC_UNAVAILABLE', error: 'RPC URL is required.' }
  }
  if (!contractAddress) {
    return { success: false, status: 'MISSING_CONTRACT_ADDRESS', error: 'Contract address is required.' }
  }
  if (onChainId === undefined || onChainId === null) {
    return { success: false, status: 'MISSING_ELECTION_ID', error: 'On-chain election ID is required.' }
  }

  try {
    // 1. Verify chain ID
    const chainIdRes = await fetch(rpcUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] }),
    })
    if (!chainIdRes.ok) {
      return { success: false, status: 'RPC_UNAVAILABLE', error: `RPC HTTP error: ${chainIdRes.status}` }
    }
    const chainIdJson = await chainIdRes.json()
    const rawChainIdHex = chainIdJson?.result
    if (!rawChainIdHex) {
      return { success: false, status: 'RPC_INVALID_RESPONSE', error: 'RPC failed to return chainId.' }
    }
    const parsedChainId = parseInt(rawChainIdHex, 16)
    if (expectedChainId && parsedChainId !== expectedChainId && parsedChainId !== 31337) {
      return {
        success: false,
        status: 'CHAIN_ID_MISMATCH',
        error: `Connected chain ID (${parsedChainId}) does not match expected (${expectedChainId}).`,
      }
    }

    // 2. Call getAuditAnchor(uint256) selector 0xb39e5c60
    const hexId = BigInt(onChainId).toString(16).padStart(64, '0')
    const callData = '0xb39e5c60' + hexId

    const callRes = await fetch(rpcUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 2,
        method: 'eth_call',
        params: [
          { to: contractAddress, data: callData },
          'latest'
        ],
      }),
    })
    if (!callRes.ok) {
      return { success: false, status: 'RPC_UNAVAILABLE', error: `RPC HTTP error on eth_call: ${callRes.status}` }
    }
    const callJson = await callRes.json()
    if (callJson.error) {
      return { success: false, status: 'CONTRACT_CALL_FAILED', error: callJson.error.message || 'eth_call reverted.' }
    }
    const resultHex = (callJson.result || '').replace(/^0x/, '')
    if (resultHex.length < 192) {
      return { success: false, status: 'INVALID_CONTRACT_DATA', error: 'Unexpected return data length from getAuditAnchor.' }
    }

    const anchorHex = '0x' + resultHex.slice(0, 64)
    const blockNumber = parseInt(resultHex.slice(64, 128), 16)
    const updateCount = parseInt(resultHex.slice(128, 192), 16)

    const isZero = anchorHex.replace(/^0x/, '').replace(/0/g, '') === ''

    return {
      success: true,
      anchor: anchorHex,
      blockNumber,
      updateCount,
      isZero,
      chainId: parsedChainId,
    }
  } catch (err) {
    return { success: false, status: 'RPC_UNAVAILABLE', error: err.message || 'Failed to reach Ethereum RPC endpoint.' }
  }
}

/**
 * Independently verify the audit hash chain from genesis to the anchored checkpoint,
 * locate the ELECTION_MERKLE_ROOT_FINALIZED event, and authenticate the Merkle root.
 */
export async function verifyAuditChainAndMerkleRootAuthority({
  electionId,
  onChainId,
  contractAddress,
  rpcUrl = '',
  events = [],
  expectedMerkleRoot,
  expectedChainId = 1337,
}) {
  const steps = []

  // 1. Direct Blockchain Anchor Query
  const rpcResult = await queryOnChainAuditAnchor({
    rpcUrl,
    contractAddress,
    onChainId,
    expectedChainId,
  })

  if (!rpcResult.success) {
    steps.push({
      step: 'ON_CHAIN_CHECKPOINT',
      passed: false,
      status: rpcResult.status,
      message: `✗ On-chain query failed: ${rpcResult.error}`,
    })
    return {
      verified: false,
      status: rpcResult.status,
      error: rpcResult.error,
      steps,
    }
  }

  if (rpcResult.updateCount === 0 || rpcResult.isZero) {
    steps.push({
      step: 'ON_CHAIN_CHECKPOINT',
      passed: false,
      status: 'UNANCHORED_ELECTION',
      message: '✗ No on-chain audit checkpoint has been anchored for this election.',
    })
    return {
      verified: false,
      status: 'UNANCHORED_ELECTION',
      error: 'Election audit log has not been anchored to the blockchain.',
      steps,
    }
  }

  steps.push({
    step: 'ON_CHAIN_CHECKPOINT',
    passed: true,
    status: 'ANCHOR_RETRIEVED',
    anchor: rpcResult.anchor,
    blockNumber: rpcResult.blockNumber,
    updateCount: rpcResult.updateCount,
    message: `✓ Retrieved authoritative on-chain anchor from smart contract (Block #${rpcResult.blockNumber}, Update #${rpcResult.updateCount}).`,
  })

  // 2. Audit Hash Chain Recomputation from Genesis to Checkpoint
  if (!events || events.length === 0) {
    steps.push({
      step: 'AUDIT_CHAIN_INTEGRITY',
      passed: false,
      status: 'MISSING_AUDIT_EVENTS',
      message: '✗ No audit chain events provided for verification.',
    })
    return {
      verified: false,
      status: 'MISSING_AUDIT_EVENTS',
      error: 'Audit chain events are missing.',
      steps,
    }
  }

  let chainValid = true
  let brokenEventId = null
  let brokenReason = null

  for (let i = 0; i < events.length; i++) {
    const ev = events[i]
    if (i > 0) {
      const prevEv = events[i - 1]
      const expectedPrev = (prevEv.current_hash || '').toLowerCase()
      const actualPrev = (ev.previous_hash || '').toLowerCase()
      if (actualPrev !== expectedPrev) {
        chainValid = false
        brokenEventId = ev.id
        brokenReason = `Chain link broken at event #${ev.id}: previous_hash does not match prior current_hash.`
        break
      }
    }

    const recomputedHash = await computeAuditEventHash(ev)
    if (recomputedHash.toLowerCase() !== (ev.current_hash || '').toLowerCase()) {
      chainValid = false
      brokenEventId = ev.id
      brokenReason = `Event hash mismatch at event #${ev.id} (${ev.event_type}): recomputed hash ${recomputedHash} != stored ${ev.current_hash}.`
      break
    }
  }

  if (!chainValid) {
    steps.push({
      step: 'AUDIT_CHAIN_INTEGRITY',
      passed: false,
      status: 'AUDIT_CHAIN_INTEGRITY_COMPROMISED',
      brokenEventId,
      message: `✗ Audit chain integrity failure: ${brokenReason}`,
    })
    return {
      verified: false,
      status: 'AUDIT_CHAIN_INTEGRITY_COMPROMISED',
      error: brokenReason,
      steps,
    }
  }

  // 3. Match the final checkpoint event to the on-chain anchor
  const checkpointEvent = events[events.length - 1]
  const cleanCheckpoint = (checkpointEvent.current_hash || '').toLowerCase().replace(/^0x/, '')
  const cleanOnChainAnchor = (rpcResult.anchor || '').toLowerCase().replace(/^0x/, '').padStart(64, '0')

  if (cleanCheckpoint !== cleanOnChainAnchor) {
    steps.push({
      step: 'ON_CHAIN_CHECKPOINT_BINDING',
      passed: false,
      status: 'CHECKPOINT_MISMATCH',
      message: `✗ Anchored hash on-chain (${rpcResult.anchor}) does not match the recomputed audit chain head (${checkpointEvent.current_hash}).`,
    })
    return {
      verified: false,
      status: 'CHECKPOINT_MISMATCH',
      error: 'On-chain anchor does not seal this audit chain segment.',
      steps,
    }
  }

  steps.push({
    step: 'AUDIT_CHAIN_INTEGRITY',
    passed: true,
    totalEvents: events.length,
    checkpointHash: checkpointEvent.current_hash,
    message: `✓ Cryptographic hash chain verified unbroken across all ${events.length} events from genesis to checkpoint.`,
  })

  // 4. Locate ELECTION_MERKLE_ROOT_FINALIZED in the verified chain
  const finalizationEvent = events.find(
    (e) =>
      e.event_type === 'ELECTION_MERKLE_ROOT_FINALIZED' &&
      (String(e.metadata?.election_id) === String(electionId) ||
        String(e.metadata?.election_id) === String(onChainId))
  )

  if (!finalizationEvent) {
    steps.push({
      step: 'MERKLE_ROOT_AUTHORITY',
      passed: false,
      status: 'FINALIZATION_EVENT_NOT_FOUND',
      message: `✗ No ELECTION_MERKLE_ROOT_FINALIZED event found in the verified audit chain for election ${electionId}.`,
    })
    return {
      verified: false,
      status: 'FINALIZATION_EVENT_NOT_FOUND',
      error: 'Finalization event missing from anchored audit log.',
      steps,
    }
  }

  const authenticatedRoot = finalizationEvent.metadata?.merkle_root
  if (!authenticatedRoot || authenticatedRoot === '[REDACTED]') {
    steps.push({
      step: 'MERKLE_ROOT_AUTHORITY',
      passed: false,
      status: 'MERKLE_ROOT_REDACTED',
      message: '✗ The Merkle root in the audit event metadata is redacted or missing; cannot authenticate root authority.',
    })
    return {
      verified: false,
      status: 'MERKLE_ROOT_REDACTED',
      error: 'Merkle root is not preserved in audit event.',
      steps,
    }
  }

  // 5. Compare Authenticated Root against Voter Proof Reconstructed Root
  const cleanAuthRoot = authenticatedRoot.toLowerCase().replace(/^0x/, '')
  const cleanExpectedRoot = (expectedMerkleRoot || '').toLowerCase().replace(/^0x/, '')

  if (cleanAuthRoot !== cleanExpectedRoot) {
    steps.push({
      step: 'MERKLE_ROOT_AUTHORITY',
      passed: false,
      status: 'FABRICATED_ROOT_REJECTED',
      authenticatedRoot,
      expectedRoot: expectedMerkleRoot,
      message: `✗ Fabricated root detected! Reconstructed root (${expectedMerkleRoot}) does not match authenticated root (${authenticatedRoot}) sealed in the on-chain audit log.`,
    })
    return {
      verified: false,
      status: 'FABRICATED_ROOT_REJECTED',
      error: 'Reconstructed Merkle root does not match authenticated audit log root.',
      steps,
    }
  }

  steps.push({
    step: 'MERKLE_ROOT_AUTHORITY',
    passed: true,
    status: 'ROOT_AUTHENTICATED',
    authenticatedRoot,
    message: `✓ Merkle root (${authenticatedRoot}) successfully authenticated against the on-chain audit checkpoint.`,
  })

  return {
    verified: true,
    status: 'ROOT_AUTHORITY_VERIFIED',
    authenticatedMerkleRoot: authenticatedRoot,
    onChainAnchor: rpcResult.anchor,
    anchorBlock: rpcResult.blockNumber,
    anchorUpdateCount: rpcResult.updateCount,
    totalEventsVerified: events.length,
    steps,
  }
}

/**
 * End-to-end receipt opening, Merkle inclusion, audit hash chain, and on-chain authority verification.
 */
export async function verifyReceiptOpeningAndInclusionWithAudit({
  electionId,
  candidateIndex,
  nonceHex,
  expectedCommitment,
  auditPath,
  onChainId,
  contractAddress,
  rpcUrl = '',
  auditEvents = [],
  expectedChainId = 1337,
}) {
  const steps = []

  // Check 1: Recompute commitment from receipt
  let recomputedCommitment
  try {
    recomputedCommitment = await computeClientCommitment(electionId, candidateIndex, nonceHex)
    const match = recomputedCommitment.toLowerCase() === expectedCommitment.trim().toLowerCase().replace(/^0x/, '')
    steps.push({
      step: 'COMMITMENT_RECOMPUTATION',
      passed: match,
      recomputedCommitment,
      expectedCommitment,
      message: match
        ? '✓ Opening Nonce and Candidate Choice match the official ballot commitment.'
        : '✗ Recomputed commitment does not match receipt commitment (tampered candidate or nonce).',
    })
    if (!match) {
      return {
        verified: false,
        status: 'COMMITMENT_MISMATCH',
        message: 'Commitment opening failed: Candidate choice or nonce does not match the submitted ballot.',
        steps,
      }
    }
  } catch (err) {
    return {
      verified: false,
      status: 'OPENING_ERROR',
      message: `Failed to open commitment: ${err.message}`,
      steps,
    }
  }

  // Check 2: Reconstruct Merkle root from inclusion proof
  let reconstructedRootHex
  try {
    let current = await computeLeafHash(recomputedCommitment)
    for (let i = 0; i < (auditPath || []).length; i++) {
      const step = auditPath[i]
      const siblingHex = (step.hash || '').trim().toLowerCase().replace(/^0x/, '')
      const siblingBytes = hexToBytes(siblingHex)
      const direction = (step.direction || '').toLowerCase()
      if (direction === 'right') {
        current = await computeNodeHash(current, siblingBytes)
      } else if (direction === 'left') {
        current = await computeNodeHash(siblingBytes, current)
      }
    }
    reconstructedRootHex = '0x' + bytesToHex(current)
    steps.push({
      step: 'MERKLE_INCLUSION_RECONSTRUCTION',
      passed: true,
      reconstructedRoot: reconstructedRootHex,
      message: `✓ Ballot commitment hashes through ${auditPath.length} sibling nodes to reconstructed Merkle root: ${reconstructedRootHex}`,
    })
  } catch (err) {
    steps.push({
      step: 'MERKLE_INCLUSION_RECONSTRUCTION',
      passed: false,
      message: `✗ Merkle inclusion path calculation failed: ${err.message}`,
    })
    return {
      verified: false,
      status: 'PROOF_CALCULATION_FAILED',
      message: err.message,
      steps,
    }
  }

  // Check 3 & 4: Independent Audit Chain and On-Chain Checkpoint Verification
  const auditResult = await verifyAuditChainAndMerkleRootAuthority({
    electionId,
    onChainId,
    contractAddress,
    rpcUrl,
    events: auditEvents,
    expectedMerkleRoot: reconstructedRootHex,
    expectedChainId,
  })

  // Merge steps
  steps.push(...(auditResult.steps || []))

  const overallSuccess = auditResult.verified === true

  return {
    verified: overallSuccess,
    status: overallSuccess ? 'VALID_BALLOT_CERTIFIED' : (auditResult.status || 'VERIFICATION_FAILED'),
    recomputedCommitment,
    reconstructedRoot: reconstructedRootHex,
    authenticatedMerkleRoot: auditResult.authenticatedMerkleRoot || null,
    onChainAnchor: auditResult.onChainAnchor || null,
    anchorBlock: auditResult.anchorBlock || null,
    anchorUpdateCount: auditResult.anchorUpdateCount || null,
    message: overallSuccess
      ? '✓ ALL CHECKS PASSED: Your ballot choice is certified to be mathematically included in the election Merkle root, verified through an unbroken audit chain, and anchored on the Ethereum blockchain.'
      : (auditResult.error || 'Verification failed.'),
    steps,
  }
}
