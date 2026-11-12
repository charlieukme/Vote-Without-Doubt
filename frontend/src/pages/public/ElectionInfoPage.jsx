import React, { useState, useEffect } from 'react'
import { useRouter } from '../../router/RouterContext'
import { api } from '../../api/client'
import './Pages.css'

export default function ElectionInfoPage() {
  const { navigate } = useRouter()
  const [election, setElection] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    api.get('/public/elections')
      .then((res) => {
        if (mounted) {
          setElection(res?.elections?.[0] || null)
          setLoading(false)
        }
      })
      .catch(() => {
        if (mounted) setLoading(false)
      })
    return () => { mounted = false }
  }, [])

  return (
    <div className="page-container election-info-page">
      <div className="card">
        <span className="badge badge-accent">OFFICIAL BYLAWS & SCHEDULE</span>
        <h2 className="card-title">Election Information & Parameters</h2>
        <p>
          Authoritative collegiate election overview: timelines, candidate requirements, eligibility boundaries,
          and cryptographic voting policies enforced by Ethereum smart contracts.
        </p>
      </div>

      {loading ? (
        <div className="card">Loading official election parameters from blockchain...</div>
      ) : election ? (
        <div className="card">
          <div className="election-header-row">
            <div>
              <span className={`status-badge status-${election.status?.toLowerCase()}`}>
                STATUS: {election.status}
              </span>
              <h3 className="election-title-text">{election.title}</h3>
              <p className="election-desc-text">{election.description || 'College Council General Election.'}</p>
            </div>
            <div>
              <button className="btn btn-primary" onClick={() => navigate('/login')}>
                Sign In to Vote &rarr;
              </button>
            </div>
          </div>

          <div className="section-block mt-4">
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900 }}>Authoritative Election Timeline</h4>
            <div className="election-meta-grid">
              <div className="meta-item">
                <span className="meta-label">Voting Opens</span>
                <span className="meta-value">{election.start_time ? new Date(election.start_time).toLocaleString() : 'As scheduled by Officers'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Voting Closes</span>
                <span className="meta-value">{election.end_time ? new Date(election.end_time).toLocaleString() : 'TBD'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Results Declaration</span>
                <span className="meta-value">{election.results_available ? 'Published on Blockchain' : 'Strictly Withheld Until Close'}</span>
              </div>
            </div>
          </div>

          <div className="section-block mt-6">
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900 }}>Enforced Voting Policies</h4>
            <div className="alert-box alert-info">
              <ul style={{ paddingLeft: '1.25rem', lineHeight: '1.65' }}>
                <li><strong>One Voter, One Tally:</strong> Exactly one ballot per eligible student is counted in the final tally.</li>
                <li><strong>Controlled Revoting:</strong> You may submit up to <strong>3 ballots</strong>. Only your latest valid ballot is tallied.</li>
                <li><strong>120-Second Cooldown:</strong> A server-side delay of 120 seconds prevents spam and coercion between revotes.</li>
                <li><strong>Null Ballot (Retraction):</strong> Under duress or coercion, voters may select "Retract Choice" (Null Ballot) to withhold their vote.</li>
                <li><strong>Zero PII on Blockchain:</strong> Student identifiers (USN, roll name, email) are never exposed to Ethereum or linked to ballots.</li>
              </ul>
            </div>
          </div>

          <div style={{ marginTop: '1.75rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => navigate('/candidates')}>
              Review Candidates &rarr;
            </button>
            <button className="btn" onClick={() => navigate('/verification')}>
              Verify Smart Contract &rarr;
            </button>
          </div>
        </div>
      ) : (
        <div className="card">
          <h4>No election currently scheduled.</h4>
          <p>The election committee has not published an active schedule. Please check back soon.</p>
        </div>
      )}
    </div>
  )
}
