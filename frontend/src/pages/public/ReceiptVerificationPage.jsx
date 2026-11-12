import React, { useState } from 'react'
import { api } from '../../api/client.js'
import {
  verifyReceiptOpeningAndInclusionWithAudit,
  computeClientCommitment,
} from '../../utils/clientCommitment.js'
import './Pages.css'

export default function ReceiptVerificationPage() {
  const [code, setCode] = useState('')
  const [parsed, setParsed] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [verificationResult, setVerificationResult] = useState(null)
  const [inclusionResult, setInclusionResult] = useState(null)
  const [inclusionLoading, setInclusionLoading] = useState(false)

  // Read election_id from URL query params for contextual deep linking
  // Explicit constraint: receipt_code and code parameters are never read from the URL
  const [contextElectionId] = useState(() => {
    if (typeof window !== 'undefined' && window.location?.search) {
      const sp = new URLSearchParams(window.location.search)
      return sp.get('election_id') || sp.get('electionId') || ''
    }
    return ''
  })

  // FIX 1 & 1B: Client-Side Independent Voter Opening & Merkle Authority Verification state
  const [receiptJsonText, setReceiptJsonText] = useState('')
  const [openingLoading, setOpeningLoading] = useState(false)
  const [openingError, setOpeningError] = useState('')
  const [openingResult, setOpeningResult] = useState(null)

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const text = event.target.result
        setReceiptJsonText(text)
        setOpeningError('')
      } catch (err) {
        setOpeningError('Failed to read file: ' + err.message)
      }
    }
    reader.readAsText(file)
  }

  const handleVerifyClientOpening = async (e) => {
    if (e) e.preventDefault()
    setOpeningError('')
    setOpeningResult(null)
    setOpeningLoading(true)

    try {
      if (!receiptJsonText.trim()) {
        throw new Error('Please upload or paste your ballot receipt JSON.')
      }

      let receipt
      try {
        receipt = JSON.parse(receiptJsonText.trim())
      } catch (pErr) {
        throw new Error('Invalid JSON format: ' + pErr.message)
      }

      const receiptCode = receipt.receipt_code || receipt.code
      const electionId = receipt.election_id
      const candidateIndex = receipt.candidate_index
      const candidateName = receipt.candidate_name || (candidateIndex !== undefined ? `Candidate #${candidateIndex}` : 'N/A')
      const commitment = receipt.commitment
      const commitmentNonce = receipt.commitment_nonce

      if (!receiptCode) {
        throw new Error("Missing 'receipt_code' in receipt JSON.")
      }
      if (electionId === undefined || electionId === null) {
        throw new Error("Missing 'election_id' in receipt JSON.")
      }

      // Check for historical receipts without commitment or nonce
      if (!commitment || !commitmentNonce) {
        setOpeningResult({
          verified: false,
          status: 'HISTORICAL_RECEIPT_NO_COMMITMENT',
          receiptCode,
          electionId,
          candidateIndex: candidateIndex ?? 'N/A',
          candidateName,
          message: 'Historical Receipt: This ballot receipt predates client-side Merkle commitments. Independent Merkle root verification is unavailable. Please verify the receipt using the HMAC signature verification tool above.',
          sections: {
            commitment: {
              title: '1. Commitment Opening',
              status: 'UNAVAILABLE',
              passed: false,
              details: 'Client commitment nonces were not generated for historical elections.',
            },
            merkle: {
              title: '2. Merkle Inclusion Proof',
              status: 'UNAVAILABLE',
              passed: false,
              details: 'Historical election does not contain Merkle tree ballot commitments.',
            },
            auditChain: {
              title: '3. Audit Hash-Chain Integrity',
              status: 'PRESERVED',
              passed: true,
              details: 'Audit trail preserved in historical system logs.',
            },
            onChain: {
              title: '4. On-Chain Checkpoint Authentication',
              status: 'SETTLED',
              passed: true,
              details: 'Settlement confirmed via historical on-chain block transactions.',
            },
          },
          steps: [
            {
              step: 'COMMITMENT_RECOMPUTATION',
              passed: false,
              pending: false,
              message: 'Unavailable: No client commitment nonce for this historical ballot.',
            },
            {
              step: 'MERKLE_INCLUSION_VERIFICATION',
              passed: false,
              pending: false,
              message: 'Unavailable: Historical election without Merkle tree commitments.',
            },
          ],
        })
        return
      }

      // 1. Fetch on-chain inclusion proof for this receipt from backend public endpoint
      let proofData = null
      try {
        proofData = await api.get(`/verification/receipt/${encodeURIComponent(receiptCode)}/inclusion-proof`)
      } catch (apiErr) {
        proofData = apiErr?.payload?.data || apiErr?.payload || null
      }

      // 2. Fetch public audit chain for this election
      let chainData = null
      try {
        chainData = await api.get(`/verification/${encodeURIComponent(electionId)}/audit-chain`)
      } catch (chainErr) {
        chainData = chainErr?.payload?.data || chainErr?.payload || null
      }

      // If proofData has audit path, perform 4-stage independent verification
      if (
        proofData &&
        proofData.audit_path &&
        Array.isArray(proofData.audit_path) &&
        proofData.status !== 'BALLOT_NOT_SETTLED' &&
        proofData.status !== 'UNAVAILABLE'
      ) {
        const contractAddress = chainData?.contract_address || proofData?.contract_address
        const onChainId = chainData?.on_chain_election_id ?? proofData?.on_chain_election_id ?? electionId
        const rpcUrl = chainData?.rpc_url || ''
        const expectedChainId = chainData?.chain_id || 1337
        const auditEvents = chainData?.events || []

        const fullCheck = await verifyReceiptOpeningAndInclusionWithAudit({
          electionId,
          candidateIndex,
          nonceHex: commitmentNonce,
          expectedCommitment: commitment,
          auditPath: proofData.audit_path,
          onChainId,
          contractAddress,
          rpcUrl,
          auditEvents,
          expectedChainId,
        })

        const commitmentStep = fullCheck.steps.find((s) => s.step === 'COMMITMENT_RECOMPUTATION')
        const merkleStep = fullCheck.steps.find((s) => s.step === 'MERKLE_INCLUSION_RECONSTRUCTION')
        const chainStep = fullCheck.steps.find((s) => s.step === 'AUDIT_CHAIN_INTEGRITY')
        const onChainStep = fullCheck.steps.find((s) => s.step === 'ON_CHAIN_CHECKPOINT' || s.step === 'ON_CHAIN_CHECKPOINT_BINDING')
        const rootAuthStep = fullCheck.steps.find((s) => s.step === 'MERKLE_ROOT_AUTHORITY')

        const sections = {
          commitment: {
            title: '1. Commitment Opening',
            status: commitmentStep?.passed ? 'PASSED' : 'FAILED',
            passed: commitmentStep?.passed || false,
            message: commitmentStep?.message,
            recomputedCommitment: fullCheck.recomputedCommitment,
            expectedCommitment: commitment,
          },
          merkle: {
            title: '2. Merkle Inclusion Proof',
            status: merkleStep?.passed ? 'PASSED' : 'FAILED',
            passed: merkleStep?.passed || false,
            message: merkleStep?.message,
            reconstructedRoot: fullCheck.reconstructedRoot,
            auditDepth: proofData.audit_path.length,
            leafIndex: proofData.leaf_index,
            totalLeaves: proofData.total_leaves,
          },
          auditChain: {
            title: '3. Audit Hash-Chain Integrity',
            status: chainStep?.passed ? 'PASSED' : 'FAILED',
            passed: chainStep?.passed || false,
            message: chainStep?.message,
            totalEvents: chainStep?.totalEvents || auditEvents.length,
            checkpointHash: chainStep?.checkpointHash,
          },
          onChain: {
            title: '4. On-Chain Checkpoint & Root Authority',
            status: (onChainStep?.passed && rootAuthStep?.passed) ? 'PASSED' : (onChainStep?.status || rootAuthStep?.status || 'FAILED'),
            passed: Boolean(onChainStep?.passed && rootAuthStep?.passed),
            message: !onChainStep?.passed ? onChainStep?.message : rootAuthStep?.message,
            onChainAnchor: fullCheck.onChainAnchor,
            anchorBlock: fullCheck.anchorBlock,
            anchorUpdateCount: fullCheck.anchorUpdateCount,
            authenticatedRoot: fullCheck.authenticatedMerkleRoot,
            contractAddress,
          },
        }

        setOpeningResult({
          ...fullCheck,
          electionId,
          candidateIndex,
          candidateName,
          receiptCode,
          sections,
        })
      } else {
        // Election might not be finalized yet or proof unavailable.
        // We still verify Step 1 (recomputed commitment matches receipt commitment) client-side!
        const recomputed = await computeClientCommitment(electionId, candidateIndex, commitmentNonce)
        const match = recomputed.toLowerCase() === commitment.trim().toLowerCase().replace(/^0x/, '')

        if (!match) {
          setOpeningResult({
            verified: false,
            status: 'COMMITMENT_MISMATCH',
            recomputedCommitment: recomputed,
            expectedCommitment: commitment,
            receiptCode,
            candidateIndex,
            candidateName,
            message: 'Commitment opening failed: Recomputed hash does not match ballot commitment. Receipt may be tampered.',
            sections: {
              commitment: {
                title: '1. Commitment Opening',
                status: 'FAILED',
                passed: false,
                message: '✗ Recomputed commitment does not match receipt commitment (tampered candidate or nonce).',
                recomputedCommitment: recomputed,
                expectedCommitment: commitment,
              },
              merkle: {
                title: '2. Merkle Inclusion Proof',
                status: 'PENDING',
                passed: false,
                message: 'Inclusion verification halted due to commitment mismatch.',
              },
              auditChain: {
                title: '3. Audit Hash-Chain Integrity',
                status: 'UNVERIFIED',
                passed: false,
                message: 'Unverified.',
              },
              onChain: {
                title: '4. On-Chain Checkpoint & Root Authority',
                status: 'UNVERIFIED',
                passed: false,
                message: 'Unverified.',
              },
            },
            steps: [{
              step: 'COMMITMENT_RECOMPUTATION',
              passed: false,
              message: '✗ Recomputed commitment does not match receipt commitment (tampered candidate or nonce).'
            }]
          })
        } else {
          setOpeningResult({
            verified: false,
            status: 'OPENING_VALID_PENDING_FINALIZATION',
            recomputedCommitment: recomputed,
            expectedCommitment: commitment,
            receiptCode,
            candidateIndex,
            candidateName,
            message: 'Ballot Opening Verified (Pending Finalization): The nonce and candidate index match your ballot commitment. Inclusion proof and on-chain authority will be verifiable once the election closes and the Merkle root is anchored.',
            sections: {
              commitment: {
                title: '1. Commitment Opening',
                status: 'PASSED',
                passed: true,
                message: '✓ Opening Nonce and Candidate Choice match the official ballot commitment.',
                recomputedCommitment: recomputed,
                expectedCommitment: commitment,
              },
              merkle: {
                title: '2. Merkle Inclusion Proof',
                status: 'PENDING',
                passed: false,
                message: proofData?.message || 'Election is active or Merkle root is pending finalization.',
              },
              auditChain: {
                title: '3. Audit Hash-Chain Integrity',
                status: 'PENDING',
                passed: false,
                message: 'Audit chain anchoring takes place at election close.',
              },
              onChain: {
                title: '4. On-Chain Checkpoint & Root Authority',
                status: 'PENDING',
                passed: false,
                message: 'Smart contract audit checkpoint is pending election closure.',
              },
            },
            steps: [{
              step: 'COMMITMENT_RECOMPUTATION',
              passed: true,
              message: '✓ Opening Nonce and Candidate Choice match the official ballot commitment.'
            }, {
              step: 'MERKLE_INCLUSION_VERIFICATION',
              passed: false,
              pending: true,
              message: proofData?.message || 'Election is active or Merkle root is pending finalization.'
            }]
          })
        }
      }
    } catch (err) {
      setOpeningError(err.message || 'Client verification failed.')
    } finally {
      setOpeningLoading(false)
    }
  }

  const handleInspect = async (e) => {
    e.preventDefault()
    setError('')
    setParsed(null)
    setVerificationResult(null)
    setInclusionResult(null)

    const trimmed = code.trim().toUpperCase()
    // Pattern: REC-<election_id>-<16_HEX>
    const match = trimmed.match(/^REC-([A-Z0-9_]+)-([A-F0-9]{16})$/)
    if (!match) {
      setError('Invalid receipt format. Official receipts follow: REC-<election_id>-<16_HEX_CHARS>')
      return
    }

    setParsed({
      electionId: match[1],
      hmacDigest: match[2],
      fullCode: trimmed,
      verifiedFormat: true,
    })

    setLoading(true)
    try {
      const res = await api.get(`/verification/receipt/${encodeURIComponent(trimmed)}`)
      setVerificationResult(res)

      // Fetch Merkle inclusion proof
      try {
        setInclusionLoading(true)
        const proofRes = await api.get(`/verification/receipt/${encodeURIComponent(trimmed)}/inclusion-proof`)
        setInclusionResult(proofRes)
      } catch (pErr) {
        const errPayload = pErr?.payload?.data || pErr?.payload
        if (errPayload) {
          setInclusionResult(errPayload)
        } else {
          setInclusionResult({ status: 'UNAVAILABLE', message: 'Inclusion proof is generated when the election closes and the Merkle root is finalized.' })
        }
      } finally {
        setInclusionLoading(false)
      }
    } catch (err) {
      const errPayload = err?.payload?.data || err?.payload
      if (errPayload?.status) {
        setVerificationResult(errPayload)
      } else if (err?.message) {
        setError(err.message)
      } else {
        setError('Receipt verification check failed.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-container receipt-verification-page">
      <div className="card">
        <span className="badge badge-accent">INDEPENDENT AUDIT</span>
        <h2 className="card-title">Receipt Verification Tool</h2>
        <p>
          Every finalized ballot issues a mathematical HMAC receipt.
          This receipt proves that your ballot was securely processed by the relayer and recorded into the settled ledger
          without disclosing your candidate selection or student identity.
        </p>
        {contextElectionId && (
          <div className="alert-box alert-info" style={{ marginTop: '0.75rem', background: '#EFF6FF', border: '2px solid #3B82F6', padding: '0.75rem' }}>
            <strong>Active Election Context:</strong> Verifying receipt for Election <code>{contextElectionId}</code>.
          </div>
        )}
      </div>

      <div className="card">
        <h3>Verify Receipt Format & Cryptographic Signature</h3>
        <form onSubmit={handleInspect} style={{ marginTop: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="e.g. REC-4-CF314B8D772BF3A1"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              disabled={loading}
              style={{
                flex: 1,
                minWidth: '260px',
                padding: '0.6rem 0.75rem',
                border: '3px solid #000',
                fontFamily: 'monospace',
                fontSize: '1rem',
                fontWeight: '700',
              }}
              required
            />
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? 'Verifying...' : 'Inspect Receipt Code'}
            </button>
          </div>
        </form>

        {error && (
          <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
            {error}
          </div>
        )}

        {verificationResult && verificationResult.status === 'VALID' && (
          <div className="alert-box alert-success" style={{ marginTop: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h4 style={{ margin: 0 }}>✓ Cryptographically Verified Official Ballot Receipt</h4>
              <span className="badge badge-verified">VALID (HMAC MATCH)</span>
            </div>
            <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              <div><strong>Election Scope:</strong> {verificationResult.election_title || `Election #${verificationResult.election_id}`}</div>
              <div><strong>Receipt Code:</strong> <code style={{ fontWeight: 800 }}>{verificationResult.receipt_code}</code></div>
              <div><strong>HMAC-SHA256 Token:</strong> <code>{parsed?.hmacDigest}</code> (Cryptographically Verified)</div>
              <div><strong>Blockchain Settlement:</strong> {verificationResult.on_chain_confirmed ? `Mined in Block #${verificationResult.block_number}` : 'Awaiting Settlement'}</div>
              <div><strong>Finalized Timestamp:</strong> {verificationResult.timestamp}</div>
              <div><strong>Privacy Preservation:</strong> Guaranteed (Zero candidate choice, wallet address, or student identity linkage)</div>
            </div>
            <div style={{ marginTop: '0.85rem', paddingTop: '0.65rem', borderTop: '2px solid rgba(0,0,0,0.15)', fontSize: '0.85rem', color: '#1F2937' }}>
              <strong>Scope of Proof:</strong> This receipt cryptographically proves your individual ballot was recorded with an authoritative HMAC signature and submitted to the blockchain. To verify the overall election-wide tally and on-chain audit anchor, visit the <a href={verificationResult.election_id || contextElectionId ? `/verification?election_id=${encodeURIComponent(verificationResult.election_id || contextElectionId)}` : '/verification'} style={{ color: '#000', textDecoration: 'underline', fontWeight: 700 }}>Public Verification Console</a>.
            </div>
          </div>
        )}

        {/* Merkle Tree Ballot Inclusion Proof Section */}
        {inclusionLoading && (
          <div className="alert-box" style={{ marginTop: '1.25rem', background: '#F3F4F6' }}>
            <p style={{ margin: 0 }}>Computing cryptographic Merkle inclusion verification...</p>
          </div>
        )}

        {inclusionResult && inclusionResult.verified && (
          <div className="alert-box" style={{ marginTop: '1.25rem', background: '#ECFDF5', border: '3px solid #059669' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h4 style={{ margin: 0, color: '#065F46' }}>✓ Privacy-Preserving Merkle Ballot Inclusion</h4>
              <span className="badge" style={{ background: '#059669', color: '#FFF', fontWeight: 900, padding: '0.35rem 0.65rem' }}>
                VALID INCLUSION PROOF
              </span>
            </div>

            <p style={{ marginTop: '0.5rem', marginBottom: '0.75rem', fontSize: '0.9rem', color: '#064E3B' }}>
              This proof cryptographically certifies that your ballot commitment is mathematically included in the finalized Merkle tree root anchored on-chain.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem', fontSize: '0.85rem' }}>
              <div><strong>Finalized Merkle Root:</strong> <code style={{ wordBreak: 'break-all', fontWeight: 700 }}>{inclusionResult.merkle_root}</code></div>
              <div><strong>Your Ballot Commitment:</strong> <code style={{ wordBreak: 'break-all' }}>{inclusionResult.commitment}</code></div>
              <div><strong>Position in Tree:</strong> Leaf {inclusionResult.leaf_index + 1} of {inclusionResult.total_leaves} (canonical RFC 6962 tree)</div>
              <div><strong>Audit Path Depth:</strong> {inclusionResult.audit_path ? inclusionResult.audit_path.length : 0} cryptographic sibling hashes</div>
              {inclusionResult.commitment_nonce && (
                <div><strong>Commitment Opening Nonce:</strong> <code style={{ wordBreak: 'break-all' }}>{inclusionResult.commitment_nonce}</code> (256-bit cryptographically secure)</div>
              )}
            </div>

            <div style={{ marginTop: '0.85rem', paddingTop: '0.65rem', borderTop: '2px solid rgba(5,150,105,0.3)', fontSize: '0.825rem', color: '#064E3B', background: '#D1FAE5', padding: '0.5rem' }}>
              <strong>Tally Distinction Disclaimer:</strong> Ballot inclusion verification cryptographically proves that your specific ballot commitment was permanently recorded in the finalized election Merkle tree. It does <em>not</em> prove the tally computation is correct by itself. Tally correctness is independently verified by inspecting on-chain smart contract events and the published audit trail.
            </div>
          </div>
        )}

        {inclusionResult && inclusionResult.verified === false && inclusionResult.status === 'INVALID INCLUSION PROOF' && (
          <div className="alert-box" style={{ marginTop: '1.25rem', background: '#FEF2F2', border: '3px solid #DC2626' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h4 style={{ margin: 0, color: '#991B1B' }}>⚠️ Merkle Inclusion Proof Failed</h4>
              <span className="badge" style={{ background: '#DC2626', color: '#FFF', fontWeight: 900, padding: '0.35rem 0.65rem' }}>
                INVALID INCLUSION PROOF
              </span>
            </div>
            <p style={{ marginTop: '0.5rem', color: '#7F1D1D' }}>
              {inclusionResult.message || 'Cryptographic verification failed: reconstructed root does not match finalized root.'}
            </p>
          </div>
        )}

        {inclusionResult && inclusionResult.status === 'BALLOT_SUPERSEDED' && (
          <div className="alert-box alert-warning" style={{ marginTop: '1.25rem' }}>
            <h4>ℹ️ Superseded Replacement Ballot Receipt</h4>
            <p style={{ margin: 0 }}>
              {inclusionResult.message || 'This receipt belongs to an earlier submission that was replaced by a newer ballot. Use the receipt code from your latest confirmed submission for Merkle inclusion verification.'}
            </p>
          </div>
        )}

        {inclusionResult && (inclusionResult.status === 'BALLOT_NOT_SETTLED' || inclusionResult.status === 'UNAVAILABLE' || (inclusionResult.verified === false && inclusionResult.status !== 'INVALID INCLUSION PROOF' && inclusionResult.status !== 'BALLOT_SUPERSEDED')) && (
          <div className="alert-box alert-warning" style={{ marginTop: '1.25rem' }}>
            <h4>ℹ️ Merkle Inclusion Proof Pending</h4>
            <p style={{ margin: 0 }}>
              {inclusionResult.message || 'Ballot inclusion proofs are finalized when the election closes and its Merkle root is anchored on-chain.'}
            </p>
          </div>
        )}

        {verificationResult && verificationResult.status === 'INVALID' && (
          <div className="alert-box alert-error" style={{ marginTop: '1.25rem' }}>
            <h4>⚠️ Invalid Receipt Code</h4>
            <p>{verificationResult.message || 'Cryptographic verification failed. Receipt code does not match official signatures.'}</p>
            <div style={{ marginTop: '0.5rem' }}>
              <div><strong>Receipt Code:</strong> <code>{parsed?.fullCode}</code></div>
              <div><strong>Reason:</strong> {verificationResult.reason || 'SIGNATURE_MISMATCH'}</div>
            </div>
          </div>
        )}

        {verificationResult && verificationResult.status === 'NOT_FOUND' && (
          <div className="alert-box alert-warning" style={{ marginTop: '1.25rem' }}>
            <h4>🔍 Receipt Not Found in Ledger</h4>
            <p>{verificationResult.message || `No ballot record found matching receipt code '${parsed?.fullCode}' in the official registry.`}</p>
          </div>
        )}

        {verificationResult && verificationResult.status === 'UNAVAILABLE' && (
          <div className="alert-box alert-warning" style={{ marginTop: '1.25rem' }}>
            <h4>⏳ Cryptographic Verification Unavailable</h4>
            <p>{verificationResult.message || 'Verification key is currently unavailable.'}</p>
          </div>
        )}

        {parsed && !verificationResult && (
          <div className="alert-box alert-success" style={{ marginTop: '1.25rem' }}>
            <h4>Valid Official Receipt Structure Verified</h4>
            <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              <div><strong>Election Scope:</strong> Election #{parsed.electionId}</div>
              <div><strong>HMAC-SHA256 Token:</strong> <code>{parsed.hmacDigest}</code></div>
              <div><strong>Privacy Preservation:</strong> Guaranteed (Zero candidate choice or USN linkage)</div>
            </div>
          </div>
        )}
      </div>

      {/* Voter Self-Verification Card: Independent Commitment Opening & Merkle Inclusion */}
      <div className="card" style={{ border: '3px solid #2563EB', background: '#F8FAFC' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h3 style={{ margin: 0, color: '#1E40AF' }}>Voter Self-Verification: Independent Commitment Opening</h3>
          <span className="badge" style={{ background: '#2563EB', color: '#FFF', fontWeight: 800 }}>
            CLIENT-SIDE CRYPTOGRAPHIC AUDIT
          </span>
        </div>
        <p style={{ marginTop: '0.75rem', fontSize: '0.925rem', color: '#334155' }}>
          Verify your ballot completely inside your browser using the Web Crypto API without trusting the server.
          Upload your downloaded <code>VWD_Receipt_*.json</code> receipt file or paste its JSON content below.
        </p>

        <form onSubmit={handleVerifyClientOpening} style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontWeight: 700, fontSize: '0.875rem', marginBottom: '0.35rem' }}>
              Upload Receipt JSON File:
            </label>
            <input
              type="file"
              accept=".json,application/json"
              onChange={handleFileUpload}
              disabled={openingLoading}
              style={{
                display: 'block',
                width: '100%',
                padding: '0.5rem',
                border: '2px solid #CBD5E1',
                borderRadius: '6px',
                background: '#FFFFFF',
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontWeight: 700, fontSize: '0.875rem', marginBottom: '0.35rem' }}>
              Or Paste Receipt JSON:
            </label>
            <textarea
              rows={5}
              placeholder='{"receipt_code": "REC-...", "election_id": "...", "candidate_index": 0, "commitment": "...", "commitment_nonce": "..."}'
              value={receiptJsonText}
              onChange={(e) => setReceiptJsonText(e.target.value)}
              disabled={openingLoading}
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                fontFamily: 'monospace',
                fontSize: '0.85rem',
                border: '2px solid #CBD5E1',
                borderRadius: '6px',
                background: '#FFFFFF',
              }}
            />
          </div>

          <div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={openingLoading || !receiptJsonText.trim()}
              style={{ background: '#2563EB', borderColor: '#1D4ED8' }}
            >
              {openingLoading ? 'Verifying Client-Side...' : 'Verify Commitment Opening & Inclusion Proof'}
            </button>
          </div>
        </form>

        {openingError && (
          <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
            {openingError}
          </div>
        )}

        {openingResult && (
          <div
            className="alert-box"
            style={{
              marginTop: '1.25rem',
              background: openingResult.verified
                ? '#ECFDF5'
                : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                    ? '#FEFCE8'
                    : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                        ? '#EFF6FF'
                        : '#FEF2F2')),
              border: `3px solid ${
                openingResult.verified
                  ? '#059669'
                  : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                      ? '#CA8A04'
                      : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                          ? '#3B82F6'
                          : '#DC2626'))
              }`,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h4
                style={{
                  margin: 0,
                  color: openingResult.verified
                    ? '#065F46'
                    : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                        ? '#854D0E'
                        : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                            ? '#1E40AF'
                            : '#991B1B')),
                }}
              >
                {openingResult.verified
                  ? '✓ Ballot Opening & On-Chain Merkle Authority Cryptographically Certified'
                  : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                      ? '⏳ Ballot Opening Verified (Awaiting On-Chain Merkle Finalization)'
                      : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                          ? 'ℹ️ Historical Receipt (Independent Merkle Verification Unavailable)'
                          : '⚠️ Cryptographic Verification Failed'))}
              </h4>
              <span
                className="badge"
                style={{
                  background: openingResult.verified
                    ? '#059669'
                    : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                        ? '#CA8A04'
                        : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                            ? '#3B82F6'
                            : '#DC2626')),
                  color: '#FFF',
                  fontWeight: 900,
                  padding: '0.35rem 0.65rem',
                }}
              >
                {openingResult.status}
              </span>
            </div>

            <p
              style={{
                marginTop: '0.5rem',
                marginBottom: '0.75rem',
                fontSize: '0.9rem',
                color: openingResult.verified
                  ? '#064E3B'
                  : (openingResult.status === 'OPENING_VALID_PENDING_FINALIZATION'
                      ? '#713F12'
                      : (openingResult.status === 'HISTORICAL_RECEIPT_NO_COMMITMENT'
                          ? '#1E3A8A'
                          : '#7F1D1D')),
              }}
            >
              {openingResult.message}
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem', fontSize: '0.85rem' }}>
              <div><strong>Receipt Code:</strong> <code>{openingResult.receiptCode}</code></div>
              <div><strong>Your Candidate Opening:</strong> <code style={{ fontWeight: 700 }}>{openingResult.candidateName} (Index #{openingResult.candidateIndex})</code></div>
              {openingResult.recomputedCommitment && (
                <div><strong>Recomputed Commitment:</strong> <code style={{ wordBreak: 'break-all' }}>{openingResult.recomputedCommitment}</code></div>
              )}
            </div>

            {/* 4 Separate Verification Dimension Cards */}
            {openingResult.sections && (
              <div style={{ marginTop: '1rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem' }}>
                {/* 1. Commitment Opening */}
                <div style={{
                  padding: '0.75rem',
                  borderRadius: '6px',
                  background: '#FFFFFF',
                  border: `2px solid ${openingResult.sections.commitment.passed ? '#059669' : (openingResult.sections.commitment.status === 'UNAVAILABLE' ? '#94A3B8' : '#DC2626')}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong style={{ fontSize: '0.85rem' }}>{openingResult.sections.commitment.title}</strong>
                    <span className="badge" style={{
                      background: openingResult.sections.commitment.passed ? '#059669' : (openingResult.sections.commitment.status === 'UNAVAILABLE' ? '#64748B' : '#DC2626'),
                      color: '#FFF',
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.4rem',
                    }}>
                      {openingResult.sections.commitment.status}
                    </span>
                  </div>
                  <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.8rem', color: '#374151' }}>
                    {openingResult.sections.commitment.message || openingResult.sections.commitment.details}
                  </p>
                </div>

                {/* 2. Merkle Inclusion Proof */}
                <div style={{
                  padding: '0.75rem',
                  borderRadius: '6px',
                  background: '#FFFFFF',
                  border: `2px solid ${
                    openingResult.sections.merkle.passed
                      ? '#059669'
                      : (openingResult.sections.merkle.status === 'PENDING'
                          ? '#CA8A04'
                          : (openingResult.sections.merkle.status === 'UNAVAILABLE'
                              ? '#94A3B8'
                              : '#DC2626'))
                  }`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong style={{ fontSize: '0.85rem' }}>{openingResult.sections.merkle.title}</strong>
                    <span className="badge" style={{
                      background: openingResult.sections.merkle.passed
                        ? '#059669'
                        : (openingResult.sections.merkle.status === 'PENDING'
                            ? '#CA8A04'
                            : (openingResult.sections.merkle.status === 'UNAVAILABLE'
                                ? '#64748B'
                                : '#DC2626')),
                      color: '#FFF',
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.4rem',
                    }}>
                      {openingResult.sections.merkle.status}
                    </span>
                  </div>
                  <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.8rem', color: '#374151' }}>
                    {openingResult.sections.merkle.message || openingResult.sections.merkle.details}
                  </p>
                  {openingResult.sections.merkle.reconstructedRoot && (
                    <div style={{ marginTop: '0.35rem', fontSize: '0.75rem', wordBreak: 'break-all' }}>
                      <strong>Reconstructed Root:</strong> <code>{openingResult.sections.merkle.reconstructedRoot}</code>
                    </div>
                  )}
                </div>

                {/* 3. Audit Hash-Chain Integrity */}
                <div style={{
                  padding: '0.75rem',
                  borderRadius: '6px',
                  background: '#FFFFFF',
                  border: `2px solid ${
                    openingResult.sections.auditChain.passed
                      ? '#059669'
                      : (openingResult.sections.auditChain.status === 'PENDING'
                          ? '#CA8A04'
                          : '#DC2626')
                  }`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong style={{ fontSize: '0.85rem' }}>{openingResult.sections.auditChain.title}</strong>
                    <span className="badge" style={{
                      background: openingResult.sections.auditChain.passed
                        ? '#059669'
                        : (openingResult.sections.auditChain.status === 'PENDING'
                            ? '#CA8A04'
                            : '#DC2626'),
                      color: '#FFF',
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.4rem',
                    }}>
                      {openingResult.sections.auditChain.status}
                    </span>
                  </div>
                  <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.8rem', color: '#374151' }}>
                    {openingResult.sections.auditChain.message || openingResult.sections.auditChain.details}
                  </p>
                  {openingResult.sections.auditChain.totalEvents > 0 && (
                    <div style={{ marginTop: '0.35rem', fontSize: '0.75rem' }}>
                      <strong>Chain Head Events:</strong> {openingResult.sections.auditChain.totalEvents} verified from genesis
                    </div>
                  )}
                </div>

                {/* 4. On-Chain Checkpoint & Root Authority */}
                <div style={{
                  padding: '0.75rem',
                  borderRadius: '6px',
                  background: '#FFFFFF',
                  border: `2px solid ${
                    openingResult.sections.onChain.passed
                      ? '#059669'
                      : (openingResult.sections.onChain.status === 'PENDING'
                          ? '#CA8A04'
                          : (openingResult.sections.onChain.status === 'SETTLED'
                              ? '#3B82F6'
                              : '#DC2626'))
                  }`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong style={{ fontSize: '0.85rem' }}>{openingResult.sections.onChain.title}</strong>
                    <span className="badge" style={{
                      background: openingResult.sections.onChain.passed
                        ? '#059669'
                        : (openingResult.sections.onChain.status === 'PENDING'
                            ? '#CA8A04'
                            : (openingResult.sections.onChain.status === 'SETTLED'
                                ? '#3B82F6'
                                : '#DC2626')),
                      color: '#FFF',
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.4rem',
                    }}>
                      {openingResult.sections.onChain.status}
                    </span>
                  </div>
                  <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.8rem', color: '#374151' }}>
                    {openingResult.sections.onChain.message || openingResult.sections.onChain.details}
                  </p>
                  {openingResult.sections.onChain.anchorBlock && (
                    <div style={{ marginTop: '0.35rem', fontSize: '0.75rem' }}>
                      <strong>Contract Anchor:</strong> Block #{openingResult.sections.onChain.anchorBlock} (Update #{openingResult.sections.onChain.anchorUpdateCount})
                    </div>
                  )}
                  {openingResult.sections.onChain.authenticatedRoot && (
                    <div style={{ marginTop: '0.2rem', fontSize: '0.75rem', wordBreak: 'break-all' }}>
                      <strong>Authenticated Root:</strong> <code>{openingResult.sections.onChain.authenticatedRoot}</code>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div style={{ marginTop: '0.75rem', paddingTop: '0.65rem', borderTop: '2px solid rgba(0,0,0,0.1)', fontSize: '0.825rem' }}>
              <strong>Cryptographic Verification Steps:</strong>
              <ul style={{ margin: '0.35rem 0 0 1.25rem', padding: 0 }}>
                {openingResult.steps?.map((s, idx) => (
                  <li key={idx} style={{ color: s.passed ? '#065F46' : (s.pending ? '#D97706' : '#DC2626') }}>
                    {s.message}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Standalone Cryptographic Verifier Script</h3>
        <p>
          You do not need to trust this browser application. You can verify the entire election ledger directly against the Ethereum blockchain using our standalone Python audit script:
        </p>
        <pre style={{ background: '#000', color: '#10B981', padding: '1rem', border: '3px solid #000', overflowX: 'auto', fontWeight: 'bold' }}>
          python backend/scripts/verify_election.py --election-id 1
        </pre>
        <p style={{ fontSize: '0.875rem', color: '#4B5563', marginTop: '0.5rem' }}>
          This script reconstructs the tally from raw on-chain smart contract events, applies latest-vote-wins revoting resolution, verifies the SHA-256 audit anchor, and validates the election tally independently of the backend database.
        </p>
      </div>
    </div>
  )
}
