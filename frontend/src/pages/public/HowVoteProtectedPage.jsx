import React from 'react'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export default function HowVoteProtectedPage() {
  const { navigate } = useRouter()

  return (
    <div className="page-container how-protected-page">
      <div className="card">
        <span className="badge badge-accent">TECHNICAL INTEGRITY</span>
        <h2 className="card-title">How Your Vote Is Protected</h2>
        <p>
          "Vote Without Doubt" is engineered to achieve both ends of the classic cryptographic voting paradox:
          <strong> total individual ballot secrecy</strong> and <strong>complete public verifiability</strong>.
        </p>
      </div>

      <div className="section-block">
        <div className="card">
          <span className="badge badge-violet">LAYER 1 — IDENTITY AUTHENTICATION</span>
          <h3>Electoral Roll Verification & 2FA OTP</h3>
          <p>
            Voters must match an official pre-imported college electoral roll. A single-use 6-digit OTP is dispatched
            exclusively to your verified email address. This prevents arbitrary self-registration and impersonation.
          </p>
        </div>

        <div className="card">
          <span className="badge badge-violet">LAYER 2 — CRYPTOGRAPHIC WALLET PROOF</span>
          <h3>MetaMask Challenge-Response Authentication</h3>
          <p>
            Voters bind their Ethereum address using a server-issued challenge nonce via MetaMask <code>personal_sign</code>.
            <strong>Important:</strong> Candidate selections are NEVER passed to MetaMask. MetaMask only proves wallet ownership.
          </p>
        </div>

        <div className="card">
          <span className="badge badge-violet">LAYER 3 — AI BIOMETRIC LIVENESS</span>
          <h3>Biometric Face Verification</h3>
          <p>
            To defeat camera replay attacks, deepfakes, and coerced phone-passing, our AI engine verifies facial biometrics.
            Captured frames are analyzed securely and template embeddings are encrypted.
          </p>
        </div>

        <div className="card">
          <span className="badge badge-violet">LAYER 4 — PSEUDONYMITY & RELAYER</span>
          <h3>Asynchronous Relayer & Key Destruction</h3>
          <p>
            Your student identity is mathematically decoupled from your ballot through HMAC-SHA256 pseudonyms.
            An independent server-side relayer shuffles ballot submissions. Upon election finalization, the pseudonym keys
            are permanently destroyed, providing forward secrecy so no one can ever trace a vote back to a student.
          </p>
        </div>

        <div className="card">
          <span className="badge badge-violet">LAYER 5 — COERCION RESISTANCE</span>
          <h3>Controlled Revoting & Null Ballots</h3>
          <p>
            If someone looks over your shoulder or coerces you to vote, you may submit up to <strong>3 ballots</strong> with a 120-second cooldown.
            Only the latest valid ballot is tallied by the smart contract. You can also cast a <strong>Null Ballot</strong> to retract your vote.
          </p>
        </div>

        <div className="card">
          <span className="badge badge-violet">LAYER 6 — GOVERNANCE & AUDIT</span>
          <h3>Two-Officer Approval & Public Ledger</h3>
          <p>
            No single administrator can alter or schedule an election. Critical actions require two independent officers (Four-Eyes Principle).
            All administrative events are anchored into an append-only SHA-256 hash-chain verified on the blockchain.
          </p>
        </div>
      </div>

      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h4>Ready to exercise your democratic right?</h4>
          <p>Register your student voter profile in under 2 minutes.</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/register')}>
          Start Voter Registration &rarr;
        </button>
      </div>
    </div>
  )
}
