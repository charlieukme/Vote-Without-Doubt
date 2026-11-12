import React, { useState, useEffect, useCallback } from 'react'
import { useRouter } from '../../router/RouterContext'
import { api } from '../../api/client'
import { selectAuthoritativeElection } from '../../utils/electionUtils'
import '../public/Pages.css'

export default function MyVotePage() {
  const { navigate, params } = useRouter()
  const [electionId, setElectionId] = useState(() => {
    if (params?.election_id) return params.election_id
    if (typeof window !== 'undefined' && window.location?.search) {
      return new URLSearchParams(window.location.search).get('election_id')
    }
    return null
  })
  const [voteInfo, setVoteInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')
  const [cooldownSeconds, setCooldownSeconds] = useState(0)

  const loadVoteStatus = useCallback(async () => {
    setErrorMsg('')
    try {
      let eid = electionId
      if (!eid) {
        const eleRes = await api.get('/public/elections')
        if (eleRes?.elections?.length) {
          const chosen = selectAuthoritativeElection(eleRes.elections)
          eid = chosen?.election_id || eleRes.elections[0]?.election_id
          if (eid) {
            setElectionId(eid)
          }
        }
      }
      if (eid) {
        let res = null
        let primaryErr = null
        try {
          res = await api.get(`/voting/status?election_id=${encodeURIComponent(eid)}`)
        } catch (err) {
          primaryErr = err
        }

        if (!res?.has_ballot) {
          try {
            const v2Res = await api.get(`/v2/voting/status?election_id=${encodeURIComponent(eid)}`)
            if (v2Res && (v2Res.has_voted || (v2Res.state && v2Res.state !== 'NONE'))) {
              res = {
                ...v2Res,
                has_ballot: true,
                status: v2Res.status || v2Res.state || 'CONFIRMED',
                state: v2Res.state || v2Res.status || 'CONFIRMED',
                sequence: v2Res.sequence,
                submissions_used: v2Res.submissions_used ?? v2Res.confirmed_count ?? v2Res.sequence ?? 0,
                max_ballots: v2Res.max_ballots || 3,
                receipt: v2Res.receipt,
                can_revote: v2Res.can_revote,
              }
            }
          } catch (v2Err) {
            if (!res && primaryErr) {
              throw v2Err || primaryErr
            }
          }
        }
        setVoteInfo(res)
        if (res?.cooldown_remaining_sec && res.cooldown_remaining_sec > 0) {
          setCooldownSeconds(Math.ceil(res.cooldown_remaining_sec))
        } else {
          setCooldownSeconds(0)
        }
      }
    } catch (err) {
      setErrorMsg(err?.payload?.message || err?.payload?.error || err?.message || 'Unable to retrieve your voting status.')
    } finally {
      setLoading(false)
    }
  }, [electionId])

  useEffect(() => {
    loadVoteStatus()
  }, [loadVoteStatus])

  // Live countdown ticker for cooldown
  useEffect(() => {
    if (cooldownSeconds <= 0) return
    const timer = setInterval(() => {
      setCooldownSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer)
          // When cooldown expires, refresh authoritative server state
          loadVoteStatus()
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldownSeconds, loadVoteStatus])

  const status = String(voteInfo?.status || voteInfo?.state || 'NONE').toUpperCase()
  const isFinalized = status === 'FINALIZED' || status === 'CONFIRMED'
  const isFailed = status === 'FAILED' || status === 'REVERTED'
  const isQueued = status === 'QUEUED'
  const isSubmitted = status === 'SUBMITTED' || status === 'PENDING'
  const isUncertain = status === 'UNCERTAIN'
  const hasBallotRecord = (voteInfo?.has_ballot === true || voteInfo?.has_voted === true) && status !== 'NONE'

  const sequence = voteInfo?.sequence || 0
  const maxBallots = voteInfo?.max_ballots || 3
  const confirmedCount = voteInfo?.submissions_used ?? voteInfo?.confirmed_count ?? (isFinalized ? sequence : 0)
  const remainingSubmissions = Math.max(0, maxBallots - confirmedCount)
  const isCooldown = cooldownSeconds > 0
  const canRevote = voteInfo?.can_revote === true && !isCooldown && remainingSubmissions > 0
  const retryAllowed = voteInfo?.retry_allowed === true

  return (
    <div className="page-container my-vote-page" style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="card">
        <span className="badge badge-accent">VOTING STATUS</span>
        <h2 className="card-title">My Vote & Submission History</h2>
        <p>
          Check your ballot status and access your official receipt. To guarantee complete vote privacy, your individual candidate choice is never recorded or shown here.
        </p>
      </div>

      {loading ? (
        <div className="card">Loading your voting status...</div>
      ) : errorMsg ? (
        <div className="card">
          <div className="alert-box alert-error">
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>Unable to Load Voting Status</h4>
            <p>{errorMsg}</p>
          </div>
          <div style={{ marginTop: '1rem' }}>
            <button className="btn btn-primary" onClick={loadVoteStatus}>
              Retry &#x21bb;
            </button>
          </div>
        </div>
      ) : hasBallotRecord ? (
        <div className="card">
          <div className="election-header-row">
            <div>
              {/* Distinct Badge & Title per State */}
              {isFinalized && (
                <>
                  <span className="badge badge-verified">✓ VOTE RECORDED</span>
                  <h3 style={{ fontSize: '1.45rem', fontWeight: 900, margin: '0.4rem 0', textTransform: 'uppercase' }}>
                    Ballot Submission #{sequence} Confirmed
                  </h3>
                  <p style={{ color: '#374151', fontSize: '0.95rem', margin: 0, fontWeight: 700 }}>
                    {confirmedCount} of {maxBallots} permitted submissions used for this election.
                  </p>
                </>
              )}

              {isFailed && (
                <>
                  <span className="badge" style={{ background: '#FEE2E2', color: '#DC2626', borderColor: '#DC2626', fontWeight: 800 }}>
                    SUBMISSION FAILED
                  </span>
                  <h3 style={{ fontSize: '1.45rem', fontWeight: 900, margin: '0.4rem 0', textTransform: 'uppercase', color: '#DC2626' }}>
                    Ballot Submission Failed
                  </h3>
                  <p style={{ color: '#374151', fontSize: '0.95rem', margin: 0, fontWeight: 700 }}>
                    {confirmedCount} of {maxBallots} allowable submissions used for this election.
                  </p>
                </>
              )}

              {isQueued && (
                <>
                  <span className="badge" style={{ background: '#FEF3C7', color: '#D97706', borderColor: '#D97706', fontWeight: 800 }}>
                    PROCESSING BALLOT
                  </span>
                  <h3 style={{ fontSize: '1.45rem', fontWeight: 900, margin: '0.4rem 0', textTransform: 'uppercase' }}>
                    Ballot Queued for Recording
                  </h3>
                  <p style={{ color: '#374151', fontSize: '0.95rem', margin: 0, fontWeight: 700 }}>
                    Submission #{sequence} is being processed ({confirmedCount} of {maxBallots} confirmed).
                  </p>
                </>
              )}

              {isSubmitted && (
                <>
                  <span className="badge" style={{ background: '#DBEAFE', color: '#2563EB', borderColor: '#2563EB', fontWeight: 800 }}>
                    RECORDING IN PROGRESS
                  </span>
                  <h3 style={{ fontSize: '1.45rem', fontWeight: 900, margin: '0.4rem 0', textTransform: 'uppercase' }}>
                    Ballot Transmitted to Ledger
                  </h3>
                  <p style={{ color: '#374151', fontSize: '0.95rem', margin: 0, fontWeight: 700 }}>
                    Awaiting block confirmation for Submission #{sequence}.
                  </p>
                </>
              )}

              {isUncertain && (
                <>
                  <span className="badge" style={{ background: '#FEF3C7', color: '#B45309', borderColor: '#B45309', fontWeight: 800 }}>
                    CONFIRMATION UNCERTAIN
                  </span>
                  <h3 style={{ fontSize: '1.45rem', fontWeight: 900, margin: '0.4rem 0', textTransform: 'uppercase', color: '#B45309' }}>
                    Awaiting Network Reconciliation
                  </h3>
                  <p style={{ color: '#374151', fontSize: '0.95rem', margin: 0, fontWeight: 700 }}>
                    Submission #{sequence} status is being verified against the blockchain ({confirmedCount} of {maxBallots} confirmed).
                  </p>
                </>
              )}
            </div>

            {voteInfo?.receipt && (
              <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/receipt?election_id=${encodeURIComponent(electionId)}` : '/receipt')}>
                View Receipt Code &rarr;
              </button>
            )}
          </div>

          {/* FAILED State Callout & Safe Retry Action */}
          {isFailed && (
            <div className="section-block mt-4">
              <div className="alert-box alert-warning">
                <strong>Not Recorded On-Chain:</strong> Your latest submission attempt did not confirm on the blockchain
                {voteInfo?.error ? ` (${voteInfo.error})` : ''}. Failed attempts do not count toward your {maxBallots}-submission quota.
              </div>

              <div style={{ marginTop: '1.5rem', borderTop: '3px solid #000000', paddingTop: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <div>
                  <div style={{ fontWeight: 900, fontSize: '1rem', textTransform: 'uppercase' }}>Safe Submission Retry</div>
                  <div style={{ fontSize: '0.875rem', color: '#4B5563', fontWeight: 700 }}>
                    You have {remainingSubmissions} of {maxBallots} submission(s) remaining. You may safely retry without creating a duplicate.
                  </div>
                </div>

                {retryAllowed ? (
                  <button
                    className="btn btn-primary"
                    onClick={() => navigate(electionId ? `/vote?election_id=${encodeURIComponent(electionId)}` : '/vote')}
                  >
                    Retry Ballot Submission &rarr;
                  </button>
                ) : (
                  <button className="btn" disabled>
                    Retry Blocked ({voteInfo?.retry_blocked_reason || 'Requires Support Investigation'})
                  </button>
                )}
              </div>
            </div>
          )}

          {/* QUEUED / SUBMITTED / UNCERTAIN State Guidance */}
          {(isQueued || isSubmitted || isUncertain) && (
            <div className="section-block mt-4">
              <div className={`alert-box ${isUncertain ? 'alert-warning' : 'alert-info'}`}>
                {isUncertain ? (
                  <>
                    <strong>Reconciliation Required:</strong> The blockchain transaction for Submission #{sequence} did not return a clear receipt in time. Do not resubmit yet; refresh status in a moment while reconciliation verifies block inclusion.
                  </>
                ) : (
                  <>
                    <strong>Settlement in Progress:</strong> Your encrypted ballot has been received and submitted. Status updates automatically once confirmed on-chain.
                  </>
                )}
              </div>
              <div style={{ marginTop: '1rem', textAlign: 'right' }}>
                <button className="btn btn-secondary" onClick={loadVoteStatus}>
                  Refresh Status &#x21bb;
                </button>
              </div>
            </div>
          )}

          {/* FINALIZED State: Revoting Policies & Information */}
          {isFinalized && (
            <div className="section-block mt-4">
              <h4 style={{ textTransform: 'uppercase', fontWeight: 900 }}>Change Your Vote</h4>
              <div className="alert-box alert-info">
                <strong>Your latest valid submission is what counts.</strong> If you submit a new ballot before polls close, it will safely replace your previous vote. To protect your privacy, no one can see which candidate you voted for.
              </div>

              {/* Cooldown Status */}
              {isCooldown && (
                <div className="alert-box alert-warning">
                  ⏳ <strong>Revote Cooldown Active:</strong> Please wait <strong>{cooldownSeconds}s</strong> before casting a replacement vote.
                </div>
              )}

              {/* Revote CTA */}
              <div style={{ marginTop: '1.5rem', borderTop: '3px solid #000000', paddingTop: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <div>
                  <div style={{ fontWeight: 900, fontSize: '1rem', textTransform: 'uppercase' }}>Need to change your vote?</div>
                  <div style={{ fontSize: '0.875rem', color: '#4B5563', fontWeight: 700 }}>
                    {remainingSubmissions <= 0
                      ? `Maximum allowable ballot submissions reached (${maxBallots} of ${maxBallots}).`
                      : `You have ${remainingSubmissions} replacement submission(s) remaining.`}
                  </div>
                </div>

                {canRevote ? (
                  <button
                    className="btn btn-primary"
                    onClick={() => navigate(electionId ? `/vote?election_id=${encodeURIComponent(electionId)}` : '/vote')}
                  >
                    Cast Replacement Revote (Submission #{voteInfo?.next_sequence || (confirmedCount + 1)}) &rarr;
                  </button>
                ) : isCooldown ? (
                  <button className="btn" disabled>
                    Waiting for Cooldown ({cooldownSeconds}s)...
                  </button>
                ) : remainingSubmissions <= 0 ? (
                  <span className="badge" style={{ background: '#E5E7EB' }}>MAX SUBMISSIONS REACHED</span>
                ) : (
                  <button className="btn" disabled>
                    Revote Unavailable
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="alert-box alert-warning">
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>No Ballot Cast Yet</h4>
            <p>You have not participated in the active election yet. Your voting quota is 0 of {maxBallots} used.</p>
          </div>
          <div style={{ marginTop: '1.25rem' }}>
            <button
              className="btn btn-primary"
              onClick={() => navigate(electionId ? `/vote?election_id=${electionId}` : '/vote')}
            >
              Proceed to Cast Your Ballot &rarr;
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
