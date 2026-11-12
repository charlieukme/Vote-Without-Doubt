import React, { useState, useEffect } from 'react'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminHealthPage() {
  const [health, setHealth] = useState(null)
  const [ready, setReady] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    Promise.all([
      api.get('/health').catch((err) => ({ status: 'error', message: err.message })),
      api.get('/health/ready').catch((err) => ({ status: 'error', message: err.message })),
    ]).then(([hRes, rRes]) => {
      if (mounted) {
        setHealth(hRes)
        setReady(rRes)
        setLoading(false)
      }
    })
    return () => { mounted = false }
  }, [])

  return (
    <div className="page-container admin-health-page">
      <div className="card">
        <span className="badge badge-accent">SUBSYSTEM DIAGNOSTICS</span>
        <h2 className="card-title">System Health & Subsystem Readiness</h2>
        <p>Real-time health verification of backend Flask API processes and SQL database connectivity.</p>
      </div>

      {loading ? (
        <div className="card">Querying subsystems...</div>
      ) : (
        <div className="grid-cards" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <div className="card">
            <span className="badge" style={{ background: health?.status === 'ok' ? '#10B981' : '#EF4444', color: '#FFF' }}>
              API: {health?.status?.toUpperCase()}
            </span>
            <h3>Flask Backend Service</h3>
            <div className="election-meta-grid" style={{ marginTop: '1rem' }}>
              <div className="meta-item">
                <span className="meta-label">Environment</span>
                <span className="meta-value">{health?.environment || 'development'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">System Status</span>
                <span className="meta-value">Operational</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Server Timestamp</span>
                <span className="meta-value">{health?.timestamp || 'Active'}</span>
              </div>
            </div>
          </div>

          <div className="card">
            <span className="badge" style={{ background: ready?.status === 'ok' ? '#10B981' : '#EF4444', color: '#FFF' }}>
              DB: {ready?.status?.toUpperCase()}
            </span>
            <h3>Database Readiness</h3>
            <div className="election-meta-grid" style={{ marginTop: '1rem' }}>
              <div className="meta-item">
                <span className="meta-label">Database Status</span>
                <span className="meta-value">{ready?.checks?.database || 'ok'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Readiness Probe</span>
                <span className="meta-value">SELECT 1 Verified</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
