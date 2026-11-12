/**
 * Phase 7 voting UI wiring and security tests.
 *
 * Run with `npm test`. These tests verify:
 * - Voting component is imported and rendered in App.jsx (reachable from UI);
 * - Multi-factor voting authorization is enforced (session + wallet + face);
 * - Candidate list is loaded dynamically, never hardcoded Candidate A / B;
 * - Candidate selection is not signed by MetaMask or exposed;
 * - Client cannot forge factor results;
 * - Status transitions (QUEUED -> SUBMITTED -> CONFIRMED -> FINALIZED / FAILED);
 * - Polling handles intermediate states;
 * - No premature "Vote recorded" before authoritative FINALIZED confirmation;
 * - Privacy: no pseudonym, wallet address, or biometric data in UI.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const APP = readFileSync(join(HERE, '..', 'src', 'App.jsx'), 'utf8')
const VOTING = readFileSync(join(HERE, '..', 'src', 'Voting.jsx'), 'utf8')

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const VOTING_CODE = stripComments(VOTING)

// ---------------------------------------------------- 1. Reachability & Integration

test('Voting component is imported and rendered in App.jsx', () => {
  assert.match(APP, /import\s+Voting\s+from\s+'\.\/Voting'/)
  assert.match(APP, /<Voting\s*\/>/)
})

// ---------------------------------------------------- 2. Authorization & Factor Verification

test('Voting authorization calls /voting/authorize with election_id', () => {
  assert.match(VOTING_CODE, /api\.post\('\/voting\/authorize',\s*\{\s*election_id:\s*electionId\s*\}\)/)
})

test('Factor verification checks server-side results via /voting/mark-factors', () => {
  assert.match(VOTING_CODE, /api\.post\('\/voting\/mark-factors',\s*\{\s*election_id:\s*electionId\s*\}\)/)
})

test('Client NEVER sends wallet_ok=true or face_ok=true in request payloads', () => {
  assert.doesNotMatch(VOTING_CODE, /wallet_ok\s*:\s*true/)
  assert.doesNotMatch(VOTING_CODE, /face_ok\s*:\s*true/)
})

test('UI requires both wallet_ok AND face_ok before allowing ballot selection', () => {
  assert.match(VOTING_CODE, /factors\.wallet_ok\s*&&\s*factors\.face_ok/)
  assert.match(VOTING_CODE, /setStep\('select'\)/)
  assert.match(VOTING_CODE, /setStep\('factors'\)/)
})

test('Voting renders active Face and Wallet components when factors are pending', () => {
  assert.match(VOTING, /import\s+Face\s+from\s+'\.\/Face'/)
  assert.match(VOTING, /import\s+Wallet\s+from\s+'\.\/Wallet'/)
  assert.match(VOTING_CODE, /!factorStatus\.face_ok\s*&&\s*\([\s\S]*<Face\s+onVerified=\{recheckFactors\}/)
  assert.match(VOTING_CODE, /!factorStatus\.wallet_ok\s*&&\s*\([\s\S]*<Wallet\s+onBound=\{recheckFactors\}/)
})

// ---------------------------------------------------- 3. Dynamic Candidate Loading & Selection

test('Candidates are fetched dynamically from backend, never hardcoded Candidate A/B', () => {
  assert.match(VOTING_CODE, /api\.get\(`\/voting\/election\/\$\{eid\}`\)/)
  assert.doesNotMatch(VOTING_CODE, /Candidate A/)
  assert.doesNotMatch(VOTING_CODE, /Candidate B/)
  assert.match(VOTING_CODE, /election\?\.candidates/)
})

test('Candidate selection validates selection before proceeding to confirmation', () => {
  assert.match(VOTING_CODE, /if\s*\(candidate\s*!==\s*null\)\s*setStep\('confirm'\)/)
  assert.match(VOTING_CODE, /disabled=\{candidate\s*===\s*null/)
})

test('Confirmation warns about Phase 6 one-counted-ballot policy and revoting prohibition', () => {
  assert.match(VOTING_CODE, /One Counted Ballot Policy/)
  assert.match(VOTING_CODE, /sequence\s*=\s*1/)
  assert.match(VOTING_CODE, /Revoting is strictly\s+prohibited/)
})

// ---------------------------------------------------- 4. Ballot Submission & Lifecycle Tracking

test('Legacy V1 ballot submission is permanently disabled per SEC-001', () => {
  assert.match(VOTING_CODE, /Legacy V1 plaintext ballot submission is permanently disabled/i)
  assert.match(VOTING_CODE, /SEC-001/i)
  assert.doesNotMatch(VOTING_CODE, /api\.post\('\/voting\/submit'/)
})

test('Status transitions handle QUEUED, SUBMITTED, CONFIRMED, FINALIZED, FAILED', () => {
  assert.match(VOTING_CODE, /QUEUED/)
  assert.match(VOTING_CODE, /SUBMITTED/)
  assert.match(VOTING_CODE, /CONFIRMED/)
  assert.match(VOTING_CODE, /FINALIZED/)
  assert.match(VOTING_CODE, /FAILED/)
})

test('Authoritative status polling queries /voting/status?election_id=', () => {
  assert.match(VOTING_CODE, /api\.get\(`\/voting\/status\?election_id=\$\{eid\}`\)/)
})

// ---------------------------------------------------- 5. No Premature "Vote recorded" & Receipt Rules

test('No premature "Vote recorded" message in queued, submitted, or confirming states', () => {
  // In submitting state, only processing / awaiting messages are shown
  const submittingBlock = VOTING_CODE.slice(
    VOTING_CODE.indexOf("step === 'submitting'"),
    VOTING_CODE.indexOf("step === 'done'"),
  )
  assert.doesNotMatch(submittingBlock, /Vote recorded|Vote finalized|Success/i)
})

test('Vote Finalized and Receipt display is strictly guarded by step === "done"', () => {
  const doneBlock = VOTING_CODE.slice(VOTING_CODE.indexOf("step === 'done'"))
  assert.match(doneBlock, /Vote Finalized & Confirmed on Blockchain/)
  assert.match(doneBlock, /receipt\.receipt_code/)
  assert.match(doneBlock, /receipt\.timestamp/)
})

// ---------------------------------------------------- 6. Privacy & Secret Hygiene

test('No pseudonym, wallet private key, or biometric vector is exposed in UI', () => {
  for (const forbidden of ['pseudonym', 'private_key', 'privateKey', 'face_vector', 'embedding', 'wallet_address']) {
    assert.equal(VOTING_CODE.includes(forbidden), false, `Forbidden sensitive property: ${forbidden}`)
  }
})

test('Candidate choice is never passed to MetaMask personal_sign', () => {
  assert.doesNotMatch(VOTING_CODE, /personal_sign/)
  assert.doesNotMatch(VOTING_CODE, /eth_sendTransaction/)
})

test('Uses shared API client and announces states to assistive technology', () => {
  assert.match(VOTING, /import\s+\{\s*api\s*\}\s+from\s+'\.\/api\/client\.js'/)
  assert.doesNotMatch(VOTING, /\bfetch\(/)
  assert.match(VOTING_CODE, /role="status"/)
  assert.match(VOTING_CODE, /role="alert"/)
})

// ---------------------------------------------------- 7. Authoritative Finalization & Recheck Controls

test('FINALIZED status stops polling and transitions to done with receipt', () => {
  assert.match(VOTING_CODE, /if\s*\(res\.status\s*===\s*'FINALIZED'\)\s*\{[\s\S]*setReceipt\(res\.receipt\)[\s\S]*setStep\('done'\)/)
})

test('FAILED status transitions to failed and distinguishes genuine failure from pending', () => {
  assert.match(VOTING_CODE, /if\s*\(res\.status\s*===\s*'FAILED'\)\s*\{[\s\S]*setStep\('failed'\)/)
})

test('Temporary status lookup timeout enables rechecking without submitting duplicate ballot', () => {
  assert.match(VOTING_CODE, /id="check-status-btn"/)
  assert.match(VOTING_CODE, /onClick=\{.*pollStatus\(electionId\)\}/)
  assert.match(VOTING_CODE, /Transaction confirmation timed out\. Check status later\./)
})

test('Finalized vote prevents duplicate submission on election load', () => {
  assert.match(VOTING_CODE, /statusRes\?\.status\s*===\s*'FINALIZED'[\s\S]*setStep\('done'\)/)
})
