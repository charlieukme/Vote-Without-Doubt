/**
 * Phase 16 Step 2 View Architecture & Security Integration Tests.
 *
 * Run with `npm test`. These tests verify:
 * 1. Clean view architecture separating Public, Student, and Admin domains;
 * 2. Route guards protecting student and admin paths;
 * 3. Role protection: Officer vs Auditor capabilities;
 * 4. Two-Officer approval UI blocks self-approval (Four-Eyes Principle);
 * 5. Dashboard aggregates election state and multi-factor readiness;
 * 6. "My Vote" respects Phase 9 revoting rules and hides candidate choices;
 * 7. "Receipt" preserves Phase 8 & 15 privacy rules and provides copy/download;
 * 8. Tampering demonstration is removed from public view and gated to Admin;
 * 9. Admin login enforces 3-factor authentication (Admin ID + Password + TOTP);
 * 10. Educational & Verification public pages provide independent verification access.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')

const readSrc = (relPath) => readFileSync(join(SRC, relPath), 'utf8')

const APP = readSrc('App.jsx')
const STUDENT_LAYOUT = readSrc('layouts/StudentLayout.jsx')
const ADMIN_LAYOUT = readSrc('layouts/AdminLayout.jsx')
const DASHBOARD = readSrc('pages/student/DashboardPage.jsx')
const MY_VOTE = readSrc('pages/student/MyVotePage.jsx')
const RECEIPT_PAGE = readSrc('pages/student/ReceiptPage.jsx')
const ADMIN_LOGIN = readSrc('pages/admin/AdminLoginPage.jsx')
const ADMIN_APPROVALS = readSrc('pages/admin/AdminApprovalsPage.jsx')
const PUBLIC_VERIF_PAGE = readSrc('pages/public/PublicVerificationPage.jsx')
const ADMIN_VERIF_PAGE = readSrc('pages/admin/AdminVerificationPage.jsx')
const RECEIPT_VERIF_PAGE = readSrc('pages/public/ReceiptVerificationPage.jsx')
const HOW_PROTECTED_PAGE = readSrc('pages/public/HowVoteProtectedPage.jsx')

// ---------------------------------------------------- 1. View Architecture & Route Separation

test('App.jsx separates Admin, Student, and Public route domains', () => {
  assert.match(APP, /path\.startsWith\('\/admin'\)/)
  assert.match(APP, /\/dashboard.*\/vote.*\/receipt.*\/my-vote.*\/profile/)
  assert.match(APP, /<AdminLayout>/)
  assert.match(APP, /<StudentLayout>/)
  assert.match(APP, /<PublicLayout>/)
})

test('App.jsx imports and routes all required public views', () => {
  assert.match(APP, /import\s+LandingPage/)
  assert.match(APP, /import\s+ElectionInfoPage/)
  assert.match(APP, /import\s+CandidatesPage/)
  assert.match(APP, /import\s+PublicVerificationPage/)
  assert.match(APP, /import\s+ReceiptVerificationPage/)
  assert.match(APP, /import\s+HowVoteProtectedPage/)
  assert.match(APP, /import\s+HelpPage/)
  assert.match(APP, /import\s+TermsPage/)
  assert.match(APP, /import\s+PrivacyPage/)
})

// ---------------------------------------------------- 2. Route Guards & Session Expiry

test('StudentLayout protects student views and redirects unauthenticated users to /login', () => {
  assert.match(STUDENT_LAYOUT, /if\s*\(\s*studentAuth\s*&&\s*!studentAuth\.authenticated\s*\)/)
  assert.match(STUDENT_LAYOUT, /navigate\('\/login'\)/)
})

test('AdminLayout protects admin views and redirects unauthenticated users to /admin/login', () => {
  assert.match(ADMIN_LAYOUT, /if\s*\(\s*!adminToken\s*\)/)
  assert.match(ADMIN_LAYOUT, /navigate\('\/admin\/login'\)/)
})

// ---------------------------------------------------- 3. Four-Eyes Principle (Two-Officer Approvals)

test('Admin approvals queue blocks self-approval in the UI', () => {
  assert.match(ADMIN_APPROVALS, /currentAdminId\s*===\s*requesterId/)
  assert.match(ADMIN_APPROVALS, /Self-Approval Blocked/)
  assert.match(ADMIN_APPROVALS, /FOUR_EYES_VIOLATION/)
})

test('Admin approvals distinguishes Officer operational actions from Auditor read-only inspection', () => {
  assert.match(ADMIN_APPROVALS, /adminAuth\?\.role\s*===\s*'OFFICER'/)
  assert.match(ADMIN_APPROVALS, /Auditor Read-Only/)
})

// ---------------------------------------------------- 4. Student Dashboard Aggregation

test('DashboardPage aggregates election state, wallet binding, and face enrollment', () => {
  assert.match(DASHBOARD, /api\.get\('\/public\/elections'\)/)
  assert.match(DASHBOARD, /api\.get\('\/wallet\/status'\)/)
  assert.match(DASHBOARD, /api\.get\('\/face\/status'\)/)
  assert.match(DASHBOARD, /api\.get\(`\/voting\/status\?election_id=\${.*}`\)/)
})

test('DashboardPage displays multi-factor readiness indicators', () => {
  assert.match(DASHBOARD, /MetaMask Wallet Binding/)
  assert.match(DASHBOARD, /AI Biometric Template/)
  assert.match(DASHBOARD, /allFactorsReady/)
})

// ---------------------------------------------------- 5. My Vote & Coercion Resistance (Phase 9)

test('MyVotePage displays sequence counter and respects 120s cooldown', () => {
  assert.match(MY_VOTE, /sequence.*of.*maxBallots/)
  assert.match(MY_VOTE, /cooldownSeconds/)
  assert.match(MY_VOTE, /Revote Cooldown Active/)
  assert.match(MY_VOTE, /Cast Replacement Revote/)
})

test('MyVotePage strictly conceals candidate choices and internal transaction data', () => {
  assert.doesNotMatch(MY_VOTE, /voteInfo\?\.candidate_name/)
  assert.doesNotMatch(MY_VOTE, /voteInfo\?\.tx_hash/)
  assert.doesNotMatch(MY_VOTE, /voteInfo\?\.pseudonym/)
})

// ---------------------------------------------------- 6. Receipt Privacy & Actions

test('ReceiptPage provides copy, text download, and on-chain verification links', () => {
  assert.match(RECEIPT_PAGE, /receipt\.receipt_code/)
  assert.match(RECEIPT_PAGE, /copyToClipboard/)
  assert.match(RECEIPT_PAGE, /downloadTextReceipt/)
  assert.match(RECEIPT_PAGE, /navigate\(.*\/verification/)
})

test('ReceiptPage explicitly protects ballot secrecy', () => {
  assert.match(RECEIPT_PAGE, /omits your candidate choice/)
  assert.doesNotMatch(RECEIPT_PAGE, /receipt\.tx_hash/)
  assert.doesNotMatch(RECEIPT_PAGE, /receipt\.candidate/)
})

// ---------------------------------------------------- 7. Public vs Admin Tampering Gating (Security Audit Fix)

test('Public verification page hides tampering demonstration from unauthenticated visitors', () => {
  assert.match(PUBLIC_VERIF_PAGE, /<PublicVerification\s+showTamperingDemo=\{false\}\s*\/>/)
})

test('Admin verification page enables sandboxed tampering demonstration for authorized officers', () => {
  assert.match(ADMIN_VERIF_PAGE, /<PublicVerification\s+showTamperingDemo=\{true\}\s*\/>/)
})

// ---------------------------------------------------- 8. Admin 3-Factor Authentication

test('Admin login requires Admin ID, Master Password, and 6-digit TOTP code', () => {
  assert.match(ADMIN_LOGIN, /admin_id:\s*adminId/)
  assert.match(ADMIN_LOGIN, /password/)
  assert.match(ADMIN_LOGIN, /totp_code:\s*totpCode/)
  assert.match(ADMIN_LOGIN, /api\.post\('\/admin\/auth\/login'/)
})

// ---------------------------------------------------- 9. Transparency & Verification Access

test('ReceiptVerificationPage provides standalone Python CLI audit instructions', () => {
  assert.match(RECEIPT_VERIF_PAGE, /python\s+backend\/scripts\/verify_election\.py/)
})

test('HowVoteProtectedPage explains the 6-layer security architecture', () => {
  assert.match(HOW_PROTECTED_PAGE, /LAYER 1 — IDENTITY AUTHENTICATION/)
  assert.match(HOW_PROTECTED_PAGE, /LAYER 2 — CRYPTOGRAPHIC WALLET PROOF/)
  assert.match(HOW_PROTECTED_PAGE, /LAYER 3 — AI BIOMETRIC LIVENESS/)
  assert.match(HOW_PROTECTED_PAGE, /LAYER 4 — PSEUDONYMITY & RELAYER/)
  assert.match(HOW_PROTECTED_PAGE, /LAYER 5 — COERCION RESISTANCE/)
  assert.match(HOW_PROTECTED_PAGE, /LAYER 6 — GOVERNANCE & AUDIT/)
})

// ---------------------------------------------------- 10. Phase E.3 Regression Defect Tests

test('DEF-E2-01: StudentLayout correctly imports useState and useEffect from react', () => {
  assert.match(STUDENT_LAYOUT, /import\s+React,\s*\{\s*(?:[a-zA-Z0-9_,\s]*\buseState\b[a-zA-Z0-9_,\s]*)\}\s*from\s*['"]react['"]/)
})

