import React from 'react'
import './Pages.css'

export default function TermsPage() {
  return (
    <div className="page-container terms-page">
      <div className="card">
        <span className="badge badge-accent">LEGAL & CODE OF CONDUCT</span>
        <h2 className="card-title">College Election Bylaws & Terms of Participation</h2>
        <p>The rules governing voter participation, candidate campaigning, and system integrity.</p>
      </div>

      <div className="card" style={{ lineHeight: '1.6' }}>
        <h4>1. Voter Eligibility</h4>
        <p>
          Only actively enrolled students on the official institutional electoral roll are eligible to register and vote.
          Any attempt to register with another student's USN or credentials is an academic disciplinary offense.
        </p>

        <h4 style={{ marginTop: '1rem' }}>2. One Student, One Final Vote</h4>
        <p>
          Students may use the controlled revoting mechanism up to 3 times to counter coercion or rectify a selection.
          Only the highest sequence ballot recorded on the blockchain will be counted in the official results.
        </p>

        <h4 style={{ marginTop: '1rem' }}>3. Anti-Coercion Protections</h4>
        <p>
          Voters have the right to cast a Null Ballot (retracting vote choice) without disclosing this action to anyone.
          Taking screenshots of ballot choices to prove a vote to a third party is strictly discouraged and counterproductive,
          as subsequent revotes can silently replace earlier ballots.
        </p>

        <h4 style={{ marginTop: '1rem' }}>4. System Auditing</h4>
        <p>
          All election events, candidate additions, and scheduling operations are permanently recorded in a SHA-256 hash-chain
          and public Ethereum smart contract. Any unauthorized administrative tampering results in automated cryptographic mismatch flags.
        </p>
      </div>
    </div>
  )
}
