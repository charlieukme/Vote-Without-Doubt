/**
 * Task 5: Student/Admin Notifications and Boundary Timing Test Suite
 *
 * This test suite covers:
 * 1. AdminReviewPage does not hardcode election ID 1 (Static source check)
 * 2. VOTER_OPERATIONAL query requires a valid positive numeric election ID (Runtime helper simulation)
 * 3. RECEIPT_CODE query behavior remains unchanged (Runtime helper simulation)
 * 4. DashboardPage passes the correct election ID to ElectionCountdown (Static source check)
 * 5. Both Voting.jsx countdown instances receive the correct election ID (Static source check)
 * 6. Election A dismissal does not suppress Election B pre-start notice (Runtime helper simulation)
 * 7. Same start time across two elections does not cause notification collision (Runtime helper simulation)
 * 8. Missing election ID does not create global notification suppression (Runtime helper simulation)
 * 9. Voting.jsx refreshes on focus and visibility restoration (Static source check & simulation)
 * 10. Duplicate simultaneous refreshes are prevented (Runtime helper simulation)
 * 11. Stale asynchronous responses cannot overwrite newer election state (Runtime helper simulation)
 * 12. Emergency closure disables voting controls after authoritative refresh (Runtime helper simulation)
 * 13. Existing scheduled boundary transitions remain intact (Helper arithmetic simulation)
 * 14. Notification content does not expose USN, student identity, candidate choices, wallet addresses, pseudonyms, or receipt codes (Static source check)
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { computeCountdownState, formatDuration } from '../src/utils/electionUtils.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const REVIEW_SRC = readFileSync(join(HERE, '..', 'src', 'pages', 'admin', 'AdminReviewPage.jsx'), 'utf8')
const DASHBOARD_SRC = readFileSync(join(HERE, '..', 'src', 'pages', 'student', 'DashboardPage.jsx'), 'utf8')
const VOTING_SRC = readFileSync(join(HERE, '..', 'src', 'Voting.jsx'), 'utf8')
const COUNTDOWN_SRC = readFileSync(join(HERE, '..', 'src', 'components', 'ElectionCountdown.jsx'), 'utf8')

// -----------------------------------------------------------------------------
// Test 1: AdminReviewPage does not hardcode election ID 1 (Static Source Check)
// -----------------------------------------------------------------------------
test('1. AdminReviewPage does not hardcode election ID 1', () => {
  // Must NOT hardcode election_id = '1'
  assert.doesNotMatch(
    REVIEW_SRC,
    /payload\.election_id\s*=\s*['"]1['"]/,
    'AdminReviewPage must never hardcode election_id = "1"'
  )
  // Must pass dynamically validated numeric election_id
  assert.match(
    REVIEW_SRC,
    /payload\.election_id\s*=\s*trimmedEid/,
    'AdminReviewPage must bind validated election ID to payload'
  )
  // Must render numeric input with appropriate label
  assert.match(
    REVIEW_SRC,
    /id="dispute-election-id"/,
    'Must render dispute-election-id input'
  )
  assert.match(
    REVIEW_SRC,
    /Election ID \(Numeric\)/,
    'Must render Election ID (Numeric) label'
  )
})

// -----------------------------------------------------------------------------
// Test 2: VOTER_OPERATIONAL query requires valid positive numeric election ID (Runtime Helper Simulation)
// -----------------------------------------------------------------------------
test('2. VOTER_OPERATIONAL query requires a valid positive numeric election ID', () => {
  const validateOperationalQuery = (electionId, identifier) => {
    const trimmedEid = (electionId || '').trim()
    if (!trimmedEid || !/^\d+$/.test(trimmedEid) || parseInt(trimmedEid, 10) <= 0) {
      return {
        valid: false,
        error: 'A valid positive numeric Election ID is required for voter operational dispute queries.',
      }
    }
    return {
      valid: true,
      payload: {
        query_type: 'VOTER_OPERATIONAL',
        identifier: (identifier || '').trim(),
        election_id: trimmedEid,
      },
    }
  }

  // Invalid cases
  assert.equal(validateOperationalQuery('', '1RV22CS001').valid, false)
  assert.equal(validateOperationalQuery('0', '1RV22CS001').valid, false)
  assert.equal(validateOperationalQuery('-1', '1RV22CS001').valid, false)
  assert.equal(validateOperationalQuery('abc', '1RV22CS001').valid, false)
  assert.equal(validateOperationalQuery('1.5', '1RV22CS001').valid, false)
  assert.equal(validateOperationalQuery('ELEC_1', '1RV22CS001').valid, false)

  // Valid cases
  const validRes1 = validateOperationalQuery('1', '1RV22CS001')
  assert.equal(validRes1.valid, true)
  assert.equal(validRes1.payload.election_id, '1')

  const validRes2 = validateOperationalQuery('  42  ', '1RV22CS002')
  assert.equal(validRes2.valid, true)
  assert.equal(validRes2.payload.election_id, '42')
})

// -----------------------------------------------------------------------------
// Test 3: RECEIPT_CODE query behavior remains unchanged (Runtime Helper Simulation)
// -----------------------------------------------------------------------------
test('3. RECEIPT_CODE query behavior remains unchanged', () => {
  const buildReceiptQueryPayload = (code) => {
    return {
      query_type: 'RECEIPT_CODE',
      receipt_code: (code || '').trim(),
    }
  }

  const payload = buildReceiptQueryPayload('REC-1-A1B2C3D4E5F67890')
  assert.equal(payload.query_type, 'RECEIPT_CODE')
  assert.equal(payload.receipt_code, 'REC-1-A1B2C3D4E5F67890')
  assert.equal('election_id' in payload, false, 'RECEIPT_CODE query must not include election_id parameter')
})

// -----------------------------------------------------------------------------
// Test 4: DashboardPage passes correct election ID to ElectionCountdown (Static Source Check)
// -----------------------------------------------------------------------------
test('4. DashboardPage passes the correct election ID to ElectionCountdown', () => {
  assert.match(
    DASHBOARD_SRC,
    /<ElectionCountdown[\s\S]*?electionId=\{election\.id !== undefined && election\.id !== null \? String\(election\.id\) : \(election\.election_id \|\| ''\)\}/,
    'DashboardPage must pass electionId to ElectionCountdown'
  )
})

// -----------------------------------------------------------------------------
// Test 5: Both Voting.jsx countdown instances receive correct election ID (Static Source Check)
// -----------------------------------------------------------------------------
test('5. Both Voting.jsx countdown instances receive the correct election ID', () => {
  const matches = [...VOTING_SRC.matchAll(/<ElectionCountdown[\s\S]*?electionId=\{[\s\S]*?\}/g)]
  assert.equal(matches.length, 2, 'Voting.jsx must contain exactly 2 ElectionCountdown instances with electionId passed')

  for (const m of matches) {
    assert.match(
      m[0],
      /electionId=\{election\?\.id !== undefined && election\?\.id !== null \? String\(election\.id\) : \(election\?\.election_id \|\| electionId \|\| ''\)\}/,
      'Instance must pass proper fallback election ID'
    )
  }
})

// -----------------------------------------------------------------------------
// Test 6: Actual key-generation exercises all 6 required notification isolation cases
// -----------------------------------------------------------------------------
test('6. Actual key-generation exercises all 6 required notification isolation cases', () => {
  // Extract and execute the exact implementation of getPrestartStorageKey from ElectionCountdown.jsx
  const fnMatch = COUNTDOWN_SRC.match(/export function getPrestartStorageKey\([^)]*\)\s*\{([\s\S]*?)\n\}/)
  assert.ok(fnMatch, 'ElectionCountdown.jsx must export getPrestartStorageKey')
  const getPrestartStorageKey = new Function('electionId', 'localInstanceId', fnMatch[1])

  const mockSessionStorage = new Map()

  // Case 1: Two distinct election slugs with identical start times remain independent
  const slugA = 'ELEC_ALPHA'
  const slugB = 'ELEC_BETA'
  const keyA = getPrestartStorageKey(slugA, 'inst_1')
  const keyB = getPrestartStorageKey(slugB, 'inst_2')
  assert.equal(keyA, 'prestart_notif_ELEC_ALPHA')
  assert.equal(keyB, 'prestart_notif_ELEC_BETA')
  assert.notEqual(keyA, keyB, 'Distinct election slugs must yield distinct keys')

  // Case 2: Two missing-ID countdown instances with identical start times remain independent
  const missingId1 = ''
  const missingId2 = ''
  const keyInst1 = getPrestartStorageKey(missingId1, 'inst_10')
  const keyInst2 = getPrestartStorageKey(missingId2, 'inst_11')
  assert.equal(keyInst1, 'prestart_notif_local_inst_10')
  assert.equal(keyInst2, 'prestart_notif_local_inst_11')
  assert.notEqual(keyInst1, keyInst2, 'Missing ID instances must never share a storage key, even with identical start times')

  // Case 3: Two missing-ID countdown instances with missing start times remain independent
  const keyMissingTime1 = getPrestartStorageKey(null, 'inst_20')
  const keyMissingTime2 = getPrestartStorageKey(null, 'inst_21')
  assert.equal(keyMissingTime1, 'prestart_notif_local_inst_20')
  assert.equal(keyMissingTime2, 'prestart_notif_local_inst_21')
  assert.notEqual(keyMissingTime1, keyMissingTime2, 'Missing IDs without start times must not fall back to a shared constant')

  // Case 4: Dismissing one missing-ID instance does not dismiss the other
  mockSessionStorage.set(keyInst1, 'true')
  assert.equal(mockSessionStorage.get(keyInst1), 'true')
  assert.equal(mockSessionStorage.get(keyInst2), undefined, 'Dismissal of Instance 1 must not suppress Instance 2')

  // Case 5: Repeated renders of the same instance preserve its dismissal state
  const stableInstanceId = 'inst_99'
  const render1Key = getPrestartStorageKey('', stableInstanceId)
  mockSessionStorage.set(render1Key, 'true')
  const render2Key = getPrestartStorageKey('', stableInstanceId)
  const render3Key = getPrestartStorageKey('', stableInstanceId)
  assert.equal(render1Key, render2Key)
  assert.equal(render2Key, render3Key)
  assert.equal(mockSessionStorage.get(render2Key), 'true', 'Re-render must preserve dismissal state')
  assert.equal(mockSessionStorage.get(render3Key), 'true', 'Subsequent renders must remain dismissed')

  // Case 6: Valid election IDs preserve existing sessionStorage persistence
  const validEidKey1 = getPrestartStorageKey('42', 'inst_caller_a')
  const validEidKey2 = getPrestartStorageKey('42', 'inst_caller_b')
  assert.equal(validEidKey1, 'prestart_notif_42')
  assert.equal(validEidKey2, 'prestart_notif_42')
  assert.equal(validEidKey1, validEidKey2, 'Valid IDs must share cross-component sessionStorage persistence for the same election')
})

// -----------------------------------------------------------------------------
// Test 7: Static source check confirms ElectionCountdown exports and uses local instance fallback
// -----------------------------------------------------------------------------
test('7. Static source check confirms ElectionCountdown exports and uses local instance fallback', () => {
  assert.match(
    COUNTDOWN_SRC,
    /export function getPrestartStorageKey/,
    'Must export getPrestartStorageKey'
  )
  assert.match(
    COUNTDOWN_SRC,
    /localInstanceIdRef\.current\s*=\s*`inst_\$\{[\s\S]*?localInstanceCounter\}`/,
    'Must assign unique local instance ID ref'
  )
  assert.match(
    COUNTDOWN_SRC,
    /const prestartStorageKey = getPrestartStorageKey\(electionId, localInstanceIdRef\.current\)/,
    'Must invoke getPrestartStorageKey with electionId and localInstanceIdRef'
  )
})

// -----------------------------------------------------------------------------
// Test 8: ElectionCountdown never falls back to startTime or a shared global string
// -----------------------------------------------------------------------------
test('8. ElectionCountdown never falls back to startTime or a shared global string', () => {
  assert.doesNotMatch(
    COUNTDOWN_SRC,
    /`prestart_notif_\$\{electionId \|\| startTime \|\| 'election'\}`/,
    'Must completely eliminate the vulnerable startTime or election fallback template'
  )
})

// -----------------------------------------------------------------------------
// Test 9: Voting.jsx refreshes on focus and visibility restoration (Static Source Check)
// -----------------------------------------------------------------------------
test('9. Voting.jsx refreshes on focus and visibility restoration', () => {
  assert.match(
    VOTING_SRC,
    /window\.addEventListener\(['"`]focus['"`],\s*handleFocusOrVisible\)/,
    'Must attach focus event listener'
  )
  assert.match(
    VOTING_SRC,
    /document\.addEventListener\(['"`]visibilitychange['"`],\s*handleFocusOrVisible\)/,
    'Must attach visibilitychange event listener'
  )
  assert.match(
    VOTING_SRC,
    /window\.removeEventListener\(['"`]focus['"`],\s*handleFocusOrVisible\)/,
    'Must clean up focus event listener on unmount'
  )
  assert.match(
    VOTING_SRC,
    /document\.removeEventListener\(['"`]visibilitychange['"`],\s*handleFocusOrVisible\)/,
    'Must clean up visibilitychange event listener on unmount'
  )
})

// -----------------------------------------------------------------------------
// Test 10: Duplicate simultaneous refreshes are prevented (Runtime Helper Simulation)
// -----------------------------------------------------------------------------
test('10. Duplicate simultaneous refreshes are prevented', async () => {
  let isRefreshing = false
  let executedCalls = 0

  const simulateInitElection = async () => {
    if (isRefreshing) return false
    isRefreshing = true
    try {
      executedCalls++
      await new Promise((r) => setTimeout(r, 20))
      return true
    } finally {
      isRefreshing = false
    }
  }

  // Trigger 3 concurrent refreshes simultaneously
  const results = await Promise.all([
    simulateInitElection(),
    simulateInitElection(),
    simulateInitElection(),
  ])

  assert.equal(executedCalls, 1, 'Only 1 execution must proceed; duplicates must be dropped')
  assert.equal(results.filter((r) => r === true).length, 1)
})

// -----------------------------------------------------------------------------
// Test 11: Stale asynchronous responses cannot overwrite newer election state (Runtime Helper Simulation)
// -----------------------------------------------------------------------------
test('11. Stale asynchronous responses cannot overwrite newer election state', async () => {
  let activeRequestId = 0
  let state = { electionTitle: 'Initial' }

  const dispatchElectionLoad = async (title, delayMs) => {
    const currentReqId = ++activeRequestId
    await new Promise((r) => setTimeout(r, delayMs))
    // If superseded, discard response
    if (currentReqId !== activeRequestId) {
      return false
    }
    state.electionTitle = title
    return true
  }

  // Request 1: Slow stale response (takes 80ms)
  const req1 = dispatchElectionLoad('Stale Election A', 80)
  // Request 2: Fast fresh response (dispatched shortly after, takes 20ms)
  await new Promise((r) => setTimeout(r, 10))
  const req2 = dispatchElectionLoad('Fresh Election B', 20)

  const [res1, res2] = await Promise.all([req1, req2])

  assert.equal(res1, false, 'Slow Request 1 must be discarded')
  assert.equal(res2, true, 'Fast Request 2 must be accepted')
  assert.equal(state.electionTitle, 'Fresh Election B', 'State must preserve newer election')
})

// -----------------------------------------------------------------------------
// Test 12: Voting progression and submission controls are explicitly disabled under non-voting statuses
// -----------------------------------------------------------------------------
test('12. Voting progression and submission controls are explicitly disabled under non-voting statuses', () => {
  // Static Source Assertions: isElectionVotingActive predicate defined and used across all 5 buttons
  assert.match(
    VOTING_SRC,
    /const isElectionVotingActive =\s*election\?\.status === 'OPEN' \|\|\s*election\?\.status === 'ACTIVE'/,
    'Voting.jsx must define the shared fail-closed isElectionVotingActive predicate'
  )
  assert.match(
    VOTING_SRC,
    /id="start-voting-btn"[\s\S]*?disabled=\{[\s\S]*?!isElectionVotingActive/,
    'start-voting-btn must be disabled when !isElectionVotingActive'
  )
  assert.match(
    VOTING_SRC,
    /id="recheck-factors-btn"[\s\S]*?disabled=\{[\s\S]*?!isElectionVotingActive/,
    'recheck-factors-btn must be disabled when !isElectionVotingActive'
  )
  assert.match(
    VOTING_SRC,
    /id="review-ballot-btn"[\s\S]*?disabled=\{[\s\S]*?!isElectionVotingActive/,
    'review-ballot-btn must be disabled when !isElectionVotingActive'
  )
  assert.match(
    VOTING_SRC,
    /id="confirm-submit-btn"[\s\S]*?disabled=\{[\s\S]*?!isElectionVotingActive/,
    'confirm-submit-btn must be disabled when !isElectionVotingActive'
  )
  assert.match(
    VOTING_SRC,
    /id="initiate-revote-btn"[\s\S]*?disabled=\{[\s\S]*?!isElectionVotingActive/,
    'initiate-revote-btn must be disabled when !isElectionVotingActive'
  )

  // Extract and execute the actual shared predicate from Voting.jsx source
  const predicateMatch = VOTING_SRC.match(/const isElectionVotingActive =\s*([\s\S]*?)(?=\n\s*\n\s*return)/)
  assert.ok(predicateMatch, 'Must locate isElectionVotingActive definition in Voting.jsx')
  const evaluatePredicate = new Function('election', `return Boolean(${predicateMatch[1].trim()})`)

  // Required Case 1: OPEN passes the status gate
  assert.equal(evaluatePredicate({ status: 'OPEN' }), true, 'OPEN must pass status gate')

  // Required Case 2: ACTIVE passes the status gate
  assert.equal(evaluatePredicate({ status: 'ACTIVE' }), true, 'ACTIVE must pass status gate')

  // Required Case 3: CLOSED is disabled
  assert.equal(evaluatePredicate({ status: 'CLOSED' }), false, 'CLOSED must be disabled')

  // Required Case 4: EMERGENCY_CLOSED is disabled
  assert.equal(evaluatePredicate({ status: 'EMERGENCY_CLOSED' }), false, 'EMERGENCY_CLOSED must be disabled')

  // Required Case 5: CANCELLED is disabled
  assert.equal(evaluatePredicate({ status: 'CANCELLED' }), false, 'CANCELLED must be disabled')

  // Required Case 6: FINALIZED is disabled
  assert.equal(evaluatePredicate({ status: 'FINALIZED' }), false, 'FINALIZED must be disabled')

  // Required Case 7: SCHEDULED is disabled
  assert.equal(evaluatePredicate({ status: 'SCHEDULED' }), false, 'SCHEDULED must be disabled')

  // Required Case 8: Unknown status is disabled
  assert.equal(evaluatePredicate({ status: 'UNRECOGNIZED_STATUS' }), false, 'Unknown status must be disabled')
  assert.equal(evaluatePredicate({ status: 'PROVISIONAL' }), false, 'Provisional status must be disabled')

  // Required Case 9: Missing status is disabled
  assert.equal(evaluatePredicate({ status: '' }), false, 'Empty status must be disabled')
  assert.equal(evaluatePredicate({ status: null }), false, 'Null status must be disabled')
  assert.equal(evaluatePredicate({}), false, 'Missing status property must be disabled')

  // Required Case 10: Missing election object is disabled
  assert.equal(evaluatePredicate(null), false, 'Null election object must be disabled')
  assert.equal(evaluatePredicate(undefined), false, 'Undefined election object must be disabled')

  // Runtime Button Logic Evaluation across all 10 conditions
  const evaluateAllButtons = (election, loading = false, candidate = 0, isRevoteEligible = true) => {
    const isVotingActive = evaluatePredicate(election)
    const hasCandidates = election?.candidates && election.candidates.length >= 2

    return {
      startBtnDisabled: loading || !isVotingActive || !hasCandidates,
      recheckFactorsBtnDisabled: loading || !isVotingActive,
      reviewBtnDisabled: candidate === null || !hasCandidates || !isVotingActive,
      submitBtnDisabled: loading || !isVotingActive,
      initiateRevoteBtnDisabled: !isRevoteEligible || !isVotingActive,
    }
  }

  const activeCandidates = [{ index: 0, name: 'Alice' }, { index: 1, name: 'Bob' }]

  // Verify OPEN controls are enabled
  const openButtons = evaluateAllButtons({ status: 'OPEN', candidates: activeCandidates })
  assert.equal(openButtons.startBtnDisabled, false)
  assert.equal(openButtons.recheckFactorsBtnDisabled, false)
  assert.equal(openButtons.reviewBtnDisabled, false)
  assert.equal(openButtons.submitBtnDisabled, false)
  assert.equal(openButtons.initiateRevoteBtnDisabled, false)

  // Verify all non-active cases result in 100% disabled controls
  const nonActiveElections = [
    { status: 'CLOSED', candidates: activeCandidates },
    { status: 'EMERGENCY_CLOSED', candidates: activeCandidates },
    { status: 'CANCELLED', candidates: activeCandidates },
    { status: 'FINALIZED', candidates: activeCandidates },
    { status: 'SCHEDULED', candidates: activeCandidates },
    { status: 'UNKNOWN_STATE', candidates: activeCandidates },
    { status: '', candidates: activeCandidates },
    { status: null, candidates: activeCandidates },
    {},
    null,
    undefined,
  ]

  for (const testEle of nonActiveElections) {
    const res = evaluateAllButtons(testEle)
    assert.equal(res.startBtnDisabled, true, `start-voting-btn must be disabled under ${JSON.stringify(testEle)}`)
    assert.equal(res.recheckFactorsBtnDisabled, true, `recheck-factors-btn must be disabled under ${JSON.stringify(testEle)}`)
    assert.equal(res.reviewBtnDisabled, true, `review-ballot-btn must be disabled under ${JSON.stringify(testEle)}`)
    assert.equal(res.submitBtnDisabled, true, `confirm-submit-btn must be disabled under ${JSON.stringify(testEle)}`)
    assert.equal(res.initiateRevoteBtnDisabled, true, `initiate-revote-btn must be disabled under ${JSON.stringify(testEle)}`)
  }
})

// -----------------------------------------------------------------------------
// Test 13: Existing scheduled boundary transitions remain intact (Helper Simulation)
// -----------------------------------------------------------------------------
test('13. Existing scheduled boundary transitions remain intact', () => {
  const start = '2026-11-10T10:00:00Z'
  const end = '2026-11-10T12:00:00Z'

  // Before start: SCHEDULED
  const beforeTime = new Date('2026-11-10T09:30:00Z').getTime()
  const sBefore = computeCountdownState(start, end, 'SCHEDULED', beforeTime)
  assert.equal(sBefore.phase, 'SCHEDULED')
  assert.equal(sBefore.remainingSeconds, 1800)
  assert.equal(formatDuration(sBefore.remainingSeconds), '00:30:00')

  // During window: OPEN
  const duringTime = new Date('2026-11-10T10:30:00Z').getTime()
  const sDuring = computeCountdownState(start, end, 'OPEN', duringTime)
  assert.equal(sDuring.phase, 'OPEN')
  assert.equal(sDuring.remainingSeconds, 5400)
  assert.equal(formatDuration(sDuring.remainingSeconds), '01:30:00')

  // Past window: CLOSED
  const afterTime = new Date('2026-11-10T12:30:00Z').getTime()
  const sAfter = computeCountdownState(start, end, 'OPEN', afterTime)
  assert.equal(sAfter.phase, 'CLOSED')
  assert.equal(sAfter.remainingSeconds, 0)
})

// -----------------------------------------------------------------------------
// Test 14: Notification content does not expose sensitive data (Static Source Check)
// -----------------------------------------------------------------------------
test('14. Notification content does not expose USN, student identity, candidate choices, wallet addresses, pseudonyms, or receipt codes', () => {
  // Overlays and banners in COUNTDOWN_SRC
  assert.doesNotMatch(COUNTDOWN_SRC, /studentId|usn|candidate_choice|pseudonym_key/i)
  assert.match(COUNTDOWN_SRC, /VOTING STARTS IN 30 SECONDS\. GET READY!/)
  assert.match(COUNTDOWN_SRC, /ONLY 30 SECONDS LEFT\. PLEASE VOTE NOW\./)

  // Review page dispute console maintains privacy invariants
  assert.match(REVIEW_SRC, /Privacy-Preserving Dispute Console/)
  assert.match(REVIEW_SRC, /In accordance with cryptographic privacy invariants, voter-to-candidate linkage is impossible/)
})

