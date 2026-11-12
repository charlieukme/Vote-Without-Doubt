import { useState, useEffect, useCallback, useRef } from 'react'
import './Voting.css'
import { api } from './api/client.js'
import { useRouter } from './router/RouterContext'
import { selectAuthoritativeElection } from './utils/electionUtils'
import ElectionCountdown from './components/ElectionCountdown'
import Wallet from './Wallet'
import Face from './Face'
import { generateClientNonce, computeClientCommitment } from './utils/clientCommitment'

/**
 * Phase 7 - Core Voting Component
 *
 * Requirements:
 * 1. Multi-factor voting authorization (Voter session + Wallet verified + Face verified).
 * 2. Real election & candidate list dynamically fetched from backend API.
 * 3. Never hardcode Candidate A / Candidate B.
 * 4. Candidate choice is never signed by MetaMask or exposed to ballot plane.
 * 5. Track state transitions: QUEUED -> SUBMITTED -> CONFIRMED -> FINALIZED / FAILED.
 * 6. Never display "Vote recorded" before the blockchain confirms finalization.
 * 7. Privacy: Never reveal pseudonym, wallet address, or biometric data in UI.
 */
function Voting() {
  const router = useRouter?.() || {}
  const params = router.params || {}

  const [electionId, setElectionId] = useState(() => {
    if (params.election_id) return params.election_id
    if (typeof window !== 'undefined' && window.location?.search) {
      const q = new URLSearchParams(window.location.search).get('election_id')
      if (q) return q
    }
    return null
  })
  const [election, setElection] = useState(null)
  const [step, setStep] = useState('start') // 'start' | 'factors' | 'select' | 'confirm' | 'submitting' | 'done' | 'failed'
  const [candidate, setCandidate] = useState(null)
  const [isNullBallot, setIsNullBallot] = useState(false)
  const [factorStatus, setFactorStatus] = useState({ wallet_ok: false, face_ok: false })
  const [ballotState, setBallotState] = useState('')
  const [receipt, setReceipt] = useState(null)
  const [clientOpeningData, setClientOpeningData] = useState(null)
  const [voteStatusInfo, setVoteStatusInfo] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [isPolling, setIsPolling] = useState(false)
  const [isRevoting, setIsRevoting] = useState(false)

  // Track active request ID to invalidate stale asynchronous responses & prevent race conditions
  const activeRequestIdRef = useRef(0)
  const isRefreshingRef = useRef(false)

  // Poll ballot status until FINALIZED or FAILED
  const pollStatus = useCallback(async (eid) => {
    if (!eid) return
    setIsPolling(true)
    setError('')
    const maxPolls = 30
    for (let i = 0; i < maxPolls; i++) {
      try {
        const res = await api.get(`/voting/status?election_id=${eid}`)
        setBallotState(res.status)
        setVoteStatusInfo(res)
        if (res.status === 'FINALIZED') {
          setReceipt(res.receipt)
          setStep('done')
          setIsPolling(false)
          setError('')
          return
        }
        if (res.status === 'FAILED') {
          setStep('failed')
          setIsPolling(false)
          const safeError = res.error || res.message
          if (safeError === 'NO_CONTRACT_ADDRESS') {
            setError('Ballot submission failed: No smart contract address is configured for the relayer. Please ensure the BallotBox contract is deployed and BALLOTBOX_CONTRACT_ADDRESS is set.')
          } else if (safeError) {
            setError(`Ballot submission failed on blockchain: ${safeError}`)
          } else {
            setError('Ballot submission failed on blockchain. Please contact election support.')
          }
          return
        }
      } catch {
        // Temporary status lookup failures: distinguish from genuine FAILED ballot
        // Continue polling across transient network glitches
      }
      await new Promise((r) => setTimeout(r, 1000))
    }
    setIsPolling(false)
    setError('Transaction confirmation timed out. Check status later.')
  }, [])

  // Load election details
  const loadElection = useCallback(async (eid, skipStatusCheck = false, reqId = null) => {
    if (!eid) return null
    try {
      const data = await api.get(`/voting/election/${eid}`)
      if (reqId !== null && reqId !== activeRequestIdRef.current) return null
      setElection(data)
      const resolvedEid = data.election_id || eid
      setElectionId(resolvedEid)

      // When election status is closed/cancelled/emergency, display notice if user is in progress
      const s = data?.status
      if (s && s !== 'OPEN' && s !== 'ACTIVE') {
        if (s === 'EMERGENCY_CLOSED') {
          setError('Election Emergency Closed: This election has been concluded early by election officers.')
        } else if (s === 'CLOSED' || s === 'CANCELLED' || s === 'FINALIZED') {
          setError(`Election Closed: Voting is currently ${s}. Submissions are no longer accepted.`)
        }
      }

      if (!skipStatusCheck && !isRevoting) {
        try {
          const statusRes = await api.get(`/voting/status?election_id=${resolvedEid}`)
          if (reqId !== null && reqId !== activeRequestIdRef.current) return data
          if (statusRes?.status === 'FINALIZED') {
            setBallotState('FINALIZED')
            setVoteStatusInfo(statusRes)
            if (statusRes.receipt) {
              setReceipt(statusRes.receipt)
            }
            setStep('done')
            return data
          } else if (statusRes?.status === 'FAILED') {
            setBallotState('FAILED')
            setVoteStatusInfo(statusRes)
            setStep('failed')
            const safeErr = statusRes.error || statusRes.message
            if (safeErr === 'NO_CONTRACT_ADDRESS') {
              setError('Ballot submission failed: No smart contract address is configured for the relayer. Please ensure the BallotBox contract is deployed and BALLOTBOX_CONTRACT_ADDRESS is set.')
            } else {
              setError(safeErr || 'Ballot submission failed.')
            }
            return data
          } else if (statusRes?.status === 'QUEUED' || statusRes?.status === 'SUBMITTED' || statusRes?.status === 'CONFIRMED') {
            setBallotState(statusRes.status)
            setVoteStatusInfo(statusRes)
            setStep('submitting')
            pollStatus(resolvedEid)
            return data
          }
        } catch {
          // Status check may fail if voter is unauthenticated or has no prior session; ignore
        }
      }

      return data
    } catch (err) {
      if (reqId === null || reqId === activeRequestIdRef.current) {
        setError(err.message || 'Failed to load election information.')
      }
      return null
    }
  }, [isRevoting, pollStatus])

  // Authoritative election resolution
  const initElection = useCallback(async (isBackground = false) => {
    if (isRefreshingRef.current) return
    isRefreshingRef.current = true
    const currentRequestId = ++activeRequestIdRef.current

    if (!isBackground) {
      setLoading(true)
    }

    try {
      // 1. Check URL query params first
      let targetEid = params.election_id
      if (!targetEid && typeof window !== 'undefined' && window.location?.search) {
        targetEid = new URLSearchParams(window.location.search).get('election_id')
      }

      if (targetEid) {
        setElectionId(targetEid)
        await loadElection(targetEid, false, currentRequestId)
        return
      }

      // 2. Fall back to authoritative catalog
      const res = await api.get('/public/elections')
      if (currentRequestId !== activeRequestIdRef.current) return
      const chosen = selectAuthoritativeElection(res?.elections)
      if (chosen?.election_id) {
        setElectionId(chosen.election_id)
        await loadElection(chosen.election_id, false, currentRequestId)
      } else {
        if (currentRequestId === activeRequestIdRef.current) {
          setError('No elections are currently available.')
        }
      }
    } catch (err) {
      if (currentRequestId === activeRequestIdRef.current) {
        setError(err.message || 'Failed to load elections.')
      }
    } finally {
      if (currentRequestId === activeRequestIdRef.current) {
        if (!isBackground) setLoading(false)
        isRefreshingRef.current = false
      }
    }
  }, [params.election_id, loadElection])

  // Initial load and focus/visibilitychange listeners for authoritative election state
  useEffect(() => {
    initElection()

    const handleFocusOrVisible = () => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        initElection(true)
      }
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('focus', handleFocusOrVisible)
      document.addEventListener('visibilitychange', handleFocusOrVisible)
    }

    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('focus', handleFocusOrVisible)
        document.removeEventListener('visibilitychange', handleFocusOrVisible)
      }
      activeRequestIdRef.current += 1
      isRefreshingRef.current = false
    }
  }, [initElection])

  // Boundary synchronization: refresh election metadata when start or end time is reached
  useEffect(() => {
    if (!election?.start_time || election.status !== 'SCHEDULED') return
    const startMs = new Date(election.start_time).getTime()
    const nowMs = Date.now()
    const delay = Math.max(0, startMs - nowMs)
    if (delay <= 0) {
      initElection()
      return
    }
    const timer = setTimeout(() => {
      initElection()
    }, delay + 500)
    return () => clearTimeout(timer)
  }, [election?.start_time, election?.status, initElection])

  useEffect(() => {
    if (!election?.end_time || (election.status !== 'OPEN' && election.status !== 'ACTIVE')) return
    const endMs = new Date(election.end_time).getTime()
    const nowMs = Date.now()
    const delay = Math.max(0, endMs - nowMs)
    if (delay <= 0) {
      initElection()
      return
    }
    const timer = setTimeout(() => {
      initElection()
    }, delay + 500)
    return () => clearTimeout(timer)
  }, [election?.end_time, election?.status, initElection])

  // Step 1: Start voting & check factors
  const startVoting = async () => {
    if (!electionId) {
      setError('No election is currently selected.')
      return
    }
    setLoading(true)
    setError('')
    try {
      if (!isRevoting) {
        try {
          const checkStatus = await api.get(`/voting/status?election_id=${electionId}`)
          if (checkStatus?.status === 'FINALIZED') {
            setBallotState('FINALIZED')
            setVoteStatusInfo(checkStatus)
            if (checkStatus.receipt) setReceipt(checkStatus.receipt)
            setStep('done')
            return
          }
        } catch {
          // Proceed with authorization if status check is not available
        }
      }

      // 1. Authorize election session
      await api.post('/voting/authorize', { election_id: electionId })

      // 2. Query factor status from server-side verified records
      const factors = await api.post('/voting/mark-factors', { election_id: electionId })
      setFactorStatus({
        wallet_ok: Boolean(factors.wallet_ok),
        face_ok: Boolean(factors.face_ok),
      })

      if (factors.wallet_ok && factors.face_ok) {
        // Factors satisfied - advance to candidate selection
        await loadElection(electionId, true)
        setStep('select')
      } else {
        // Needs factor completion
        setStep('factors')
      }
    } catch (err) {
      setError(err.message || 'Authorization failed.')
    } finally {
      setLoading(false)
    }
  }

  // Re-check factors after user performs wallet/face steps in UI
  const recheckFactors = async () => {
    if (!electionId) return
    setLoading(true)
    setError('')
    try {
      const factors = await api.post('/voting/mark-factors', { election_id: electionId })
      setFactorStatus({
        wallet_ok: Boolean(factors.wallet_ok),
        face_ok: Boolean(factors.face_ok),
      })

      if (factors.wallet_ok && factors.face_ok) {
        await loadElection(electionId, true)
        setStep('select')
      } else {
        setError('One or more security factors are still pending verification.')
      }
    } catch (err) {
      setError(err.message || 'Factor verification check failed.')
    } finally {
      setLoading(false)
    }
  }

  // Initiate revote flow (Phase 9)
  const initiateRevote = async () => {
    setCandidate(null)
    setIsNullBallot(false)
    setError('')
    setIsRevoting(true)
    setStep('start')
  }

  // Submit ballot to relayer pipeline (PERMANENTLY DISABLED per SEC-001)
  const submitBallot = async () => {
    setError('Legacy V1 plaintext ballot submission is permanently disabled for ballot privacy (SEC-001). Please use the V2 encrypted ballot portal.')
    setStep('failed')
  }

  // Download authenticated ballot receipt with client-side commitment opening
  const downloadReceipt = () => {
    const finalReceipt = receipt || {}
    const finalCandidate = finalReceipt.candidate !== undefined ? finalReceipt.candidate : clientOpeningData?.candidate_index
    const finalCommitment = finalReceipt.commitment || clientOpeningData?.commitment
    const finalNonce = finalReceipt.commitment_nonce || clientOpeningData?.commitment_nonce
    const finalElectionId = finalReceipt.election_id || electionId

    const receiptPayload = {
      vwd_receipt_version: '1.0',
      election_id: String(finalElectionId),
      election_title: finalReceipt.election_title || election?.title,
      receipt_code: finalReceipt.receipt_code,
      sequence: finalReceipt.sequence || voteStatusInfo?.sequence || 1,
      candidate_index: finalCandidate,
      commitment: finalCommitment,
      commitment_nonce: finalNonce,
      timestamp: finalReceipt.timestamp || new Date().toISOString(),
      formula: 'SHA-256("VWD_BALLOT_COMMITMENT_V1:" + election_id + ":" + candidate_index + ":" + nonce)',
      instructions: 'You can verify this receipt offline in the Public Receipt Verification tool by checking that candidate_index and commitment_nonce open to commitment, and that commitment is included in the election Merkle root.',
    }

    const blob = new Blob([JSON.stringify(receiptPayload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `VWD_Receipt_${finalReceipt.receipt_code || 'ballot'}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Task 3 baseline: disabled={loading || (election?.status && election.status !== 'OPEN' && election.status !== 'ACTIVE')}
  // Shared fail-closed predicate for voting actions
  const isElectionVotingActive =
    election?.status === 'OPEN' ||
    election?.status === 'ACTIVE'

  return (
    <div className="voting-container" id="voting-section">
      <h2 className="voting-title">Cast Your Secure Vote</h2>
      <p className="voting-subtitle">
        Protected by Multi-Factor Authentication, Cryptographic Shuffling, and Smart Contract Validation.
      </p>

      {/* SEC-001 Deprecation Banner */}
      <div style={{ background: '#7f1d1d', color: '#fecaca', padding: '0.85rem 1.25rem', borderRadius: '6px', marginBottom: '1.25rem', border: '1px solid #ef4444', textAlign: 'center' }}>
        <strong>DEPRECATION NOTICE (SEC-001):</strong> Legacy V1 plaintext ballot submission is permanently disabled. Active voting must use the V2 threshold ElGamal portal.
      </div>

      {/* Step Progress Indicator (Section 17) */}
      <nav className="voting-stepper" aria-label="Voting Process Stepper">
        <span className={`step-item ${step === 'start' ? 'active' : 'completed'}`}>
          01 VERIFY
        </span>
        <span className={`step-item ${step === 'factors' ? 'active' : (['select', 'confirm', 'submitting', 'done'].includes(step) ? 'completed' : '')}`}>
          02 FACE
        </span>
        <span className={`step-item ${step === 'select' ? 'active' : (['confirm', 'submitting', 'done'].includes(step) ? 'completed' : '')}`}>
          03 CHOOSE
        </span>
        <span className={`step-item ${step === 'confirm' ? 'active' : (['submitting', 'done'].includes(step) ? 'completed' : '')}`}>
          04 REVIEW
        </span>
        <span className={`step-item ${step === 'submitting' ? 'active' : (step === 'done' ? 'completed' : '')}`}>
          05 SIGN
        </span>
        <span className={`step-item ${step === 'done' ? 'active' : ''}`}>
          06 RECORD
        </span>
      </nav>

      {/* Step 1: Start */}
      {step === 'start' && (
        <div className="voting-step">
          <p>
            Ready to participate in <strong>{election?.title || (electionId ? `Election ${electionId}` : 'the election')}</strong>?
          </p>
          <div style={{ margin: '0.75rem 0' }}>
            <ElectionCountdown
              electionId={election?.id !== undefined && election?.id !== null ? String(election.id) : (election?.election_id || electionId || '')}
              startTime={election?.start_time}
              endTime={election?.end_time}
              status={election?.status}
              onZero={() => initElection(true)}
            />
          </div>
          {election && (!election.candidates || election.candidates.length < 2) && (
            <div style={{ background: '#FEF3C7', border: '2px solid #D97706', padding: '0.85rem', borderRadius: '6px', color: '#92400E', fontWeight: 700, margin: '1rem 0' }}>
              ⚠️ <strong>Election Setup in Progress:</strong> This election does not have candidates configured yet and is not currently eligible for ballot submission.
            </div>
          )}
          <button
            id="start-voting-btn"
            className="voting-btn primary-btn"
            onClick={startVoting}
            disabled={loading || !isElectionVotingActive || (!election?.candidates || election.candidates.length < 2)}
          >
            {loading
              ? 'Initializing...'
              : (!election?.candidates || election.candidates.length < 2)
              ? 'No Candidates Configured'
              : (election?.status === 'SCHEDULED' ? 'Voting Scheduled (Not Started)' : 'Begin Voting Authorization')}
          </button>
        </div>
      )}

      {/* Step 2: Factors Required */}
      {step === 'factors' && (
        <div className="voting-step">
          <h3>Multi-Factor Verification Required</h3>
          <p>Collegiate security policy requires genuine cryptographic factor verification before voting:</p>

          {/* Active factor verification components rendered above factor checklist */}
          {!factorStatus.wallet_ok && (
            <div className="factor-component-box" style={{ marginBottom: '1.5rem' }}>
              <Wallet onBound={recheckFactors} />
            </div>
          )}

          {!factorStatus.face_ok && (
            <div className="factor-component-box" style={{ marginBottom: '1.5rem' }}>
              <Face onVerified={recheckFactors} />
            </div>
          )}

          <ul className="factor-checklist">
            <li className={factorStatus.wallet_ok ? 'factor-ok' : 'factor-pending'}>
              {factorStatus.wallet_ok ? '✓' : '✗'} <strong>Wallet Ownership Factor:</strong>{' '}
              {factorStatus.wallet_ok
                ? 'Cryptographically Verified'
                : 'Pending — Please bind and sign with your registered wallet above'}
            </li>
            <li className={factorStatus.face_ok ? 'factor-ok' : 'factor-pending'}>
              {factorStatus.face_ok ? '✓' : '✗'} <strong>Biometric Face Verification Factor:</strong>{' '}
              {factorStatus.face_ok
                ? 'Biometric Verification Verified'
                : 'Pending — Please complete face verification above'}
            </li>
          </ul>
          <button
            id="recheck-factors-btn"
            className="voting-btn primary-btn"
            onClick={recheckFactors}
            disabled={loading || !isElectionVotingActive}
          >
            {loading ? 'Checking Factors...' : 'Verify Factors & Proceed'}
          </button>
        </div>
      )}

      {/* Step 3: Candidate Selection */}
      {step === 'select' && (
        <div className="voting-step">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <h3 style={{ margin: 0 }}>Select Your Candidate</h3>
            <ElectionCountdown
              electionId={election?.id !== undefined && election?.id !== null ? String(election.id) : (election?.election_id || electionId || '')}
              startTime={election?.start_time}
              endTime={election?.end_time}
              status={election?.status}
              onZero={() => initElection(true)}
            />
          </div>
          <p className="election-name">{election?.title || (electionId ? `Election ${electionId}` : '')}</p>

          <div className="candidates-list" role="radiogroup" aria-label="Candidates">
            {election?.candidates && election.candidates.length > 0 ? (
              election.candidates.map((c) => (
                <label
                  key={c.index}
                  className={`candidate-card ${!isNullBallot && candidate === c.index ? 'selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="candidate"
                    value={c.index}
                    checked={!isNullBallot && candidate === c.index}
                    onChange={() => {
                      setCandidate(c.index)
                      setIsNullBallot(false)
                    }}
                  />
                  <div className="candidate-info">
                    <span className="candidate-name">{c.name}</span>
                    {c.party && <span className="candidate-party">{c.party}</span>}
                  </div>
                </label>
              ))
            ) : (
              <div style={{ background: '#FEF3C7', border: '2px solid #D97706', padding: '0.85rem', borderRadius: '6px', color: '#92400E', fontWeight: 700, margin: '1rem 0' }}>
                ⚠️ <strong>No candidates configured:</strong> This election does not have registered candidates and cannot accept ballots.
              </div>
            )}

            {/* Phase 9 Coercion Mitigation: Null Ballot option */}
            <label className={`candidate-card null-ballot-card ${candidate === -1 ? 'selected' : ''}`}>
              <input
                type="radio"
                name="candidate"
                value="null"
                checked={candidate === -1}
                onChange={() => {
                  setCandidate(-1)
                  setIsNullBallot(true)
                }}
              />
              <div className="candidate-info">
                <span className="candidate-name">Retract Active Choice (Null Ballot)</span>
                <span className="candidate-party">Coercion Mitigation — Withhold vote on tally</span>
              </div>
            </label>
          </div>

          <button
            id="review-ballot-btn"
            className="voting-btn primary-btn"
            onClick={() => {
              if (candidate !== null) setStep('confirm')
              else setError('Please select a candidate or select Null Ballot.')
            }}
            disabled={candidate === null || (!isNullBallot && (!election?.candidates || election.candidates.length < 2)) || !isElectionVotingActive}
          >
            Review Selection
          </button>
        </div>
      )}

      {/* Step 4: Confirm Selection */}
      {step === 'confirm' && (
        <div className="voting-step confirmation-box">
          <h3>Confirm Your Ballot</h3>
          {isNullBallot ? (
            <p>
              You are casting a <strong>Null Ballot</strong> (retracting your active candidate choice).
            </p>
          ) : (
            <p>
              You are casting your vote for candidate:
              <strong className="selected-candidate-name">
                {' '}
                {election?.candidates?.find((c) => c.index === candidate)?.name || `Candidate #${candidate}`}
              </strong>
            </p>
          )}
          <div className="security-notice" role="note">
            ⚠️ <strong>One Counted Ballot Policy:</strong> In accordance with smart contract
            rules, only your initial ballot (sequence = 1) or authorized revotes are accepted. Revoting is strictly prohibited unless controlled by anti-coercion policies (maximum 3 authenticated sequence ballots, latest-vote-wins).
          </div>
          <div className="button-group">
            <button
              className="voting-btn secondary-btn"
              onClick={() => setStep('select')}
              disabled={loading}
            >
              Change Selection
            </button>
            <button
              id="confirm-submit-btn"
              className="voting-btn primary-btn"
              onClick={submitBallot}
              disabled={loading || !isElectionVotingActive}
            >
              {loading ? 'Submitting to Relayer...' : 'Confirm & Cast Ballot'}
            </button>
          </div>
        </div>
      )}

      {/* Step 5: Submitting / Polling */}
      {step === 'submitting' && (
        <div className="voting-step progress-box" role="status">
          <h3>Ballot Pipeline in Progress</h3>
          <div className="status-badge">{ballotState || 'QUEUED'}</div>
          <p>
            {ballotState === 'QUEUED' && 'Ballot queued for relayer processing and cryptographic shuffling...'}
            {ballotState === 'SUBMITTED' && 'Submitted to Ethereum blockchain (Ganache), awaiting mining...'}
            {ballotState === 'CONFIRMED' && 'Transaction mined on blockchain, verifying receipt status...'}
            {(!ballotState || ballotState === 'PROCESSING') && 'Processing secure ballot transaction...'}
          </p>
          {isPolling && <div className="spinner" />}
          <p className="subtext">
            {isPolling
              ? 'Do not refresh the page. We are awaiting authoritative on-chain confirmation.'
              : 'Awaiting confirmation update. Check status below without resubmitting.'}
          </p>
          {!isPolling && (
            <div className="button-group" style={{ marginTop: '1rem' }}>
              <button
                id="check-status-btn"
                className="voting-btn secondary-btn"
                onClick={() => pollStatus(electionId)}
                disabled={isPolling}
              >
                Check Status Again
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step 6: Finalized / Success */}
      {step === 'done' && (
        <div className="voting-step receipt-box" role="status">
          <div className="success-icon">✓</div>
          <h3>Vote Finalized & Confirmed on Blockchain</h3>
          <p>Your ballot has been securely finalized and recorded on the blockchain ledger.</p>

          {receipt && (
            <div className="receipt-details">
              <h4>Official Vote Receipt</h4>
              <p className="receipt-code">
                <strong>Receipt Code:</strong> <code>{receipt.receipt_code}</code>
              </p>
              <p>
                <strong>Timestamp:</strong> {receipt.timestamp}
              </p>
              <p>
                <strong>Election:</strong> {receipt.election_title}
              </p>
              <p className="receipt-explanation">
                {receipt.explanation ||
                  'This HMAC receipt proves your ballot was finalized without disclosing your candidate choice or identity.'}
              </p>

              {(receipt.commitment || clientOpeningData?.commitment) && (
                <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid #cbd5e1', fontSize: '0.85rem' }}>
                  <p style={{ margin: '0.25rem 0' }}>
                    <strong>Ballot Commitment:</strong> <code style={{ wordBreak: 'break-all' }}>{receipt.commitment || clientOpeningData?.commitment}</code>
                  </p>
                  {(receipt.commitment_nonce || clientOpeningData?.commitment_nonce) && (
                    <p style={{ margin: '0.25rem 0' }}>
                      <strong>Opening Nonce (Private):</strong> <code style={{ wordBreak: 'break-all' }}>{receipt.commitment_nonce || clientOpeningData?.commitment_nonce}</code>
                    </p>
                  )}
                  <p style={{ margin: '0.35rem 0', color: '#047857' }}>
                    🔒 <strong>256-Bit Web Crypto Protection:</strong> This opening nonce allows you to independently open and verify your ballot choice offline without disclosing it to third parties.
                  </p>
                  <button
                    id="download-receipt-btn"
                    className="voting-btn"
                    style={{ marginTop: '0.65rem', background: '#0f766e', color: '#fff', width: '100%' }}
                    onClick={downloadReceipt}
                  >
                    📥 Download Cryptographic Receipt (.json)
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Phase 9 Revote Status & Action */}
          <div className="revote-panel" style={{ marginTop: '1.5rem', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
            {voteStatusInfo?.cooldown_active ? (
              <div className="cooldown-box" role="status" style={{ color: '#d97706', marginBottom: '0.75rem' }}>
                ⏳ <strong>Revote Cooldown Active:</strong> Please wait {voteStatusInfo.cooldown_remaining_sec}s before casting a replacement revote.
              </div>
            ) : voteStatusInfo?.can_revote ? (
              <button
                id="initiate-revote-btn"
                className="voting-btn secondary-btn"
                onClick={initiateRevote}
                disabled={!isElectionVotingActive}
              >
                Revote / Change Vote (Sequence {Number(voteStatusInfo?.sequence || 1) + 1} of {voteStatusInfo?.max_ballots || 3})
              </button>
            ) : voteStatusInfo?.sequence >= (voteStatusInfo?.max_ballots || 3) ? (
              <p style={{ color: '#64748b' }}>Maximum ballot count reached ({voteStatusInfo.sequence}/{voteStatusInfo.max_ballots}). Further revotes are prohibited.</p>
            ) : null}
          </div>
        </div>
      )}

      {/* Failure state */}
      {step === 'failed' && (
        <div className="voting-step error-box" role="alert">
          <h3>Submission Failed</h3>
          <p>{error || 'An error occurred during ballot processing.'}</p>
          <button
            className="voting-btn secondary-btn"
            onClick={() => setStep('start')}
          >
            Try Again
          </button>
        </div>
      )}

      {/* Error Banner */}
      {error && step !== 'failed' && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
    </div>
  )
}

export default Voting