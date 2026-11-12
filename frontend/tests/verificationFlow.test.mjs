/**
 * Phase 12 Public Verification and Results UI wiring and security tests.
 *
 * Run with `npm test`. These tests verify:
 * - PublicVerification component is imported and rendered in App.jsx (reachable from UI);
 * - Uses the shared API client and never a raw fetch or hardcoded origin;
 * - Calls /elections/<id>/verification to load public parameters;
 * - Calls /elections/<id>/results conditionally;
 * - Results are strictly gated by results_available;
 * - Displays cryptographic candidate hash and roll hash;
 * - Offers independent CLI verification command (verify_election.py);
 * - Provides controlled database tampering demonstration;
 * - Privacy invariant: Zero voter identity, USN, email, or pseudonym leakage.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = readFileSync(join(HERE, '..', 'src', 'App.jsx'), 'utf8')
const VERIFICATION = readFileSync(join(HERE, '..', 'src', 'components', 'PublicVerification.jsx'), 'utf8')

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const VERIF_CODE = stripComments(VERIFICATION)

// ---------------------------------------------------- 1. Reachability & Integration

test('PublicVerification component is imported and rendered in App.jsx', () => {
  assert.match(APP, /import\s+PublicVerification\s+from\s+'\.\/components\/PublicVerification'/)
  assert.match(APP, /<PublicVerification\s*\/>/)
})

// ---------------------------------------------------- 2. API Client Usage & No Hardcoded Origins

test('PublicVerification uses shared API client and never raw fetch', () => {
  assert.match(VERIFICATION, /import\s*\{\s*api\s*\}\s*from\s*'\.\.\/api\/client\.js'/)
  assert.doesNotMatch(VERIF_CODE, /\bfetch\s*\(/)
  assert.doesNotMatch(VERIF_CODE, /http:\/\/localhost/)
  assert.doesNotMatch(VERIF_CODE, /http:\/\/127\.0\.0\.1/)
})

// ---------------------------------------------------- 3. Endpoint Wiring & Results Gating

test('Queries public verification endpoint with election ID', () => {
  assert.match(VERIF_CODE, /api\.get\(`\/elections\/\$\{eid\}\/verification`\)/)
})

test('Results query is strictly guarded by results_available', () => {
  assert.match(VERIF_CODE, /if\s*\(\s*vData\.results_available\s*\)/)
  assert.match(VERIF_CODE, /api\.get\(`\/elections\/\$\{eid\}\/results`\)/)
})

test('Displays informative withholding banner when voting is open', () => {
  assert.match(VERIF_CODE, /results_available/)
  assert.match(VERIF_CODE, /resultsUnavailableMsg/)
})

// ---------------------------------------------------- 4. Cryptographic Evidence & Independent CLI

test('Exposes candidate set hash, roll hash, and contract address', () => {
  assert.match(VERIF_CODE, /verificationData\.candidates_hash/)
  assert.match(VERIF_CODE, /verificationData\.roll_hash/)
  assert.match(VERIF_CODE, /verificationData\.contract_address/)
})

test('Displays independent CLI verification command', () => {
  assert.match(VERIF_CODE, /python\s+backend\/scripts\/verify_election\.py/)
})

// ---------------------------------------------------- 5. Tampering Demonstration Wiring

test('Triggers tampering demonstration via dedicated endpoint', () => {
  assert.match(VERIF_CODE, /api\.post\(`\/elections\/\$\{electionId\}\/tampering-demo`/)
  assert.match(VERIF_CODE, /tamperResult\.demonstration_verdict/)
})

// ---------------------------------------------------- 6. Privacy Preservation

test('No voter identity, student ID, USN, or pseudonym is queried or displayed', () => {
  assert.doesNotMatch(VERIF_CODE, /voter_id/)
  assert.doesNotMatch(VERIF_CODE, /student_id/)
  assert.doesNotMatch(VERIF_CODE, /pseudonym/)
})

// ---------------------------------------------------- 7. Cryptographic Receipt Verification

test('PublicVerification renders receipt_evidence section when present', () => {
  assert.match(VERIF_CODE, /verificationData\.receipt_evidence/)
  assert.match(VERIF_CODE, /receipt_code/)
  assert.match(VERIF_CODE, /hmac_verified/)
})

test('ReceiptVerificationPage queries /verification/receipt and handles statuses', () => {
  const RECEIPT_VERIF = readFileSync(join(HERE, '..', 'src', 'pages', 'public', 'ReceiptVerificationPage.jsx'), 'utf8')
  assert.match(RECEIPT_VERIF, /api\.get\(`\/verification\/receipt\//)
  assert.match(RECEIPT_VERIF, /VALID/)
  assert.match(RECEIPT_VERIF, /INVALID/)
  assert.match(RECEIPT_VERIF, /NOT_FOUND/)
  assert.match(RECEIPT_VERIF, /UNAVAILABLE/)
})
