import React from 'react'
import CandidateCard from './CandidateCard'

/**
 * CandidateShowcase Component
 *
 * Displays all candidates linked to an election in an interactive responsive grid.
 * Supports any number of candidates.
 * Keeps candidate inspection decoupled from voting selection.
 */
export default function CandidateShowcase({
  candidates = [],
  election = null,
  loading = false,
  error = '',
  allElections = [],
  selectedElectionId = '',
  onSelectElection = null,
}) {
  return (
    <section className="candidate-showcase-section" aria-label="Official Candidate Showcase">
      <div className="showcase-header card">
        <div className="showcase-header-content">
          <div className="showcase-badge-row">
            <span className="badge badge-accent">
              CERTIFIED CANDIDATE DIRECTORY
            </span>
            {candidates.length > 0 && (
              <span className="badge badge-violet">
                {candidates.length} {candidates.length === 1 ? 'CANDIDATE' : 'CANDIDATES'} REGISTERED
              </span>
            )}
          </div>

          <h2 className="showcase-title">
            {election?.title ? `Candidates Running in ${election.title}` : 'Certified Student Candidates'}
          </h2>

          <p className="showcase-desc">
            Explore certified candidates, their campaign platforms, and manifestos.
            Click or tap any candidate card to flip and inspect their complete policy agenda.
          </p>

          <div className="showcase-disclaimer alert-box alert-info">
            <strong>Ballot Shielding Guarantee:</strong> Flipping or inspecting candidate profiles does not register a vote. Ballot choices are made privately on the official ballot page when voting is open.
          </div>
        </div>

        {/* Optional Election Selector if elections exist */}
        {allElections.length > 0 && onSelectElection && (
          <div className="showcase-selector-box">
            <label htmlFor="showcase-election-select" className="showcase-select-label">
              Select Election:
            </label>
            <select
              id="showcase-election-select"
              value={selectedElectionId || election?.election_id || ''}
              onChange={(e) => onSelectElection(e.target.value)}
              className="showcase-select-input"
            >
              {!selectedElectionId && <option value="">-- Choose Election to Inspect --</option>}
              {allElections.map((el) => (
                <option key={el.election_id} value={el.election_id}>
                  {el.title} [{el.status}]
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Grid or Status Display */}
      {loading ? (
        <div className="card loading-card">
          <span className="badge badge-accent">LOADING ROSTER</span>
          <p style={{ marginTop: '0.75rem', fontWeight: 700 }}>
            Loading candidate roster from authoritative electoral ledger...
          </p>
        </div>
      ) : error ? (
        <div className="card alert-box alert-error">
          <p style={{ margin: 0, fontWeight: 700 }}>{error}</p>
        </div>
      ) : !election ? (
        <div className="card empty-roster-card">
          <span className="badge badge-subtle">SELECT AN ELECTION</span>
          <h3 style={{ margin: '0.5rem 0' }}>No Active Election Selected</h3>
          <p style={{ color: '#4B5563', margin: 0 }}>
            There is no active election running. Choose an election from the selector above to inspect historical candidate rosters.
          </p>
        </div>
      ) : candidates.length === 0 ? (
        <div className="card empty-roster-card">
          <span className="badge badge-subtle">ROSTER EMPTY</span>
          <h3 style={{ margin: '0.5rem 0' }}>No Candidates Configured</h3>
          <p style={{ color: '#4B5563', margin: 0 }}>
            There are currently no certified candidate profiles registered for this election.
          </p>
        </div>
      ) : (
        <div className="candidate-cards-grid" role="list">
          {candidates.map((c) => (
            <div key={c.index !== undefined ? c.index : c.name} role="listitem">
              <CandidateCard candidate={c} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
