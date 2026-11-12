/**
 * Election selection and timing utilities.
 * 
 * Rules:
 * - Prefer OPEN/ACTIVE elections.
 * - If none is OPEN/ACTIVE, prefer SCHEDULED elections.
 * - Do not select a CLOSED election when a SCHEDULED/OPEN election exists.
 * - Timestamps are strictly parsed as UTC using standard ISO-8601 parsing.
 */

export function selectAuthoritativeElection(elections) {
  if (!Array.isArray(elections) || elections.length === 0) return null

  const nowMs = Date.now()
  const hasCandidates = (e) => e.candidate_count === undefined || e.candidate_count === null || Number(e.candidate_count) >= 2

  // 1. Prefer genuinely OPEN / ACTIVE election whose end_time has not passed and has candidates configured
  const openElection = elections.find((e) => {
    const s = (e.status || '').toUpperCase()
    if (s !== 'OPEN' && s !== 'ACTIVE') return false
    if (e.end_time && new Date(e.end_time).getTime() <= nowMs) return false
    return hasCandidates(e)
  })
  if (openElection) return openElection

  // 2. If none is OPEN/ACTIVE, prefer SCHEDULED election whose end_time has not passed and has candidates configured
  const scheduledElection = elections.find((e) => {
    const s = (e.status || '').toUpperCase()
    if (s !== 'SCHEDULED') return false
    if (e.end_time && new Date(e.end_time).getTime() <= nowMs) return false
    return hasCandidates(e)
  })
  if (scheduledElection) return scheduledElection

  // 3. Fallback: if all active/scheduled elections have < 2 candidates, return setup election so UI can display clear setup message
  const setupElection = elections.find((e) => {
    const s = (e.status || '').toUpperCase()
    if (s !== 'OPEN' && s !== 'ACTIVE' && s !== 'SCHEDULED') return false
    if (e.end_time && new Date(e.end_time).getTime() <= nowMs) return false
    return true
  })
  if (setupElection) return setupElection

  // 4. When no genuinely OPEN/ACTIVE or SCHEDULED election exists, return null
  // DRAFT, PENDING_APPROVAL, CLOSED, FINALIZED, CANCELLED elections must never be selected as current published election
  return null
}

export function getUpcomingElections(elections) {
  if (!Array.isArray(elections)) return []
  const nowMs = Date.now()
  return elections.filter((e) => {
    const s = (e.status || '').toUpperCase()
    return s === 'SCHEDULED' && (!e.end_time || new Date(e.end_time).getTime() > nowMs)
  })
}

export function getPastElections(elections) {
  if (!Array.isArray(elections)) return []
  const nowMs = Date.now()
  return elections.filter((e) => {
    const s = (e.status || '').toUpperCase()
    if (s === 'CLOSED' || s === 'FINALIZED' || s === 'CANCELLED' || s === 'EMERGENCY_CLOSED') return true
    if (e.end_time && new Date(e.end_time).getTime() <= nowMs) return true
    return false
  })
}

export function formatDuration(totalSeconds) {
  if (!totalSeconds || totalSeconds <= 0) return '00:00:00'
  const secs = Math.floor(totalSeconds % 60)
  const totalMins = Math.floor(totalSeconds / 60)
  const mins = Math.floor(totalMins % 60)
  const totalHours = Math.floor(totalMins / 60)
  const hours = totalHours % 24
  const days = Math.floor(totalHours / 24)

  const pad = (n) => String(n).padStart(2, '0')
  if (days > 0) {
    return `${days}d ${pad(hours)}:${pad(mins)}:${pad(secs)}`
  }
  return `${pad(hours)}:${pad(mins)}:${pad(secs)}`
}

export function computeCountdownState(startTime, endTime, status, currentTimestampMs = Date.now()) {
  const sUpper = (status || '').toUpperCase()
  if (sUpper === 'CLOSED' || sUpper === 'FINALIZED' || sUpper === 'CANCELLED' || sUpper === 'EMERGENCY_CLOSED') {
    return { phase: 'CLOSED', text: 'Voting Closed', remainingSeconds: 0 }
  }

  const startMs = startTime ? new Date(startTime).getTime() : null
  const endMs = endTime ? new Date(endTime).getTime() : null

  // 1. Before start window
  if (startMs && currentTimestampMs < startMs) {
    const remainingSeconds = Math.max(0, Math.floor((startMs - currentTimestampMs) / 1000))
    return {
      phase: 'SCHEDULED',
      text: `Voting starts in ${formatDuration(remainingSeconds)}`,
      remainingSeconds,
    }
  }

  // 2. Inside voting window
  if ((!startMs || currentTimestampMs >= startMs) && endMs && currentTimestampMs < endMs) {
    const remainingSeconds = Math.max(0, Math.floor((endMs - currentTimestampMs) / 1000))
    return {
      phase: 'OPEN',
      text: `Voting ends in ${formatDuration(remainingSeconds)}`,
      remainingSeconds,
    }
  }

  // 3. Past end window
  return { phase: 'CLOSED', text: 'Voting Closed', remainingSeconds: 0 }
}
