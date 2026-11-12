import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const resultsPagePath = path.resolve(__dirname, '../src/pages/admin/AdminResultsPage.jsx')

test('AdminResultsPage does not hardcode election ID 1', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.doesNotMatch(code, /api\.get\(['"`]\/elections\/1\/results['"`]\)/, 'Must not hardcode /elections/1/results')
})

test('AdminResultsPage loads elections list for dropdown', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.match(code, /\/admin\/elections/, 'Must fetch /admin/elections for selector')
  assert.match(code, /<select/, 'Must render a select element for elections')
  assert.match(code, /onChange=/, 'Must have onChange handler for election selection')
})

test('AdminResultsPage implements URL persistence for election selection', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.match(code, /election_id/, 'Must reference election_id URL parameter')
  assert.match(code, /URLSearchParams/, 'Must parse window.location.search URL query parameters')
  assert.match(code, /navigate\(`\/admin\/results\?election_id=/, 'Must persist selection via navigate to URL query parameter')
})

test('AdminResultsPage includes a manual Refresh Results button without auto-polling', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.match(code, /Refresh Results/, 'Must render a Refresh Results button')
  assert.doesNotMatch(code, /setInterval/, 'Must not use setInterval auto-polling')
})

test('AdminResultsPage handles all five display conditions', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')

  // 1. In-flight pending ballots
  assert.match(code, /PROCESSING_PENDING_BALLOTS/, 'Must handle PROCESSING_PENDING_BALLOTS state')
  assert.match(code, /pending_ballots_count/, 'Must show pending ballots count')

  // 2. Results under review
  assert.match(code, /RESULTS_UNDER_REVIEW/, 'Must handle RESULTS_UNDER_REVIEW state')
  assert.match(code, /open_reconciliation_issues/, 'Must show open reconciliation issues')

  // 3. Provisional unfinalized
  assert.match(code, /PROVISIONAL_UNFINALIZED/, 'Must handle PROVISIONAL_UNFINALIZED state')

  // 4. Finalized results
  assert.match(code, /FINALIZED_RESULTS/, 'Must handle FINALIZED_RESULTS state')

  // 5. Results withheld (OPEN / SCHEDULED / DRAFT)
  assert.match(code, /RESULTS_UNAVAILABLE/, 'Must handle RESULTS_UNAVAILABLE state')
  assert.match(code, /RESULTS WITHHELD/, 'Must present a friendly withheld notice')
})

test('AdminResultsPage preserves ballot privacy and displays only aggregate tallies', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.match(code, /total_distinct_voters/, 'Must display aggregate distinct voters')
  assert.match(code, /turnout_percentage/, 'Must display turnout percentage')
  assert.match(code, /total_valid_votes/, 'Must display valid votes')
  assert.doesNotMatch(code, /candidate_choice/, 'Must never expose individual candidate choices')
})

test('AdminResultsPage protects against stale asynchronous response overwrites via activeRequestIdRef', () => {
  const code = fs.readFileSync(resultsPagePath, 'utf8')
  assert.match(code, /activeRequestIdRef\s*=\s*useRef\(0\)/, 'Must initialize activeRequestIdRef')
  assert.match(code, /\+\+activeRequestIdRef\.current/, 'Must increment activeRequestIdRef on every new request')
  assert.match(code, /if\s*\(\s*activeRequestIdRef\.current\s*!==\s*requestId\s*\)\s*return/, 'Must drop stale responses and errors')
  assert.match(code, /if\s*\(\s*activeRequestIdRef\.current\s*===\s*requestId\s*\)\s*\{\s*setResultsLoading\(false\)/, 'Must only clear loading state if request is still active')
})

test('Simulated race condition test: out-of-order responses do not overwrite current election', async () => {
  // Pure logic simulation of the fetchResults activeRequestIdRef closure contract
  const state = {
    selectedElectionId: 'ELEC_A',
    results: null,
    resultsLoading: false,
  }
  const activeRequestIdRef = { current: 0 }

  const simulateFetchResults = async (eid, delayMs, payload) => {
    const requestId = ++activeRequestIdRef.current
    state.resultsLoading = true
    state.selectedElectionId = eid

    await new Promise((resolve) => setTimeout(resolve, delayMs))

    // The exact check implemented in AdminResultsPage.jsx
    if (activeRequestIdRef.current !== requestId) {
      return // Stale request dropped!
    }

    state.results = payload
    if (activeRequestIdRef.current === requestId) {
      state.resultsLoading = false
    }
  }

  // 1. User selects Election A (slow API response, 60ms)
  const reqA = simulateFetchResults('ELEC_A', 60, { election_id: 'ELEC_A', title: 'Slow Election A' })

  // 2. 10ms later, user rapidly switches to Election B (fast API response, 15ms)
  await new Promise((resolve) => setTimeout(resolve, 10))
  const reqB = simulateFetchResults('ELEC_B', 15, { election_id: 'ELEC_B', title: 'Fast Election B' })

  // Wait for both to complete
  await Promise.all([reqA, reqB])

  // Assertions:
  // - Election B resolved first (at t=25ms) and set state.results to Election B.
  // - Election A finished later (at t=60ms) but was rejected by the activeRequestIdRef check.
  // - Current results MUST be Election B, not Election A.
  assert.equal(state.selectedElectionId, 'ELEC_B')
  assert.equal(state.results?.election_id, 'ELEC_B')
  assert.equal(state.results?.title, 'Fast Election B')
  assert.equal(state.resultsLoading, false)
})


