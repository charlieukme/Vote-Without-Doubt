import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../../api/client.js'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export default function ResultsV2Page() {
  const { navigate } = useRouter()
  const [electionList, setElectionList] = useState([])
  const [electionId, setElectionId] = useState(() => {
    if (typeof window !== 'undefined' && window.location?.search) {
      const sp = new URLSearchParams(window.location.search)
      return sp.get('election_id') || sp.get('electionId') || ''
    }
    return ''
  })

  const [election, setElection] = useState(null)
  const [keyStatus, setKeyStatus] = useState(null)
  const [results, setResults] = useState(null)
  const [canonicalResults, setCanonicalResults] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSelectElection = (nextId) => {
    setElectionId(nextId)
    if (typeof window !== 'undefined' && nextId) {
      const currentUrl = new URL(window.location.href)
      currentUrl.searchParams.set('election_id', nextId)
      window.history.replaceState(null, '', currentUrl.toString())
    }
  }

  // 1. Load public elections catalog
  useEffect(() => {
    let mounted = true
    async function loadCatalog() {
      try {
        const res = await api.get('/public/elections').catch(() => null)
        const list = Array.isArray(res?.elections) ? res.elections : []
        if (!mounted) return
        setElectionList(list)
        if (!electionId && list.length > 0) {
          const preferred = list.find((el) => el.status === 'FINALIZED' || el.status === 'CLOSED') || list[0]
          handleSelectElection(String(preferred.election_id))
        }
      } catch {
        // silent
      }
    }
    loadCatalog()
    return () => { mounted = false }
  }, [electionId])

  // 2. Fetch Election Metadata, Candidates, Key Status, and Results
  const fetchResultsData = useCallback(async () => {
    if (!electionId) return
    setLoading(true)
    setError('')
    try {
      // 1. Fetch Election Metadata & Candidates
      let eData = null
      try {
        eData = await api.get(`/public/elections/${encodeURIComponent(electionId)}`)
        setElection(eData)
        if (eData.candidates && eData.candidates.length > 0) {
          setCandidates(eData.candidates)
        } else {
          setCandidates([])
        }
      } catch {
        setCandidates([])
      }

      // 2. Fetch V2 State (let backend resolve the election's contract address)
      const q = new URLSearchParams({ election_id: electionId })
      const kData = await api.get(`/v2/officer/key-status?${q.toString()}`).catch(() => null)
      setKeyStatus(kData)

      // 3. If State is 7 (TallyFinalized), fetch verified V2 results; also query canonical /results when closed/finalized
      let v2Res = null
      if (kData?.state === 7) {
        try {
          v2Res = await api.get(`/v2/voting/results?${q.toString()}`)
          setResults(v2Res)
        } catch (v2Err) {
          setResults(null)
          setError(v2Err?.payload?.message || v2Err?.message || 'Unable to retrieve V2 blockchain results.')
        }
      } else {
        setResults(null)
      }

      const effStat = String(eData?.status || '').toUpperCase()
      if (effStat === 'CLOSED' || effStat === 'FINALIZED') {
        try {
          const canon = await api.get(`/elections/${encodeURIComponent(electionId)}/results`)
          setCanonicalResults(canon)
        } catch (canonErr) {
          const payload = canonErr?.payload || null
          if (payload?.result_state) {
            setCanonicalResults(payload)
          } else {
            setCanonicalResults(null)
          }
        }
      } else {
        setCanonicalResults(null)
      }
    } catch (err) {
      setError(err?.payload?.message || err?.message || 'Unable to retrieve election results.')
    } finally {
      setLoading(false)
    }
  }, [electionId])

  useEffect(() => {
    fetchResultsData()
  }, [fetchResultsData])

  const canonFinalized = canonicalResults?.result_state === 'FINALIZED_RESULTS' && Array.isArray(canonicalResults?.candidates)
  const effectiveTallies = results?.tallies || (canonFinalized ? canonicalResults.candidates.map((c) => c.votes) : null)
  const totalVotes = effectiveTallies ? effectiveTallies.reduce((acc, v) => acc + Number(v), 0) : 0
  const isUnderReview = Boolean(
    canonicalResults?.result_state === 'RESULTS_UNDER_REVIEW' ||
    canonicalResults?.is_under_review === true ||
    results?.tally_matches_blockchain === false
  )
  const isPendingQueue = Boolean(canonicalResults?.result_state === 'PROCESSING_PENDING_BALLOTS')
  const isFinalized = Boolean(
    !isUnderReview &&
    !isPendingQueue &&
    ((keyStatus?.state === 7 && results?.tallies) || canonFinalized)
  )

  const resolveCandidateByIndex = (idx) => {
    const fromResults = Array.isArray(results?.candidates)
      ? results.candidates.find((c) => Number(c.candidate_index) === idx)
      : null
    if (fromResults) return fromResults
    const fromCatalog = candidates.find((c) => Number(c.candidate_index) === idx)
    if (fromCatalog) return fromCatalog
    const fromCanon = Array.isArray(canonicalResults?.candidates)
      ? canonicalResults.candidates.find((c) => Number(c.candidate_index) === idx)
      : null
    return fromCanon || { candidate_index: idx, name: `Candidate #${idx + 1}`, department: 'Nominee' }
  }

  // Compute winner if finalized cleanly
  let winner = null
  if (isFinalized && totalVotes > 0 && effectiveTallies && effectiveTallies.length > 0) {
    let maxIdx = 0
    let maxVotes = -1
    let isTie = false
    effectiveTallies.forEach((v, idx) => {
      const num = Number(v)
      if (num > maxVotes) {
        maxVotes = num
        maxIdx = idx
        isTie = false
      } else if (num === maxVotes && maxVotes > 0) {
        isTie = true
      }
    })
    if (!isTie && maxVotes > 0) {
      const cand = resolveCandidateByIndex(maxIdx)
      const pct = ((maxVotes / totalVotes) * 100).toFixed(1)
      winner = { ...cand, votes: maxVotes, pct }
    }
  }

  const effectiveStatus = (election?.status || '').toUpperCase()

  return (
    <div className="page-container results-v2-page" style={{ maxWidth: '960px', margin: '0 auto' }}>
      {/* Header Banner */}
      <div className="card" style={{ marginBottom: '1.5rem', background: '#FFFDF5' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <span className="badge badge-accent">ELECTION RESULTS</span>
            <h2 className="card-title" style={{ margin: '0.4rem 0 0.25rem 0' }}>
              {election?.title || 'Official Election Results'}
            </h2>
            <p style={{ margin: 0, color: '#4B5563', fontWeight: 600 }}>
              Official candidate tallies verified and recorded on the college blockchain ledger.
            </p>
          </div>
          <div>
            <span className={`badge ${isFinalized ? 'badge-verified' : 'badge-phase'}`}>
              {isFinalized
                ? 'Results Finalized & Certified'
                : effectiveStatus === 'OPEN' || effectiveStatus === 'ACTIVE'
                ? 'Voting in Progress'
                : 'Finalization Pending'}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="alert-box alert-warning" style={{ marginBottom: '1.5rem' }}>
          {error}
        </div>
      )}

      {/* Election Selector & Controls */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flex: 1, minWidth: '280px' }}>
            <label htmlFor="election-select" style={{ fontWeight: 800, fontSize: '0.9rem', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>
              Election:
            </label>
            <select
              id="election-select"
              className="input-field"
              value={electionId}
              onChange={(e) => handleSelectElection(e.target.value)}
              style={{ flex: 1 }}
            >
              {electionList.map((el) => (
                <option key={el.election_id} value={el.election_id}>
                  {el.title} [{el.status}]
                </option>
              ))}
            </select>
          </div>

          <button
            className="btn btn-secondary"
            onClick={fetchResultsData}
            disabled={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh Results'}
          </button>
        </div>
      </div>

      {isUnderReview && (
        <div className="alert-box alert-error" style={{ marginBottom: '1.5rem' }}>
          <strong>Results Under Review:</strong>{' '}
          {results?.discrepancy_warning || canonicalResults?.warning || 'Discrepancy detected between on-chain tallies and confirmed ballot records. Official results are withheld pending audit.'}
        </div>
      )}

      {isPendingQueue && (
        <div className="alert-box alert-warning" style={{ marginBottom: '1.5rem' }}>
          <strong>Ballot Settlement In Progress:</strong>{' '}
          {canonicalResults?.message || 'In-flight ballot transactions are settling on-chain. Results will appear automatically once all ballots confirm.'}
        </div>
      )}

      {/* Main Results View */}
      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ fontWeight: 700, color: '#4B5563' }}>Loading election results...</p>
        </div>
      ) : isUnderReview ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem 1.5rem', marginBottom: '1.5rem' }}>
          <span className="badge badge-danger">VERIFICATION MISMATCH</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>
            Tallies Held for Reconciliation Review
          </h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            {results?.discrepancy_warning || canonicalResults?.warning || 'An integrity discrepancy between smart-contract tallies and confirmed ballot records prevented automatic publication.'}
          </p>
          <button
            className="btn btn-primary"
            onClick={() => navigate(electionId ? `/verification?election_id=${encodeURIComponent(electionId)}` : '/verification')}
          >
            Inspect Public Audit Console &rarr;
          </button>
        </div>
      ) : isFinalized ? (
        <>
          {/* Winner Banner if distinct winner exists */}
          {winner && (
            <div className="card" style={{ background: 'var(--neo-yellow, #FFD93D)', border: '4px solid #000', marginBottom: '1.5rem', boxShadow: '6px 6px 0px #000' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                {winner.photo_url ? (
                  <img
                    src={winner.photo_url}
                    alt={winner.name}
                    style={{ width: '80px', height: '80px', borderRadius: '8px', border: '3px solid #000', objectFit: 'cover' }}
                  />
                ) : (
                  <div style={{ width: '80px', height: '80px', borderRadius: '8px', border: '3px solid #000', background: '#FFFFFF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '2rem' }}>
                    🏆
                  </div>
                )}
                <div style={{ flex: 1 }}>
                  <span className="badge" style={{ background: '#000000', color: '#FFFFFF', fontWeight: 900 }}>
                    OFFICIAL WINNER
                  </span>
                  <h3 style={{ margin: '0.4rem 0 0.2rem 0', fontSize: '1.6rem', fontWeight: 900 }}>
                    {winner.name}
                  </h3>
                  <div style={{ fontWeight: 700, color: '#1F2937' }}>
                    {winner.position || winner.department} &bull; {winner.votes} votes ({winner.pct}%)
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Candidate Tallies Card */}
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '3px solid #000', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
              <h3 style={{ textTransform: 'uppercase', margin: 0, fontWeight: 900 }}>
                Certified Candidate Tallies
              </h3>
              <span className="badge badge-accent">
                Total Valid Ballots: {totalVotes}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {(effectiveTallies || []).map((votes, idx) => {
                const cand = resolveCandidateByIndex(idx)
                const voteCount = Number(votes)
                const pct = totalVotes > 0 ? ((voteCount / totalVotes) * 100).toFixed(1) : '0.0'
                const isTop = winner && winner.name === cand.name

                return (
                  <div
                    key={idx}
                    style={{
                      padding: '1.25rem',
                      border: '3px solid #000000',
                      background: isTop ? '#FFFDF5' : '#FFFFFF',
                      boxShadow: '4px 4px 0px #000000',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        {cand.photo_url ? (
                          <img
                            src={cand.photo_url}
                            alt={cand.name}
                            style={{ width: '48px', height: '48px', borderRadius: '6px', border: '2px solid #000', objectFit: 'cover' }}
                          />
                        ) : (
                          <div style={{ width: '48px', height: '48px', borderRadius: '6px', border: '2px solid #000', background: '#E2E8F0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900 }}>
                            {cand.name ? cand.name.charAt(0) : '#'}
                          </div>
                        )}
                        <div>
                          <div style={{ fontSize: '1.15rem', fontWeight: 900 }}>
                            {cand.name} {isTop && '🏆'}
                          </div>
                          <div style={{ fontSize: '0.85rem', color: '#4B5563', fontWeight: 700 }}>
                            {cand.position || cand.department}
                          </div>
                        </div>
                      </div>

                      <div style={{ textAlign: 'right' }}>
                        <span style={{ fontSize: '1.35rem', fontWeight: 900 }}>
                          {voteCount} {voteCount === 1 ? 'vote' : 'votes'}
                        </span>
                        <span style={{ marginLeft: '0.5rem', fontWeight: 700, color: '#4B5563' }}>
                          ({pct}%)
                        </span>
                      </div>
                    </div>

                    {/* Simple Progress Bar */}
                    <div style={{ width: '100%', height: '14px', border: '2px solid #000', background: '#F3F4F6', overflow: 'hidden' }}>
                      <div
                        style={{
                          width: `${pct}%`,
                          height: '100%',
                          background: isTop ? 'var(--neo-yellow, #FFD93D)' : '#3B82F6',
                          transition: 'width 0.4s ease',
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      ) : (
        /* Results Not Yet Available Card */
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1.5rem', marginBottom: '1.5rem' }}>
          <span className="badge badge-phase">RESULTS PENDING</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>
            Final results are not available yet
          </h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            {keyStatus?.state && keyStatus.state < 5
              ? 'Voting is still open for this election. Official tallies will be computed and published here once voting officially closes.'
              : 'Voting has closed. The encrypted ballot box is being tallied and verified on the blockchain ledger.'}
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              &larr; Back to Dashboard
            </button>
            <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/verification?election_id=${encodeURIComponent(electionId)}` : '/verification')}>
              Public Audit Console
            </button>
            <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/receipt-verification?election_id=${encodeURIComponent(electionId)}` : '/receipt-verification')}>
              Verify Vote Receipt
            </button>
          </div>
        </div>
      )}

      {/* Optional Collapsed Section for Technical & Blockchain Auditors */}
      <details className="card" style={{ marginTop: '1.5rem', background: '#F8FAFC' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 900, fontSize: '0.95rem', textTransform: 'uppercase' }}>
          Technical & Blockchain Verification Details
        </summary>
        <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '2px solid #E2E8F0', fontSize: '0.9rem' }}>
          <div className="election-meta-grid" style={{ marginBottom: '1rem' }}>
            <div className="meta-item">
              <span className="meta-label">Smart Contract Address</span>
              <span className="meta-value font-mono" style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>
                {keyStatus?.contract_address || election?.contract_address || 'Not available'}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">On-Chain State</span>
              <span className="meta-value">
                {keyStatus ? `State ${keyStatus.state} (${isFinalized ? 'Tally Finalized' : 'In Progress'})` : 'N/A'}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Cryptographic Protocol</span>
              <span className="meta-value">BN254 Threshold ElGamal & Chaum-Pedersen DLEQ</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Joint Public Key (Affinity X)</span>
              <span className="meta-value font-mono" style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>
                {keyStatus?.joint_public_key?.x ? `${keyStatus.joint_public_key.x.slice(0, 18)}...` : 'N/A'}
              </span>
            </div>
          </div>
          <p style={{ color: '#6B7280', fontSize: '0.8rem', margin: 0 }}>
            Ballots are homomorphically aggregated directly on the Ethereum virtual machine. Decryption shares are proven via zero-knowledge proofs and verified on-chain.
          </p>
        </div>
      </details>
    </div>
  )
}
