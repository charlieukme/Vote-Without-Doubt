import React, { useState, useEffect, useCallback } from 'react'
import '../Voting.css'
import { api } from '../api/client.js'
import { useRouter } from '../router/RouterContext'
import Wallet from '../Wallet'
import Face from '../Face'
import {
  generateClientBallotProof,
} from '../utils/bn254_client.js'

function resolveCandidatePhoto(url) {
  if (!url) return null
  let cleaned = String(url).trim().replace(/^["']|["']$/g, '').replace(/\\/g, '/')
  if (cleaned.startsWith('http://') || cleaned.startsWith('https://')) return cleaned
  if (cleaned.includes('/api/public/candidate-photo/')) {
    return '/api/public/candidate-photo/' + cleaned.split('/api/public/candidate-photo/').pop()
  }
  if (cleaned.startsWith('/')) return cleaned
  return `/api/public/candidate-photo/${cleaned}`
}

export default function VotingV2({ electionId: propElectionId, initialElection = null, initialCandidates = [] }) {
  const router = useRouter?.() || {}
  const params = router.params || {}
  const navigate = router.navigate || (() => { })

  const [electionId, setElectionId] = useState(() => {
    if (propElectionId) return String(propElectionId)
    if (params.election_id) return String(params.election_id)
    if (typeof window !== 'undefined' && window.location?.search) {
      const q = new URLSearchParams(window.location.search).get('election_id')
      if (q) return q
    }
    return ''
  })

  // Synchronize when propElectionId changes and clear stale verification state
  useEffect(() => {
    if (propElectionId && String(propElectionId) !== electionId) {
      setElectionId(String(propElectionId))
      setFactorStatus({ wallet_ok: false, face_ok: false })
      setAuthorizationId(null)
      setError('')
      setReceipt(null)
      setStep('factors')
    }
  }, [propElectionId])

  // Election and Status state
  const [election, setElection] = useState(() => initialElection || null)
  const [keyStatus, setKeyStatus] = useState(null)
  const [voterStatus, setVoterStatus] = useState(null)
  const [candidates, setCandidates] = useState(() => (Array.isArray(initialCandidates) && initialCandidates.length > 0) ? initialCandidates : [])
  const [selectedCandidateIndex, setSelectedCandidateIndex] = useState(null)
  const [expandedManifestoIdx, setExpandedManifestoIdx] = useState(null)

  // Sync initial props if updated by parent
  useEffect(() => {
    if (initialElection && !election) setElection(initialElection)
    if (Array.isArray(initialCandidates) && initialCandidates.length > 0 && candidates.length === 0) {
      setCandidates(initialCandidates)
    }
  }, [initialElection, initialCandidates])

  // Multi-factor state
  const [factorStatus, setFactorStatus] = useState({ wallet_ok: false, face_ok: false })
  const [walletAccount, setWalletAccount] = useState('')
  const [authorizationId, setAuthorizationId] = useState(null)

  // Memoized wallet callbacks to prevent re-render cascades
  const handleWalletStatusChange = useCallback((ok, addr) => {
    setFactorStatus((prev) => ({ ...prev, wallet_ok: Boolean(ok) }))
    if (addr) setWalletAccount(addr)
  }, [])

  const handleWalletBound = useCallback((addr) => {
    setFactorStatus((prev) => ({ ...prev, wallet_ok: true }))
    if (addr) setWalletAccount(addr)
  }, [])

  // Workflow steps: 'factors' -> 'select' -> 'review' -> 'submitting' -> 'confirmed' | 'exhausted' | 'pending_settlement' | 'failed'
  const [step, setStep] = useState('factors')
  const [loading, setLoading] = useState(false)
  const [candidatesLoaded, setCandidatesLoaded] = useState(() => Array.isArray(initialCandidates) && initialCandidates.length > 0)
  const [submittingMessage, setSubmittingMessage] = useState('Securing your vote...')
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState(null)

  // Fetch Election, Candidates, Key Status, and Voter Status
  const loadElectionData = useCallback(async () => {
    if (!electionId) return
    setError('')
    try {
      let candList = []
      let electionMeta = null

      try {
        const eData = await api.get(`/public/elections/${electionId}`)
        if (eData) {
          electionMeta = eData
          if (Array.isArray(eData.candidates) && eData.candidates.length > 0) {
            candList = eData.candidates
          }
        }
      } catch (err) {
        console.warn('Failed to load from /public/elections, trying fallback:', err)
      }

      // Fallback to /voting/election if needed
      if (candList.length === 0) {
        try {
          const vData = await api.get(`/voting/election/${electionId}`)
          if (vData) {
            if (!electionMeta) electionMeta = vData
            if (Array.isArray(vData.candidates) && vData.candidates.length > 0) {
              candList = vData.candidates
            }
          }
        } catch (err) {
          console.warn('Fallback /voting/election also failed:', err)
        }
      }

      if (candList.length === 0 && Array.isArray(initialCandidates) && initialCandidates.length > 0) {
        candList = initialCandidates
      }

      if (electionMeta) {
        setElection(electionMeta)
      }
      if (candList.length > 0) {
        setCandidates(candList)
      } else {
        setCandidates([])
      }
      setCandidatesLoaded(true)

      // Initialize authoritative VotingAuthorization for this election & session
      try {
        const authData = await api.post('/voting/authorize', { election_id: electionId })
        if (authData?.authorization_id) {
          setAuthorizationId(authData.authorization_id)
        }
        if (authData) {
          setFactorStatus((prev) => ({
            wallet_ok: Boolean(authData.wallet_verified ?? authData.wallet_ok ?? prev.wallet_ok),
            face_ok: Boolean(authData.face_verified ?? authData.face_ok ?? prev.face_ok),
          }))
          if (authData.authorized) {
            setFactorStatus({ wallet_ok: true, face_ok: true })
            setError('')
          }
        }
      } catch {
        // Non-fatal if unauthenticated or election not active yet
      }

      // Check authoritative wallet status directly on mount
      try {
        const wData = await api.get('/wallet/status')
        if (wData && wData.bound) {
          setFactorStatus((prev) => ({ ...prev, wallet_ok: true }))
          if (wData.wallet_address) setWalletAccount(wData.wallet_address)
        }
      } catch {
        // Non-fatal
      }

      // Check authoritative factor status
      try {
        const fData = await api.get(`/voting/factors-status?election_id=${electionId}`)
        if (fData) {
          setFactorStatus((prev) => ({
            wallet_ok: Boolean(fData.wallet_verified ?? fData.wallet_ok ?? prev.wallet_ok),
            face_ok: Boolean(fData.face_verified ?? fData.face_ok ?? prev.face_ok),
          }))
          if (fData.authorized) {
            setFactorStatus({ wallet_ok: true, face_ok: true })
            setError('')
          }
        }
      } catch {
        // Non-fatal
      }

      const kData = await api.get(`/v2/officer/key-status?election_id=${electionId}`).catch(() => null)
      if (kData) setKeyStatus(kData)

      try {
        const vData = await api.get(`/v2/voting/status?election_id=${electionId}`)
        setVoterStatus(vData)
        if (vData?.has_voted) {
          const maxAllowed = Number(vData.max_ballots || 3)
          const usedSeq = Number(vData.active_sequence ?? vData.submissions_used ?? vData.sequence ?? 0)
          const isMax = Boolean(usedSeq >= maxAllowed || vData.retry_blocked_reason === 'MAX_BALLOTS_REACHED')
          setReceipt({
            sequence: usedSeq || vData.sequence,
            block_number: vData.block_number,
            receipt_code: vData.receipt?.receipt_code,
            timestamp: vData.receipt?.timestamp || new Date().toISOString(),
          })
          if (isMax) {
            setStep('exhausted')
          } else {
            setStep((curr) => (curr === 'factors' ? 'confirmed' : curr))
          }
        } else if (vData?.status === 'QUEUED' || vData?.status === 'SUBMITTED' || vData?.state === 'QUEUED' || vData?.state === 'SUBMITTED') {
          setStep('pending_settlement')
        }
      } catch {
        // If unauthenticated or no session
      }
    } catch (err) {
      setError('Failed to load election data: ' + (err.message || String(err)))
    } finally {
      setCandidatesLoaded(true)
    }
  }, [electionId])

  useEffect(() => {
    loadElectionData()
  }, [loadElectionData])

  // Poll key status only while encryption parameters are still initializing
  useEffect(() => {
    if (!electionId || keyStatus?.joint_public_key) return
    const timer = setInterval(() => {
      api.get(`/v2/officer/key-status?election_id=${electionId}`)
        .then((kData) => {
          if (kData && kData.joint_public_key) {
            setKeyStatus(kData)
          }
        })
        .catch(() => {})
    }, 4000)
    return () => clearInterval(timer)
  }, [electionId, keyStatus?.joint_public_key])

  // Multi-factor validation handler
  const handleFactorsVerified = async () => {
    if (!factorStatus.wallet_ok || !factorStatus.face_ok) {
      const missing = []
      if (!factorStatus.wallet_ok) missing.push('wallet connection')
      if (!factorStatus.face_ok) missing.push('face verification')
      setError(`Please complete required identity verification step(s): ${missing.join(' and ')}.`)
      return
    }
    setLoading(true)
    setError('')
    setSubmittingMessage('Verifying your identity...')
    try {
      if (!authorizationId) {
        const authRes = await api.post('/voting/authorize', { election_id: electionId })
        if (authRes?.authorization_id) {
          setAuthorizationId(authRes.authorization_id)
        }
      }
      let res
      try {
        res = await api.post('/voting/mark-factors', { election_id: electionId })
      } catch (markErr) {
        if (markErr?.status === 400 && markErr?.payload?.error === 'INVALID_OR_EXPIRED_AUTH') {
          const authRes = await api.post('/voting/authorize', { election_id: electionId })
          if (authRes?.authorization_id) {
            setAuthorizationId(authRes.authorization_id)
          }
          res = await api.post('/voting/mark-factors', { election_id: electionId })
        } else {
          throw markErr
        }
      }
      if (res && res.authorized === true) {
        setError('')
        setFactorStatus({ wallet_ok: true, face_ok: true })
        if (candidates.length === 0) {
          await loadElectionData()
        }
        setStep('select')
      } else {
        const missing = res?.missing_factors || []
        if (missing.includes('wallet') && missing.includes('face')) {
          setError('Identity verification incomplete: Both wallet connection and face verification are required.')
        } else if (missing.includes('wallet')) {
          setError('Identity verification incomplete: Wallet connection and ownership proof are required.')
        } else if (missing.includes('face')) {
          setError('Identity verification incomplete: Face verification is required.')
        } else {
          setError('Verification pending. Please ensure your wallet is connected and face check succeeded.')
        }
      }
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setError('Too many verification requests. Please wait a few seconds and try again.')
      } else {
        if (err?.status === 401) {
          setFactorStatus({ wallet_ok: false, face_ok: false })
        }
        setError('Verification failed: ' + (err?.payload?.message || err?.payload?.error || err.message || String(err)))
      }
    } finally {
      setLoading(false)
    }
  }

  // Handle Candidate Selection
  const handleSelectCandidate = (index) => {
    setSelectedCandidateIndex(index)
  }

  // Perform Client-Side Encryption & Cast Ballot
  const handleGenerateProofAndCast = async () => {
    if (selectedCandidateIndex === null) {
      setError('Please select a candidate before proceeding.')
      return
    }
    if (!keyStatus?.joint_public_key) {
      setError('Election setup is in progress. Encryption parameters are initializing automatically. Please wait a moment...')
      return
    }
    if (!voterStatus?.pseudonym) {
      setError('Voter session not initialized. Please refresh and log in.')
      return
    }

    setStep('submitting')
    setSubmittingMessage('Securing your vote...')
    setLoading(true)
    setError('')

    try {
      const candidateCount = candidates.length || 2
      const chosenIndex = selectedCandidateIndex
      const sequence = voterStatus.next_sequence || 1

      // Resolve authoritative numeric election ID, verifier contract, and chain ID (never hardcode election fallbacks)
      const rawNumericId = (election && election.id) ?? (keyStatus && keyStatus.election_id)
      const numericElectionId = Number(rawNumericId)
      if (!Number.isInteger(numericElectionId) || numericElectionId <= 0) {
        setError('Election numeric metadata is unavailable. Please reload before casting your ballot.')
        setStep('review')
        setLoading(false)
        return
      }
      const verifierAddr = keyStatus?.verifier_address
      if (!verifierAddr) {
        setError('Cryptographic verifier contract metadata is unavailable for this election. Please wait for setup or reload.')
        setStep('review')
        setLoading(false)
        return
      }
      const chainId = Number(keyStatus?.chain_id)
      if (!Number.isInteger(chainId) || chainId <= 0) {
        setError('Blockchain network chain ID is unavailable for this election. Please reload and try again.')
        setStep('review')
        setLoading(false)
        return
      }

      // Generate client-side zero-knowledge proof & encrypted ballot vector
      setSubmittingMessage('Securing your vote...')
      const ballotData = generateClientBallotProof({
        selectedCandidate: chosenIndex,
        candidateCount,
        context: {
          electionId: numericElectionId,
          numericElectionId: numericElectionId,
          pseudonym: voterStatus.pseudonym,
          sequence: sequence,
          jointPubKey: { x: keyStatus.joint_public_key.x, y: keyStatus.joint_public_key.y },
        },
        verifierAddress: verifierAddr,
        chainId: chainId,
      })

      const payload = {
        election_id: electionId,
        numeric_election_id: numericElectionId,
        sequence: sequence,
        ciphertexts: ballotData.ciphertexts,
        proof: ballotData.proof,
      }

      setSubmittingMessage('Submitting your ballot...')
      const res = await api.post('/v2/voting/cast-ballot', payload)

      setReceipt({
        tx_hash: res.tx_hash,
        block_number: res.block_number,
        sequence: sequence,
        candidate_name: candidates[chosenIndex]?.name || `Candidate #${chosenIndex + 1}`,
        timestamp: new Date().toISOString(),
      })

      setStep('confirmed')
      loadElectionData()
    } catch (err) {
      setError('Submission error: ' + (err?.payload?.message || err?.payload?.error || err.message || String(err)))
      setStep('failed')
    } finally {
      setLoading(false)
    }
  }

  // Handle Revoting
  const handleInitiateRevote = async () => {
    setSelectedCandidateIndex(null)
    setReceipt(null)
    setFactorStatus({ wallet_ok: false, face_ok: false })
    setStep('factors')
    try {
      const authRes = await api.post('/voting/authorize', { election_id: electionId })
      if (authRes?.authorization_id) {
        setAuthorizationId(authRes.authorization_id)
      }
      const wData = await api.get('/wallet/status')
      if (wData && wData.bound) {
        setFactorStatus((prev) => ({ ...prev, wallet_ok: true }))
      }
    } catch {
      // Non-fatal
    }
  }

  const sequence = Number(voterStatus?.active_sequence ?? voterStatus?.submissions_used ?? voterStatus?.sequence ?? 0)
  const maxBallots = Number(voterStatus?.max_ballots || 3)
  const hasVoted = Boolean(voterStatus?.has_voted)
  const cooldownActive = Boolean(voterStatus?.cooldown_active)
  const cooldownRemaining = Number(voterStatus?.cooldown_remaining_sec || 0)
  const canRevote = Boolean(hasVoted && sequence < maxBallots && voterStatus?.can_revote !== false && !cooldownActive)

  return (
    <div className="voting-container v2-voting-container">
      {/* Informative Header */}
      <div className="card voting-header-card" style={{ marginBottom: '1.5rem', background: '#FFFDF5' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <span className="badge badge-accent">OFFICIAL BALLOT</span>
            <h2 style={{ margin: '0.4rem 0 0.25rem 0', fontSize: '1.5rem', fontWeight: 900 }}>
              {election?.title || 'Cast Your Vote'}
            </h2>
            <p style={{ margin: 0, color: '#4B5563', fontSize: '0.95rem', fontWeight: 600 }}>
              Your vote is private and securely encrypted. No administrator or officer can see your selection.
            </p>
          </div>
          {hasVoted && (
            <div>
              <span className="badge badge-verified">
                ✓ Submissions used: {sequence} of {maxBallots}
              </span>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="alert-box alert-warning" style={{ marginBottom: '1.5rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* STEP 1: Verify your identity */}
      {step === 'factors' && (
        <div className="card">
          <div style={{ borderBottom: '3px solid #000000', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
            <span className="badge badge-phase">STEP 1 OF 4</span>
            <h3 style={{ textTransform: 'uppercase', margin: '0.4rem 0 0.2rem 0', fontWeight: 900 }}>
              Verify your identity
            </h3>
            <p style={{ color: '#4B5563', margin: 0, fontWeight: 600, fontSize: '0.925rem' }}>
              To ensure election integrity, please complete the identity verification checks below.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem', marginBottom: '1.75rem' }}>
            <div>
              <Wallet
                onStatusChange={handleWalletStatusChange}
                onBound={handleWalletBound}
              />
            </div>
            <div>
              <Face
                onVerified={() => {
                  setFactorStatus((prev) => ({ ...prev, face_ok: true }))
                }}
                authorizationId={authorizationId}
                electionId={electionId}
              />
            </div>
          </div>

          <div style={{ textAlign: 'right', borderTop: '2px solid #E5E7EB', paddingTop: '1.25rem' }}>
            <button
              className="btn btn-primary"
              onClick={handleFactorsVerified}
              disabled={loading || !factorStatus.wallet_ok || !factorStatus.face_ok}
              style={{ minWidth: '220px' }}
            >
              {loading ? 'Verifying your identity...' : 'Continue to Select Candidate →'}
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: Select your candidate */}
      {step === 'select' && (
        <div className="card">
          <div style={{ borderBottom: '3px solid #000000', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div>
                <span className="badge badge-phase">STEP 2 OF 4</span>
                <h3 style={{ textTransform: 'uppercase', margin: '0.4rem 0 0.2rem 0', fontWeight: 900 }}>
                  Select your candidate
                </h3>
              </div>
              {hasVoted && (
                <span className="badge badge-accent">
                  Updating vote (Submission #{voterStatus?.next_sequence || sequence + 1})
                </span>
              )}
            </div>
            <p style={{ color: '#4B5563', margin: '0.5rem 0 0 0', fontWeight: 600, fontSize: '0.925rem' }}>
              Choose one candidate from the nominees below. Click on a candidate card to select them.
            </p>
            {hasVoted && (
              <p style={{ color: '#2563EB', margin: '0.35rem 0 0 0', fontWeight: 700, fontSize: '0.85rem' }}>
                You can change your vote up to the permitted limit before voting closes. Only your valid final submission will count.
              </p>
            )}
          </div>

          {/* Candidate Cards Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1.25rem', marginBottom: '1.75rem' }}>
            {candidates.length === 0 ? (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '2.5rem', background: '#F9FAFB', border: '2px dashed #9CA3AF', borderRadius: '8px' }}>
                <p style={{ fontWeight: 700, color: '#374151', marginBottom: '1rem', fontSize: '1rem' }}>
                  {candidatesLoaded
                    ? 'No certified candidates are registered for this election yet.'
                    : 'Loading certified candidate profiles...'}
                </p>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={loadElectionData}
                  style={{ minWidth: '180px' }}
                >
                  Reload Nominees
                </button>
              </div>
            ) : (
              candidates.map((cand, idx) => {
              const isSelected = selectedCandidateIndex === idx
              const isExpanded = expandedManifestoIdx === idx
              const candIndex = cand.index !== undefined ? cand.index : (cand.candidate_index ?? idx)
              const photo = resolveCandidatePhoto(cand.photo_url)
              const position = cand.position || cand.department || 'Candidate'
              const affiliation = cand.affiliation || cand.party || cand.department || ''

              return (
                <div
                  key={cand.id ?? candIndex}
                  onClick={() => handleSelectCandidate(idx)}
                  className="card"
                  style={{
                    margin: 0,
                    cursor: 'pointer',
                    background: isSelected ? 'var(--neo-yellow, #FFD93D)' : '#FFFFFF',
                    border: isSelected ? '4px solid #000000' : '3px solid #000000',
                    boxShadow: isSelected ? '6px 6px 0px #000000' : '3px 3px 0px #000000',
                    transition: 'transform 0.15s, box-shadow 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '0.75rem' }}>
                    {photo ? (
                      <img
                        src={photo}
                        alt={cand.name}
                        style={{
                          width: '64px',
                          height: '64px',
                          borderRadius: '8px',
                          border: '2px solid #000000',
                          objectFit: 'cover',
                        }}
                        onError={(e) => {
                          e.target.style.display = 'none'
                          if (e.target.nextSibling) e.target.nextSibling.style.display = 'flex'
                        }}
                      />
                    ) : null}
                    <div
                      style={{
                        width: '64px',
                        height: '64px',
                        borderRadius: '8px',
                        border: '2px solid #000000',
                        background: '#E2E8F0',
                        display: photo ? 'none' : 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '1.5rem',
                        fontWeight: 900,
                      }}
                    >
                      {cand.name ? cand.name.charAt(0).toUpperCase() : 'C'}
                    </div>

                    <div style={{ flex: 1 }}>
                      <h4 style={{ margin: '0 0 0.2rem 0', fontSize: '1.15rem', fontWeight: 900 }}>
                        {cand.name}
                      </h4>
                      <div style={{ fontSize: '0.85rem', color: '#4B5563', fontWeight: 700 }}>
                        {position}
                      </div>
                      {affiliation && affiliation !== position && (
                        <div style={{ fontSize: '0.78rem', color: '#6B7280', fontWeight: 600 }}>
                          Affiliation: {affiliation}
                        </div>
                      )}
                    </div>

                    <div style={{ textAlign: 'right' }}>
                      <input
                        type="radio"
                        name="candidateSelection"
                        checked={isSelected}
                        onChange={() => handleSelectCandidate(idx)}
                        style={{ width: '22px', height: '22px', cursor: 'pointer' }}
                      />
                    </div>
                  </div>

                  {cand.slogan && (
                    <p style={{ fontSize: '0.875rem', fontStyle: 'italic', margin: '0.25rem 0 0.5rem 0', color: '#1F2937' }}>
                      &ldquo;{cand.slogan}&rdquo;
                    </p>
                  )}

                  {cand.manifesto && (
                    <div style={{ borderTop: '1px solid #D1D5DB', paddingTop: '0.5rem', marginTop: '0.5rem' }}>
                      <button
                        type="button"
                        className="link-button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setExpandedManifestoIdx(isExpanded ? null : idx)
                        }}
                        style={{ fontSize: '0.8rem', fontWeight: 800 }}
                      >
                        {isExpanded ? 'Hide Manifesto ▲' : 'Read Manifesto ▼'}
                      </button>
                      {isExpanded && (
                        <p style={{ fontSize: '0.85rem', color: '#374151', marginTop: '0.35rem', lineHeight: 1.5 }}>
                          {cand.manifesto}
                        </p>
                      )}
                    </div>
                  )}

                  {isSelected && (
                    <div style={{ marginTop: '0.75rem', fontWeight: 900, fontSize: '0.85rem', color: '#000000' }}>
                      ✓ SELECTED
                    </div>
                  )}
                </div>
              )
            }))}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '2px solid #E5E7EB', paddingTop: '1.25rem' }}>
            <button className="btn btn-secondary" onClick={() => setStep('factors')}>
              &larr; Back
            </button>
            <button
              className="btn btn-primary"
              onClick={() => setStep('review')}
              disabled={selectedCandidateIndex === null}
              style={{ minWidth: '200px' }}
            >
              Review Your Choice &rarr;
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: Review your choice */}
      {step === 'review' && (
        <div className="card">
          <div style={{ borderBottom: '3px solid #000000', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
            <span className="badge badge-phase">STEP 3 OF 4</span>
            <h3 style={{ textTransform: 'uppercase', margin: '0.4rem 0 0.2rem 0', fontWeight: 900 }}>
              Review your choice
            </h3>
            <p style={{ color: '#4B5563', margin: 0, fontWeight: 600, fontSize: '0.925rem' }}>
              Please review your selected candidate before confirming your vote.
            </p>
          </div>

          <div className="card" style={{ background: 'var(--neo-cream, #FFFDF5)', marginBottom: '1.5rem', padding: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                {resolveCandidatePhoto(candidates[selectedCandidateIndex]?.photo_url) ? (
                  <img
                    src={resolveCandidatePhoto(candidates[selectedCandidateIndex]?.photo_url)}
                    alt={candidates[selectedCandidateIndex]?.name || 'Candidate'}
                    style={{
                      width: '64px',
                      height: '64px',
                      borderRadius: '8px',
                      border: '2px solid #000000',
                      objectFit: 'cover',
                    }}
                    onError={(e) => {
                      e.target.style.display = 'none'
                      if (e.target.nextSibling) e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                ) : null}
                <div
                  style={{
                    width: '64px',
                    height: '64px',
                    borderRadius: '8px',
                    border: '2px solid #000000',
                    background: '#E2E8F0',
                    display: resolveCandidatePhoto(candidates[selectedCandidateIndex]?.photo_url) ? 'none' : 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '1.5rem',
                    fontWeight: 900,
                  }}
                >
                  {candidates[selectedCandidateIndex]?.name ? candidates[selectedCandidateIndex].name.charAt(0).toUpperCase() : 'C'}
                </div>

                <div>
                  <span className="meta-label">Selected Candidate</span>
                  <div style={{ fontSize: '1.5rem', fontWeight: 900, marginTop: '0.25rem' }}>
                    {candidates[selectedCandidateIndex]?.name}
                  </div>
                  <div style={{ color: '#4B5563', fontWeight: 700 }}>
                    {candidates[selectedCandidateIndex]?.position || 'Candidate'}
                    {(candidates[selectedCandidateIndex]?.department || candidates[selectedCandidateIndex]?.party || candidates[selectedCandidateIndex]?.affiliation) ? ` • ${candidates[selectedCandidateIndex]?.affiliation || candidates[selectedCandidateIndex]?.party || candidates[selectedCandidateIndex]?.department}` : ''}
                  </div>
                </div>
              </div>
              <div>
                <span className="badge badge-accent">
                  Ballot #{voterStatus?.next_sequence || sequence + 1}
                </span>
              </div>
            </div>

            {!keyStatus?.joint_public_key ? (
              <div className="alert-box alert-warning" style={{ margin: 0 }}>
                <strong>Election Setup in Progress:</strong> Cryptographic parameters are being initialized. Please wait a few moments; the confirm button will activate automatically.
              </div>
            ) : (
              <div className="alert-box alert-info" style={{ margin: 0 }}>
                <strong>Notice:</strong> Your vote will be encrypted on your device. If you cast a previous vote in this election, this submission will safely replace it.
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '2px solid #E5E7EB', paddingTop: '1.25rem' }}>
            <button className="btn btn-secondary" onClick={() => setStep('select')}>
              &larr; Change Selection
            </button>
            <button
              className="btn btn-primary"
              onClick={handleGenerateProofAndCast}
              disabled={loading || !keyStatus?.joint_public_key}
              style={{ minWidth: '220px' }}
            >
              {loading ? 'Securing your vote...' : (!keyStatus?.joint_public_key ? 'Waiting for Election Setup...' : 'Confirm and Cast Your Vote')}
            </button>
          </div>
        </div>
      )}

      {/* STEP 4: Submitting */}
      {step === 'submitting' && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
          <div className="spinner" style={{ margin: '0 auto 1.5rem auto' }} />
          <h3 style={{ textTransform: 'uppercase', marginBottom: '0.5rem', fontWeight: 900 }}>
            {submittingMessage}
          </h3>
          <p style={{ color: '#4B5563', fontWeight: 600 }}>
            Please wait while your ballot is encrypted and recorded on the election ledger...
          </p>
        </div>
      )}

      {/* STEP 5: Confirmed Receipt */}
      {step === 'confirmed' && receipt && (
        <div className="card" style={{ background: '#FFFDF5' }}>
          <div style={{ textAlign: 'center', borderBottom: '3px solid #000000', paddingBottom: '1.25rem', marginBottom: '1.5rem' }}>
            <span style={{ fontSize: '2.5rem' }}>🎉</span>
            <h3 style={{ textTransform: 'uppercase', color: '#047857', margin: '0.5rem 0', fontWeight: 900 }}>
              Your vote has been recorded successfully
            </h3>
            <p style={{ color: '#4B5563', fontWeight: 600, margin: 0 }}>
              Your encrypted ballot has been safely received and registered in the digital ballot box.
            </p>
          </div>

          <div className="election-meta-grid" style={{ marginBottom: '1.5rem' }}>
            <div className="meta-item">
              <span className="meta-label">Submission</span>
              <span className="meta-value">Ballot #{receipt.sequence}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Time Recorded</span>
              <span className="meta-value">{new Date(receipt.timestamp).toLocaleTimeString()}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Ledger Block</span>
              <span className="meta-value">Block #{receipt.block_number}</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap', borderTop: '2px solid #E5E7EB', paddingTop: '1.25rem' }}>
            <button className="btn btn-primary" onClick={() => navigate(electionId ? `/receipt?election_id=${electionId}` : '/receipt')}>
              View Full Official Receipt &rarr;
            </button>
            {canRevote ? (
              <button className="btn btn-secondary" onClick={handleInitiateRevote}>
                Change Vote (Revote #{(receipt.sequence || sequence) + 1})
              </button>
            ) : (hasVoted && sequence < maxBallots && cooldownActive) ? (
              <button className="btn btn-secondary" disabled title="Revote cooldown active">
                Revote Cooldown ({cooldownRemaining}s)
              </button>
            ) : null}
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              Back to Dashboard
            </button>
          </div>

          {/* Candidate Nominees View-Only Cards */}
          {candidates.length > 0 && (
            <div style={{ borderTop: '3px solid #000', paddingTop: '1.5rem', marginTop: '2rem', textAlign: 'left' }}>
              <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.5rem' }}>
                Certified Candidate Nominees
              </h4>
              <p style={{ color: '#4B5563', fontSize: '0.9rem', marginBottom: '1rem', fontWeight: 600 }}>
                Candidate profiles configured for this election:
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                {candidates.map((c, idx) => (
                  <div key={c.id || idx} className="candidate-card" style={{ cursor: 'default', background: '#FFFFFF' }}>
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                      {resolveCandidatePhoto(c.photo_url) ? (
                        <img
                          src={resolveCandidatePhoto(c.photo_url)}
                          alt={c.name}
                          style={{ width: '56px', height: '56px', borderRadius: '8px', objectFit: 'cover', border: '2px solid #000' }}
                          onError={(e) => { e.target.style.display = 'none'; if (e.target.nextSibling) e.target.nextSibling.style.display = 'flex' }}
                        />
                      ) : null}
                      <div style={{ width: '56px', height: '56px', borderRadius: '8px', border: '2px solid #000', background: '#E2E8F0', display: resolveCandidatePhoto(c.photo_url) ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: '1.3rem' }}>
                        {c.name ? c.name.charAt(0).toUpperCase() : 'C'}
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontWeight: 900 }}>{c.name}</h4>
                        <div style={{ fontSize: '0.85rem', color: '#4B5563', fontWeight: 700 }}>
                          {c.position || 'Candidate'} {c.affiliation ? `• ${c.affiliation}` : ''}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* EXHAUSTED / MAX SUBMISSIONS STATE */}
      {step === 'exhausted' && (
        <div className="card" style={{ background: '#FFFDF5' }}>
          <div style={{ textAlign: 'center', borderBottom: '3px solid #000000', paddingBottom: '1.25rem', marginBottom: '1.5rem' }}>
            <span className="badge badge-verified" style={{ fontSize: '0.85rem' }}>
              ✓ ALL {maxBallots} OF {maxBallots} SUBMISSIONS USED
            </span>
            <h3 style={{ textTransform: 'uppercase', color: '#047857', margin: '0.6rem 0 0.3rem 0', fontWeight: 900, fontSize: '1.45rem' }}>
              Official Ballot Confirmed On-Chain
            </h3>
            <p style={{ color: '#4B5563', fontWeight: 600, margin: 0, fontSize: '0.95rem' }}>
              Your final ballot (Submission #{receipt?.sequence || sequence || maxBallots}) has been successfully encrypted, broadcast, and permanently mined into the blockchain ledger.
            </p>
          </div>

          <div className="election-meta-grid" style={{ marginBottom: '1.25rem' }}>
            <div className="meta-item">
              <span className="meta-label">Active Ballot</span>
              <span className="meta-value">Submission #{receipt?.sequence || sequence || maxBallots} of {maxBallots} (Active)</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Ledger Block</span>
              <span className="meta-value">
                {(receipt?.block_number ?? voterStatus?.block_number) != null
                  ? `Block #${receipt?.block_number ?? voterStatus?.block_number}`
                  : 'Confirmed'}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Settlement Status</span>
              <span className="meta-value" style={{ color: '#047857', fontWeight: 800 }}>MINED & CONFIRMED</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Time Recorded</span>
              <span className="meta-value">
                {receipt?.timestamp ? new Date(receipt.timestamp).toLocaleString() : 'Confirmed'}
              </span>
            </div>
          </div>

          <div className="alert-box alert-info" style={{ fontSize: '0.9rem', marginBottom: '1.5rem', textAlign: 'left' }}>
            <strong>Maximum Submissions Policy:</strong> Under the Four-Eyes election protocol, students are permitted up to {maxBallots} encrypted submissions per election. Your final submission is the only vote that decrypts during officer tallying.
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap', borderTop: '2px solid #E5E7EB', paddingTop: '1.25rem', marginBottom: '2rem' }}>
            <button className="btn btn-primary" onClick={() => navigate(electionId ? `/receipt?election_id=${electionId}` : '/receipt')}>
              View Official Receipt &rarr;
            </button>
            <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/my-vote?election_id=${electionId}` : '/my-vote')}>
              My Vote Status
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              Return to Dashboard
            </button>
          </div>

          {/* Certified Nominees View-Only Cards */}
          {candidates.length > 0 && (
            <div style={{ borderTop: '3px solid #000', paddingTop: '1.5rem', textAlign: 'left' }}>
              <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.5rem' }}>
                Certified Candidate Nominees
              </h4>
              <p style={{ color: '#4B5563', fontSize: '0.9rem', marginBottom: '1rem', fontWeight: 600 }}>
                Candidate profiles and manifestos configured for this election:
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                {candidates.map((c, idx) => (
                  <div key={c.id || idx} className="candidate-card" style={{ cursor: 'default', background: '#FFFFFF' }}>
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                      {resolveCandidatePhoto(c.photo_url) ? (
                        <img
                          src={resolveCandidatePhoto(c.photo_url)}
                          alt={c.name}
                          style={{ width: '56px', height: '56px', borderRadius: '8px', objectFit: 'cover', border: '2px solid #000' }}
                          onError={(e) => { e.target.style.display = 'none'; if (e.target.nextSibling) e.target.nextSibling.style.display = 'flex' }}
                        />
                      ) : null}
                      <div style={{ width: '56px', height: '56px', borderRadius: '8px', border: '2px solid #000', background: '#E2E8F0', display: resolveCandidatePhoto(c.photo_url) ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: '1.3rem' }}>
                        {c.name ? c.name.charAt(0).toUpperCase() : 'C'}
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontWeight: 900 }}>{c.name}</h4>
                        <div style={{ fontSize: '0.85rem', color: '#4B5563', fontWeight: 700 }}>
                          {c.position || 'Candidate'} {c.affiliation ? `• ${c.affiliation}` : ''}
                        </div>
                      </div>
                    </div>
                    {c.manifesto && (
                      <p style={{ fontSize: '0.825rem', color: '#374151', marginTop: '0.75rem', marginBottom: 0, lineHeight: 1.4 }}>
                        {c.manifesto}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* PENDING SETTLEMENT (IN-FLIGHT QUEUED / SUBMITTED) */}
      {step === 'pending_settlement' && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge badge-phase">TRANSACTION IN PROGRESS</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.6rem 0' }}>
            Ballot Submission Awaiting Ledger Confirmation
          </h3>
          <p style={{ color: '#4B5563', fontWeight: 600, maxWidth: '540px', margin: '0 auto 1.5rem auto' }}>
            You already have an encrypted ballot attempt currently queued or confirming on-chain ({voterStatus?.status || voterStatus?.state}). Please wait for settlement before refreshing or submitting a replacement vote.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={loadElectionData}>
              Refresh Voting Status
            </button>
            <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/my-vote?election_id=${electionId}` : '/my-vote')}>
              View My Vote Status &rarr;
            </button>
          </div>
        </div>
      )}

      {/* STEP 6: Failed */}
      {step === 'failed' && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge" style={{ background: '#FEE2E2', color: '#DC2626' }}>SUBMISSION NOTICE</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.5rem 0', color: '#DC2626' }}>
            Submission Could Not Be Completed
          </h3>
          <p style={{ color: '#4B5563', fontWeight: 600, maxWidth: '520px', margin: '0 auto 1.5rem auto' }}>
            {error || 'An unexpected issue occurred while submitting your ballot. Please try again.'}
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
            <button className="btn btn-primary" onClick={() => setStep('review')}>
              Retry Submission
            </button>
            <button className="btn btn-secondary" onClick={() => setStep('select')}>
              Change Candidate
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
