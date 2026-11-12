import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { ApiError } from '../src/api/client.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')
const readSrc = (relPath) => readFileSync(join(SRC, relPath), 'utf8')

const CLIENT_SRC = readSrc('api/client.js')
const DASHBOARD_SRC = readSrc('pages/admin/AdminDashboardPage.jsx')
const ELECTIONS_SRC = readSrc('pages/admin/AdminElectionsPage.jsx')
const APPROVALS_SRC = readSrc('pages/admin/AdminApprovalsPage.jsx')

// ------------------------------------------------------------------ ApiError 429 tests
test('ApiError exposes isRateLimited getter when status is 429', () => {
  const err429 = new ApiError('Rate limit exceeded', { status: 429 })
  assert.equal(err429.isRateLimited, true)
  assert.equal(err429.status, 429)

  const err400 = new ApiError('Bad Request', { status: 400 })
  assert.equal(err400.isRateLimited, false)

  const err500 = new ApiError('Server Error', { status: 500 })
  assert.equal(err500.isRateLimited, false)

  assert.match(CLIENT_SRC, /get isRateLimited\(\)\s*\{\s*return this\.status === 429/)
})

// -------------------------------------------------------- AdminDashboardPage 429 tests
test('AdminDashboardPage explicitly detects 429 and displays rate limit notice', () => {
  // Checks explicit 429 check
  assert.match(DASHBOARD_SRC, /status === 429 \|\| err\?\.isRateLimited/)
  assert.match(DASHBOARD_SRC, /Rate limit exceeded\. Please retry later\./)
  assert.match(DASHBOARD_SRC, /setIsRateLimited\(true\)/)
})

test('AdminDashboardPage preserves loaded elections and approvals when refresh fails', () => {
  // When eleResult or appResult is rejected, state should NOT be set to []
  assert.doesNotMatch(DASHBOARD_SRC, /\.catch\(\(\)\s*=>\s*\(\{\s*elections:\s*\[\]\s*\}\)\)/)
  assert.doesNotMatch(DASHBOARD_SRC, /\.catch\(\(\)\s*=>\s*\(\{\s*approval_requests:\s*\[\]\s*\}\)\)/)
})

test('AdminDashboardPage does not show misleading "0" metrics when rate limited or failed', () => {
  // Uses null as initial state so unloaded is distinguished from 0
  assert.match(DASHBOARD_SRC, /useState\(null\)/)
  // Shows '—' with error message when failed instead of 0
  assert.match(DASHBOARD_SRC, /elections !== null \? elections\.length : '—'/)
  assert.match(DASHBOARD_SRC, /approvals !== null \? approvals\.length : '—'/)
  assert.match(DASHBOARD_SRC, /Rate limit exceeded/)
})

// -------------------------------------------------------- AdminElectionsPage 429 tests
test('AdminElectionsPage detects 429 and sets rate limit banner', () => {
  assert.match(ELECTIONS_SRC, /err\?\.status === 429 \|\| err\?\.isRateLimited/)
  assert.match(ELECTIONS_SRC, /setIsRateLimited\(true\)/)
  assert.match(ELECTIONS_SRC, /Rate limit exceeded\. Please retry later\./)
  assert.match(ELECTIONS_SRC, /alert-box.*isRateLimited \? 'alert-warning' : 'alert-error'/)
})

test('AdminElectionsPage does not replace elections with empty array or display "No elections found" on 429', () => {
  // Initial state is null rather than empty array
  assert.match(ELECTIONS_SRC, /const \[elections, setElections\] = useState\(null\)/)

  // In catch block, existing elections are preserved rather than setElections([])
  assert.doesNotMatch(ELECTIONS_SRC, /catch\s*\(err\)\s*\{\s*setElections\(\[\]\)/)

  // Rate limit condition prevents misleading "No elections found"
  assert.match(ELECTIONS_SRC, /isRateLimited \? \(/)
  assert.match(ELECTIONS_SRC, /Rate limit exceeded\. Please retry later\./)
})

test('AdminElectionsPage lifecycle action handlers handle 429 rate limits', () => {
  // handleCreate, handleRequestSchedule, handleOpen, handleClose should check 429
  const occurrences = (ELECTIONS_SRC.match(/err\?\.status === 429 \|\| err\?\.isRateLimited/g) || []).length
  assert.ok(occurrences >= 5, `Expected at least 5 rate limit checks in AdminElectionsPage, found ${occurrences}`)
})

// -------------------------------------------------------- AdminApprovalsPage 429 tests
test('AdminApprovalsPage detects 429 and sets rate limit banner', () => {
  assert.match(APPROVALS_SRC, /err\?\.status === 429 \|\| err\?\.isRateLimited/)
  assert.match(APPROVALS_SRC, /setIsRateLimited\(true\)/)
  assert.match(APPROVALS_SRC, /Rate limit exceeded\. Please retry later\./)
  assert.match(APPROVALS_SRC, /alert-box.*isRateLimited \? 'alert-warning' : 'alert-error'/)
})

test('AdminApprovalsPage does not replace approvals with empty array or display "No approval requests found" on 429', () => {
  // Initial state is null rather than empty array
  assert.match(APPROVALS_SRC, /const \[approvals, setApprovals\] = useState\(null\)/)

  // In catch block, existing approvals are preserved rather than setApprovals([])
  assert.doesNotMatch(APPROVALS_SRC, /catch\s*\(err\)\s*\{\s*setApprovals\(\[\]\)/)

  // Rate limit condition prevents misleading "No approval requests found in queue."
  assert.match(APPROVALS_SRC, /isRateLimited \? \(/)
  assert.match(APPROVALS_SRC, /Rate limit exceeded\. Please retry later\./)
})

test('AdminApprovalsPage handleApprove and handleReject handle 429 rate limits', () => {
  const occurrences = (APPROVALS_SRC.match(/err\?\.status === 429 \|\| err\?\.isRateLimited/g) || []).length
  assert.ok(occurrences >= 3, `Expected at least 3 rate limit checks in AdminApprovalsPage, found ${occurrences}`)
})
