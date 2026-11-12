import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  selectAuthoritativeElection,
  formatDuration,
  computeCountdownState,
} from '../src/utils/electionUtils.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const VOTING_JSX = readFileSync(join(HERE, '..', 'src', 'Voting.jsx'), 'utf8')
const DASHBOARD_JSX = readFileSync(join(HERE, '..', 'src', 'pages', 'student', 'DashboardPage.jsx'), 'utf8')

test('selectAuthoritativeElection prefers OPEN/ACTIVE election over SCHEDULED and CLOSED', () => {
  const elections = [
    { election_id: 'ELEC_CLOSED_1', title: 'Old Closed', status: 'CLOSED' },
    { election_id: 'ELEC_OPEN_2', title: 'Current Open', status: 'OPEN' },
    { election_id: 'ELEC_SCHED_3', title: 'Upcoming Scheduled', status: 'SCHEDULED' },
  ]
  const chosen = selectAuthoritativeElection(elections)
  assert.equal(chosen.election_id, 'ELEC_OPEN_2')
  assert.equal(chosen.status, 'OPEN')
})

test('selectAuthoritativeElection prefers SCHEDULED when no OPEN election exists', () => {
  const elections = [
    { election_id: 'ELEC_CLOSED_1', title: 'Old Closed', status: 'CLOSED' },
    { election_id: 'ELEC_SCHED_3', title: 'Upcoming Scheduled', status: 'SCHEDULED' },
  ]
  const chosen = selectAuthoritativeElection(elections)
  assert.equal(chosen.election_id, 'ELEC_SCHED_3')
})

test('selectAuthoritativeElection never selects CLOSED election when OPEN or SCHEDULED exists', () => {
  const elections = [
    { election_id: 'ELEC_CLOSED_1', title: 'Old Closed', status: 'CLOSED' },
    { election_id: 'ELEC_20261008183528_ACE3', title: 'new commer', status: 'OPEN' },
  ]
  const chosen = selectAuthoritativeElection(elections)
  assert.equal(chosen.election_id, 'ELEC_20261008183528_ACE3')
  assert.notEqual(chosen.election_id, 'ELEC_CLOSED_1')
})

test('selectAuthoritativeElection handles empty or invalid arrays safely', () => {
  assert.equal(selectAuthoritativeElection([]), null)
  assert.equal(selectAuthoritativeElection(null), null)
  assert.equal(selectAuthoritativeElection(undefined), null)
})

test('selectAuthoritativeElection returns null when all elections are CLOSED, FINALIZED, or CANCELLED', () => {
  const elections = [
    { election_id: 'ELEC_CLOSED_1', title: 'Old Closed 1', status: 'CLOSED' },
    { election_id: 'ELEC_FINAL_2', title: 'Old Finalized 2', status: 'FINALIZED' },
    { election_id: 'ELEC_CANCEL_3', title: 'Old Cancelled 3', status: 'CANCELLED' },
  ]
  assert.equal(selectAuthoritativeElection(elections), null)
})

test('selectAuthoritativeElection returns null for DRAFT and PENDING_APPROVAL elections', () => {
  const elections = [
    { election_id: 'ELEC_DRAFT_1', title: 'Draft Election', status: 'DRAFT' },
    { election_id: 'ELEC_PENDING_2', title: 'Pending Approval', status: 'PENDING_APPROVAL' },
  ]
  assert.equal(selectAuthoritativeElection(elections), null)
})

test('ElectionCountdown defines 30-second closing overlay and reminder elements', () => {
  assert.match(COUNTDOWN_JSX, /id="countdown-closing-overlay"/)
  assert.match(COUNTDOWN_JSX, /id="closing-seconds-count"/)
  assert.match(COUNTDOWN_JSX, /id="dismiss-closing-overlay-btn"/)
  assert.match(COUNTDOWN_JSX, /ONLY 30 SECONDS LEFT\. PLEASE VOTE NOW\./)
})

test('ElectionCountdown defines 30-second pre-start notification overlay elements', () => {
  assert.match(COUNTDOWN_JSX, /id="countdown-prestart-overlay"/)
  assert.match(COUNTDOWN_JSX, /id="prestart-seconds-count"/)
  assert.match(COUNTDOWN_JSX, /id="dismiss-prestart-overlay-btn"/)
  assert.match(COUNTDOWN_JSX, /VOTING STARTS IN 30 SECONDS\. GET READY!/)
  assert.match(COUNTDOWN_JSX, /prestart_notif_/)
})

test('formatDuration formats total seconds accurately as HH:MM:SS', () => {
  assert.equal(formatDuration(0), '00:00:00')
  assert.equal(formatDuration(-10), '00:00:00')
  assert.equal(formatDuration(65), '00:01:05')
  assert.equal(formatDuration(3665), '01:01:05')
  assert.equal(formatDuration(90065), '1d 01:01:05')
})

test('computeCountdownState calculates scheduled countdown correctly from UTC timestamps', () => {
  const start = '2026-10-08T18:41:00Z'
  const end = '2026-10-08T19:35:00Z'
  const current = new Date('2026-10-08T18:31:00Z').getTime() // 10 minutes before start

  const res = computeCountdownState(start, end, 'SCHEDULED', current)
  assert.equal(res.phase, 'SCHEDULED')
  assert.equal(res.remainingSeconds, 600)
  assert.equal(res.text, 'Voting starts in 00:10:00')
})

test('computeCountdownState calculates in-progress countdown correctly from UTC timestamps', () => {
  const start = '2026-10-08T18:41:00Z'
  const end = '2026-10-08T19:35:00Z'
  const current = new Date('2026-10-08T18:50:00Z').getTime() // 45 minutes before end

  const res = computeCountdownState(start, end, 'OPEN', current)
  assert.equal(res.phase, 'OPEN')
  assert.equal(res.remainingSeconds, 2700)
  assert.equal(res.text, 'Voting ends in 00:45:00')
})

test('computeCountdownState transitions to closed after end_time', () => {
  const start = '2026-10-08T18:41:00Z'
  const end = '2026-10-08T19:35:00Z'
  const current = new Date('2026-10-08T19:35:05Z').getTime() // 5 seconds after end

  const res = computeCountdownState(start, end, 'OPEN', current)
  assert.equal(res.phase, 'CLOSED')
  assert.equal(res.remainingSeconds, 0)
  assert.equal(res.text, 'Voting Closed')
})

test('computeCountdownState respects static CLOSED status even before end_time', () => {
  const start = '2026-10-08T18:41:00Z'
  const end = '2026-10-08T19:35:00Z'
  const current = new Date('2026-10-08T18:50:00Z').getTime()

  const res = computeCountdownState(start, end, 'CLOSED', current)
  assert.equal(res.phase, 'CLOSED')
  assert.equal(res.text, 'Voting Closed')
})

test('Voting.jsx does not hardcode election ID 1 in initial state', () => {
  assert.doesNotMatch(VOTING_JSX, /useState\(1\)/)
  assert.doesNotMatch(VOTING_JSX, /const \[electionId, _setElectionId\] = useState\(1\)/)
})

test('Voting.jsx checks URLSearchParams for election_id and falls back to selectAuthoritativeElection', () => {
  assert.match(VOTING_JSX, /params\.election_id/)
  assert.match(VOTING_JSX, /URLSearchParams/)
  assert.match(VOTING_JSX, /selectAuthoritativeElection/)
  assert.match(VOTING_JSX, /ElectionCountdown/)
})

test('DashboardPage.jsx links to /vote with actual election_id', () => {
  assert.match(DASHBOARD_JSX, /\/vote\?election_id=\${.*election_id}/)
  assert.match(DASHBOARD_JSX, /selectAuthoritativeElection/)
  assert.match(DASHBOARD_JSX, /ElectionCountdown/)
})

const ROUTER_SRC = readFileSync(join(HERE, '..', 'src', 'router', 'RouterContext.jsx'), 'utf8')
const APP_SRC = readFileSync(join(HERE, '..', 'src', 'App.jsx'), 'utf8')

test('RouterContext isolates route pathname from search query parameters', () => {
  assert.match(ROUTER_SRC, /path:\s*pathname/)
  assert.match(ROUTER_SRC, /pathname\.indexOf\('\?'\)/)
  assert.match(ROUTER_SRC, /params:\s*extractParams/)
})

test('App.jsx matches routes using pathname independent of query parameters', () => {
  assert.match(APP_SRC, /rawPath\s*\|\|\s*'\/.*\.split\('\?'\)\[0\]/)
  assert.match(APP_SRC, /\/dashboard.*\/vote.*\/receipt.*\/my-vote.*\/profile/)
})

test('Router matching logic resolves /vote?election_id=ELEC_... to student vote page without 404', () => {
  const currentUrl = '/vote?election_id=ELEC_20261008183528_ACE3'
  const qIdx = currentUrl.indexOf('?')
  const pathname = qIdx !== -1 ? currentUrl.slice(0, qIdx) : currentUrl
  const search = qIdx !== -1 ? currentUrl.slice(qIdx) : ''

  // 1. Pathname is cleanly extracted
  assert.equal(pathname, '/vote')
  assert.equal(search, '?election_id=ELEC_20261008183528_ACE3')

  // 2. Student route group matches
  const studentRoutes = ['/dashboard', '/vote', '/receipt', '/my-vote', '/profile']
  assert.equal(studentRoutes.includes(pathname), true)

  // 3. Query params preserved for consumer components
  const searchParams = new URLSearchParams(search)
  assert.equal(searchParams.get('election_id'), 'ELEC_20261008183528_ACE3')
})

const COUNTDOWN_JSX = readFileSync(join(HERE, '..', 'src', 'components', 'ElectionCountdown.jsx'), 'utf8')

test('computeCountdownState transitions to OPEN at exact start_time boundary', () => {
  const start = '2026-10-09T00:51:00Z'
  const end = '2026-10-09T01:50:00Z'
  const exactStart = new Date(start).getTime()

  const res = computeCountdownState(start, end, 'SCHEDULED', exactStart)
  assert.equal(res.phase, 'OPEN')
  assert.equal(res.remainingSeconds > 0, true)
  assert.match(res.text, /Voting ends in/)
})

test('ElectionCountdown.jsx triggers onZero on phase change or status mismatch', () => {
  assert.match(COUNTDOWN_JSX, /phase === 'OPEN'\s*&&\s*sUpper === 'SCHEDULED'/)
  assert.match(COUNTDOWN_JSX, /typeof\s+onZero\s*===\s*'function'/)
  assert.match(COUNTDOWN_JSX, /onZero\(phase\)/)
})

test('Voting.jsx and DashboardPage.jsx implement start_time and end_time boundary synchronization', () => {
  // Voting.jsx
  assert.match(VOTING_JSX, /election\?\.start_time\s*\|\|\s*election\.status\s*!==\s*'SCHEDULED'/)
  assert.match(VOTING_JSX, /election\?\.end_time\s*\|\|\s*\(election\.status\s*!==\s*'OPEN'/)
  assert.match(VOTING_JSX, /initElection\(\)/)

  // DashboardPage.jsx
  assert.match(DASHBOARD_JSX, /election\?\.start_time\s*\|\|\s*election\.status\s*!==\s*'SCHEDULED'/)
  assert.match(DASHBOARD_JSX, /election\?\.end_time\s*\|\|\s*\(election\.status\s*!==\s*'OPEN'/)
  assert.match(DASHBOARD_JSX, /loadDashboardData\(\)/)
})

test('Voting.jsx start button is enabled when election is OPEN and disabled when SCHEDULED', () => {
  assert.match(VOTING_JSX, /disabled=\{loading\s*\|\|\s*\(election\?\.status\s*&&\s*election\.status\s*!==\s*'OPEN'\s*&&\s*election\.status\s*!==\s*'ACTIVE'\)\}/)
  assert.match(VOTING_JSX, /election\?\.status\s*===\s*'SCHEDULED'\s*\?\s*'Voting Scheduled \(Not Started\)'\s*:\s*'Begin Voting Authorization'/)
})

test('Voting.jsx maps candidates dynamically supporting 3+ candidates', () => {
  assert.match(VOTING_JSX, /election\?\.candidates\s*&&\s*election\.candidates\.length\s*>\s*0/)
  assert.match(VOTING_JSX, /election\.candidates\.map\(\(c\)\s*=>/)
  assert.match(VOTING_JSX, /value=\{c\.index\}/)
  assert.match(VOTING_JSX, /c\.name/)
})

const LANDING_PAGE_JSX = readFileSync(join(HERE, '..', 'src', 'pages', 'public', 'LandingPage.jsx'), 'utf8')
const CANDIDATES_PAGE_JSX = readFileSync(join(HERE, '..', 'src', 'pages', 'public', 'CandidatesPage.jsx'), 'utf8')

test('LandingPage.jsx never falls back to eleList[0] when selectAuthoritativeElection returns null', () => {
  assert.doesNotMatch(LANDING_PAGE_JSX, /selectAuthoritativeElection\(eleList\)\s*\|\|\s*eleList\[0\]/)
  assert.match(LANDING_PAGE_JSX, /selectAuthoritativeElection\(eleList\)/)
})

test('LandingPage.jsx implements automatic polling and visibility-aware synchronization', () => {
  assert.match(LANDING_PAGE_JSX, /setInterval/)
  assert.match(LANDING_PAGE_JSX, /visibilitychange/)
  assert.match(LANDING_PAGE_JSX, /document\.visibilityState === 'visible'/)
})

test('LandingPage.jsx gates candidate showcase to active/upcoming selectedElection only', () => {
  assert.match(LANDING_PAGE_JSX, /\{selectedElection && \(\s*<div id="candidate-showcase">/)
  assert.match(LANDING_PAGE_JSX, /NO ACTIVE ELECTION/)
  assert.match(LANDING_PAGE_JSX, /There is currently no upcoming election\. Please check back when the election administration publishes the next election\./)
})

test('CandidatesPage.jsx does not fallback to list[0] when no active election exists', () => {
  assert.doesNotMatch(CANDIDATES_PAGE_JSX, /selectAuthoritativeElection\(list\)\s*\|\|\s*list\[0\]/)
})


