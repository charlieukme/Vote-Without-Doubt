import React from 'react'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export default function CandidateDetailPage() {
  const { params, navigate } = useRouter()
  const candidateId = Number(params?.id || 0)

  // Supported candidate data matching backend indices 0 and 1
  const candidateDirectory = {
    0: {
      name: 'Aditya Sharma',
      department: 'Computer Science',
      year: 'Final Year',
      party: 'Student Alliance',
      position: 'President',
      slogan: 'Transparency & Student Welfare',
      manifesto: 'Promoting student welfare, open governance, improved campus technology infrastructure, and transparent collegiate budgeting. Dedicated to creating an inclusive campus environment with enhanced student-faculty communication channels.',
    },
    1: {
      name: 'Priya Patel',
      department: 'Information Science',
      year: 'Third Year',
      party: 'Tech Leaders Union',
      position: 'Vice President',
      slogan: 'Innovation, Hackathons & Campus Growth',
      manifesto: 'Advocating for expanded hackathons, industry mentorship networks, sustainable campus initiatives, and academic flexibility. Fostering cross-departmental collaboration and career readiness programs for all undergraduates.',
    },
  }

  const candidate = candidateDirectory[candidateId] || {
    name: `Candidate #${candidateId}`,
    department: 'General Collegiate',
    year: 'Collegiate',
    party: 'Independent',
    position: 'Council Member',
    slogan: 'Representative for Student Body',
    manifesto: 'Official statement and manifesto registered with the college election committee.',
  }

  return (
    <div className="page-container candidate-detail-page">
      <div className="card">
        <button className="btn btn-secondary" onClick={() => navigate('/candidates')} style={{ marginBottom: '1.25rem' }}>
          &larr; Back to Candidate Directory
        </button>
        <span className="badge badge-accent">BALLOT POSITION #{candidateId}</span>
        <h2 className="card-title">{candidate.name}</h2>
        <p style={{ fontWeight: 800, fontSize: '1.1rem', color: '#1F2937' }}>
          Affiliation: {candidate.party} ({candidate.department} • {candidate.year}) — Seeking {candidate.position}
        </p>
      </div>

      <div className="card">
        <h3>Official Platform & Manifesto</h3>
        <blockquote className="candidate-box-slogan" style={{ margin: '1rem 0', fontSize: '1rem' }}>
          "{candidate.slogan}"
        </blockquote>
        <p style={{ fontSize: '1.05rem', lineHeight: '1.65', marginTop: '1rem', fontWeight: 600 }}>
          {candidate.manifesto}
        </p>

        <div className="alert-box alert-info" style={{ marginTop: '2rem' }}>
          <strong>Ballot Privacy Protection:</strong> Reviewing candidate profiles is public and open to all.
          When casting your actual ballot, your choice is protected through cryptographic relayers and pseudonymity.
        </div>

        <div style={{ marginTop: '1.75rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={() => navigate('/login')}>
            Sign In to Cast Your Ballot &rarr;
          </button>
          <button className="btn btn-secondary" onClick={() => navigate('/how-vote-protected')}>
            Learn How Votes Are Shielded &rarr;
          </button>
        </div>
      </div>
    </div>
  )
}
