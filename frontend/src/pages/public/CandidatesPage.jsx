import React, { useState, useEffect, useCallback } from 'react'
import { useRouter } from '../../router/RouterContext'
import { api } from '../../api/client'
import { selectAuthoritativeElection } from '../../utils/electionUtils'
import CandidateShowcase from '../../components/CandidateShowcase'
import './Pages.css'

export default function CandidatesPage() {
  const { navigate, params } = useRouter()
  const [elections, setElections] = useState([])
  const [selectedElection, setSelectedElection] = useState(null)
  const [selectedElectionId, setSelectedElectionId] = useState('')
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 1. Load public elections
  const loadElections = useCallback(async () => {
    try {
      const eleRes = await api.get('/public/elections').catch(() => null)
      const list = eleRes?.elections || []
      setElections(list)

      if (list.length > 0) {
        let eid = params?.election_id || (typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('election_id') : null)
        let chosen = null
        if (eid) {
          chosen = list.find((e) => String(e.election_id) === String(eid))
        }
        if (!chosen) {
          // Strictly select active or upcoming election; do not default to historical closed election
          chosen = selectAuthoritativeElection(list)
        }
        setSelectedElection(chosen)
        setSelectedElectionId(chosen ? chosen.election_id : '')
      } else {
        setSelectedElection(null)
        setSelectedElectionId('')
      }
    } catch {
      setElections([])
      setSelectedElection(null)
      setSelectedElectionId('')
    }
  }, [params?.election_id])

  useEffect(() => {
    loadElections()
  }, [loadElections])

  // 2. Load candidates for selected election
  useEffect(() => {
    if (!selectedElectionId) {
      setCandidates([])
      setLoading(false)
      return
    }

    let mounted = true
    setLoading(true)
    setError('')

    async function fetchCandidates() {
      try {
        const res = await api.get(`/public/elections/${selectedElectionId}`).catch(() => null)
        if (mounted && res?.candidates) {
          setCandidates(res.candidates)
          setLoading(false)
          return
        }
      } catch {
        // Fallback to voting route
      }

      try {
        const res2 = await api.get(`/voting/election/${selectedElectionId}`).catch(() => null)
        if (mounted && res2?.candidates) {
          setCandidates(res2.candidates)
          setLoading(false)
          return
        }
      } catch {
        // Empty
      }

      if (mounted) {
        setError('No candidate records found for this election.')
        setCandidates([])
        setLoading(false)
      }
    }

    fetchCandidates()
    return () => {
      mounted = false
    }
  }, [selectedElectionId])

  const handleSelectElection = (eid) => {
    setSelectedElectionId(eid)
    const found = elections.find((e) => String(e.election_id) === String(eid))
    if (found) setSelectedElection(found)
  }

  const isElectionOpen = selectedElection?.status === 'OPEN' || selectedElection?.status === 'ACTIVE'

  return (
    <div className="page-container candidates-page">
      {/* Overview Card */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <span className="badge badge-accent">CERTIFIED CANDIDATES DIRECTORY</span>
            <h2 className="card-title" style={{ margin: '0.4rem 0 0.2rem 0' }}>
              {selectedElection ? 'Official Candidate Showcase' : 'Candidate Directory (Audit & Verification)'}
            </h2>
            <p style={{ margin: 0, color: '#374151', maxWidth: '720px' }}>
              {selectedElection ? (
                <>
                  Review the certified student candidates running in{' '}
                  <strong>{selectedElection.title}</strong>. Click or tap any card to flip it and read the candidate's campaign platform and agenda.
                </>
              ) : (
                <>
                  There is currently no active upcoming election. You may choose any historical election from the directory below to review certified candidate profiles and manifestos for public audit.
                </>
              )}
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={() => navigate('/')}>
              &larr; Back to Portal
            </button>
            {isElectionOpen ? (
              <button className="btn btn-primary" onClick={() => navigate('/vote')}>
                Cast Ballot Now &rarr;
              </button>
            ) : (
              <button className="btn btn-secondary" onClick={() => navigate('/election')}>
                Election Bylaws &rarr;
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Interactive Candidate Showcase with 3D Flip Cards (Section 15 candidate-box-card candidate-photo-frame candidate-box-name candidate-box-slogan CANDIDATE #0) */}
      <CandidateShowcase
        candidates={candidates}
        election={selectedElection}
        loading={loading}
        error={error}
        allElections={elections}
        selectedElectionId={selectedElectionId}
        onSelectElection={handleSelectElection}
      />
    </div>
  )
}
