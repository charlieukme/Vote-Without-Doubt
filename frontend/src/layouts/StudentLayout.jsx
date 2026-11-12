import React, { useState, useEffect } from 'react'
import { useRouter } from '../router/RouterContext'
import { useAuth } from '../router/AuthContext'
import './StudentLayout.css'

export default function StudentLayout({ children }) {
  const { path, navigate } = useRouter()
  const { studentAuth, studentLogout } = useAuth()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  // Close mobile drawer on route navigation
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [path])

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && mobileMenuOpen) {
        setMobileMenuOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [mobileMenuOpen])

  useEffect(() => {
    // If not authenticated, redirect to login
    if (studentAuth && !studentAuth.authenticated) {
      navigate('/login')
    }
  }, [studentAuth, navigate])

  const handleLogout = async () => {
    await studentLogout()
    navigate('/login')
  }

  if (!studentAuth) {
    return (
      <div className="layout-container student-layout loading-layout">
        <div className="card" style={{ maxWidth: 450, margin: '4rem auto', textAlign: 'center' }}>
          <h3>Authenticating Session...</h3>
          <p>Verifying voter authorization status with server authority...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="layout-container student-layout">
      {/* Top Banner */}
      <div className="student-top-banner">
        <div className="banner-inner">
          <span className="badge-verified-student">AUTHENTICATED VOTER SESSION</span>
          <span className="session-status-text">
            Session Status: <strong>{studentAuth?.state || 'AUTHORIZED'}</strong>
          </span>
        </div>
      </div>

      {/* Student Navigation Header */}
      <header className="student-header" role="banner">
        <div className="header-top-row">
          <div className="header-brand" onClick={() => navigate('/dashboard')}>
            <span className="brand-badge">STUDENT PORTAL</span>
            <h1 className="brand-title">Vote Without Doubt</h1>
          </div>

          <button
            type="button"
            className="mobile-nav-toggle btn"
            aria-label="Toggle student navigation menu"
            aria-expanded={mobileMenuOpen}
            aria-controls="student-nav-menu"
            onClick={() => setMobileMenuOpen(prev => !prev)}
          >
            <span className="mobile-toggle-icon" aria-hidden="true">{mobileMenuOpen ? '✕' : '☰'}</span>
            <span className="mobile-toggle-label">{mobileMenuOpen ? 'CLOSE' : 'MENU'}</span>
          </button>
        </div>

        <nav
          id="student-nav-menu"
          className={`student-nav ${mobileMenuOpen ? 'is-open' : ''}`}
          aria-label="Student Navigation"
        >
          <button className={`nav-link ${path === '/dashboard' ? 'active' : ''}`} onClick={() => navigate('/dashboard')}>
            Dashboard
          </button>
          <button className={`nav-link ${path === '/vote' ? 'active' : ''}`} onClick={() => navigate('/vote')}>
            Vote
          </button>
          <button className={`nav-link ${path === '/my-vote' ? 'active' : ''}`} onClick={() => navigate('/my-vote')}>
            My Vote
          </button>
          <button className={`nav-link ${path === '/profile' ? 'active' : ''}`} onClick={() => navigate('/profile')}>
            Profile & Security
          </button>
        </nav>

        <div className={`student-actions ${mobileMenuOpen ? 'is-open' : ''}`}>
          <button className="btn btn-logout" onClick={handleLogout}>
            Sign Out
          </button>
        </div>
      </header>

      {/* Main Student Workspace */}
      <main className="student-main-content" id="student-main" role="main">
        {children}
      </main>

      {/* Minimal Footer */}
      <footer className="student-footer" role="contentinfo">
        <div className="student-footer-inner">
          <p>Protected by AI Liveness + Cryptographic Pseudonyms. Candidate choices remain strictly confidential and pseudonymized.</p>
          <button className="link-button" onClick={() => navigate('/verification')}>Verify System on Blockchain &rarr;</button>
        </div>
      </footer>
    </div>
  )
}
