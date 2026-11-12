import React, { useState } from 'react'

/**
 * Interactive 3D Flip Card for Candidate Showcase
 *
 * Requirements:
 * - Display candidate photo, name, position, and introduction on front.
 * - Clicking/tapping or keyboard (Enter/Space) flips card to show agenda/manifesto.
 * - Accessible way to flip back with full keyboard/mobile support.
 * - NEVER preselects candidate or initiates ballot casting.
 */
export function normalizeCandidatePhoto(url) {
  if (!url) return null
  let cleaned = String(url).trim().replace(/^["']|["']$/g, '')
  cleaned = cleaned.replace(/\\/g, '/')
  if (cleaned.includes('/api/public/candidate-photo/')) {
    cleaned = '/api/public/candidate-photo/' + cleaned.split('/api/public/candidate-photo/').pop()
  } else if (cleaned.includes('api/public/candidate-photo/')) {
    cleaned = '/api/public/candidate-photo/' + cleaned.split('api/public/candidate-photo/').pop()
  } else if (cleaned.includes('/images/candidates/')) {
    cleaned = '/images/candidates/' + cleaned.split('/images/candidates/').pop()
  } else if (cleaned.includes('images/candidates/')) {
    cleaned = '/images/candidates/' + cleaned.split('images/candidates/').pop()
  } else if (/\.(jpg|jpeg|png|webp|svg)$/i.test(cleaned) && !cleaned.startsWith('/') && !cleaned.startsWith('http')) {
    cleaned = `/images/candidates/${cleaned}`
  }
  return cleaned
}

export default function CandidateCard({ candidate }) {
  const [isFlipped, setIsFlipped] = useState(false)
  const [imgError, setImgError] = useState(false)

  if (!candidate) return null

  const candidateIdx = candidate.index !== undefined ? candidate.index : (candidate.candidate_index ?? 0)
  const displayName = candidate.name || `Candidate #${candidateIdx + 1}`
  const displayPosition = candidate.position || candidate.department || 'Council Representative'
  const displayDept = candidate.department && candidate.department !== displayPosition ? candidate.department : null
  const displayYear = candidate.year || null
  const displayIntro = candidate.slogan || 'Committed to transparent collegiate leadership and authentic student representation.'
  const displayManifesto = candidate.manifesto || 'Official platform registered with the collegiate electoral board. Dedicated to advocacy, academic flexibility, student welfare, and campus community development.'
  const rawPhoto = candidate.photo_url || candidate.photo_path || null
  const photoUrl = normalizeCandidatePhoto(rawPhoto)

  const getInitials = (name) => {
    if (!name) return 'C'
    const parts = name.trim().split(/\s+/)
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }

  const handleToggleFlip = (e) => {
    // Only flip if not clicking another interactive link
    if (e.target.tagName === 'A') return
    setIsFlipped((prev) => !prev)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      // Toggle flip on Enter or Space when card container is focused
      if (e.target === e.currentTarget) {
        e.preventDefault()
        setIsFlipped((prev) => !prev)
      }
    }
  }

  return (
    <div
      className={`candidate-flip-card ${isFlipped ? 'flipped' : ''}`}
      id={`candidate-card-${candidateIdx}`}
      tabIndex={0}
      role="region"
      aria-label={`Candidate ${displayName}, running for ${displayPosition}. ${isFlipped ? 'Showing manifesto. Press Enter to flip to profile.' : 'Press Enter or click View Manifesto to read campaign platform.'}`}
      onKeyDown={handleKeyDown}
    >
      <div className="candidate-flip-inner">
        {/* FRONT FACE: Photo, Name, Position, Intro */}
        <div className="candidate-card-face candidate-card-front card">
          <div>
            <div className="candidate-card-header-row">
              <span className="badge badge-violet">
                BALLOT POSITION #{candidateIdx + 1}
              </span>
              {displayYear && (
                <span className="badge badge-accent">
                  {displayYear}
                </span>
              )}
            </div>

            {/* Candidate Photo Frame */}
            <div className="candidate-photo-frame" aria-label={`Photo of ${displayName}`}>
              {photoUrl && !imgError ? (
                <img
                  src={photoUrl}
                  alt={`Candidate ${displayName}`}
                  className="candidate-photo-img"
                  onError={() => setImgError(true)}
                />
              ) : (
                <div className="candidate-avatar-initials" aria-hidden="true">
                  {getInitials(displayName)}
                </div>
              )}
            </div>

            {/* Identification Details */}
            <h3 className="candidate-box-name">{displayName}</h3>
            <p className="candidate-box-position">
              <strong>{displayPosition}</strong>
            </p>
            {displayDept && (
              <p className="candidate-box-dept">
                {displayDept}
              </p>
            )}

            {/* Short Introduction / Slogan */}
            <div className="candidate-box-slogan" title="Candidate Campaign Slogan">
              "{displayIntro}"
            </div>
          </div>

          {/* Accessible Action Footer */}
          <div className="candidate-card-actions">
            <button
              type="button"
              className="btn btn-secondary candidate-flip-btn"
              onClick={handleToggleFlip}
              aria-expanded={isFlipped}
              aria-label={`View manifesto and campaign agenda for ${displayName}`}
            >
              View Manifesto & Agenda ↻
            </button>
          </div>
        </div>

        {/* BACK FACE: Campaign Agenda & Manifesto */}
        <div className="candidate-card-face candidate-card-back card">
          <div className="candidate-back-scroll-area">
            <div className="candidate-card-header-row">
              <span className="badge badge-accent">
                CAMPAIGN MANIFESTO
              </span>
              <span className="badge badge-violet">
                #{candidateIdx + 1}
              </span>
            </div>

            <h4 className="candidate-back-name">{displayName}</h4>
            <p className="candidate-back-sub">
              Platform Agenda — Seeking <strong>{displayPosition}</strong>
            </p>

            <div className="candidate-manifesto-body">
              <div className="manifesto-quote-pill">KEY OBJECTIVES & PLEDGES</div>
              <p className="manifesto-text">
                {displayManifesto}
              </p>
            </div>
          </div>

          {/* Flip Back Action Footer */}
          <div className="candidate-card-actions">
            <button
              type="button"
              className="btn btn-primary candidate-flip-btn"
              onClick={handleToggleFlip}
              aria-expanded={isFlipped}
              aria-label={`Flip back to profile overview for ${displayName}`}
            >
              &larr; Back to Profile ↺
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
