import React, { useState, useEffect, useRef } from 'react'
import { computeCountdownState, formatDuration } from '../utils/electionUtils'
import './ElectionCountdown.css'

/**
 * Reusable Election Countdown Component
 *
 * Rules:
 * - Uses only backend UTC timestamps (with explicit 'Z').
 * - Parses dates as UTC, does not hardcode local offsets.
 * - Updates every 1000ms.
 * - Before start: "ELECTION BEGINS IN HH:MM:SS"
 * - During election: "VOTING ENDS IN HH:MM:SS"
 * - After end: "ELECTION CLOSED"
 * - State C (30s pre-start): prominent notification "VOTING STARTS IN 30 SECONDS. GET READY!"
 * - State E (30s closing): prominent reminder "ONLY 30 SECONDS LEFT. PLEASE VOTE NOW."
 * - Calls onZero callback when countdown expires to re-fetch authoritative metadata.
 */
let localInstanceCounter = 0

/**
 * Generate a sessionStorage isolation key for the 30s pre-start alert.
 *
 * Invariants:
 * 1. When a valid non-empty electionId is supplied, returns `prestart_notif_${cleanId}`
 *    so notifications are persisted once-per-election across pages/renders.
 * 2. When no election identifier is available, NEVER uses startTime or a shared constant.
 *    Instead, returns `prestart_notif_local_${localInstanceId}` so separate countdown
 *    instances cannot suppress one another.
 */
export function getPrestartStorageKey(electionId, localInstanceId = null) {
  const cleanId = electionId !== undefined && electionId !== null ? String(electionId).trim() : ''
  if (cleanId) {
    return `prestart_notif_${cleanId}`
  }
  if (localInstanceId) {
    return `prestart_notif_local_${localInstanceId}`
  }
  return null
}

export default function ElectionCountdown({ electionId = '', startTime, endTime, status, onZero, className = '' }) {
  const [now, setNow] = useState(() => Date.now())
  const hasTriggeredZeroRef = useRef(false)
  const previousPhaseRef = useRef(null)
  const localInstanceIdRef = useRef(null)
  if (!localInstanceIdRef.current) {
    localInstanceIdRef.current = `inst_${++localInstanceCounter}`
  }

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now())
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const { phase, text, remainingSeconds } = computeCountdownState(startTime, endTime, status, now)

  const lastReportedPhaseRef = useRef(null)

  useEffect(() => {
    const sUpper = (status || '').toUpperCase()
    const phaseChanged = previousPhaseRef.current !== null && previousPhaseRef.current !== phase
    const isStatusMismatch =
      (phase === 'OPEN' && sUpper === 'SCHEDULED') ||
      (phase === 'CLOSED' && (sUpper === 'OPEN' || sUpper === 'ACTIVE'))

    if ((phaseChanged || isStatusMismatch) && lastReportedPhaseRef.current !== phase) {
      lastReportedPhaseRef.current = phase
      if (typeof onZero === 'function') {
        onZero(phase)
      }
    }
    previousPhaseRef.current = phase
  }, [phase, status, onZero])

  useEffect(() => {
    if (remainingSeconds === 0 && (phase === 'SCHEDULED' || phase === 'OPEN') && !hasTriggeredZeroRef.current) {
      hasTriggeredZeroRef.current = true
      if (typeof onZero === 'function') {
        onZero(phase)
      }
    } else if (remainingSeconds > 0) {
      hasTriggeredZeroRef.current = false
    }
  }, [remainingSeconds, phase, onZero])

  const badgeClass =
    phase === 'OPEN'
      ? 'countdown-badge-open'
      : phase === 'SCHEDULED'
      ? 'countdown-badge-scheduled'
      : 'countdown-badge-closed'

  const [dismissedClosingOverlay, setDismissedClosingOverlay] = useState(false)
  const [dismissedPrestartOverlay, setDismissedPrestartOverlay] = useState(false)

  // Session storage key for 30s pre-start alert (per election per session, or per instance fallback)
  const prestartStorageKey = getPrestartStorageKey(electionId, localInstanceIdRef.current)
  const hasSeenPrestartInSession = Boolean(
    prestartStorageKey &&
    typeof sessionStorage !== 'undefined' &&
    sessionStorage.getItem(prestartStorageKey) === 'true'
  )

  // State C: 30-second pre-start notification (appears once per election per browser session)
  const showPrestartNotification =
    !hasSeenPrestartInSession &&
    !dismissedPrestartOverlay &&
    phase === 'SCHEDULED' &&
    remainingSeconds > 0 &&
    remainingSeconds <= 30

  const handleDismissPrestart = () => {
    setDismissedPrestartOverlay(true)
    try {
      if (prestartStorageKey && typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem(prestartStorageKey, 'true')
      }
    } catch {
      // sessionStorage unavailable
    }
  }

  // Automatically mark prestart as recorded once phase reaches OPEN so it never pops up again
  useEffect(() => {
    if (phase === 'OPEN' && prestartStorageKey) {
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem(prestartStorageKey, 'true')
        }
      } catch {
        // ignore
      }
    }
  }, [phase, prestartStorageKey])

  // State E: 30-second dismissible overlay before election close
  const showClosingOverlay =
    !dismissedClosingOverlay &&
    phase === 'OPEN' &&
    remainingSeconds > 0 &&
    remainingSeconds <= 30

  const displayCountdownText =
    phase === 'SCHEDULED'
      ? `ELECTION BEGINS IN ${formatDuration(remainingSeconds)}`
      : phase === 'OPEN'
      ? `VOTING ENDS IN ${formatDuration(remainingSeconds)}`
      : 'ELECTION CLOSED'

  return (
    <>
      <div className={`election-countdown-container ${badgeClass} ${className}`} id="election-countdown">
        <span className="countdown-icon" aria-hidden="true">
          {phase === 'OPEN' ? '🟢' : phase === 'SCHEDULED' ? '⏳' : '🔒'}
        </span>
        <span className="countdown-text" id="countdown-timer-text" title={text}>
          {displayCountdownText}
        </span>
      </div>

      {/* State C: 30-second pre-start notification */}
      {showPrestartNotification && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Election Starting in 30 Seconds Alert"
          id="countdown-prestart-overlay"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.85)',
            zIndex: 99999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1.5rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '480px',
              width: '100%',
              background: 'var(--neo-cream, #FFFDF5)',
              border: '4px solid #000000',
              boxShadow: '8px 8px 0px #000000',
              padding: '2rem 1.5rem',
              textAlign: 'center',
            }}
          >
            <span className="badge badge-accent" style={{ fontSize: '0.85rem', marginBottom: '0.75rem' }}>
              ELECTION STARTING SOON
            </span>
            <h2 style={{ fontSize: '1.75rem', fontWeight: 900, textTransform: 'uppercase', margin: '0.5rem 0', color: '#1E3A8A' }}>
              VOTING STARTS IN 30 SECONDS. GET READY!
            </h2>
            <div
              id="prestart-seconds-count"
              style={{
                fontSize: '3.8rem',
                fontWeight: 900,
                fontFamily: 'monospace',
                color: '#2563EB',
                margin: '0.5rem 0 1rem 0',
                letterSpacing: '-0.03em',
              }}
            >
              {remainingSeconds}s
            </div>
            <p style={{ fontSize: '0.95rem', color: '#1F2937', fontWeight: 700, marginBottom: '1.5rem', lineHeight: 1.5 }}>
              The voting window is about to open. Eligible authenticated students can cast their ballots as soon as the countdown reaches zero.
            </p>
            <button
              id="dismiss-prestart-overlay-btn"
              className="btn btn-primary"
              onClick={handleDismissPrestart}
              style={{ width: '100%', minHeight: '44px', fontWeight: 900 }}
            >
              I Am Ready &rarr;
            </button>
          </div>
        </div>
      )}

      {/* State E: 30-second final reminder before close */}
      {showClosingOverlay && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Election Closing Soon Alert"
          id="countdown-closing-overlay"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.85)',
            zIndex: 99999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1.5rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '480px',
              width: '100%',
              background: 'var(--neo-cream, #FFFDF5)',
              border: '4px solid #000000',
              boxShadow: '8px 8px 0px #000000',
              padding: '2rem 1.5rem',
              textAlign: 'center',
            }}
          >
            <span className="badge badge-danger" style={{ fontSize: '0.85rem', marginBottom: '0.75rem' }}>
              URGENT ELECTION NOTICE
            </span>
            <h2 style={{ fontSize: '1.75rem', fontWeight: 900, textTransform: 'uppercase', margin: '0.5rem 0', color: '#B91C1C' }}>
              ONLY 30 SECONDS LEFT. PLEASE VOTE NOW.
            </h2>
            <div
              id="closing-seconds-count"
              style={{
                fontSize: '3.8rem',
                fontWeight: 900,
                fontFamily: 'monospace',
                color: '#DC2626',
                margin: '0.5rem 0 1rem 0',
                letterSpacing: '-0.03em',
              }}
            >
              {remainingSeconds}s
            </div>
            <p style={{ fontSize: '0.95rem', color: '#1F2937', fontWeight: 700, marginBottom: '1.5rem', lineHeight: 1.5 }}>
              The election window is closing. Finalize your ballot promptly. Submissions initiated after the deadline cannot be processed.
            </p>
            <button
              id="dismiss-closing-overlay-btn"
              className="btn btn-secondary"
              onClick={() => setDismissedClosingOverlay(true)}
              style={{ width: '100%', minHeight: '44px', fontWeight: 900 }}
            >
              Dismiss Warning & Continue Voting &rarr;
            </button>
          </div>
        </div>
      )}
    </>
  )
}
