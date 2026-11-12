import React, { useEffect } from 'react'
import Wallet from '../../Wallet'
import Face from '../../Face'
import { useAuth } from '../../router/AuthContext'
import '../public/Pages.css'

export default function ProfilePage() {
  const { studentAuth, studentSession, refreshStudentAuth } = useAuth()

  useEffect(() => {
    refreshStudentAuth()
  }, [refreshStudentAuth])

  const sessionStateText = studentAuth?.authenticated
    ? 'Active & Signed In'
    : 'Not Signed In'

  return (
    <div className="page-container profile-page" style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="card">
        <span className="badge badge-accent">VOTER ACCOUNT & SECURITY</span>
        <h2 className="card-title">Voter Verification & Security</h2>
        <p>
          Review your voting verification status. To protect your vote and ensure each student votes only once, please complete your wallet connection and face verification.
        </p>
      </div>

      {/* Account Session Information Card */}
      <div className="card">
        <span className="badge badge-phase">STUDENT ACCOUNT</span>
        <h3 style={{ textTransform: 'uppercase', marginTop: '0.4rem', fontWeight: 900 }}>Account & Session</h3>
        <div className="election-meta-grid" style={{ marginTop: '1.25rem' }}>
          <div className="meta-item">
            <span className="meta-label">Account Status</span>
            <span className="meta-value">{sessionStateText}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Email Verification</span>
            <span className="meta-value">{studentAuth?.authenticated ? 'Verified via OTP' : 'Pending Sign In'}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Session Login Time</span>
            <span className="meta-value">{studentSession?.authenticated_at ? new Date(studentSession.authenticated_at).toLocaleTimeString() : 'Active'}</span>
          </div>
        </div>
      </div>

      {/* Verification Step 1: Connected Wallet */}
      <div className="card">
        <span className="badge badge-phase">VERIFICATION STEP 1</span>
        <h3 style={{ textTransform: 'uppercase', marginTop: '0.4rem', fontWeight: 900 }}>Connected Wallet (MetaMask)</h3>
        <p style={{ fontSize: '0.925rem', color: '#374151', marginBottom: '1.25rem', fontWeight: 600 }}>
          Connect your MetaMask wallet to verify your voter signature key. Your candidate choices are always encrypted and are never visible in MetaMask.
        </p>
        <Wallet />
      </div>

      {/* Verification Step 2: Face Verification */}
      <div className="card">
        <span className="badge badge-phase">VERIFICATION STEP 2</span>
        <h3 style={{ textTransform: 'uppercase', marginTop: '0.4rem', fontWeight: 900 }}>Face Verification</h3>
        <p style={{ fontSize: '0.925rem', color: '#374151', marginBottom: '1.25rem', fontWeight: 600 }}>
          A quick camera check ensures one vote per student. Your photo is securely transformed into an anonymous verification code and your privacy is fully protected.
        </p>
        <Face />
      </div>
    </div>
  )
}
