import React from 'react'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export default function PrivacyPage() {
  const { navigate } = useRouter()

  return (
    <div className="page-container privacy-page">
      <div className="card">
        <span className="badge badge-accent">DATA PROTECTION & PRIVACY ARCHITECTURE</span>
        <h2 className="card-title">Voter Privacy Policy & Consent Notice</h2>
        <p>
          In full accordance with collegiate privacy and data minimization principles, our architecture enforces strict unlinkability
          between your student identity and your cast vote.
        </p>
      </div>

      <div className="card" style={{ lineHeight: '1.6' }}>
        <h4>1. Data Minimization</h4>
        <p>
          We collect only what is strictly necessary: your USN (to check the official roll) and your email (to dispatch 2FA OTPs).
          We never collect personal telephone numbers, home addresses, or device fingerprints.
        </p>

        <h4 style={{ marginTop: '1rem' }}>2. Biometric Template & Ephemeral Frames</h4>
        <p>
          When you perform face enrollment, camera frames are processed in-memory for active head-movement liveness.
          Raw frames are never stored on disk. Only a mathematical embedding vector is retained.
          You can withdraw biometric consent and permanently delete your stored facial embedding at any time from your
          <button className="link-button" onClick={() => navigate('/profile')}> Profile & Settings</button> page.
        </p>

        <h4 style={{ marginTop: '1rem' }}>3. Cryptographic Pseudonymity & Forward Secrecy</h4>
        <p>
          Ballots are associated only with per-election pseudonyms.
          Upon election finalization, all master pseudonym keys are permanently destroyed.
          Even with full administrative database access, it is mathematically impossible to reconstruct who voted for whom.
        </p>

        <h4 style={{ marginTop: '1rem' }}>4. Zero Public Transaction Linkage</h4>
        <p>
          Ballots are submitted through an asynchronous relayer that dispatches transactions from a neutral pool.
          Voters never receive raw blockchain transaction hashes, preventing timing or gas-correlation attacks.
        </p>
      </div>
    </div>
  )
}
