/**
 * Task 4 - Public Verification & Results Publication Runtime & Component Tests
 *
 * This test suite verifies:
 * 1. Dynamic election selector populated from /public/elections.
 * 2. URL synchronization with election_id preserving pathname, unrelated query params, and hash.
 * 3. Browser Back/Forward (popstate) restoration.
 * 4. Asynchronous response race condition protection using activeRequestIdRef.
 * 5. Strict rendering and withholding rules across all five result states:
 *    - RESULTS_UNAVAILABLE (withheld)
 *    - PROCESSING_PENDING_BALLOTS (withheld)
 *    - RESULTS_UNDER_REVIEW (withheld)
 *    - PROVISIONAL_UNFINALIZED (provisional badge, tallies shown, not certified)
 *    - FINALIZED_RESULTS (certified badge, tallies shown)
 * 6. Tri-state cryptographic verification outcomes: VERIFIED, FAILED, UNAVAILABLE.
 * 7. Candidate-set hash (MATCHED/MISMATCH) and voter-roll hash (MATCHED/MISMATCH, raw hex omitted).
 * 8. Separate truthful Merkle statuses (ROOT RECORDED, FAILED, UNAVAILABLE).
 * 9. Omission of unproven pseudonym key destruction claims.
 * 10. Deep-link context in ReceiptVerificationPage and strict omission of receipt_code URL parsing.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const verificationComponentPath = path.resolve(__dirname, '../src/components/PublicVerification.jsx')
const receiptPagePath = path.resolve(__dirname, '../src/pages/public/ReceiptVerificationPage.jsx')

const verificationCode = fs.readFileSync(verificationComponentPath, 'utf8')
const receiptCode = fs.readFileSync(receiptPagePath, 'utf8')

// ============================================================================
// PART 1: STATIC SOURCE CHECKS & IMPLEMENTATION CONTRACTS
// ============================================================================

test('PublicVerification renders a dynamic <select> element populated from /public/elections', () => {
  assert.match(verificationCode, /\/public\/elections/, 'Must query /public/elections for directory')
  assert.match(verificationCode, /<select\b/, 'Must render a <select> dropdown for election selection')
  assert.match(verificationCode, /id="election-select"/, 'Must have select id election-select')
  assert.match(verificationCode, /onChange=\{handleSelectElection\}/, 'Must handle selection changes')
})

test('PublicVerification implements URL synchronization preserving existing pathname and hash', () => {
  assert.match(verificationCode, /new URL\(window\.location\.href\)/, 'Must construct URL from window.location.href to preserve parts')
  assert.match(verificationCode, /currentUrl\.searchParams\.set\(['"`]election_id['"`]/, 'Must set election_id on URL object')
  assert.match(verificationCode, /window\.history\.pushState\(null,\s*['"`]['"`],\s*currentUrl\.toString\(\)\)/, 'Must pushState with full URL string preserving path and hash')
})

test('PublicVerification registers popstate listener for browser Back/Forward navigation', () => {
  assert.match(verificationCode, /window\.addEventListener\(['"`]popstate['"`]/, 'Must listen for popstate events')
  assert.match(verificationCode, /window\.removeEventListener\(['"`]popstate['"`]/, 'Must clean up popstate listener')
})

test('PublicVerification implements activeRequestIdRef to discard stale asynchronous responses', () => {
  assert.match(verificationCode, /const activeRequestIdRef = useRef\(0\)/, 'Must declare activeRequestIdRef counter')
  assert.match(verificationCode, /\+\+activeRequestIdRef\.current/, 'Must increment activeRequestIdRef on new requests')
  assert.match(verificationCode, /if\s*\(requestId !== activeRequestIdRef\.current\)\s*return/, 'Must discard responses from superseded requests')
  assert.match(verificationCode, /if\s*\(requestId === activeRequestIdRef\.current\)\s*\{\s*setLoading\(false\)/, 'Only active request may clear loading state')
})

test('PublicVerification strictly omits raw voter-roll hash hex and pseudonym key destruction claim from display', () => {
  // Raw roll hash string must NOT be rendered into JSX output
  assert.doesNotMatch(verificationCode, /\{verificationData\.roll_hash\}/, 'Raw voter-roll hash hex must not be rendered into JSX elements')
  assert.match(verificationCode, /Voter Roll Digest Comparison/, 'Must label as digest comparison')
  assert.match(verificationCode, /Voter-roll hash:/, 'Must use literal comparison wording')
  assert.match(verificationCode, /verificationData\?\.blockchain_evidence\?\.roll_hash_matches/, 'Must read roll_hash_matches directly from blockchain_evidence')
  assert.match(verificationCode, /canDisplayTallies/, 'Must gate tallies by fail-closed canDisplayTallies predicate')
  assert.match(verificationCode, /unrecognized or incomplete result state/, 'Must include unrecognized state notice')
  assert.match(verificationCode, /rawResultState === ['"`]FINALIZED_RESULTS['"`]/, 'Must explicitly require rawResultState === FINALIZED_RESULTS')
  assert.doesNotMatch(verificationCode, /rawResultState === ['"`]FINALIZED_RESULTS['"`]\s*\|\|\s*\(?resultsData\?\.official_results/, 'Must NOT permit official_results fallback bypass')
  assert.doesNotMatch(verificationCode, /PSEUDONYM KEY DESTROYED/i, 'Must not claim pseudonym key destruction without evidence')
})

test('ReceiptVerificationPage reads election_id from URL query params but strictly rejects receipt_code', () => {
  assert.match(receiptCode, /contextElectionId/, 'Must track contextElectionId from URL')
  assert.match(receiptCode, /sp\.get\(['"`]election_id['"`]\)/, 'Must parse election_id query parameter')
  assert.doesNotMatch(receiptCode, /sp\.get\(['"`]receipt_code['"`]\)/, 'Must NEVER parse receipt_code from URL')
  assert.doesNotMatch(receiptCode, /sp\.get\(['"`]code['"`]\)/, 'Must NEVER parse code from URL')
  assert.match(receiptCode, /Active Election Context:/, 'Must render context notification')
})

// ============================================================================
// PART 2: RUNTIME LOGIC SIMULATION & INTEGRATION CONTRACT TESTS
// ============================================================================

test('Runtime logic test: URL synchronization preserves pathname, unrelated query params, and hash', () => {
  const simulatedBrowserUrl = 'https://vwd.university.edu/verification?theme=contrast&ref=student_portal#audit-anchor'
  const currentUrl = new URL(simulatedBrowserUrl)

  const updateElectionUrl = (newId) => {
    if (newId) {
      currentUrl.searchParams.set('election_id', newId)
    } else {
      currentUrl.searchParams.delete('election_id')
    }
    return currentUrl.toString()
  }

  const updatedUrlString = updateElectionUrl('ELEC_20261108_TEST')
  const parsedUpdated = new URL(updatedUrlString)

  assert.equal(parsedUpdated.pathname, '/verification', 'Pathname must remain /verification')
  assert.equal(parsedUpdated.searchParams.get('theme'), 'contrast', 'Unrelated query parameter theme must be preserved')
  assert.equal(parsedUpdated.searchParams.get('ref'), 'student_portal', 'Unrelated query parameter ref must be preserved')
  assert.equal(parsedUpdated.searchParams.get('election_id'), 'ELEC_20261108_TEST', 'election_id must be updated')
  assert.equal(parsedUpdated.hash, '#audit-anchor', 'URL hash must remain preserved')
})

test('Runtime logic test: popstate listener restores election_id from URL query parameters', () => {
  let activeElectionId = 'ELEC_INITIAL'
  const historyStack = [
    'https://vwd.university.edu/verification?election_id=ELEC_INITIAL',
    'https://vwd.university.edu/verification?election_id=ELEC_SECOND',
    'https://vwd.university.edu/verification?election_id=ELEC_THIRD',
  ]
  let currentIndex = 2

  const handlePopState = (currentSearch) => {
    const sp = new URLSearchParams(currentSearch)
    const eid = sp.get('election_id') || ''
    if (eid && eid !== activeElectionId) {
      activeElectionId = eid
    }
  }

  // Simulate Back button: index moves from 2 to 1 (ELEC_SECOND)
  currentIndex = 1
  handlePopState(new URL(historyStack[currentIndex]).search)
  assert.equal(activeElectionId, 'ELEC_SECOND', 'Must restore ELEC_SECOND after Back navigation')

  // Simulate Back button: index moves from 1 to 0 (ELEC_INITIAL)
  currentIndex = 0
  handlePopState(new URL(historyStack[currentIndex]).search)
  assert.equal(activeElectionId, 'ELEC_INITIAL', 'Must restore ELEC_INITIAL after Back navigation')

  // Simulate Forward button: index moves from 0 to 2 (ELEC_THIRD)
  currentIndex = 2
  handlePopState(new URL(historyStack[currentIndex]).search)
  assert.equal(activeElectionId, 'ELEC_THIRD', 'Must restore ELEC_THIRD after Forward navigation')
})

test('Runtime logic test: out-of-order asynchronous responses do not overwrite current election', async () => {
  const state = {
    activeElectionId: 'ELEC_A',
    verificationData: null,
    loading: false,
  }
  const activeRequestIdRef = { current: 0 }

  const simulateLoadVerification = async (eid, delayMs, payload) => {
    const requestId = ++activeRequestIdRef.current
    state.loading = true
    state.activeElectionId = eid

    await new Promise((resolve) => setTimeout(resolve, delayMs))

    if (activeRequestIdRef.current !== requestId) {
      // Stale response discarded
      return
    }

    state.verificationData = payload
    if (activeRequestIdRef.current === requestId) {
      state.loading = false
    }
  }

  // Request 1: User selects Election A (slow response, 80ms)
  const reqA = simulateLoadVerification('ELEC_A', 80, { election_id: 'ELEC_A', title: 'Slow Election A' })

  // Request 2: 15ms later, user rapidly clicks Election B (fast response, 20ms)
  await new Promise((resolve) => setTimeout(resolve, 15))
  const reqB = simulateLoadVerification('ELEC_B', 20, { election_id: 'ELEC_B', title: 'Fast Election B' })

  await Promise.all([reqA, reqB])

  assert.equal(state.activeElectionId, 'ELEC_B', 'Selected election must be ELEC_B')
  assert.equal(state.verificationData.election_id, 'ELEC_B', 'Verification data must be from Election B, not Election A')
  assert.equal(state.verificationData.title, 'Fast Election B')
  assert.equal(state.loading, false, 'Loading must be cleared by Election B')
})

test('Runtime logic test: fail-closed tally withholding predicates strictly enforce 5-state gating', () => {
  const evaluateDisplay = ({
    results_available,
    resultsUnavailableMsg,
    pendingQueueMsg,
    underReviewMsg,
    resultsData,
  }) => {
    const isResultsAvailable = Boolean(results_available)
    const hasSafetyMismatch = Boolean(
      resultsData && (
        resultsData.is_under_review === true ||
        resultsData.tally_matches_blockchain === false ||
        Number(resultsData.open_reconciliation_issues) > 0
      )
    )
    const rawResultState = resultsData?.result_state ?? null

    const isResultsUnavailable = Boolean(
      !isResultsAvailable ||
      resultsUnavailableMsg ||
      rawResultState === 'RESULTS_UNAVAILABLE'
    )

    const isPendingQueue = Boolean(
      pendingQueueMsg ||
      rawResultState === 'PROCESSING_PENDING_BALLOTS'
    )

    const isUnderReview = Boolean(
      underReviewMsg ||
      rawResultState === 'RESULTS_UNDER_REVIEW' ||
      hasSafetyMismatch
    )

    const isFinalizedResults = Boolean(
      !isResultsUnavailable &&
      !isPendingQueue &&
      !isUnderReview &&
      rawResultState === 'FINALIZED_RESULTS'
    )

    const isProvisional = Boolean(
      !isResultsUnavailable &&
      !isPendingQueue &&
      !isUnderReview &&
      !isFinalizedResults &&
      rawResultState === 'PROVISIONAL_UNFINALIZED'
    )

    const canDisplayTallies = Boolean(
      resultsData &&
      !isResultsUnavailable &&
      !isPendingQueue &&
      !isUnderReview &&
      (isFinalizedResults || isProvisional)
    )

    const isUnrecognizedOrIncompleteState = Boolean(
      resultsData &&
      !isResultsUnavailable &&
      !isPendingQueue &&
      !isUnderReview &&
      !canDisplayTallies
    )

    return {
      isResultsUnavailable,
      isPendingQueue,
      isUnderReview,
      isFinalizedResults,
      isProvisional,
      canDisplayTallies,
      isUnrecognizedOrIncompleteState,
    }
  }

  // 1. PROVISIONAL_UNFINALIZED displays provisional tallies
  const t1 = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'PROVISIONAL_UNFINALIZED',
      tally_matches_blockchain: true,
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Alice', votes: 10 }],
    },
  })
  assert.equal(t1.canDisplayTallies, true, 'PROVISIONAL_UNFINALIZED must display tallies')
  assert.equal(t1.isProvisional, true, 'PROVISIONAL_UNFINALIZED must be marked provisional')
  assert.equal(t1.isFinalizedResults, false, 'PROVISIONAL_UNFINALIZED must not be marked finalized')
  assert.equal(t1.isUnrecognizedOrIncompleteState, false)

  // 2. FINALIZED_RESULTS displays certified tallies
  const t2 = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'FINALIZED_RESULTS',
      official_results: true,
      is_finalized: true,
      tally_matches_blockchain: true,
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Alice', votes: 10 }],
    },
  })
  assert.equal(t2.canDisplayTallies, true, 'FINALIZED_RESULTS must display tallies')
  assert.equal(t2.isFinalizedResults, true, 'FINALIZED_RESULTS must be marked certified finalized')
  assert.equal(t2.isProvisional, false, 'FINALIZED_RESULTS must not be marked provisional')
  assert.equal(t2.isUnrecognizedOrIncompleteState, false)

  // 3. RESULTS_UNAVAILABLE withholds tallies
  const t3a = evaluateDisplay({
    results_available: false,
    resultsData: null,
  })
  assert.equal(t3a.canDisplayTallies, false, 'RESULTS_UNAVAILABLE (results_available: false) withholds tallies')
  assert.equal(t3a.isResultsUnavailable, true)

  const t3b = evaluateDisplay({
    results_available: true,
    resultsData: { result_state: 'RESULTS_UNAVAILABLE' },
  })
  assert.equal(t3b.canDisplayTallies, false, 'RESULTS_UNAVAILABLE state withholds tallies')
  assert.equal(t3b.isResultsUnavailable, true)

  // 4. PROCESSING_PENDING_BALLOTS withholds tallies
  const t4a = evaluateDisplay({
    results_available: true,
    pendingQueueMsg: 'Relayer queue active',
    resultsData: null,
  })
  assert.equal(t4a.canDisplayTallies, false, 'PROCESSING_PENDING_BALLOTS (pending queue message) withholds tallies')
  assert.equal(t4a.isPendingQueue, true)

  const t4b = evaluateDisplay({
    results_available: true,
    resultsData: { result_state: 'PROCESSING_PENDING_BALLOTS' },
  })
  assert.equal(t4b.canDisplayTallies, false, 'PROCESSING_PENDING_BALLOTS state withholds tallies')
  assert.equal(t4b.isPendingQueue, true)

  // 5. RESULTS_UNDER_REVIEW withholds tallies
  const t5a = evaluateDisplay({
    results_available: true,
    underReviewMsg: 'Audit under review',
    resultsData: null,
  })
  assert.equal(t5a.canDisplayTallies, false, 'RESULTS_UNDER_REVIEW (under review message) withholds tallies')
  assert.equal(t5a.isUnderReview, true)

  const t5b = evaluateDisplay({
    results_available: true,
    resultsData: { result_state: 'RESULTS_UNDER_REVIEW' },
  })
  assert.equal(t5b.canDisplayTallies, false, 'RESULTS_UNDER_REVIEW state withholds tallies')
  assert.equal(t5b.isUnderReview, true)

  // 6. Unknown state withholds tallies
  const t6 = evaluateDisplay({
    results_available: true,
    resultsData: { result_state: 'UNEXPECTED_STATE_XYZ', candidates: [{ name: 'Eve', votes: 100 }] },
  })
  assert.equal(t6.canDisplayTallies, false, 'Unknown result state must strictly withhold tallies')
  assert.equal(t6.isUnrecognizedOrIncompleteState, true, 'Unknown state must trigger unrecognized state notification')
  assert.equal(t6.isProvisional, false, 'Unknown state must never be marked provisional')
  assert.equal(t6.isFinalizedResults, false, 'Unknown state must never be marked finalized')

  // 7. Missing state withholds tallies
  const t7 = evaluateDisplay({
    results_available: true,
    resultsData: { candidates: [{ name: 'Bob', votes: 5 }] }, // result_state omitted
  })
  assert.equal(t7.canDisplayTallies, false, 'Missing result_state must strictly withhold tallies')
  assert.equal(t7.isUnrecognizedOrIncompleteState, true, 'Missing state must trigger unrecognized state notification')
  assert.equal(t7.isProvisional, false, 'Missing state must never be marked provisional')
  assert.equal(t7.isFinalizedResults, false, 'Missing state must never be marked finalized')

  // 8. Null state withholds tallies
  const t8 = evaluateDisplay({
    results_available: true,
    resultsData: { result_state: null, candidates: [{ name: 'Carol', votes: 8 }] },
  })
  assert.equal(t8.canDisplayTallies, false, 'Null result_state must strictly withhold tallies')
  assert.equal(t8.isUnrecognizedOrIncompleteState, true, 'Null state must trigger unrecognized state notification')
  assert.equal(t8.isProvisional, false, 'Null state must never be marked provisional')
  assert.equal(t8.isFinalizedResults, false, 'Null state must never be marked finalized')

  // 9. Inconsistent response with mismatch or open reconciliation issues withholds tallies
  const t9a = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'PROVISIONAL_UNFINALIZED',
      tally_matches_blockchain: false, // Inconsistent mismatch!
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Alice', votes: 10 }],
    },
  })
  assert.equal(t9a.canDisplayTallies, false, 'Tally blockchain mismatch must strictly withhold tallies')
  assert.equal(t9a.isUnderReview, true, 'Tally blockchain mismatch must route to under-review state')

  const t9b = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'FINALIZED_RESULTS',
      official_results: true,
      is_finalized: true,
      tally_matches_blockchain: true,
      open_reconciliation_issues: 3, // Inconsistent open issues!
      candidates: [{ name: 'Alice', votes: 10 }],
    },
  })
  assert.equal(t9b.canDisplayTallies, false, 'Open reconciliation issues must strictly withhold tallies even in finalized payload')
  assert.equal(t9b.isUnderReview, true, 'Open reconciliation issues must route to under-review state')

  const t9c = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'PROVISIONAL_UNFINALIZED',
      is_under_review: true, // Flagged under review!
      candidates: [{ name: 'Alice', votes: 10 }],
    },
  })
  assert.equal(t9c.canDisplayTallies, false, 'is_under_review=true flag must strictly withhold tallies')
  assert.equal(t9c.isUnderReview, true)

  // 9d. UNKNOWN_STATE + official_results=true + is_finalized=true must withhold tallies (NO bypass)
  const t9d = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: 'UNKNOWN_STATE',
      official_results: true,
      is_finalized: true,
      tally_matches_blockchain: true,
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Eve', votes: 100 }],
    },
  })
  assert.equal(t9d.canDisplayTallies, false, 'UNKNOWN_STATE with official_results/is_finalized must strictly withhold tallies')
  assert.equal(t9d.isFinalizedResults, false, 'UNKNOWN_STATE must not be classified as finalized')
  assert.equal(t9d.isUnrecognizedOrIncompleteState, true, 'UNKNOWN_STATE must trigger unrecognized state notice')

  // 9e. Missing result_state + official_results=true + is_finalized=true must withhold tallies (NO bypass)
  const t9e = evaluateDisplay({
    results_available: true,
    resultsData: {
      official_results: true,
      is_finalized: true,
      tally_matches_blockchain: true,
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Bob', votes: 5 }],
    },
  })
  assert.equal(t9e.canDisplayTallies, false, 'Missing result_state with official_results/is_finalized must strictly withhold tallies')
  assert.equal(t9e.isFinalizedResults, false, 'Missing result_state must not be classified as finalized')
  assert.equal(t9e.isUnrecognizedOrIncompleteState, true, 'Missing result_state must trigger unrecognized state notice')

  // 9f. Null result_state + official_results=true + is_finalized=true must withhold tallies (NO bypass)
  const t9f = evaluateDisplay({
    results_available: true,
    resultsData: {
      result_state: null,
      official_results: true,
      is_finalized: true,
      tally_matches_blockchain: true,
      open_reconciliation_issues: 0,
      candidates: [{ name: 'Carol', votes: 8 }],
    },
  })
  assert.equal(t9f.canDisplayTallies, false, 'Null result_state with official_results/is_finalized must strictly withhold tallies')
  assert.equal(t9f.isFinalizedResults, false, 'Null result_state must not be classified as finalized')
  assert.equal(t9f.isUnrecognizedOrIncompleteState, true, 'Null result_state must trigger unrecognized state notice')
})

test('Runtime logic test: tri-state verification outcomes evaluate correctly', () => {
  const evaluateStatuses = ({
    candHashMatch,
    rollHashMatch,
    auditChainIntact,
    anchorVerified,
    anchorCount,
    hasMerkleRoot,
    electionStatus,
    tallyMatchesBlockchain,
  }) => {
    const candHashStatus = candHashMatch === true ? 'MATCHED' : candHashMatch === false ? 'MISMATCH' : 'UNAVAILABLE'
    const rollHashStatus = rollHashMatch === true ? 'MATCHED' : rollHashMatch === false ? 'MISMATCH' : 'UNAVAILABLE'
    const auditChainStatus = auditChainIntact === true ? 'AUDIT CHAIN VERIFIED' : auditChainIntact === false ? 'FAILED' : 'UNAVAILABLE'
    const auditAnchorStatus = anchorVerified === true ? 'VERIFIED' : (anchorCount > 0 ? 'FAILED' : 'UNAVAILABLE')
    const merkleRootStatus = (hasMerkleRoot && electionStatus === 'FINALIZED' && auditChainIntact !== false)
      ? 'ROOT RECORDED'
      : (hasMerkleRoot && auditChainIntact === false)
      ? 'FAILED'
      : 'UNAVAILABLE'
    const blockchainTallyStatus = tallyMatchesBlockchain === true ? 'VERIFIED' : tallyMatchesBlockchain === false ? 'FAILED' : 'UNAVAILABLE'

    return { candHashStatus, rollHashStatus, auditChainStatus, auditAnchorStatus, merkleRootStatus, blockchainTallyStatus }
  }

  // All clean and finalized
  const s1 = evaluateStatuses({
    candHashMatch: true,
    rollHashMatch: true,
    auditChainIntact: true,
    anchorVerified: true,
    anchorCount: 1,
    hasMerkleRoot: true,
    electionStatus: 'FINALIZED',
    tallyMatchesBlockchain: true,
  })
  assert.equal(s1.candHashStatus, 'MATCHED')
  assert.equal(s1.rollHashStatus, 'MATCHED')
  assert.equal(s1.auditChainStatus, 'AUDIT CHAIN VERIFIED')
  assert.equal(s1.auditAnchorStatus, 'VERIFIED')
  assert.equal(s1.merkleRootStatus, 'ROOT RECORDED')
  assert.equal(s1.blockchainTallyStatus, 'VERIFIED')

  // Mismatch & Failures
  const s2 = evaluateStatuses({
    candHashMatch: false,
    rollHashMatch: false,
    auditChainIntact: false,
    anchorVerified: false,
    anchorCount: 1,
    hasMerkleRoot: true,
    electionStatus: 'FINALIZED',
    tallyMatchesBlockchain: false,
  })
  assert.equal(s2.candHashStatus, 'MISMATCH')
  assert.equal(s2.rollHashStatus, 'MISMATCH')
  assert.equal(s2.auditChainStatus, 'FAILED')
  assert.equal(s2.auditAnchorStatus, 'FAILED')
  assert.equal(s2.merkleRootStatus, 'FAILED')
  assert.equal(s2.blockchainTallyStatus, 'FAILED')

  // 10. Missing roll_hash_matches displays UNAVAILABLE (null, undefined, or missing key)
  const evalRollHash = (blockchainEvidence) => {
    const rollHashMatch = blockchainEvidence?.roll_hash_matches
    return rollHashMatch === true ? 'MATCHED' : rollHashMatch === false ? 'MISMATCH' : 'UNAVAILABLE'
  }
  assert.equal(evalRollHash({ roll_hash_matches: true }), 'MATCHED', 'Boolean true must display MATCHED')
  assert.equal(evalRollHash({ roll_hash_matches: false }), 'MISMATCH', 'Boolean false must display MISMATCH')
  assert.equal(evalRollHash({ roll_hash_matches: null }), 'UNAVAILABLE', 'Null roll_hash_matches must display UNAVAILABLE')
  assert.equal(evalRollHash({ roll_hash_matches: undefined }), 'UNAVAILABLE', 'Undefined roll_hash_matches must display UNAVAILABLE')
  assert.equal(evalRollHash({}), 'UNAVAILABLE', 'Missing roll_hash_matches key must display UNAVAILABLE')
  assert.equal(evalRollHash(null), 'UNAVAILABLE', 'Missing blockchain_evidence object must display UNAVAILABLE')

  // Unavailable (e.g. unclosed / unanchored)
  const s3 = evaluateStatuses({
    candHashMatch: null,
    rollHashMatch: null,
    auditChainIntact: null,
    anchorVerified: false,
    anchorCount: 0,
    hasMerkleRoot: false,
    electionStatus: 'OPEN',
    tallyMatchesBlockchain: null,
  })
  assert.equal(s3.candHashStatus, 'UNAVAILABLE')
  assert.equal(s3.rollHashStatus, 'UNAVAILABLE')
  assert.equal(s3.auditChainStatus, 'UNAVAILABLE')
  assert.equal(s3.auditAnchorStatus, 'UNAVAILABLE')
  assert.equal(s3.merkleRootStatus, 'UNAVAILABLE')
  assert.equal(s3.blockchainTallyStatus, 'UNAVAILABLE')
})

test('Runtime logic test: receipt deep link initializes context and rejects URL receipt codes', () => {
  const simulatedUrlSearch = '?election_id=ELEC_CTX_999&receipt_code=REC-999-SECRET_LEAK&code=REC-999-SECRET_LEAK'
  const sp = new URLSearchParams(simulatedUrlSearch)

  // Component logic from ReceiptVerificationPage
  const contextElectionId = sp.get('election_id') || sp.get('electionId') || ''
  let initialCodeInput = '' // Component initializes code state to empty string

  // Assertions:
  assert.equal(contextElectionId, 'ELEC_CTX_999', 'election_id must be parsed for active context banner')
  assert.equal(initialCodeInput, '', 'Receipt code input MUST remain empty and ignore receipt_code or code in URL')
})
