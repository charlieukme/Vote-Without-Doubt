import React, { useState, useEffect, useCallback } from 'react'
import VotingV2 from '../../components/VotingV2'
import { api } from '../../api/client'
import { useRouter } from '../../router/RouterContext'
import { selectAuthoritativeElection } from '../../utils/electionUtils'
import '../public/Pages.css'

export default function VotePage() {
  const { navigate } = useRouter()
  const [election, setElection] = useState(null)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState(null)

  const resolveElection = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const sp = new URLSearchParams(window.location.search)
      let eid = sp.get('election_id')

      const eleRes = await api.get('/public/elections').catch(() => null)
      const list = Array.isArray(eleRes?.elections) ? eleRes.elections : []

      let chosen = null
      if (eid) {
        chosen = list.find((e) => String(e.election_id) === String(eid) || String(e.id) === String(eid)) || null
        if (!chosen) {
          chosen = await api.get(`/public/elections/${encodeURIComponent(eid)}`).catch(() => null)
        }
      } else if (list.length > 0) {
        chosen = selectAuthoritativeElection(list) || list[0]
      }

      if (chosen?.election_id && (!Array.isArray(chosen.candidates) || chosen.candidates.length === 0)) {
        const full = await api.get(`/public/elections/${chosen.election_id}`).catch(() => null)
        if (full && (Array.isArray(full.candidates) ? full.candidates.length > 0 : full.election_id)) {
          chosen = { ...chosen, ...full }
        }
      }

      setElection(chosen || null)
    } catch (err) {
      setErrorMessage(err?.message || 'Unable to load election details.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    resolveElection()
  }, [resolveElection])

  const status = (election?.status || '').toUpperCase()
  const isOpen = status === 'OPEN' || status === 'ACTIVE'

  return (
    <div className="page-container vote-page" style={{ maxWidth: '960px', margin: '0 auto' }}>
      {/* Clean Student-Facing Header */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <span className="badge badge-accent">STUDENT VOTING PORTAL</span>
            <h2 className="card-title" style={{ margin: '0.4rem 0 0.25rem 0' }}>
              {election?.title || 'Cast Your Official Ballot'}
            </h2>
            <p style={{ margin: 0, color: '#4B5563', fontWeight: 600 }}>
              Your vote is completely confidential. Your candidate choice is encrypted and cannot be seen by administrators or officers.
            </p>
          </div>

          {election && (
            <div>
              <span className={`badge ${isOpen ? 'badge-verified' : 'badge-phase'}`}>
                {status === 'OPEN' || status === 'ACTIVE'
                  ? 'Voting Open'
                  : status === 'SCHEDULED'
                  ? 'Scheduled'
                  : status === 'CLOSED'
                  ? 'Voting Ended'
                  : status === 'FINALIZED'
                  ? 'Results Available'
                  : status === 'DRAFT'
                  ? 'In Preparation'
                  : 'Notice'}
              </span>
            </div>
          )}
        </div>
      </div>

      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <p style={{ fontWeight: 700, color: '#4B5563' }}>Loading election status...</p>
        </div>
      ) : errorMessage ? (
        <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
          <div className="alert-box alert-warning" style={{ marginBottom: '1.25rem' }}>
            {errorMessage}
          </div>
          <button className="btn btn-secondary" onClick={resolveElection}>
            Try Again
          </button>
        </div>
      ) : !election ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3 style={{ textTransform: 'uppercase', marginBottom: '0.75rem' }}>No Elections Available</h3>
          <p style={{ color: '#4B5563', marginBottom: '1.5rem', fontWeight: 600 }}>
            There are currently no elections available. Please check back later or contact your student council.
          </p>
          <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
            &larr; Back to Dashboard
          </button>
        </div>
      ) : status === 'DRAFT' ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge badge-phase">ELECTION PREPARATION</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>This election is being prepared</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            The election details and candidate nominations are currently being finalized. Voting will be scheduled once preparation is complete.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              &larr; Back to Dashboard
            </button>
          </div>
        </div>
      ) : status === 'PENDING_APPROVAL' ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge badge-phase">ELECTION NOTICE</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>This election is not yet available for voting</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            This election schedule is currently pending final confirmation. Please check back closer to the scheduled election time.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              &larr; Back to Dashboard
            </button>
          </div>
        </div>
      ) : status === 'SCHEDULED' ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge badge-phase">UPCOMING ELECTION</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>Voting has not started yet</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            Polls are scheduled to open as indicated below. You can browse candidate profiles and manifestos to prepare for the vote.
          </p>

          <div className="election-meta-grid" style={{ maxWidth: '520px', margin: '0 auto 1.75rem auto', textAlign: 'left' }}>
            <div className="meta-item">
              <span className="meta-label">Voting Opens</span>
              <span className="meta-value">
                {election.start_time ? new Date(election.start_time).toLocaleString() : 'As scheduled'}
              </span>
            </div>
            <div className="meta-item">
              <span className="meta-label">Voting Closes</span>
              <span className="meta-value">
                {election.end_time ? new Date(election.end_time).toLocaleString() : 'As scheduled'}
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              onClick={() => navigate(election?.election_id ? `/candidates?election_id=${election.election_id}` : '/candidates')}
            >
              Browse Candidates & Manifestos &rarr;
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
              &larr; Back to Dashboard
            </button>
          </div>
        </div>
      ) : isOpen ? (
        <VotingV2
          key={election.election_id}
          electionId={election.election_id}
          initialElection={election}
          initialCandidates={election.candidates}
        />
      ) : status === 'CLOSED' ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge" style={{ background: '#FEE2E2', color: '#DC2626' }}>POLLS CLOSED</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>Voting has ended</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            Voting has concluded for this election. The digital ballot box is closed and official tallies are being verified.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              onClick={() => navigate(election?.election_id ? `/results-v2?election_id=${election.election_id}` : '/results-v2')}
            >
              View Election Results &rarr;
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => navigate(election?.election_id ? `/receipt?election_id=${election.election_id}` : '/receipt')}
            >
              View My Receipt &rarr;
            </button>
          </div>
        </div>
      ) : status === 'FINALIZED' ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <span className="badge badge-verified">RESULTS CERTIFIED</span>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>Election results are available</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', lineHeight: 1.6, fontWeight: 600 }}>
            This election has concluded and official certified results have been calculated and verified on the blockchain ledger.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              onClick={() => navigate(election?.election_id ? `/results-v2?election_id=${election.election_id}` : '/results-v2')}
            >
              View Official Results &rarr;
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => navigate(election?.election_id ? `/receipt?election_id=${election.election_id}` : '/receipt')}
            >
              View My Receipt &rarr;
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/receipt-verification')}>
              Verify Vote Receipt
            </button>
          </div>
        </div>
      ) : (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3 style={{ textTransform: 'uppercase', margin: '0.75rem 0' }}>Election Unavailable</h3>
          <p style={{ color: '#4B5563', maxWidth: '580px', margin: '0 auto 1.5rem auto', fontWeight: 600 }}>
            This election is currently not accepting ballots (Status: {status}).
          </p>
          <button className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
            &larr; Back to Dashboard
          </button>
        </div>
      )}
    </div>
  )
}
