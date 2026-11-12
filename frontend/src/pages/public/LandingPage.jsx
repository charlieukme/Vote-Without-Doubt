import React, { useState, useEffect, useCallback } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import { selectAuthoritativeElection } from '../../utils/electionUtils'
import ElectionCountdown from '../../components/ElectionCountdown'
import CandidateShowcase from '../../components/CandidateShowcase'
import './Pages.css'

export default function LandingPage() {
  const { navigate } = useRouter()
  const { studentAuth } = useAuth()

  // State
  const [elections, setElections] = useState([])
  const [selectedElection, setSelectedElection] = useState(null)
  const [selectedElectionId, setSelectedElectionId] = useState('')
  const [candidates, setCandidates] = useState([])
  const [loadingElection, setLoadingElection] = useState(true)
  const [loadingCandidates, setLoadingCandidates] = useState(false)
  const [candidateError, setCandidateError] = useState('')

  // If a student is already authenticated, allow them to navigate to dashboard or stay to inspect candidates
  // Short skippable intro animation (~3 seconds)
  const [showIntro, setShowIntro] = useState(() => {
    return !sessionStorage.getItem('intro_seen')
  })

  useEffect(() => {
    if (showIntro) {
      const timer = setTimeout(() => {
        dismissIntro()
      }, 3000)
      return () => clearTimeout(timer)
    }
  }, [showIntro])

  const dismissIntro = () => {
    sessionStorage.setItem('intro_seen', 'true')
    setShowIntro(false)
  }

  // Load elections catalog
  const loadElections = useCallback(async (isBackground = false) => {
    if (!isBackground) {
      setLoadingElection(true)
    }
    try {
      const res = await api.get('/public/elections')
      const eleList = res?.elections || []
      setElections(eleList)

      if (eleList.length > 0) {
        // Check URL query param first
        let targetId = null
        if (typeof window !== 'undefined' && window.location?.search) {
          targetId = new URLSearchParams(window.location.search).get('election_id')
        }

        let chosen = null
        if (targetId) {
          const matched = eleList.find((e) => String(e.election_id) === String(targetId))
          // Only show targeted election on homepage if it is active/upcoming
          if (matched && (matched.status === 'OPEN' || matched.status === 'ACTIVE' || matched.status === 'SCHEDULED')) {
            chosen = matched
          }
        }
        if (!chosen) {
          // Strictly select OPEN or SCHEDULED election; never draft or historical closed
          chosen = selectAuthoritativeElection(eleList)
        }

        setSelectedElection(chosen)
        setSelectedElectionId(chosen ? chosen.election_id : '')
      } else {
        setSelectedElection(null)
        setSelectedElectionId('')
      }
    } catch {
      if (!isBackground) {
        setElections([])
        setSelectedElection(null)
        setSelectedElectionId('')
      }
    } finally {
      if (!isBackground) {
        setLoadingElection(false)
      }
    }
  }, [])

  useEffect(() => {
    // Initial fetch
    loadElections(false)

    // Periodic synchronization every 5 seconds when tab is active/visible
    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
        loadElections(true)
      }
    }, 5000)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadElections(true)
      }
    }

    const handleFocus = () => {
      loadElections(true)
    }

    window.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleFocus)

    return () => {
      clearInterval(interval)
      window.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleFocus)
    }
  }, [loadElections])

  // Load candidates whenever selectedElectionId changes or candidate_count changes
  useEffect(() => {
    if (!selectedElectionId) {
      setCandidates([])
      setLoadingCandidates(false)
      return
    }

    let mounted = true
    setLoadingCandidates(true)
    setCandidateError('')

    async function fetchCandidates() {
      try {
        // Try dedicated public endpoint first
        const res = await api.get(`/public/elections/${selectedElectionId}`)
        if (mounted && res?.candidates) {
          setCandidates(res.candidates)
          setLoadingCandidates(false)
          return
        }
      } catch {
        // Fallback to voting/election route
        try {
          const res2 = await api.get(`/voting/election/${selectedElectionId}`)
          if (mounted && res2?.candidates) {
            setCandidates(res2.candidates)
            setLoadingCandidates(false)
            return
          }
        } catch {
          if (mounted) {
            setCandidateError('Unable to load candidate details for this election.')
            setCandidates([])
          }
        }
      }
      if (mounted) setLoadingCandidates(false)
    }

    fetchCandidates()
    return () => {
      mounted = false
    }
  }, [selectedElectionId, selectedElection?.candidate_count])

  const handleSelectElection = (eid) => {
    setSelectedElectionId(eid)
    const found = elections.find((e) => String(e.election_id) === String(eid))
    if (found) setSelectedElection(found)
  }

  // Authoritative Status Helpers
  const status = (selectedElection?.status || '').toUpperCase()
  const isElectionOpen = status === 'OPEN' || status === 'ACTIVE'
  const isScheduled = status === 'SCHEDULED'
  const isClosed = status === 'CLOSED' || status === 'FINALIZED'
  const isDraft = status === 'DRAFT' || status === 'PENDING_APPROVAL'

  // Format Dates in Local Timezone (e.g. IST)
  const formatDateTime = (isoStr) => {
    if (!isoStr) return 'TBD'
    try {
      let normalized = String(isoStr).trim()
      if (!normalized.endsWith('Z') && !normalized.includes('+')) {
        normalized = normalized.replace(' ', 'T') + 'Z'
      }
      const d = new Date(normalized)
      return d.toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    } catch {
      return isoStr
    }
  }

  // Accurate State-Dependent Message
  const renderStateMessage = () => {
    if (!selectedElection) {
      return (
        <div className="alert-box alert-info" style={{ background: 'var(--neo-cream, #FFFDF5)', border: '3px solid #000' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
            <span className="badge badge-subtle" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}>NO ACTIVE ELECTION</span>
            <strong style={{ fontSize: '1.05rem', textTransform: 'uppercase' }}>No Active Election</strong>
          </div>
          <p style={{ margin: 0, color: '#1F2937', fontWeight: 600, lineHeight: 1.5 }}>
            There is currently no upcoming election. Please check back when the election administration publishes the next election.
          </p>
        </div>
      )
    }

    if (isElectionOpen) {
      return (
        <div className="alert-box alert-success" style={{ background: '#DCFCE7', border: '3px solid #000' }}>
          <strong>VOTING CURRENTLY OPEN:</strong> Ballots are actively being accepted until{' '}
          <strong>{formatDateTime(selectedElection.end_time)}</strong>. Review candidate platforms below and cast your ballot.
        </div>
      )
    }

    if (isScheduled) {
      return (
        <div className="alert-box alert-info" style={{ background: '#E0E7FF', border: '3px solid #000' }}>
          <strong>UPCOMING ELECTION:</strong> Voting is scheduled to open on{' '}
          <strong>{formatDateTime(selectedElection.start_time)}</strong>. Review candidate platforms below before voting begins.
        </div>
      )
    }

    return null
  }

  const scrollToCandidates = () => {
    const el = document.getElementById('candidate-showcase')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  return (
    <div className="page-container landing-page">
      {/* Short 3-second skippable intro animation */}
      {showIntro && (
        <div
          role="dialog"
          aria-label="Welcome animation"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '1rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '460px',
              width: '100%',
              background: 'var(--neo-card-surface, #FFFEFA)',
              border: '4px solid #000',
              boxShadow: '8px 8px 0px #000',
              textAlign: 'center',
              padding: '2rem 1.5rem',
            }}
          >
            <span className="badge badge-accent" style={{ marginBottom: '1rem' }}>
              SECURE ELECTORAL PLATFORM
            </span>
            <h2 style={{ fontSize: '2rem', fontWeight: 900, margin: '0.5rem 0' }}>
              Vote Without Doubt
            </h2>
            <p style={{ fontWeight: 700, color: '#374151', margin: '0.5rem 0 1.5rem 0' }}>
              Student Council General Election Portal
            </p>

            <div style={{ width: '100%', height: '8px', border: '2px solid #000', background: '#FFF', marginBottom: '1.5rem', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  background: 'var(--neo-yellow, #FFD93D)',
                  animation: 'introProgress 3s linear forwards',
                }}
              />
            </div>

            <button
              className="btn btn-secondary"
              onClick={dismissIntro}
              style={{ width: '100%', fontWeight: 900 }}
            >
              Enter Portal &rarr;
            </button>
          </div>
        </div>
      )}

      {/* Hero Section — Two-Column Composition */}
      <section className="landing-hero-grid" aria-label="Electoral Portal Introduction">
        {/* Left Column: Active Election or Neutral State */}
        <div className="landing-hero-main hero-section card">
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.75rem' }}>
            <span className="badge badge-accent landing-badge" style={{ marginBottom: 0 }}>
              STUDENT ELECTORAL PORTAL
            </span>
            {selectedElection ? (
              <span className={`status-badge status-${status.toLowerCase()}`}>
                {status}
              </span>
            ) : (
              <span className="status-badge status-neutral" style={{ background: '#E5E7EB', color: '#1F2937', border: '2px solid #000' }}>
                NO ACTIVE ELECTION
              </span>
            )}
          </div>

          <h1 className="landing-hero-title">
            {selectedElection?.title || 'Vote Without Doubt'}
          </h1>

          <p className="landing-hero-subtitle">
            {selectedElection?.description || 'Secure, transparent and independently verifiable college elections.'}
          </p>

          <p className="landing-hero-desc">
            A secure college election platform built around identity verification, privacy-preserving voting, and independently verifiable results.
          </p>

          {/* Authoritative Schedule Block (Only when active/upcoming election exists) */}
          {selectedElection && (
            <div className="election-meta-grid" style={{ margin: '1rem 0 1.25rem 0' }}>
              <div className="meta-item">
                <span className="meta-label">Voting Opens</span>
                <span className="meta-value">{formatDateTime(selectedElection.start_time)}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Voting Closes</span>
                <span className="meta-value">{formatDateTime(selectedElection.end_time)}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Candidates Registered</span>
                <span className="meta-value"><strong>{candidates.length || selectedElection.candidate_count || 0}</strong></span>
              </div>
            </div>
          )}

          {/* State-Dependent Alert Banner */}
          <div style={{ marginBottom: '1.5rem' }}>
            {renderStateMessage()}
          </div>

          {/* Countdown timer when scheduled or open */}
          {selectedElection && (isElectionOpen || isScheduled) && (
            <div style={{ marginBottom: '1.5rem' }}>
              <ElectionCountdown
                electionId={selectedElection.election_id}
                startTime={selectedElection.start_time}
                endTime={selectedElection.end_time}
                status={selectedElection.status}
                onZero={() => loadElections(true)}
              />
            </div>
          )}

          {/* Quick Route Buttons */}
          <div className="landing-hero-links">
            {selectedElection ? (
              <>
                <button
                  className="btn btn-secondary"
                  onClick={scrollToCandidates}
                  style={{ fontWeight: 900 }}
                >
                  Explore Candidates & Platforms &darr;
                </button>
                <button
                  className="link-button"
                  onClick={() => navigate('/election')}
                  style={{ fontWeight: 800, fontSize: '0.95rem' }}
                >
                  Review Election Bylaws &rarr;
                </button>
              </>
            ) : (
              <>
                <button
                  className="btn btn-secondary"
                  onClick={() => navigate('/verification')}
                  style={{ fontWeight: 900 }}
                >
                  View Historical Audits & Verifier &rarr;
                </button>
                <button
                  className="link-button"
                  onClick={() => navigate('/how-vote-protected')}
                  style={{ fontWeight: 800, fontSize: '0.95rem' }}
                >
                  Review Security Architecture &rarr;
                </button>
              </>
            )}
          </div>
        </div>

        {/* Right Column: Voter Access Card */}
        <aside className="voter-access-card card" aria-label="Student Access Actions">
          <div className="access-header">
            <span className="badge badge-violet">
              STUDENT ACTION
            </span>
            <h2 className="access-title">Voter Portal Access</h2>
            <p className="access-desc">
              Eligible college voters verify credentials and participate in university elections using privacy-preserving zero-PII ballots.
            </p>
          </div>

          <div className="access-actions">
            {/* Context-aware primary action: if election is open, show vote; if scheduled, show candidate browse */}
            {isElectionOpen ? (
              <button
                className="btn btn-primary"
                onClick={() => navigate('/vote')}
                aria-label="Proceed to vote now"
                style={{ background: 'var(--neo-green, #4EBA6F)' }}
              >
                CAST BALLOT NOW &rarr;
              </button>
            ) : isScheduled ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <button
                  className="btn btn-primary"
                  onClick={scrollToCandidates}
                  aria-label="Browse candidate platforms before voting opens"
                >
                  BROWSE CANDIDATES &rarr;
                </button>
                <div style={{ fontSize: '0.825rem', color: '#4B5563', fontWeight: 700, textAlign: 'center' }}>
                  Voting will become available at scheduled start time
                </div>
              </div>
            ) : (
              <button
                className="btn btn-secondary"
                onClick={() => navigate('/verification')}
                aria-label="Inspect public verification results"
              >
                INDEPENDENT VERIFIER &rarr;
              </button>
            )}

            <button
              className="btn btn-secondary"
              onClick={() => navigate('/register')}
              aria-label="Register as a voter"
            >
              NEW STUDENT REGISTRATION
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => navigate('/login')}
              aria-label="Sign in to voter account"
            >
              STUDENT SIGN IN
            </button>
          </div>

          <div style={{ borderTop: '2px solid #000000', paddingTop: '0.85rem' }}>
            {selectedElection ? (
              <button
                className="access-footer-link"
                onClick={() => navigate('/candidates')}
              >
                View Full Dedicated Candidate Roster &rarr;
              </button>
            ) : (
              <button
                className="access-footer-link"
                onClick={() => navigate('/verification')}
              >
                Inspect Historical Elections & Results &rarr;
              </button>
            )}
          </div>
        </aside>
      </section>

      {/* Prominent Candidate Showcase Section (Only rendered when an active/upcoming election exists) */}
      {selectedElection && (
        <div id="candidate-showcase">
          <CandidateShowcase
            candidates={candidates}
            election={selectedElection}
            loading={loadingCandidates}
            error={candidateError}
            allElections={elections}
            selectedElectionId={selectedElectionId}
            onSelectElection={handleSelectElection}
          />
        </div>
      )}

      {/* Supporting Feature Cards */}
      <section className="landing-features-section" aria-label="Electoral System Capabilities">
        <div className="features-header-row">
          <h2 className="features-title">Cryptographic Architecture & Voter Protections</h2>
        </div>

        <div className="landing-features-grid">
          {/* Card 1: Public Cryptographic Verification */}
          <div
            className="feature-hub-card card"
            onClick={() => navigate('/verification')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/verification') } }}
          >
            <div className="feature-card-content">
              <span className="badge badge-accent">PUBLIC AUDIT</span>
              <h3>Independent Verifier</h3>
              <p>
                Independently verify election parameters, smart contract state, candidate set hashes, and blockchain audit chain anchors.
              </p>
            </div>
            <span className="feature-card-action">
              Launch Verifier &rarr;
            </span>
          </div>

          {/* Card 2: Receipt Verification */}
          <div
            className="feature-hub-card card"
            onClick={() => navigate('/receipt-verification')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/receipt-verification') } }}
          >
            <div className="feature-card-content">
              <span className="badge badge-violet">VOTER RECEIPT</span>
              <h3>Receipt Verifier</h3>
              <p>
                Verify that your cryptographic ballot receipt was authentically anchored into Ethereum without revealing your vote choice.
              </p>
            </div>
            <span className="feature-card-action">
              Verify Receipt &rarr;
            </span>
          </div>

          {/* Card 3: Technical Security Controls */}
          <div
            className="feature-hub-card card"
            onClick={() => navigate('/how-vote-protected')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/how-vote-protected') } }}
          >
            <div className="feature-card-content">
              <span className="badge badge-accent">SECURITY CONTROLS</span>
              <h3>How Vote Is Protected</h3>
              <p>
                Learn how identity roll checks, 2FA email OTPs, cryptographic wallet proofs, and relayer pseudonymity protect ballot confidentiality.
              </p>
            </div>
            <span className="feature-card-action">
              Read Protections &rarr;
            </span>
          </div>
        </div>
      </section>
    </div>
  )
}
