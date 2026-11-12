/**
 * Phase 16 Step 3 — Neo-Brutalist Visual Redesign Tests.
 *
 * Run with `npm test`. These tests verify:
 * 1. Design token integrity in index.css (Cream, Black, Red, Yellow, Violet, White);
 * 2. Hard offset shadows with zero blur;
 * 3. Space Grotesk typography weights (400-900);
 * 4. Mechanical button behavior (lift on hover, translate on active);
 * 5. Accessible focus rings (3px solid #000);
 * 6. Prefers-reduced-motion accessibility support;
 * 7. Candidate cards conform to Section 15 visual structure;
 * 8. PublicVerification.css eliminates dark SaaS rounded styles;
 * 9. Voting stepper encompasses 6 distinct operational stages;
 * 10. Honest security language in LandingPage (no "unhackable" or "100% secure" claims).
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')
const ROOT = join(HERE, '..')

const readSrc = (relPath) => readFileSync(join(SRC, relPath), 'utf8')
const readRoot = (relPath) => readFileSync(join(ROOT, relPath), 'utf8')

const INDEX_HTML = readRoot('index.html')
const INDEX_CSS = readSrc('index.css')
const PUBLIC_LAYOUT_CSS = readSrc('layouts/PublicLayout.css')
const STUDENT_LAYOUT_CSS = readSrc('layouts/StudentLayout.css')
const ADMIN_LAYOUT_CSS = readSrc('layouts/AdminLayout.css')
const PAGES_CSS = readSrc('pages/public/Pages.css')
const VOTING_CSS = readSrc('Voting.css')
const VOTING_JSX = readSrc('Voting.jsx')
const PUBLIC_VERIF_CSS = readSrc('components/PublicVerification.css')
const LANDING_PAGE = readSrc('pages/public/LandingPage.jsx')
const CANDIDATES_PAGE = readSrc('pages/public/CandidatesPage.jsx')

// ---------------------------------------------------- 1. Design System Tokens

test('index.html loads Space Grotesk 400 through 900', () => {
  assert.match(INDEX_HTML, /family=Space\+Grotesk:wght@400;500;600;700;800;900/)
  assert.match(INDEX_HTML, /<title>Vote Without Doubt/)
})

test('index.css defines the full Neo-Brutalist color palette', () => {
  assert.match(INDEX_CSS, /--neo-cream:\s*#FFFDF5/i)
  assert.match(INDEX_CSS, /--neo-black:\s*#000000/i)
  assert.match(INDEX_CSS, /--neo-red:\s*#FF6B6B/i)
  assert.match(INDEX_CSS, /--neo-yellow:\s*#FFD93D/i)
  assert.match(INDEX_CSS, /--neo-violet:\s*#C4B5FD/i)
  assert.match(INDEX_CSS, /--neo-white:\s*#FFFFFF/i)
})

test('index.css defines hard offset shadows without blur', () => {
  assert.match(INDEX_CSS, /--shadow-sm:\s*3px 3px 0px #000000/)
  assert.match(INDEX_CSS, /--shadow-hard:\s*6px 6px 0px #000000/)
  assert.match(INDEX_CSS, /--shadow-lg:\s*8px 8px 0px #000000/)
  // Confirm no soft blur radius in root shadow variables
  assert.doesNotMatch(INDEX_CSS, /--shadow-.*:\s*\d+px \d+px \d+px rgba/)
})

test('index.css defines sharp borders and Space Grotesk font stack', () => {
  assert.match(INDEX_CSS, /--border-thick:\s*4px solid #000000/)
  assert.match(INDEX_CSS, /'Space Grotesk'/)
})

// ---------------------------------------------------- 2. Mechanical Buttons & Micro-Interactions

test('buttons implement mechanical lift on hover and depress on active', () => {
  assert.match(INDEX_CSS, /\.btn:hover:not\(:disabled\)\s*\{[^}]*transform:\s*translate\(-2px,\s*-2px\)/)
  assert.match(INDEX_CSS, /\.btn:active:not\(:disabled\)\s*\{[^}]*transform:\s*translate\(2px,\s*2px\)/)
})

test('keyboard focus rings enforce 3px high-contrast outline', () => {
  assert.match(INDEX_CSS, /\*:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--neo-black\)/)
})

test('prefers-reduced-motion disables mechanical button movement', () => {
  assert.match(INDEX_CSS, /@media\s*\(prefers-reduced-motion:\s*reduce\)/)
  assert.match(INDEX_CSS, /transform:\s*none\s*!important/)
})

// ---------------------------------------------------- 3. Layouts & Visual Polish

test('PublicLayout.css implements sticky bold header with hard shadow', () => {
  assert.match(PUBLIC_LAYOUT_CSS, /border-bottom:\s*4px solid #000000/)
  assert.match(PUBLIC_LAYOUT_CSS, /box-shadow:\s*0 4px 0 #000000/)
})

test('StudentLayout.css styles verified voter session pill and navigation', () => {
  assert.match(STUDENT_LAYOUT_CSS, /badge-verified-student/)
  assert.match(STUDENT_LAYOUT_CSS, /student-top-banner/)
})

test('AdminLayout.css provides distinct role badges and operational styling', () => {
  assert.match(ADMIN_LAYOUT_CSS, /badge-role/)
  assert.match(ADMIN_LAYOUT_CSS, /role-officer/)
  assert.match(ADMIN_LAYOUT_CSS, /role-auditor/)
})

// ---------------------------------------------------- 4. Candidate Experience (Section 15)

test('CandidatesPage renders Section 15 candidate box cards with photo frames', () => {
  assert.match(CANDIDATES_PAGE, /candidate-box-card/)
  assert.match(CANDIDATES_PAGE, /candidate-photo-frame/)
  assert.match(CANDIDATES_PAGE, /candidate-box-name/)
  assert.match(CANDIDATES_PAGE, /candidate-box-slogan/)
  assert.match(CANDIDATES_PAGE, /CANDIDATE #0/)
})

// ---------------------------------------------------- 5. Public Verification Modernization

test('PublicVerification.css eliminates dark SaaS gradients and 8px border-radius', () => {
  assert.doesNotMatch(PUBLIC_VERIF_CSS, /#1a2234/)
  assert.doesNotMatch(PUBLIC_VERIF_CSS, /border-radius:\s*8px/)
  assert.match(PUBLIC_VERIF_CSS, /border:\s*4px solid #000000/)
  assert.match(PUBLIC_VERIF_CSS, /box-shadow:\s*6px 6px 0px #000000/)
})

// ---------------------------------------------------- 6. Voting Stepper (Section 17)

test('Voting.jsx features 6-step progress stepper', () => {
  assert.match(VOTING_JSX, /voting-stepper/)
  assert.match(VOTING_JSX, /01 VERIFY/)
  assert.match(VOTING_JSX, /02 FACE/)
  assert.match(VOTING_JSX, /03 CHOOSE/)
  assert.match(VOTING_JSX, /04 REVIEW/)
  assert.match(VOTING_JSX, /05 SIGN/)
  assert.match(VOTING_JSX, /06 RECORD/)
})

// ---------------------------------------------------- 7. Honest Security Language (Section 13)

test('LandingPage uses honest security language and avoids prohibited claims', () => {
  assert.match(LANDING_PAGE, /Vote Without Doubt/)
  assert.match(LANDING_PAGE, /A secure college election platform built around identity verification, privacy-preserving voting, and independently verifiable results\./)
  assert.doesNotMatch(LANDING_PAGE, /100% secure/i)
  assert.doesNotMatch(LANDING_PAGE, /unhackable/i)
  assert.doesNotMatch(LANDING_PAGE, /completely anonymous/i)
  assert.doesNotMatch(LANDING_PAGE, /spoof-proof/i)
})

// ---------------------------------------------------- 8. Phase E.3 Regression Defect Tests

test('DEF-E2-02: mobile-nav-toggle satisfies minimum 44x44px touch target threshold', () => {
  assert.match(PUBLIC_LAYOUT_CSS, /\.mobile-nav-toggle\s*\{[^}]*min-height:\s*44px/s)
  assert.match(PUBLIC_LAYOUT_CSS, /\.mobile-nav-toggle\s*\{[^}]*min-width:\s*44px/s)
  assert.match(STUDENT_LAYOUT_CSS, /\.student-header\s+\.mobile-nav-toggle\s*\{[^}]*min-height:\s*44px/s)
  assert.match(STUDENT_LAYOUT_CSS, /\.student-header\s+\.mobile-nav-toggle\s*\{[^}]*min-width:\s*44px/s)
})

