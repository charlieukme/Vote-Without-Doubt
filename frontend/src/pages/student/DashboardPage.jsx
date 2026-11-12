import React, { useState, useEffect, useCallback } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import { selectAuthoritativeElection, getPastElections, getUpcomingElections } from '../../utils/electionUtils'
import ElectionCountdown from '../../components/ElectionCountdown'
import '../public/Pages.css'

export default function DashboardPage() {
  const { navigate } = useRouter()
  const { studentAuth, refreshStudentAuth } = useAuth()

  const [election, setElection] = useState(null)
  const [allElections, setAllElections] = useState([])
  const [walletStatus, setWalletStatus] = useState({ bound: false })
  const [faceStatus, setFaceStatus] = useState({ enrolled: false })
  const [voteStatus, setVoteStatus] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadDashboardData = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      // 0. Synchronize student auth state with server only if not yet established
      if (!studentAuth?.authenticated) {
        await refreshStudentAuth()
      }

      // 1. Election info from authoritative public catalog
      const eleRes = await api.get('/public/elections').catch(() => null)
      let chosen = null
      if (eleRes?.elections?.length) {
        setAllElections(eleRes.elections)
        chosen = selectAuthoritativeElection(eleRes.elections)
        setElection(chosen)
      } else {
        setAllElections([])
        setElection(null)
      }

      // 2. Wallet binding status
      const wRes = await api.get('/wallet/status').catch(() => null)
      if (wRes) setWalletStatus(wRes)

      // 3. Face enrollment status
      const fRes = await api.get('/face/status').catch(() => null)
      if (fRes) setFaceStatus(fRes)

      // 4. Voting status for chosen election
      if (chosen?.election_id) {
        let vRes = await api.get(`/voting/status?election_id=${chosen.election_id}`).catch(() => null)
        if (!vRes?.has_ballot) {
          const v2Res = await api.get(`/v2/voting/status?election_id=${chosen.election_id}`).catch(() => null)
          if (v2Res?.has_voted) {
            vRes = {
              has_ballot: true,
              sequence: v2Res.sequence,
              status: v2Res.state,
              receipt: v2Res.receipt,
            }
          }
        }
        if (vRes) setVoteStatus(vRes)
      } else {
        setVoteStatus(null)
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [studentAuth?.authenticated, refreshStudentAuth])

  useEffect(() => {
    loadDashboardData()

    // Visibility-aware auto-refresh polling every 15s to pick up multi-officer approvals & election status transitions
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadDashboardData(true)
      }
    }, 15000)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadDashboardData(true)
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleVisibilityChange)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleVisibilityChange)
    }
  }, [loadDashboardData])

  // Boundary synchronization: refresh dashboard data when start or end time is reached
  useEffect(() => {
    if (!election?.start_time || election.status !== 'SCHEDULED') return
    const startMs = new Date(election.start_time).getTime()
    const nowMs = Date.now()
    const delay = Math.max(0, startMs - nowMs)
    if (delay <= 0) {
      loadDashboardData()
      return
    }
    const timer = setTimeout(() => {
      loadDashboardData()
    }, delay + 500)
    return () => clearTimeout(timer)
  }, [election?.start_time, election?.status, loadDashboardData])

  useEffect(() => {
    if (!election?.end_time || (election.status !== 'OPEN' && election.status !== 'ACTIVE')) return
    const endMs = new Date(election.end_time).getTime()
    const nowMs = Date.now()
    const delay = Math.max(0, endMs - nowMs)
    if (delay <= 0) {
      loadDashboardData()
      return
    }
    const timer = setTimeout(() => {
      loadDashboardData()
    }, delay + 500)
    return () => clearTimeout(timer)
  }, [election?.end_time, election?.status, loadDashboardData])

  const allFactorsReady = Boolean(studentAuth?.authenticated && walletStatus.bound && faceStatus.enrolled)
  const hasVoted = voteStatus?.has_ballot === true
  const isElectionOpen = election?.status === 'OPEN' || election?.status === 'ACTIVE'
  const pastElections = getPastElections(allElections)
  const upcomingElections = getUpcomingElections(allElections)

  // Election Status Badge Mapper
  const getElectionBadge = (status) => {
    const s = (status || 'SCHEDULED').toUpperCase()
    if (s === 'OPEN' || s === 'ACTIVE') return <span className="status-badge status-open">VOTING OPEN</span>
    if (s === 'SCHEDULED') return <span className="status-badge status-scheduled">SCHEDULED</span>
    if (s === 'DRAFT') return <span className="status-badge status-draft">DRAFT</span>
    if (s === 'CLOSED') return <span className="status-badge status-closed">VOTING CLOSED</span>
    if (s === 'FINALIZED') return <span className="status-badge status-finalized">FINALIZED</span>
    if (s === 'EMERGENCY_CLOSED' || s === 'EMERGENCY') return <span className="status-badge status-cancelled">EMERGENCY CLOSED</span>
    if (s === 'CANCELLED') return <span className="status-badge status-cancelled">CANCELLED</span>
    return <span className="status-badge status-scheduled">{s}</span>
  }

  return (
    <div className="page-container student-dashboard-page">
      {/* Welcome Hero Banner */}
      <div className="hero-section card" style={{ background: 'var(--neo-yellow, #FFD93D)' }}>
        <span className="badge" style={{ background: '#000000', color: '#FFFFFF' }}>STUDENT VOTER PORTAL</span>
        <h2 className="hero-title" style={{ fontSize: 'clamp(1.8rem, 3.5vw, 2.5rem)', margin: '0.4rem 0 0.75rem 0' }}>
          Voter Dashboard
        </h2>
        <p className="hero-description" style={{ margin: 0, fontWeight: 700 }}>
          Welcome back. Review campus elections, check certified candidates, and cast your confidential vote.
        </p>
      </div>

      {/* Main Grid: Active Election Card + Security Factor Checklist */}
      <div className="grid-cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
        {/* Active Election Card or Explicit Empty State */}
        {election ? (
          <div className="card">
            <span className="badge badge-violet">ACTIVE ELECTION PARAMETERS</span>
            <h3 style={{ fontSize: '1.4rem', fontWeight: 900, textTransform: 'uppercase', marginTop: '0.5rem' }}>
              {election.title}
            </h3>
            <p style={{ color: '#374151', fontSize: '0.95rem', marginBottom: '1.25rem' }}>
              {election.description || 'Official collegiate election for student council representatives.'}
            </p>

            <div style={{ marginBottom: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
              {getElectionBadge(election.status)}
              <ElectionCountdown
                electionId={election.id !== undefined && election.id !== null ? String(election.id) : (election.election_id || '')}
                startTime={election.start_time}
                endTime={election.end_time}
                status={election.status}
                onZero={() => loadDashboardData(true)}
              />
            </div>

            <div className="election-meta-grid" style={{ marginBottom: '1.75rem' }}>
              <div className="meta-item">
                <span className="meta-label">Voting Opens</span>
                <span className="meta-value">{election.start_time ? new Date(election.start_time).toLocaleString() : 'As Scheduled'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Voting Closes</span>
                <span className="meta-value">{election.end_time ? new Date(election.end_time).toLocaleString() : 'TBD'}</span>
              </div>
            </div>

            {/* Action CTA */}
            <div style={{ borderTop: '3px solid #000000', paddingTop: '1.25rem' }}>
              {election.candidate_count !== undefined && election.candidate_count < 2 ? (
                <div className="alert-box alert-warning" style={{ margin: 0 }}>
                  <strong>Election Setup in Progress:</strong> Candidate nominations are currently being certified. Ballot casting will open once preparations are complete.
                </div>
              ) : !allFactorsReady ? (
                <button className="btn btn-primary" onClick={() => navigate('/profile')} style={{ width: '100%' }}>
                  Complete Verification Setup &rarr;
                </button>
              ) : (election.status === 'CLOSED' || election.status === 'FINALIZED') ? (
                <button
                  className="btn btn-primary"
                  onClick={() => navigate(election?.election_id ? `/results-v2?election_id=${election.election_id}` : '/results-v2')}
                  style={{ width: '100%' }}
                >
                  View Election Results &rarr;
                </button>
              ) : hasVoted ? (
                <button
                  className="btn btn-action"
                  onClick={() => navigate(election?.election_id ? `/my-vote?election_id=${election.election_id}` : '/my-vote')}
                  style={{ width: '100%' }}
                >
                  View My Vote & Receipt &rarr;
                </button>
              ) : isElectionOpen ? (
                <button
                  className="btn btn-primary"
                  onClick={() => navigate(election?.election_id ? `/vote?election_id=${election.election_id}` : '/vote')}
                  style={{ width: '100%' }}
                >
                  Proceed to Vote Now &rarr;
                </button>
              ) : (
                <button
                  className="btn btn-secondary"
                  onClick={() => navigate(election?.election_id ? `/candidates?election_id=${election.election_id}` : '/candidates')}
                  style={{ width: '100%' }}
                >
                  Browse Candidates & Manifestos &rarr;
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="card" style={{ background: '#FFFDF5' }}>
            <span className="badge badge-accent">ELECTION STATUS</span>
            <h3 style={{ fontSize: '1.4rem', fontWeight: 900, textTransform: 'uppercase', marginTop: '0.5rem' }}>
              No election is currently open
            </h3>
            <p style={{ color: '#4B5563', fontSize: '0.95rem', marginBottom: '1.25rem', lineHeight: 1.5 }}>
              There is no active or scheduled election accepting ballots at this time. You can verify your security factors below to prepare for the next voting window, or inspect cryptographic audit proofs and certified results from completed elections.
            </p>

            <div style={{ borderTop: '3px solid #000000', paddingTop: '1.25rem', display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" onClick={() => navigate('/verification')}>
                Audit & Verification &rarr;
              </button>
              {!allFactorsReady && (
                <button className="btn btn-primary" onClick={() => navigate('/profile')}>
                  Set Up Security Factors &rarr;
                </button>
              )}
            </div>
          </div>
        )}

        {/* Multi-Factor Security Readiness Checklist */}
        <div className="card">
          <span className="badge badge-accent">VOTING READINESS CHECK</span>
          <h3 style={{ fontSize: '1.4rem', fontWeight: 900, textTransform: 'uppercase', marginTop: '0.5rem' }}>
            Verification Status
          </h3>
          <p style={{ fontSize: '0.9rem', color: '#374151', marginBottom: '1.25rem' }}>
            To protect your vote and prevent impersonation, please ensure all three verification steps are completed.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            {/* Factor 1: Student Session */}
            <div style={{
              padding: '0.85rem 1rem',
              border: '3px solid #000000',
              background: studentAuth?.authenticated ? '#D1FAE5' : '#FEE2E2',
              boxShadow: '2px 2px 0px #000',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div>
                <strong style={{ fontSize: '0.95rem' }}>{studentAuth?.authenticated ? '✓' : '✗'} Student Account</strong>
                <div style={{ fontSize: '0.75rem', color: studentAuth?.authenticated ? '#065F46' : '#991B1B', fontWeight: 700 }}>
                  {studentAuth?.authenticated ? 'Signed in with college email OTP' : 'Please sign in to your account'}
                </div>
              </div>
              {studentAuth?.authenticated ? (
                <span className="badge badge-verified">VERIFIED</span>
              ) : (
                <button className="btn btn-secondary" onClick={() => navigate('/login')} style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}>
                  Sign In
                </button>
              )}
            </div>

            {/* Factor 2: Wallet Binding */}
            <div style={{ padding: '0.85rem 1rem', border: '3px solid #000000', background: walletStatus.bound ? '#D1FAE5' : '#FEF3C7', boxShadow: '2px 2px 0px #000', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong style={{ fontSize: '0.95rem' }}>{walletStatus.bound ? '✓' : '✗'} Connected Wallet (MetaMask Wallet Binding)</strong>
                <div style={{ fontSize: '0.75rem', color: walletStatus.bound ? '#065F46' : '#92400E', fontWeight: 700 }}>
                  {walletStatus.bound ? `Connected: ${String(walletStatus.wallet_address).slice(0, 8)}...` : 'MetaMask connection required'}
                </div>
              </div>
              {walletStatus.bound ? (
                <span className="badge badge-verified">CONNECTED</span>
              ) : (
                <button className="btn btn-secondary" onClick={() => navigate('/profile')} style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}>
                  Connect Wallet
                </button>
              )}
            </div>

            {/* Factor 3: Face Liveness */}
            <div style={{ padding: '0.85rem 1rem', border: '3px solid #000000', background: faceStatus.enrolled ? '#D1FAE5' : '#FEF3C7', boxShadow: '2px 2px 0px #000', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong style={{ fontSize: '0.95rem' }}>{faceStatus.enrolled ? '✓' : '✗'} Face Verification (AI Biometric Template)</strong>
                <div style={{ fontSize: '0.75rem', color: faceStatus.enrolled ? '#065F46' : '#92400E', fontWeight: 700 }}>
                  {faceStatus.enrolled ? 'Face verification completed' : 'Quick camera check required'}
                </div>
              </div>
              {faceStatus.enrolled ? (
                <span className="badge badge-verified">COMPLETED</span>
              ) : (
                <button className="btn btn-secondary" onClick={() => navigate('/profile')} style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}>
                  Verify Face
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Previous / Archived Elections Section */}
      {pastElections.length > 0 && (
        <div className="card" style={{ marginTop: '1.5rem', background: '#FFFFFF' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '1rem' }}>
            <div>
              <span className="badge" style={{ background: '#E5E7EB' }}>ARCHIVED RECORDS</span>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 900, textTransform: 'uppercase', marginTop: '0.35rem' }}>
                Previous & Completed Elections
              </h3>
            </div>
            <button className="btn btn-secondary" onClick={() => navigate('/verification')} style={{ fontSize: '0.825rem', padding: '0.4rem 0.85rem' }}>
              Open Public Audit &rarr;
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
            {pastElections.map((pe) => (
              <div key={pe.election_id} style={{ border: '2px solid #000000', padding: '1rem', background: '#F9F8F3', boxShadow: '3px 3px 0 #000000' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <strong style={{ fontSize: '1rem', textTransform: 'uppercase' }}>{pe.title}</strong>
                  <span className="badge badge-danger" style={{ fontSize: '0.75rem' }}>VOTING CLOSED</span>
                </div>
                <p style={{ fontSize: '0.85rem', color: '#4B5563', marginBottom: '0.75rem', lineHeight: 1.4 }}>
                  {pe.description || 'Completed election record.'}
                </p>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', borderTop: '1px solid #D1D5DB', paddingTop: '0.5rem' }}>
                  <span>Candidates: <strong>{pe.candidate_count || 0}</strong></span>
                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      className="btn btn-secondary"
                      onClick={() => navigate(`/verification?election_id=${encodeURIComponent(pe.election_id)}`)}
                      style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem', minHeight: '32px' }}
                    >
                      Audit
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={() => navigate(`/results-v2?election_id=${encodeURIComponent(pe.election_id)}`)}
                      style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem', minHeight: '32px' }}
                    >
                      View Results &rarr;
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick Action Hub */}
      <div className="grid-cards nav-hub-grid">
        <div className="card hub-card" onClick={() => navigate('/vote')}>
          <h4>Cast Ballot</h4>
          <p>Authorize security factors and submit your privacy-preserving ballot to the relayer pipeline.</p>
          <span className="hub-link">Go to Voting &rarr;</span>
        </div>

        <div className="card hub-card" onClick={() => navigate('/my-vote')}>
          <h4>My Vote & Receipts</h4>
          <p>Inspect your sequence count, revote cooldown, and official HMAC receipts.</p>
          <span className="hub-link">View My Vote &rarr;</span>
        </div>

        <div className="card hub-card" onClick={() => navigate('/profile')}>
          <h4>Account & Security</h4>
          <p>Review bound wallet details or manage your biometric consent template.</p>
          <span className="hub-link">Manage Security &rarr;</span>
        </div>

        <div className="card hub-card" onClick={() => navigate('/verification')}>
          <h4>Public Verifier</h4>
          <p>Independently inspect the blockchain smart contract and audit anchor.</p>
          <span className="hub-link">Audit Election &rarr;</span>
        </div>
      </div>
    </div>
  )
}
