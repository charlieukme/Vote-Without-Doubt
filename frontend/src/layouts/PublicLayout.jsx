import React, { useState, useEffect } from 'react'
import { useRouter } from '../router/RouterContext'
import { useAuth } from '../router/AuthContext'
import { api } from '../api/client'
import './PublicLayout.css'

export default function PublicLayout({ children }) {
  const { path, navigate } = useRouter()
  const { studentAuth } = useAuth()
  const [healthStatus, setHealthStatus] = useState({ status: 'checking' })
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
    let mounted = true
    api.get('/health')
      .then((data) => {
        if (mounted) setHealthStatus(data || { status: 'ok' })
      })
      .catch(() => {
        if (mounted) setHealthStatus({ status: 'offline' })
      })
    return () => { mounted = false }
  }, [])

  return (
    <div className="layout-container public-layout">
      {/* Top Banner with System Health */}
      <div className="system-top-banner">
        <div className="banner-inner">
          <span className="system-title">ACADEMIC E-VOTING SYSTEM</span>
          <span className="system-health-pill">
            <span className={`status-dot ${healthStatus.status === 'ok' ? 'dot-online' : 'dot-offline'}`} />
            System: {healthStatus.status === 'ok' ? 'Operational' : 'Offline / Degraded'}
          </span>
        </div>
      </div>

      {/* Main Public Header */}
      <header className="public-header" role="banner">
        <div className="header-top-row">
          <div className="header-brand" onClick={() => navigate('/')}>
            <span className="brand-badge">PROVABLE INTEGRITY</span>
            <h1 className="brand-title">Vote Without Doubt</h1>
            <p className="brand-subtitle">AI & Blockchain-Based Secure College E-Voting</p>
          </div>

          <button
            type="button"
            className="mobile-nav-toggle btn"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileMenuOpen}
            aria-controls="public-nav-menu"
            onClick={() => setMobileMenuOpen(prev => !prev)}
          >
            <span className="mobile-toggle-icon" aria-hidden="true">{mobileMenuOpen ? '✕' : '☰'}</span>
            <span className="mobile-toggle-label">{mobileMenuOpen ? 'CLOSE' : 'MENU'}</span>
          </button>
        </div>

        <nav
          id="public-nav-menu"
          className={`public-nav ${mobileMenuOpen ? 'is-open' : ''}`}
          aria-label="Main Navigation"
        >
          <button className={`nav-link ${path === '/' ? 'active' : ''}`} onClick={() => navigate('/')}>
            Home
          </button>
          <button className={`nav-link ${path.startsWith('/election') ? 'active' : ''}`} onClick={() => navigate('/election')}>
            Election Info
          </button>
          <button className={`nav-link ${path.startsWith('/candidates') ? 'active' : ''}`} onClick={() => navigate('/candidates')}>
            Candidates
          </button>
          <button className={`nav-link ${path === '/verification' ? 'active' : ''}`} onClick={() => navigate('/verification')}>
            Public Verification
          </button>
          <button className={`nav-link ${path === '/how-vote-protected' ? 'active' : ''}`} onClick={() => navigate('/how-vote-protected')}>
            Security
          </button>
          <button className={`nav-link ${path === '/help' ? 'active' : ''}`} onClick={() => navigate('/help')}>
            Help
          </button>
        </nav>

        <div className={`header-actions ${mobileMenuOpen ? 'is-open' : ''}`}>
          {studentAuth?.authenticated ? (
            <button className="btn btn-action" onClick={() => navigate('/dashboard')}>
              Go to Dashboard &rarr;
            </button>
          ) : (
            <>
              <button className="btn btn-secondary" onClick={() => navigate('/login')}>
                Sign In
              </button>
              <button className="btn btn-primary" onClick={() => navigate('/register')}>
                Register
              </button>
            </>
          )}
        </div>
      </header>

      {/* Main Page Content */}
      <main className="public-main-content" id="main-content" role="main">
        {children}
      </main>

      {/* Footer */}
      <footer className="public-footer" role="contentinfo">
        <div className="footer-columns">
          <div className="footer-col">
            <h4>Vote Without Doubt</h4>
            <p>Cryptographically verifiable academic voting system using AI biometric liveness and smart contracts.</p>
          </div>
          <div className="footer-col">
            <h4>Public Audit</h4>
            <ul>
              <li><button className="link-button" onClick={() => navigate('/verification')}>Cryptographic Verifier</button></li>
              <li><button className="link-button" onClick={() => navigate('/receipt-verification')}>Receipt Code Check</button></li>
              <li><button className="link-button" onClick={() => navigate('/how-vote-protected')}>Security Architecture</button></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Voter Support</h4>
            <ul>
              <li><button className="link-button" onClick={() => navigate('/help')}>FAQ & Guides</button></li>
              <li><button className="link-button" onClick={() => navigate('/report-problem')}>Report an Issue</button></li>
              <li><button className="link-button" onClick={() => navigate('/privacy')}>Privacy Policy</button></li>
              <li><button className="link-button" onClick={() => navigate('/terms')}>Terms & Bylaws</button></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Administrative</h4>
            <ul>
              <li><button className="link-button admin-link" onClick={() => navigate('/admin/login')}>Officer / Auditor Portal</button></li>
              <li><span className="version-tag">Vote Without Doubt v1.0</span></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <p>&copy; 2026 Vote Without Doubt. Built with provable zero-PII blockchain architecture.</p>
        </div>
      </footer>
    </div>
  )
}
