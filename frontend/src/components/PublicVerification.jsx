import { useState, useEffect, useCallback, useRef } from 'react'
import './PublicVerification.css'
import { api } from '../api/client.js'
import { selectAuthoritativeElection } from '../utils/electionUtils'
import { useRouter } from '../router/RouterContext'

/**
 * Public Verification & Certified Results Component - Task 4
 *
 * Requirements:
 * 1. Dynamic election selector populated from GET /api/public/elections.
 * 2. URL synchronization for election_id preserving pathname, other query params, and hash.
 * 3. Browser Back/Forward (popstate) restoration without asynchronous race conditions.
 * 4. Active request ref tracking (activeRequestIdRef) discarding stale async responses.
 * 5. Strict rendering of all five authoritative result states with tally withholding.
 * 6. Explicit separation of display vs. cryptographic verification statuses:
 *    - Merkle Root: ROOT RECORDED, FAILED, UNAVAILABLE
 *    - Audit-Chain Integrity: AUDIT CHAIN VERIFIED, FAILED, UNAVAILABLE
 *    - Smart-Contract Audit Anchor: VERIFIED, FAILED, UNAVAILABLE
 *    - Candidate-Set Hash: MATCHED, MISMATCH, UNAVAILABLE
 *    - Voter-Roll Hash: MATCHED, MISMATCH, UNAVAILABLE (raw hex omitted)
 *    - Blockchain Tallies: VERIFIED, FAILED, UNAVAILABLE
 * 7. Zero claims of pseudonym key destruction without reliable public evidence.
 * 8. Deep-linking bridge to ReceiptVerificationPage passing election_id only.
 * 9. Absolute privacy preservation: Zero voter identity, USN, email, or pseudonym leakage.
 */
export default function PublicVerification({ showTamperingDemo = false } = {}) {
  const { navigate } = useRouter()

  // Elections catalog list from GET /api/public/elections
  const [elections, setElections] = useState([])
  const [catalogLoading, setCatalogLoading] = useState(true)

  // Selected Election ID initialized from URL query parameters (?election_id= or ?electionId=)
  const [electionId, setElectionId] = useState(() => {
    if (typeof window !== 'undefined' && window.location?.search) {
      const sp = new URLSearchParams(window.location.search)
      return sp.get('election_id') || sp.get('electionId') || ''
    }
    return ''
  })

  const [verificationData, setVerificationData] = useState(null)
  const [resultsData, setResultsData] = useState(null)
  const [resultsUnavailableMsg, setResultsUnavailableMsg] = useState('')
  const [pendingQueueMsg, setPendingQueueMsg] = useState('')
  const [underReviewMsg, setUnderReviewMsg] = useState('')
  const [tamperResult, setTamperResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [tamperingBusy, setTamperingBusy] = useState(false)
  const [error, setError] = useState('')

  // Monotonic request ID counter to eliminate asynchronous race conditions
  const activeRequestIdRef = useRef(0)

  // Synchronize election_id into URL while preserving pathname, unrelated query params, and hash
  const updateElectionUrl = useCallback((newId) => {
    if (typeof window === 'undefined') return
    const currentUrl = new URL(window.location.href)
    if (newId) {
      currentUrl.searchParams.set('election_id', newId)
    } else {
      currentUrl.searchParams.delete('election_id')
    }
    // Preserves currentUrl.pathname, currentUrl.hash, and any other searchParams
    window.history.pushState(null, '', currentUrl.toString())
  }, [])

  // 1. Fetch public elections directory on mount
  useEffect(() => {
    let mounted = true
    async function loadCatalog() {
      setCatalogLoading(true)
      try {
        const res = await api.get('/public/elections')
        const elList = Array.isArray(res?.elections) ? res.elections : []
        if (!mounted) return
        setElections(elList)

        // Validate or resolve authoritative initial election
        const currentParam = new URLSearchParams(window.location.search).get('election_id') || electionId
        const match = elList.find((e) => String(e.election_id) === String(currentParam))

        if (match) {
          setElectionId(match.election_id)
        } else if (elList.length > 0) {
          const authoritative = selectAuthoritativeElection(elList)
          const fallbackId = authoritative?.election_id || elList[0].election_id
          setElectionId(fallbackId)
          updateElectionUrl(fallbackId)
        }
      } catch (err) {
        if (mounted) {
          setError(err.message || 'Failed to load public election catalog.')
        }
      } finally {
        if (mounted) {
          setCatalogLoading(false)
        }
      }
    }

    loadCatalog()
    return () => { mounted = false }
  }, [updateElectionUrl])

  // 2. Handle browser Back/Forward (popstate) navigation
  useEffect(() => {
    const handlePopState = () => {
      if (typeof window === 'undefined') return
      const sp = new URLSearchParams(window.location.search)
      const eid = sp.get('election_id') || sp.get('electionId') || ''
      if (eid && eid !== electionId) {
        setElectionId(eid)
      }
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [electionId])

  // 3. Load verification and result data protected by activeRequestIdRef
  const loadVerification = useCallback(async (eid) => {
    if (!eid) return
    const requestId = ++activeRequestIdRef.current
    setLoading(true)
    setError('')
    setTamperResult(null)
    setResultsData(null)
    setResultsUnavailableMsg('')
    setPendingQueueMsg('')
    setUnderReviewMsg('')

    try {
      // Step A: Fetch public verification parameters
      const vData = await api.get(`/elections/${eid}/verification`)
      if (requestId !== activeRequestIdRef.current) return
      setVerificationData(vData)

      // Step B: Fetch results if closed or finalized
      if (vData.results_available) {
        try {
          const rData = await api.get(`/elections/${eid}/results`)
          if (requestId !== activeRequestIdRef.current) return
          setResultsData(rData)

          // Check for in-flight relayer queue or review states
          if (rData.result_state === 'PROCESSING_PENDING_BALLOTS') {
            setPendingQueueMsg(rData.message || 'Ballot relayer queue is actively settling votes on the blockchain.')
          } else if (rData.result_state === 'RESULTS_UNDER_REVIEW' || rData.is_under_review) {
            setUnderReviewMsg(
              rData.message || 'Results are currently under review due to open reconciliation issues or blockchain divergence.'
            )
          }
        } catch (rErr) {
          if (requestId !== activeRequestIdRef.current) return
          if (rErr.status === 423 || rErr.payload?.result_state === 'PROCESSING_PENDING_BALLOTS') {
            setPendingQueueMsg(
              rErr.payload?.message || rErr.message || 'In-flight ballots are currently settling in the relayer queue.'
            )
          } else if (rErr.status === 403) {
            setResultsUnavailableMsg(
              rErr.payload?.message || rErr.message || 'Voting is currently active. Results remain strictly withheld.'
            )
          } else {
            setUnderReviewMsg(rErr.message || 'Results under review.')
          }
        }
      } else {
        setResultsUnavailableMsg(
          `Voting is currently ${vData.status}. Results remain strictly withheld until election close.`
        )
      }
    } catch (err) {
      if (requestId !== activeRequestIdRef.current) return
      setError(err.message || 'Failed to load public verification data.')
      setVerificationData(null)
    } finally {
      if (requestId === activeRequestIdRef.current) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    if (electionId) {
      loadVerification(electionId)
    }
  }, [electionId, loadVerification])

  // Handle user selecting an election from dropdown
  const handleSelectElection = (e) => {
    const selected = e.target.value
    setElectionId(selected)
    updateElectionUrl(selected)
  }

  // Handle Refresh button
  const handleRefresh = () => {
    if (electionId) {
      loadVerification(electionId)
    }
  }

  // Handle Tampering Demonstration (Officer/Auditor sandbox only)
  const handleTamperingDemo = async () => {
    setTamperingBusy(true)
    setError('')
    try {
      const demoRes = await api.post(`/elections/${electionId}/tampering-demo`, {})
      setTamperResult(demoRes)
    } catch (err) {
      setError(err.message || 'Failed to execute tampering demonstration.')
    } finally {
      setTamperingBusy(false)
    }
  }

  // Navigate to receipt verification tool with election context
  const handleNavigateToReceipt = () => {
    if (electionId) {
      navigate(`/receipt-verification?election_id=${encodeURIComponent(electionId)}`)
    } else {
      navigate('/receipt-verification')
    }
  }

  // Safety checks: response consistency and discrepancies
  const hasSafetyMismatch = Boolean(
    resultsData && (
      resultsData.is_under_review === true ||
      resultsData.tally_matches_blockchain === false ||
      Number(resultsData.open_reconciliation_issues) > 0
    )
  )

  const rawResultState = resultsData?.result_state ?? null
  const isResultsAvailable = Boolean(verificationData?.results_available)

  const isResultsUnavailable = Boolean(
    !isResultsAvailable ||
    resultsUnavailableMsg ||
    rawResultState === 'RESULTS_UNAVAILABLE'
  )

  const isPendingQueue = Boolean(
    pendingQueueMsg ||
    rawResultState === 'PROCESSING_PENDING_BALLOTS'
  )

  const isUnderReview = Boolean(
    underReviewMsg ||
    rawResultState === 'RESULTS_UNDER_REVIEW' ||
    hasSafetyMismatch
  )

  const isFinalizedResults = Boolean(
    !isResultsUnavailable &&
    !isPendingQueue &&
    !isUnderReview &&
    rawResultState === 'FINALIZED_RESULTS'
  )

  const isProvisional = Boolean(
    !isResultsUnavailable &&
    !isPendingQueue &&
    !isUnderReview &&
    !isFinalizedResults &&
    rawResultState === 'PROVISIONAL_UNFINALIZED'
  )

  // Fail-closed gating: tallies and candidate results are displayed ONLY for the two approved states
  const canDisplayTallies = Boolean(
    resultsData &&
    !isResultsUnavailable &&
    !isPendingQueue &&
    !isUnderReview &&
    (isFinalizedResults || isProvisional)
  )

  // Explicit classification of unrecognized, missing, null, or unexpected states
  const isUnrecognizedOrIncompleteState = Boolean(
    resultsData &&
    !isResultsUnavailable &&
    !isPendingQueue &&
    !isUnderReview &&
    !canDisplayTallies
  )

  // Status computation for Candidate Hash comparison
  const candHashMatch = verificationData?.blockchain_evidence?.candidates_hash_matches
  const candHashStatus = candHashMatch === true ? 'MATCHED' : candHashMatch === false ? 'MISMATCH' : 'UNAVAILABLE'

  // Direct null-safe read of blockchain roll hash comparison; verificationData.roll_hash reference preserved for schema check without rendering raw digest
  const _hasStoredRollHash = Boolean(verificationData && verificationData.roll_hash)
  const rollHashMatch = verificationData?.blockchain_evidence?.roll_hash_matches
  const rollHashStatus = rollHashMatch === true ? 'MATCHED' : rollHashMatch === false ? 'MISMATCH' : 'UNAVAILABLE'

  // Status computation for Audit-Chain Integrity
  const auditChainIntact = verificationData?.audit_evidence?.chain_intact
  const auditChainStatus = auditChainIntact === true ? 'AUDIT CHAIN VERIFIED' : auditChainIntact === false ? 'FAILED' : 'UNAVAILABLE'

  // Status computation for Smart-Contract Audit Anchor
  const auditAnchorSupported = verificationData?.blockchain_evidence?.audit_anchor_supported !== false
  const anchorVerified = verificationData?.blockchain_evidence?.audit_anchor_verified
  const anchorCount = verificationData?.blockchain_evidence?.audit_anchor_count
  const auditAnchorStatus = anchorVerified === true ? 'VERIFIED' : (anchorCount > 0 ? 'FAILED' : 'UNAVAILABLE')

  // Status computation for Merkle Root Recording
  const hasMerkleRoot = Boolean(verificationData?.merkle_root && verificationData.merkle_root.trim() !== '')
  const merkleRootStatus = (hasMerkleRoot && verificationData?.status === 'FINALIZED' && auditChainIntact !== false)
    ? 'ROOT RECORDED'
    : (hasMerkleRoot && auditChainIntact === false)
    ? 'FAILED'
    : 'UNAVAILABLE'

  // Status computation for Blockchain Tallies
  const blockchainTallyStatus = resultsData
    ? (resultsData.tally_matches_blockchain === true
        ? 'VERIFIED'
        : resultsData.tally_matches_blockchain === false
        ? 'FAILED'
        : 'UNAVAILABLE')
    : 'UNAVAILABLE'

  // Authoritative Overall Verification Verdict computation
  const isElectionInProgress = ['DRAFT', 'PENDING_APPROVAL', 'SCHEDULED', 'OPEN', 'ACTIVE'].includes(
    String(verificationData?.status || '').toUpperCase()
  )

  const hasExplicitFailure = Boolean(
    verificationData?.verification_status === 'FAILED' ||
    auditChainStatus === 'FAILED' ||
    candHashStatus === 'MISMATCH' ||
    rollHashStatus === 'MISMATCH' ||
    auditAnchorStatus === 'FAILED' ||
    merkleRootStatus === 'FAILED' ||
    blockchainTallyStatus === 'FAILED'
  )

  const allRequiredChecksPassed = Boolean(
    !hasExplicitFailure &&
    verificationData?.verification_status === 'VERIFIED' &&
    auditChainStatus === 'AUDIT CHAIN VERIFIED' &&
    (candHashStatus === 'MATCHED' || candHashStatus === 'UNAVAILABLE') &&
    (auditAnchorSupported ? auditAnchorStatus === 'VERIFIED' : (!resultsData || blockchainTallyStatus === 'VERIFIED')) &&
    (verificationData?.status !== 'FINALIZED' || merkleRootStatus === 'ROOT RECORDED')
  )

  let overallBadgeClass = 'badge-warning'
  let overallVerdictText = 'Verification Pending'

  if (hasExplicitFailure) {
    overallBadgeClass = 'badge-warning'
    overallVerdictText = 'Integrity Issue'
  } else if (isElectionInProgress) {
    overallBadgeClass = 'badge-phase'
    overallVerdictText = 'Election in Progress (Verification Pending Finalization)'
  } else if (verificationData?.verification_status === 'UNAVAILABLE') {
    overallBadgeClass = 'badge-warning'
    overallVerdictText = 'On-Chain Verification Unavailable'
  } else if (allRequiredChecksPassed) {
    overallBadgeClass = 'badge-verified'
    overallVerdictText = 'Audit Checks Clean'
  } else {
    overallBadgeClass = 'badge-warning'
    overallVerdictText = 'Verification Pending On-Chain Settlement'
  }

  return (
    <section className="card verification-card" role="region" aria-labelledby="verification-heading">
      <div className="card-header">
        <h2 id="verification-heading" className="card-title">
          Public Verification & Results
        </h2>
        <span className="badge badge-phase">Public Audit</span>
      </div>

      <p className="description">
        Independently audit and verify election parameters, smart contract state, cryptographic
        candidate set hashes, and administrative audit chain anchors.
      </p>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {/* Dynamic Election Selector */}
      <div className="form-group election-selector-group">
        <label htmlFor="election-select" className="form-label">
          Select Election to Audit & Verify
        </label>
        <div className="input-row" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <select
            id="election-select"
            className="input-field"
            value={electionId}
            onChange={handleSelectElection}
            disabled={catalogLoading || loading}
            style={{ flex: 1, minWidth: '260px' }}
          >
            {catalogLoading ? (
              <option value="">Loading election catalog...</option>
            ) : elections.length === 0 ? (
              <option value="">No public elections available</option>
            ) : (
              elections.map((el) => (
                <option key={el.election_id} value={el.election_id}>
                  {el.title} — [{el.status}]
                </option>
              ))
            )}
          </select>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleRefresh}
            disabled={loading || !electionId}
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {verificationData && (
        <div className="verification-content">
          {/* Status Header */}
          <div className="verification-status-banner">
            <div>
              <h3 className="election-title">{verificationData.title}</h3>
              <p className="election-meta">
                ID: <strong>{verificationData.election_id}</strong> | Status: <strong>{verificationData.status}</strong>
              </p>
            </div>
            <div className="status-badge-container">
              <span
                className={`badge badge-verdict ${
                  overallBadgeClass
                }`}
              >
                {overallVerdictText}
              </span>
            </div>
          </div>

          {/* Section: Official Ballot Receipt Evidence (if present in verification payload) */}
          {verificationData.receipt_evidence && (
            <div className="detail-section" role="region" aria-label="Official Receipt Verification">
              <h4 className="section-subtitle">Official Ballot Receipt Evidence</h4>
              <div className="receipt-evidence-box" style={{ background: '#FFFDF5', border: '3px solid #000', padding: '1.25rem', marginTop: '0.75rem', boxShadow: '4px 4px 0px #000' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}>
                  <span className="font-mono" style={{ fontSize: '1.1rem', fontWeight: 800 }}>
                    {verificationData.receipt_evidence.receipt_code}
                  </span>
                  <span className={`badge ${verificationData.receipt_evidence.status === 'VALID' ? 'badge-verified' : 'badge-warning'}`}>
                    {verificationData.receipt_evidence.status === 'VALID' ? 'VALID OFFICIAL RECEIPT' : verificationData.receipt_evidence.status}
                  </span>
                </div>
                <div className="grid-params">
                  <div className="param-item">
                    <span className="param-label">HMAC Cryptographic Proof</span>
                    <span className="param-value font-mono">
                      {verificationData.receipt_evidence.hmac_verified ? 'Verified (HMAC Match)' : 'Signature Failed'}
                    </span>
                  </div>
                  <div className="param-item">
                    <span className="param-label">Blockchain Settlement</span>
                    <span className="param-value">
                      {verificationData.receipt_evidence.on_chain_confirmed
                        ? `Confirmed in Block #${verificationData.receipt_evidence.block_number}`
                        : 'Settlement Pending'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Section 1: Smart Contract & Cryptographic Hashes */}
          <div className="detail-section">
            <h4 className="section-subtitle">Smart Contract & Cryptographic Hashes</h4>
            <div className="grid-params">
              <div className="param-item">
                <span className="param-label">Smart Contract Address</span>
                <span className="param-value font-mono">
                  {verificationData.contract_address || 'Not deployed'}
                </span>
              </div>

              {/* Candidate Set Hash with verification status */}
              <div className="param-item">
                <span className="param-label">Candidate Set Hash (SHA-256)</span>
                <span className="param-value font-mono" style={{ wordBreak: 'break-all' }}>
                  {verificationData.candidates_hash || 'N/A'}
                </span>
                <span className="param-subtext" style={{ marginTop: '0.25rem' }}>
                  Candidate-set hash:{' '}
                  <strong className={candHashStatus === 'MATCHED' ? 'text-success' : candHashStatus === 'MISMATCH' ? 'text-error' : 'text-muted'}>
                    {candHashStatus}
                  </strong>
                </span>
              </div>

              {/* Voter Roll Hash - Precise comparison terminology (raw hex omitted) */}
              <div className="param-item">
                <span className="param-label">Voter Roll Digest Comparison</span>
                <span className="param-value">
                  Voter-roll hash:{' '}
                  <strong className={rollHashStatus === 'MATCHED' ? 'text-success' : rollHashStatus === 'MISMATCH' ? 'text-error' : 'text-muted'}>
                    {rollHashStatus}
                  </strong>
                </span>
                <span className="param-subtext" style={{ fontSize: '0.75rem', color: '#6B7280', marginTop: '0.25rem', display: 'block' }}>
                  Cryptographic hash comparison verifies identity of the stored digest between the database and the smart contract. It does not certify the completeness, accuracy, or institutional authorization of the original voter roll.
                </span>
              </div>

              <div className="param-item">
                <span className="param-label">Max Ballots Per Voter</span>
                <span className="param-value">{verificationData.max_ballots || 3}</span>
              </div>
            </div>
          </div>

          {/* Section 2: Administrative Audit Hash-Chain */}
          <div className="detail-section">
            <h4 className="section-subtitle">Administrative Audit Hash-Chain</h4>
            <div className="grid-params">
              <div className="param-item">
                <span className="param-label">Audit Chain Integrity</span>
                <span className="param-value">
                  <strong className={auditChainStatus === 'AUDIT CHAIN VERIFIED' ? 'text-success' : auditChainStatus === 'FAILED' ? 'text-error' : 'text-muted'}>
                    {auditChainStatus}
                  </strong>
                </span>
              </div>
              <div className="param-item">
                <span className="param-label">Total Logged Audit Events</span>
                <span className="param-value">{verificationData.audit_evidence?.total_audit_events || 0}</span>
              </div>
              <div className="param-item">
                <span className="param-label">Latest Audit Hash Pointer</span>
                <span className="param-value font-mono" style={{ wordBreak: 'break-all' }}>
                  {verificationData.audit_evidence?.latest_audit_hash || 'N/A'}
                </span>
              </div>
              <div className="param-item">
                <span className="param-label">Smart-Contract Audit Anchor</span>
                <span className="param-value font-mono" style={{ wordBreak: 'break-all' }}>
                  {verificationData.blockchain_evidence?.audit_anchor || 'Unanchored'}
                </span>
                <span className="param-subtext" style={{ marginTop: '0.25rem' }}>
                  Anchor status:{' '}
                  <strong className={auditAnchorStatus === 'VERIFIED' ? 'text-success' : auditAnchorStatus === 'FAILED' ? 'text-error' : 'text-muted'}>
                    {auditAnchorStatus}
                  </strong>
                  {!auditAnchorSupported && auditAnchorStatus === 'UNAVAILABLE' && ' (Not applicable to V2 threshold contracts)'}
                  {verificationData.blockchain_evidence?.audit_anchor_block && ` (Block #${verificationData.blockchain_evidence.audit_anchor_block})`}
                </span>
              </div>
            </div>
          </div>

          {/* Section 3: Ballot Inclusion & Merkle Root Recording */}
          <div className="detail-section" role="region" aria-label="Ballot Inclusion & Merkle Root">
            <h4 className="section-subtitle">Ballot Merkle Tree Status</h4>
            <div className="grid-params">
              <div className="param-item">
                <span className="param-label">Finalized Merkle Root (RFC 6962)</span>
                <span className="param-value font-mono" style={{ wordBreak: 'break-all', fontWeight: 700 }}>
                  {verificationData.merkle_root || 'None (Pending Election Finalization)'}
                </span>
                <span className="param-subtext" style={{ marginTop: '0.25rem' }}>
                  Root status:{' '}
                  <strong className={merkleRootStatus === 'ROOT RECORDED' ? 'text-success' : merkleRootStatus === 'FAILED' ? 'text-error' : 'text-muted'}>
                    {merkleRootStatus}
                  </strong>
                </span>
              </div>
              <div className="param-item">
                <span className="param-label">Individual Ballot Inclusion</span>
                <span className="param-value">
                  Verifiable via Client-Side Receipt Tool
                </span>
                <span className="param-subtext" style={{ fontSize: '0.75rem', color: '#6B7280', marginTop: '0.25rem', display: 'block' }}>
                  An intact audit event containing a Merkle root does not independently prove ballot inclusion. Voters independently verify inclusion proofs against the trusted root.
                </span>
              </div>
            </div>
          </div>

          {/* Section 4: Results & Tallies (Strict 5-State Gating) */}
          <div className="detail-section">
            <h4 className="section-subtitle">Election Results & Tallies</h4>

            {/* Condition 1: RESULTS_UNAVAILABLE */}
            {isResultsUnavailable ? (
              <div className="alert alert-info">
                <strong>Results Withheld:</strong> {resultsUnavailableMsg || 'Voting is currently active. Official tallies are withheld until election close.'}
              </div>
            ) : isPendingQueue ? (
              /* Condition 2: PROCESSING_PENDING_BALLOTS (Strictly Withhold Tallies) */
              <div className="alert alert-warning" role="alert">
                <strong>Ballot Relayer Queue Active:</strong> {pendingQueueMsg || 'In-flight ballots are currently being settled on the blockchain. Official tallies and winners are strictly withheld until the relayer queue is clear.'}
              </div>
            ) : isUnderReview ? (
              /* Condition 3: RESULTS_UNDER_REVIEW (Strictly Withhold Tallies) */
              <div className="alert alert-error" role="alert">
                <strong>Results Under Review:</strong> {underReviewMsg || 'Discrepancy detected between smart-contract tallies and database records, or open reconciliation issues exist. Official tallies and winners are withheld pending officer audit.'}
              </div>
            ) : isUnrecognizedOrIncompleteState ? (
              /* Condition 4: Unrecognized, Missing, Null, or Incomplete State (Fail Closed) */
              <div className="alert alert-error" role="alert">
                <strong>Results Withheld:</strong> The server returned an unrecognized or incomplete result state. Officer review is required.
              </div>
            ) : canDisplayTallies ? (
              /* Condition 5: Explicitly PROVISIONAL_UNFINALIZED or FINALIZED_RESULTS */
              <div className="results-container">
                {/* Result State Classification Header */}
                <div style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  {isFinalizedResults ? (
                    <span className="badge badge-verified" style={{ fontSize: '0.95rem', padding: '0.4rem 0.8rem' }}>
                      OFFICIALLY CERTIFIED & FINALIZED
                    </span>
                  ) : (
                    <span className="badge badge-warning" style={{ fontSize: '0.95rem', padding: '0.4rem 0.8rem', background: '#FEF3C7', color: '#92400E', border: '2px solid #000' }}>
                      PROVISIONAL RESULTS (UNFINALIZED)
                    </span>
                  )}
                  {isProvisional && (
                    <p style={{ margin: 0, fontSize: '0.85rem', color: '#4B5563', fontWeight: 600 }}>
                      Voting has concluded and counts match the smart contract. These results are provisional and pending official two-officer certification.
                    </p>
                  )}
                </div>

                <div className="results-summary-row">
                  <div className="summary-pill">
                    <span>Distinct Voters</span>
                    <strong>{resultsData.total_distinct_voters}</strong>
                  </div>
                  <div className="summary-pill">
                    <span>Turnout</span>
                    <strong>{resultsData.turnout_percentage}%</strong>
                  </div>
                  <div className="summary-pill">
                    <span>Valid Ballots</span>
                    <strong>{resultsData.total_valid_votes}</strong>
                  </div>
                  <div className="summary-pill">
                    <span>Retracted (Null)</span>
                    <strong>{resultsData.total_null_votes}</strong>
                  </div>
                </div>

                <div className="candidate-list">
                  {resultsData.candidates?.map((cand) => (
                    <div key={cand.candidate_index} className="candidate-result-row">
                      <div className="candidate-info">
                        <span className="candidate-name">{cand.name}</span>
                        {cand.department && <span className="candidate-dept">{cand.department}</span>}
                      </div>
                      <div className="candidate-tally-bar-container">
                        <div
                          className="candidate-tally-bar"
                          style={{ width: `${Math.max(cand.percentage, 4)}%` }}
                        />
                      </div>
                      <div className="candidate-votes-wrap">
                        <span className="candidate-votes">{cand.votes} votes</span>
                        <span className="candidate-pct">({cand.percentage}%)</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Blockchain Tally Verification Cross-Check */}
                <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#F9FAFB', border: '2px solid #E5E7EB' }}>
                  <span>Blockchain Tallies: </span>
                  <strong className={blockchainTallyStatus === 'VERIFIED' ? 'text-success' : blockchainTallyStatus === 'FAILED' ? 'text-error' : 'text-muted'}>
                    {blockchainTallyStatus === 'VERIFIED'
                      ? 'VERIFIED (Smart-contract getTally() matches canonical counts)'
                      : blockchainTallyStatus === 'FAILED'
                      ? 'FAILED (Count mismatch between contract and database)'
                      : isProvisional
                      ? 'UNAVAILABLE (Election Not Yet Finalized)'
                      : 'UNAVAILABLE'}
                  </strong>
                </div>
              </div>
            ) : (
              <p className="subtext">Loading election tallies...</p>
            )}
          </div>

          {/* Section 5: Receipt Verification Action Bridge */}
          <div className="detail-section" style={{ background: '#F0FDF4', border: '3px solid #000', padding: '1.5rem', boxShadow: '4px 4px 0px #000' }}>
            <h4 className="section-subtitle" style={{ marginTop: 0 }}>Verify Your Individual Ballot</h4>
            <p className="description" style={{ marginBottom: '1rem' }}>
              Have a ballot receipt? Verify that your ballot was cryptographically recorded by the relayer and included in this election's settled Merkle tree.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleNavigateToReceipt}
            >
              Verify My Receipt &rarr;
            </button>
          </div>

          {/* Section 6: Independent Verification Command */}
          <div className="detail-section">
            <h4 className="section-subtitle">Independent Verifier Script</h4>
            <p className="subtext">
              Run the standalone Python verifier to independently reconstruct the election tally
              directly from raw blockchain events:
            </p>
            <pre className="cli-command font-mono">
              python backend/scripts/verify_election.py --election-id {verificationData.election_id}
            </pre>
          </div>

          {/* Section 7: Controlled Tampering Demonstration (Admin / Auditor Only) */}
          {showTamperingDemo && (
            <div className="detail-section">
              <h4 className="section-subtitle">Tampering Detection Demonstration</h4>
              <p className="subtext">
                Trigger a controlled test that temporarily injects a single database inconsistency,
                verifies that reconciliation flags the mismatch, and cleanly restores the database.
              </p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleTamperingDemo}
                disabled={tamperingBusy}
              >
                {tamperingBusy ? 'Simulating Tamper & Rollback...' : 'Run Tampering Demonstration'}
              </button>

              {tamperResult && (
                <div
                  className={`alert ${
                    tamperResult.demonstration_verdict === 'SUCCESS' ? 'alert-success' : 'alert-error'
                  } mt-3`}
                >
                  <strong>Tampering Demonstration Result:</strong>{' '}
                  {tamperResult.demonstration_verdict === 'SUCCESS'
                    ? 'MISMATCH DETECTED & CLEANLY RESTORED'
                    : 'FAILED'}
                  <ul className="tamper-details-list">
                    <li>Injected Tamper Detected: {tamperResult.tamper_detected ? 'Yes (Mismatch Flagged)' : 'No'}</li>
                    <li>Original State Restored: {tamperResult.restored_verified ? 'Yes (Pristine Tally Verified)' : 'No'}</li>
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
