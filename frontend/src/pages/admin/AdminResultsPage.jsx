import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import { API_BASE_URL } from '../../config/env.js'
import { buildApiUrl } from '../../api/urls.js'
import '../public/Pages.css'

/**
 * Execute client-side Blob file download with guaranteed anchor and URL cleanup.
 * - On success: temporary anchor is removed immediately; URL revocation is deferred by 1000ms.
 * - On failure: temporary anchor is removed immediately; URL is revoked immediately.
 * - Double revocation is strictly avoided.
 */
export function triggerBlobDownload(
  blob,
  filename,
  win = (typeof window !== 'undefined' ? window : null),
  doc = (typeof document !== 'undefined' ? document : null)
) {
  if (!win || !doc) return
  let blobUrl = null
  let link = null
  let revoked = false

  const revoke = () => {
    if (!revoked && blobUrl) {
      revoked = true
      try {
        win.URL.revokeObjectURL(blobUrl)
      } catch {
        // Ignore cleanup error if already revoked
      }
    }
  }

  try {
    blobUrl = win.URL.createObjectURL(blob)
    link = doc.createElement('a')
    link.href = blobUrl
    link.download = filename
    doc.body.appendChild(link)
    link.click()

    // Defer revocation by 1000ms on success
    setTimeout(revoke, 1000)
  } catch (domErr) {
    // Revoke immediately on failure
    revoke()
    throw domErr
  } finally {
    // Guarantee temporary anchor cleanup on both success and failure
    if (link && link.parentNode) {
      try {
        link.parentNode.removeChild(link)
      } catch {
        // Ignore removal error
      }
    }
  }
}

export default function AdminResultsPage() {
  const { params, navigate } = useRouter()
  const { adminToken, adminAuth } = useAuth()

  // Track active request ID to invalidate stale asynchronous responses
  const activeRequestIdRef = useRef(0)

  // Invalidate any pending in-flight requests when unmounting
  useEffect(() => {
    return () => {
      activeRequestIdRef.current += 1
    }
  }, [])

  // Officer role context
  const isOfficer = adminAuth?.role === 'OFFICER'
  const currentAdminId = adminAuth?.admin_id

  // Election directory & selection state
  const [allElections, setAllElections] = useState([])
  const [electionsLoading, setElectionsLoading] = useState(true)
  const [selectedElectionId, setSelectedElectionId] = useState('')

  // Results query state
  const [results, setResults] = useState(null)
  const [pendingPayload, setPendingPayload] = useState(null)
  const [withheldPayload, setWithheldPayload] = useState(null)
  const [resultsLoading, setResultsLoading] = useState(false)
  const [error, setError] = useState('')

  // Approvals & Finalization state
  const [approvals, setApprovals] = useState([])
  const [showFinalizeModal, setShowFinalizeModal] = useState(false)
  const [finalizeReason, setFinalizeReason] = useState('')
  const [finalizeSubmitting, setFinalizeSubmitting] = useState(false)
  const [finalizeError, setFinalizeError] = useState('')
  const [finalizeSuccess, setFinalizeSuccess] = useState('')

  // Export state
  const [exportLoading, setExportLoading] = useState(null) // null | 'csv' | 'xlsx'
  const [exportError, setExportError] = useState('')

  // Fetch approvals for two-officer governance awareness
  const fetchApprovals = useCallback(async () => {
    if (!adminToken) return
    try {
      const res = await api.get('/admin/approvals', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setApprovals(res?.approval_requests || [])
    } catch {
      // Supplementary query failure should not break results rendering
    }
  }, [adminToken])

  // 1. Fetch results for a specific election with stale-response protection
  const fetchResults = useCallback(async (eid) => {
    if (!eid) return
    const requestId = ++activeRequestIdRef.current
    setResultsLoading(true)
    setError('')
    setExportError('')
    setResults(null)
    setPendingPayload(null)
    setWithheldPayload(null)

    try {
      const res = await api.get(`/elections/${encodeURIComponent(eid)}/results`)
      // Drop response if a newer request was initiated
      if (activeRequestIdRef.current !== requestId) return
      setResults(res)
    } catch (err) {
      // Drop error if a newer request was initiated
      if (activeRequestIdRef.current !== requestId) return
      if (err.status === 423 || err.payload?.result_state === 'PROCESSING_PENDING_BALLOTS') {
        setPendingPayload(err.payload || {
          result_state: 'PROCESSING_PENDING_BALLOTS',
          message: err.message || 'Ballot queue is actively draining on blockchain.',
          pending_ballots_count: err.payload?.pending_ballots_count || 0,
        })
      } else if (err.status === 403 || err.payload?.error === 'RESULTS_UNAVAILABLE') {
        setWithheldPayload(err.payload || {
          error: 'RESULTS_UNAVAILABLE',
          message: err.message || 'Results remain strictly withheld until election close.',
        })
      } else {
        setError(err.message || 'Failed to query results for the selected election.')
      }
    } finally {
      // Only clear loading state if this request is still the active one
      if (activeRequestIdRef.current === requestId) {
        setResultsLoading(false)
      }
    }
  }, [])

  // 2. Load all elections on mount
  useEffect(() => {
    let mounted = true
    const loadElections = async () => {
      setElectionsLoading(true)
      try {
        let list = []
        try {
          const res = await api.get('/admin/elections', {
            headers: adminToken ? { Authorization: `Bearer ${adminToken}` } : {},
          })
          list = res?.elections || []
        } catch {
          const pubRes = await api.get('/public/elections')
          list = pubRes?.elections || []
        }

        if (!mounted) return
        setAllElections(list)

        // URL persistence: restore election from URL query parameter if present
        const urlParamId = (
          params?.electionId ||
          params?.id ||
          (typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('election_id') : null) ||
          ''
        ).trim()

        let initialId = ''
        if (urlParamId && list.some((e) => String(e.election_id) === urlParamId || String(e.id) === urlParamId)) {
          const matched = list.find((e) => String(e.election_id) === urlParamId || String(e.id) === urlParamId)
          initialId = matched ? String(matched.election_id) : urlParamId
        } else if (list.length > 0) {
          // Prioritize closed/finalized elections, otherwise first election
          const preferred = list.find((e) => e.status === 'CLOSED' || e.status === 'FINALIZED') || list[0]
          initialId = String(preferred.election_id)
        }

        if (initialId) {
          setSelectedElectionId(initialId)
          if (navigate && urlParamId !== initialId) {
            navigate(`/admin/results?election_id=${encodeURIComponent(initialId)}`)
          }
          fetchResults(initialId)
          fetchApprovals()
        }
      } catch (err) {
        if (mounted) {
          setError(err.message || 'Failed to load collegiate elections list.')
        }
      } finally {
        if (mounted) {
          setElectionsLoading(false)
        }
      }
    }

    loadElections()
    return () => { mounted = false }
  }, [adminToken, fetchApprovals, fetchResults, navigate, params])

  // 3. Handle selection change with URL persistence
  const handleSelectElection = (newId) => {
    if (!newId || newId === selectedElectionId) return
    setExportError('')
    setSelectedElectionId(newId)
    if (navigate) {
      navigate(`/admin/results?election_id=${encodeURIComponent(newId)}`)
    }
    fetchResults(newId)
    fetchApprovals()
  }

  // Find currently selected election object
  const currentElection = allElections.find(
    (e) => String(e.election_id) === String(selectedElectionId) || String(e.id) === String(selectedElectionId)
  )

  // Find active pending finalization request for this election
  const activeFinalizeApproval = approvals.find(
    (a) =>
      (String(a.election_id) === String(selectedElectionId) ||
        (currentElection?.id && String(a.election_id) === String(currentElection.id))) &&
      a.action_type === 'FINALIZE_ELECTION' &&
      a.status === 'PENDING'
  )

  // Handle officer requesting finalization
  const handleRequestFinalization = async (e) => {
    e.preventDefault()
    if (!finalizeReason || finalizeReason.trim().length < 10) {
      setFinalizeError('Please provide a substantive justification (minimum 10 characters).')
      return
    }
    setFinalizeSubmitting(true)
    setFinalizeError('')
    setFinalizeSuccess('')
    try {
      const res = await api.post(
        `/admin/elections/${encodeURIComponent(selectedElectionId)}/request-approval`,
        {
          action_type: 'FINALIZE_ELECTION',
          reason: finalizeReason.trim(),
        },
        {
          headers: adminToken ? { Authorization: `Bearer ${adminToken}` } : {},
        }
      )
      setFinalizeSuccess(res?.message || 'Two-officer approval requested for finalization.')
      setShowFinalizeModal(false)
      setFinalizeReason('')
      await fetchApprovals()
      await fetchResults(selectedElectionId)
    } catch (err) {
      setFinalizeError(err?.message || 'Failed to request election finalization.')
    } finally {
      setFinalizeSubmitting(false)
    }
  }

  const resultState = results?.result_state || (
    results?.is_finalized ? 'FINALIZED_RESULTS' : (results ? 'PROVISIONAL_UNFINALIZED' : null)
  )

  // Export gate: strictly withhold exports while results are unfinalized/provisional with issues,
  // actively draining, withheld, under review, or loading
  const isExportDisabled = Boolean(
    !results ||
    resultsLoading ||
    resultState === 'RESULTS_UNDER_REVIEW' ||
    results?.is_under_review === true ||
    (results?.open_reconciliation_issues && results.open_reconciliation_issues > 0) ||
    results?.tally_matches_blockchain === false ||
    (resultState !== 'PROVISIONAL_UNFINALIZED' && resultState !== 'FINALIZED_RESULTS')
  )

  // Handle CSV/XLSX export download
  const handleExport = async (format) => {
    if (exportLoading || isExportDisabled || !selectedElectionId) return
    const targetEid = selectedElectionId
    setExportLoading(format)
    setExportError('')

    try {
      const res = await api.raw(
        `/admin/elections/${encodeURIComponent(targetEid)}/export?format=${encodeURIComponent(format)}`,
        {
          method: 'GET',
          headers: {
            ...(adminToken ? { Authorization: `Bearer ${adminToken}` } : {}),
          },
        }
      )

      if (selectedElectionId !== targetEid) return

      if (!res.ok) {
        let errMsg = `Export request failed with status ${res.status}`
        try {
          const errData = await res.json()
          if (errData && (errData.error || errData.message)) {
            errMsg = errData.message || errData.error
          }
        } catch {
          // not json
        }
        setExportError(errMsg)
        return
      }

      // Extract filename from Content-Disposition header if available
      let filename = ''
      const disposition = res.headers.get('content-disposition') || res.headers.get('Content-Disposition')
      if (disposition && disposition.includes('filename=')) {
        const match = disposition.match(/filename=["']?([^"';]+)["']?/)
        if (match && match[1]) {
          filename = match[1].trim()
        }
      }
      if (!filename) {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
        filename = `${targetEid}_results_${timestamp}.${format}`
      }

      const blob = await res.blob()
      if (selectedElectionId !== targetEid) return

      triggerBlobDownload(blob, filename)
    } catch (err) {
      if (selectedElectionId === targetEid) {
        setExportError(err?.message || 'Failed to download results export file.')
      }
    } finally {
      setExportLoading(null)
    }
  }

  return (
    <div className="page-container admin-results-page">
      {/* Top Header & Election Selector */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ flex: '1 1 320px' }}>
            <span className="badge badge-accent">BLOCKCHAIN SETTLEMENT</span>
            <h2 className="card-title" style={{ margin: '0.25rem 0' }}>Official Election Tally & Audit Inspection</h2>
            <p style={{ margin: 0, color: '#4B5563', fontSize: '0.9rem' }}>
              Select any collegiate election to inspect verifiable on-chain tallies, voter turnout, and reconciliation integrity.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              <label htmlFor="election-results-select" style={{ fontSize: '0.8rem', fontWeight: 800, color: '#374151' }}>
                Select Election:
              </label>
              <select
                id="election-results-select"
                value={selectedElectionId}
                onChange={(e) => handleSelectElection(e.target.value)}
                disabled={electionsLoading || allElections.length === 0}
                style={{
                  padding: '0.55rem 0.85rem',
                  fontWeight: 700,
                  fontSize: '0.9rem',
                  border: '2px solid #000',
                  borderRadius: '4px',
                  background: '#FFF',
                  minWidth: '280px',
                  cursor: 'pointer',
                }}
              >
                {allElections.length === 0 ? (
                  <option value="">{electionsLoading ? 'Loading elections...' : 'No elections found'}</option>
                ) : (
                  allElections.map((el) => (
                    <option key={el.election_id || el.id} value={el.election_id || el.id}>
                      {el.title} ({el.election_id || el.id}) — [{el.status || 'UNKNOWN'}]
                    </option>
                  ))
                )}
              </select>
            </div>

            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                fetchResults(selectedElectionId)
                fetchApprovals()
              }}
              disabled={resultsLoading || !selectedElectionId}
              style={{ marginTop: '1.25rem', padding: '0.55rem 1rem', fontWeight: 800 }}
              title="Query smart contract, relayer state, and approval queue fresh"
            >
              {resultsLoading ? 'Querying...' : '↻ Refresh Results'}
            </button>
          </div>
        </div>

        <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid #E5E7EB', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          {currentElection ? (
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.85rem' }}>
              <div><strong>Election Title:</strong> {currentElection.title}</div>
              <div><strong>Identifier:</strong> <code>{currentElection.election_id}</code></div>
              <div><strong>Status:</strong> <span className={`badge ${currentElection.status === 'FINALIZED' ? 'badge-verified' : 'badge-neutral'}`}>{currentElection.status}</span></div>
              {currentElection.candidate_count != null && <div><strong>Candidates:</strong> {currentElection.candidate_count}</div>}
            </div>
          ) : <div />}

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              id="export-csv-btn"
              type="button"
              className="btn btn-secondary"
              onClick={() => handleExport('csv')}
              disabled={Boolean(exportLoading || resultsLoading || isExportDisabled)}
              style={{ fontSize: '0.85rem', fontWeight: 700 }}
              title="Download RFC 4180 compliant CSV format"
            >
              {exportLoading === 'csv' ? 'Generating CSV...' : '📥 Export CSV'}
            </button>
            <button
              id="export-xlsx-btn"
              type="button"
              className="btn btn-secondary"
              onClick={() => handleExport('xlsx')}
              disabled={Boolean(exportLoading || resultsLoading || isExportDisabled)}
              style={{ fontSize: '0.85rem', fontWeight: 700 }}
              title="Download multi-tab Microsoft Excel spreadsheet (.xlsx)"
            >
              {exportLoading === 'xlsx' ? 'Generating Excel...' : '📥 Export Excel (.xlsx)'}
            </button>
          </div>
        </div>
      </div>

      {/* Export Error Banner */}
      {exportError && (
        <div className="card alert-box alert-error" style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <strong>Export Failed: </strong> {exportError}
            </div>
            <button
              type="button"
              onClick={() => setExportError('')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 800, fontSize: '1rem', color: '#991B1B' }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      {resultsLoading ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center' }}>
          <div style={{ fontWeight: 800, fontSize: '1.1rem' }}>Querying On-Chain Results & Relayer Queue...</div>
          <p style={{ color: '#6B7280', margin: '0.5rem 0 0 0' }}>Cross-referencing database tallies against smart contract getTally().</p>
        </div>
      ) : error ? (
        <div className="card alert-box alert-error">
          <h4>Query Failed</h4>
          <p>{error}</p>
          <button className="btn btn-secondary" onClick={() => fetchResults(selectedElectionId)} style={{ marginTop: '0.75rem' }}>
            Retry Query
          </button>
        </div>
      ) : pendingPayload ? (
        /* State 1: PROCESSING_PENDING_BALLOTS */
        <div className="card alert-box alert-warning">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span className="badge badge-warning">IN-FLIGHT BALLOTS DRAINING</span>
            <h3 style={{ margin: 0 }}>Ballots Actively Processing on Blockchain</h3>
          </div>
          <p style={{ marginTop: '0.75rem', fontSize: '0.95rem' }}>
            {pendingPayload.message || 'Ballot queue is actively draining on blockchain. Official tallies are withheld until pending transactions settle to ensure absolute result accuracy.'}
          </p>
          <div className="election-meta-grid" style={{ marginTop: '1rem', background: '#FFFDF5' }}>
            <div className="meta-item">
              <span className="meta-label">Pending In-Flight</span>
              <span className="meta-value">{pendingPayload.pending_ballots_count || 0}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Queued Ballots</span>
              <span className="meta-value">{pendingPayload.queued_count || 0}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Submitted to Relayer</span>
              <span className="meta-value">{pendingPayload.submitted_count || 0}</span>
            </div>
          </div>
          <div style={{ marginTop: '1rem' }}>
            <button className="btn btn-primary" onClick={() => fetchResults(selectedElectionId)} disabled={resultsLoading}>
              Check Settlement Status
            </button>
          </div>
        </div>
      ) : withheldPayload ? (
        /* State 2: Results Withheld (OPEN, SCHEDULED, DRAFT) */
        <div className="card alert-box alert-warning">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span className="badge badge-warning">RESULTS WITHHELD</span>
            <h3 style={{ margin: 0 }}>Voting Has Not Concluded</h3>
          </div>
          <p style={{ marginTop: '0.75rem' }}>
            {withheldPayload.message || `Results are withheld while election is in '${currentElection?.status || 'ACTIVE'}' status. Results become accessible once voting is CLOSED or FINALIZED.`}
          </p>
          <p style={{ fontSize: '0.85rem', color: '#6B7280', margin: '0.5rem 0 0 0' }}>
            Under VWD cryptographic security invariants, ballots cannot be decrypted or aggregated while voting remains open.
          </p>
        </div>
      ) : results ? (
        /* States 3, 4, 5: Results Ready (RESULTS_UNDER_REVIEW, PROVISIONAL_UNFINALIZED, FINALIZED_RESULTS) */
        <div className="card">
          {finalizeSuccess && (
            <div className="alert-box alert-success" style={{ marginBottom: '1.25rem' }}>
              <strong>Notice: </strong> {finalizeSuccess}
            </div>
          )}

          {/* Status Banner */}
          {resultState === 'RESULTS_UNDER_REVIEW' && (
            <div className="alert-box alert-warning" style={{ marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span className="badge badge-warning">UNDER AUDIT REVIEW</span>
                <strong>Reconciliation Discrepancies Detected</strong>
              </div>
              <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.9rem' }}>
                {results.warning || `Results are under review due to ${results.open_reconciliation_issues || 0} open reconciliation issue(s). Displayed tallies are PROVISIONAL and have not been certified.`}
              </p>
              <button
                className="btn btn-secondary"
                onClick={() => navigate && navigate('/admin/review')}
                style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}
              >
                Inspect in Dispute Console &rarr;
              </button>
            </div>
          )}

          {resultState === 'PROVISIONAL_UNFINALIZED' && (
            activeFinalizeApproval ? (
              <div className="alert-box" style={{ background: '#EFF6FF', border: '2px solid #3B82F6', marginBottom: '1.25rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className="badge badge-accent">APPROVAL PENDING</span>
                    <strong>Finalization Request #{activeFinalizeApproval.id} Awaiting Review</strong>
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => navigate && navigate('/admin/approvals')}
                    style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}
                  >
                    View in Approvals Queue &rarr;
                  </button>
                </div>
                <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.9rem', color: '#1E40AF' }}>
                  Requested by <strong>{activeFinalizeApproval.requester_name || activeFinalizeApproval.requester}</strong>. Awaiting independent cryptographic review and approval from a distinct commissioning officer.
                </p>
                {activeFinalizeApproval.reason && (
                  <p style={{ margin: '0.35rem 0 0 0', fontSize: '0.85rem', color: '#374151', fontStyle: 'italic' }}>
                    Justification: "{activeFinalizeApproval.reason}"
                  </p>
                )}
                {currentAdminId && activeFinalizeApproval.requester === currentAdminId && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#B45309', fontWeight: 700 }}>
                    Four-Eyes Notice: You initiated this request. A distinct commissioning officer must approve it. Self-approval is strictly forbidden.
                  </div>
                )}
              </div>
            ) : (
              <div className="alert-box" style={{ background: '#EFF6FF', border: '2px solid #3B82F6', marginBottom: '1.25rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="badge badge-accent">PROVISIONAL TALLIES</span>
                      <strong>Election Closed — Smart Contract Cross-Check Passed</strong>
                    </div>
                    <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.9rem', color: '#1E40AF' }}>
                      All in-flight ballots have confirmed on blockchain. Database tallies match <code>getTally()</code> cleanly. Ready for formal Two-Officer Finalization.
                    </p>
                  </div>
                  {isOfficer && (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => {
                        setShowFinalizeModal(true)
                        setFinalizeError('')
                        setFinalizeSuccess('')
                      }}
                      style={{ fontSize: '0.85rem', padding: '0.4rem 0.85rem', background: '#4F46E5', borderColor: '#4F46E5' }}
                    >
                      Request Finalization
                    </button>
                  )}
                </div>
              </div>
            )
          )}

          {resultState === 'FINALIZED_RESULTS' && (
            <div className="alert-box alert-success" style={{ marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span className="badge badge-verified">OFFICIALLY FINALIZED</span>
                <strong>Blockchain Settlement Sealed & Certified</strong>
              </div>
              <p style={{ margin: '0.4rem 0 0 0', fontSize: '0.9rem' }}>
                Election finalization checks verified by two authorized officers. Authoritative Merkle root sealed on blockchain.
              </p>
            </div>
          )}

          {/* Winner Banner */}
          {results.winners && results.winners.length > 0 && results.total_valid_votes > 0 && (
            <div style={{ background: '#FFFDF5', border: '2px solid #000', padding: '1rem', marginBottom: '1.5rem', borderRadius: '4px' }}>
              {results.is_tie ? (
                <div>
                  <span className="badge badge-warning" style={{ marginBottom: '0.5rem' }}>TIE ELECTION</span>
                  <h3 style={{ margin: '0.25rem 0' }}>Tie Declared Between {results.winners.map(w => w.name).join(' and ')}</h3>
                  <p style={{ margin: 0, fontSize: '0.9rem' }}>Each tied candidate received {results.winners[0]?.votes} votes.</p>
                </div>
              ) : (
                <div>
                  <span className="badge badge-verified" style={{ marginBottom: '0.5rem' }}>PROJECTED WINNER</span>
                  <h3 style={{ margin: '0.25rem 0' }}>{results.winners[0]?.name}</h3>
                  <p style={{ margin: 0, fontSize: '0.9rem' }}>Won with {results.winners[0]?.votes} vote(s).</p>
                </div>
              )}
            </div>
          )}

          {/* Participation Metrics Grid */}
          <div className="election-meta-grid" style={{ marginBottom: '1.5rem' }}>
            <div className="meta-item">
              <span className="meta-label">Total Distinct Voters</span>
              <span className="meta-value">{results.total_distinct_voters || 0}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Voter Turnout</span>
              <span className="meta-value">{results.turnout_percentage || 0}%</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Valid Candidate Ballots</span>
              <span className="meta-value">{results.total_valid_votes || 0}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Retracted (Null) Ballots</span>
              <span className="meta-value">{results.total_null_votes || 0}</span>
            </div>
          </div>

          {/* Candidate Vote Distribution */}
          <h3 style={{ marginBottom: '0.75rem' }}>Candidate Vote Distribution</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {results.candidates && results.candidates.length > 0 ? (
              results.candidates.map((c) => (
                <div key={c.candidate_index} style={{ border: '2px solid #000', padding: '0.85rem', background: '#FFFDF5' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontWeight: 800 }}>
                    <div>
                      <span>{c.name}</span>
                      {c.department && <span style={{ fontSize: '0.8rem', color: '#6B7280', marginLeft: '0.5rem', fontWeight: 600 }}>({c.department})</span>}
                    </div>
                    <span>{c.votes} vote{c.votes !== 1 ? 's' : ''} ({c.percentage}%)</span>
                  </div>
                  <div style={{ background: '#E5E7EB', height: '14px', border: '1px solid #000', marginTop: '0.5rem', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{ background: '#FFD93D', height: '100%', width: `${Math.max(c.percentage, c.votes > 0 ? 3 : 0)}%`, transition: 'width 0.3s ease' }} />
                  </div>
                </div>
              ))
            ) : (
              <p style={{ color: '#6B7280' }}>No candidate votes recorded.</p>
            )}
          </div>

          {/* Blockchain Verification Stamp */}
          <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid #E5E7EB', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div style={{ fontSize: '0.85rem' }}>
              {results.blockchain_verified && results.tally_matches_blockchain ? (
                <span style={{ color: '#059669', fontWeight: 700 }}>
                  ✓ Cryptographic Smart Contract Verification: DB counts match <code>getTally()</code> on blockchain.
                </span>
              ) : results.blockchain_verified === false ? (
                <span style={{ color: '#D97706', fontWeight: 700 }}>
                  ⚠ Blockchain cross-check could not be completed on RPC node.
                </span>
              ) : null}
            </div>
            <div style={{ fontSize: '0.8rem', color: '#6B7280' }}>
              Election ID: <code>{results.election_id}</code> (internal #{results.internal_id})
            </div>
          </div>
        </div>
      ) : null}

      {/* Two-Officer Finalization Modal */}
      {showFinalizeModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '560px',
              width: '100%',
              background: '#FFFFFF',
              border: '3px solid #4F46E5',
              boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <span className="badge" style={{ background: '#4F46E5', color: '#FFF', fontWeight: 800 }}>
                TWO-OFFICER GOVERNANCE
              </span>
              <h3 style={{ margin: 0, color: '#1E1B4B' }}>Request Ballot Finalization</h3>
            </div>

            <p style={{ fontSize: '0.875rem', color: '#374151', margin: '0.5rem 0' }}>
              Election: <strong>{currentElection?.title || selectedElectionId}</strong> (<code>{selectedElectionId}</code>)
            </p>

            {/* High-visibility Warning Notice */}
            <div
              style={{
                background: '#FEF2F2',
                borderLeft: '4px solid #DC2626',
                padding: '0.75rem',
                margin: '0.75rem 0',
                fontSize: '0.825rem',
                color: '#991B1B',
              }}
            >
              <strong>IRREVERSIBLE CRYPTOGRAPHIC SETTLEMENT:</strong>
              <ul style={{ margin: '0.4rem 0 0 1.2rem', padding: 0 }}>
                <li>Computes & seals authoritative <strong>RFC 6962 Merkle tree</strong> root over all confirmed ballots.</li>
                <li><strong>Permanently destroys election pseudonym key material</strong> to ensure perpetual voter anonymity.</li>
                <li>Election status transitions permanently to <code>FINALIZED</code>.</li>
                <li><strong>Four-Eyes Rule:</strong> Requires independent review and cryptographic approval from a distinct commissioning officer.</li>
              </ul>
            </div>

            {finalizeError && (
              <div className="alert-box alert-error" style={{ marginBottom: '1rem', fontSize: '0.85rem' }}>
                {finalizeError}
              </div>
            )}

            <form onSubmit={handleRequestFinalization}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Officer Justification / Settlement Notes <span style={{ color: '#DC2626' }}>*</span>
                </label>
                <textarea
                  className="form-input"
                  rows={3}
                  value={finalizeReason}
                  onChange={(e) => setFinalizeReason(e.target.value)}
                  placeholder="e.g. Cross-check against smart contract getTally() passed cleanly with zero disputes or pending ballots."
                  disabled={finalizeSubmitting}
                  style={{ width: '100%', boxSizing: 'border-box' }}
                />
                <div style={{ fontSize: '0.75rem', color: '#6B7280', marginTop: '0.25rem' }}>
                  Minimum 10 characters required. This note will be recorded permanently in the tamper-evident audit log.
                </div>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setShowFinalizeModal(false)
                    setFinalizeError('')
                  }}
                  disabled={finalizeSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={finalizeSubmitting || !finalizeReason || finalizeReason.trim().length < 10}
                  style={{ background: '#4F46E5', borderColor: '#4F46E5' }}
                >
                  {finalizeSubmitting ? 'Submitting Request...' : 'Submit Finalization Request'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
