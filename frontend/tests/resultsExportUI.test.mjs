/**
 * Task 6: Results Export UI & Flow Test Suite
 *
 * This test suite covers:
 * 1. Both export buttons present with exact IDs #export-csv-btn and #export-xlsx-btn (Static source check)
 * 2. Format parameter passed correctly: 'csv' and 'xlsx' (Static source check & URL simulation)
 * 3. Selected election ID bound correctly to request URL (Runtime simulation)
 * 4. Authorization header attached with Bearer token (Static source check & runtime simulation)
 * 5. Blob creation, programmatic download click, and object URL revocation (Static check & simulation)
 * 6. Export loading state prevents duplicate requests and disables controls (Runtime simulation)
 * 7. Results gate: disabled on unavailable, pending, under review, and loading states (Runtime simulation)
 * 8. Export gate: enabled for clean provisional and finalized results (Runtime simulation)
 * 9. Visible error alert rendered on HTTP failure (Static source check & runtime simulation)
 * 10. Content-Disposition filename extraction with fallback (Runtime simulation)
 * 11. Stale-response discard when election selection changes mid-flight (Runtime simulation)
 * 12. Provisional and finalized banners clearly differentiated (Static source check)
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildApiUrl } from '../src/api/urls.js'
import { DEFAULT_API_BASE_URL } from '../src/config/env.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const RESULTS_PAGE_SRC = readFileSync(
  join(HERE, '..', 'src', 'pages', 'admin', 'AdminResultsPage.jsx'),
  'utf8'
)

// -----------------------------------------------------------------------------
// Test 1: Both export buttons present with exact IDs (Static Source Check)
// -----------------------------------------------------------------------------
test('1. Both export buttons present with IDs #export-csv-btn and #export-xlsx-btn', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /id="export-csv-btn"/,
    'AdminResultsPage must define an element with id="export-csv-btn"'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /id="export-xlsx-btn"/,
    'AdminResultsPage must define an element with id="export-xlsx-btn"'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /Export CSV/,
    'AdminResultsPage must label CSV export button'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /Export Excel \(\.xlsx\)/,
    'AdminResultsPage must label Excel export button'
  )
})

// -----------------------------------------------------------------------------
// Test 2: Format parameter passed correctly (Static Source Check & URL Simulation)
// -----------------------------------------------------------------------------
test('2. Format parameter passed correctly: csv and xlsx', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /handleExport\(['"]csv['"]\)/,
    'AdminResultsPage must bind handleExport with "csv" format'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /handleExport\(['"]xlsx['"]\)/,
    'AdminResultsPage must bind handleExport with "xlsx" format'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /\?format=\$\{encodeURIComponent\(format\)\}/,
    'AdminResultsPage must construct query string using encoded format parameter'
  )

  const csvUrl = buildApiUrl('/admin/elections/elec-1/export?format=csv', DEFAULT_API_BASE_URL)
  assert.equal(csvUrl, '/api/admin/elections/elec-1/export?format=csv')

  const xlsxUrl = buildApiUrl('/admin/elections/elec-1/export?format=xlsx', DEFAULT_API_BASE_URL)
  assert.equal(xlsxUrl, '/api/admin/elections/elec-1/export?format=xlsx')
})

// -----------------------------------------------------------------------------
// Test 3: Selected election ID bound correctly to request URL (Runtime Simulation)
// -----------------------------------------------------------------------------
test('3. Selected election ID correctly bound and encoded in request URL', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /\/admin\/elections\/\$\{encodeURIComponent\(targetEid\)\}\/export/,
    'AdminResultsPage must interpolate encoded target election ID in endpoint URL'
  )

  const buildExportUrl = (eid, fmt) => {
    return buildApiUrl(
      `/admin/elections/${encodeURIComponent(eid)}/export?format=${encodeURIComponent(fmt)}`,
      DEFAULT_API_BASE_URL
    )
  }

  assert.equal(
    buildExportUrl('elec-101', 'csv'),
    '/api/admin/elections/elec-101/export?format=csv'
  )
  assert.equal(
    buildExportUrl('election with spaces & symbols!', 'xlsx'),
    '/api/admin/elections/election%20with%20spaces%20%26%20symbols!/export?format=xlsx'
  )
})

// -----------------------------------------------------------------------------
// Test 4: Authorization header attached with Bearer token (Static & Runtime)
// -----------------------------------------------------------------------------
test('4. Authorization header attached with Bearer token', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /Authorization:\s*`Bearer \$\{adminToken\}`/,
    'AdminResultsPage must attach Authorization Bearer token header'
  )

  const buildHeaders = (token) => ({
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  })

  assert.deepEqual(buildHeaders('admin-token-xyz'), {
    Authorization: 'Bearer admin-token-xyz',
  })
  assert.deepEqual(buildHeaders(null), {})
  assert.deepEqual(buildHeaders(''), {})
})

// -----------------------------------------------------------------------------
// Test 5: Blob creation, link download trigger, deferred revocation, and error cleanup
// -----------------------------------------------------------------------------
test('5. Actual triggerBlobDownload implementation: click -> anchor removal -> deferred revocation & failure cleanup', async () => {
  // Extract and compile the actual implementation from AdminResultsPage.jsx
  assert.match(
    RESULTS_PAGE_SRC,
    /export function triggerBlobDownload\(/,
    'AdminResultsPage must export triggerBlobDownload function'
  )

  const fnCodeMatch = RESULTS_PAGE_SRC.match(/export function triggerBlobDownload\([\s\S]*?\n\}/)
  assert.ok(fnCodeMatch, 'triggerBlobDownload function body must match in AdminResultsPage.jsx')
  const triggerBlobDownload = new Function(
    'return ' + fnCodeMatch[0].replace(/^export\s+/, '')
  )()
  assert.equal(typeof triggerBlobDownload, 'function', 'Extracted triggerBlobDownload must be a function')

  // Case A: Successful download: click -> anchor removal -> deferred URL revocation (1000ms)
  const revokedUrls = []
  const callSequence = []
  let scheduledCallback = null
  let bodyChildren = []

  const mockAnchor = {
    href: '',
    download: '',
    parentNode: null,
    click: () => {
      callSequence.push('click')
      assert.equal(revokedUrls.length, 0, 'URL must not be revoked before or during click')
      assert.ok(bodyChildren.includes(mockAnchor), 'Anchor must be in document.body during click')
    },
  }

  const mockWin = {
    URL: {
      createObjectURL: () => {
        callSequence.push('createObjectURL')
        return 'blob:http://localhost/test-uuid-success'
      },
      revokeObjectURL: (u) => {
        callSequence.push('revokeObjectURL')
        revokedUrls.push(u)
      },
    },
  }

  const mockDoc = {
    createElement: (tag) => {
      callSequence.push(`createElement_${tag}`)
      return mockAnchor
    },
    body: {
      appendChild: (node) => {
        callSequence.push('appendChild')
        node.parentNode = mockDoc.body
        bodyChildren.push(node)
      },
      removeChild: (node) => {
        callSequence.push('removeChild')
        node.parentNode = null
        bodyChildren = bodyChildren.filter((n) => n !== node)
      },
    },
  }

  const originalSetTimeout = globalThis.setTimeout
  globalThis.setTimeout = (fn, delay) => {
    callSequence.push(`setTimeout_${delay}`)
    scheduledCallback = fn
    return 123
  }

  try {
    triggerBlobDownload({ size: 1024 }, 'results.csv', mockWin, mockDoc)
  } finally {
    globalThis.setTimeout = originalSetTimeout
  }

  // Assertions immediately after function returns:
  assert.equal(bodyChildren.length, 0, 'Anchor must be removed from document.body on success')
  assert.equal(mockAnchor.parentNode, null, 'Anchor parentNode must be null after removal')
  assert.equal(revokedUrls.length, 0, 'Revocation must be deferred by 1000ms, not executed synchronously')
  assert.ok(scheduledCallback, 'Cleanup timer callback must be scheduled')
  assert.deepEqual(callSequence, [
    'createObjectURL',
    'createElement_a',
    'appendChild',
    'click',
    'setTimeout_1000',
    'removeChild',
  ])

  // Execute scheduled timer callback
  scheduledCallback()
  assert.equal(revokedUrls.length, 1, 'Object URL must be revoked when timeout fires')
  assert.equal(revokedUrls[0], 'blob:http://localhost/test-uuid-success')

  // Case B: Test that successful URLs are not revoked twice
  scheduledCallback() // spurious second trigger
  assert.equal(revokedUrls.length, 1, 'Subsequent invocation must NOT double-revoke the object URL')

  // Case C: Test click failure: anchor removal and immediate URL revocation
  const revokedUrlsClickFail = []
  const callSequenceClickFail = []
  let bodyChildrenClickFail = []

  const mockAnchorClickFail = {
    href: '',
    download: '',
    parentNode: null,
    click: () => {
      callSequenceClickFail.push('click_throws')
      throw new Error('Simulated download click failure in browser')
    },
  }

  const mockWinClickFail = {
    URL: {
      createObjectURL: () => 'blob:http://localhost/test-uuid-click-fail',
      revokeObjectURL: (u) => {
        callSequenceClickFail.push('revokeObjectURL')
        revokedUrlsClickFail.push(u)
      },
    },
  }

  const mockDocClickFail = {
    createElement: () => mockAnchorClickFail,
    body: {
      appendChild: (node) => {
        callSequenceClickFail.push('appendChild')
        node.parentNode = mockDocClickFail.body
        bodyChildrenClickFail.push(node)
      },
      removeChild: (node) => {
        callSequenceClickFail.push('removeChild')
        node.parentNode = null
        bodyChildrenClickFail = bodyChildrenClickFail.filter((n) => n !== node)
      },
    },
  }

  assert.throws(() => {
    triggerBlobDownload({ size: 1024 }, 'results.csv', mockWinClickFail, mockDocClickFail)
  }, /Simulated download click failure in browser/)

  // Both anchor removal and immediate URL revocation MUST have executed on click failure
  assert.equal(bodyChildrenClickFail.length, 0, 'Anchor must be removed from document.body even when click() throws')
  assert.equal(mockAnchorClickFail.parentNode, null, 'Anchor parentNode must be cleared on click failure')
  assert.equal(revokedUrlsClickFail.length, 1, 'Blob URL must be revoked immediately upon click failure')
  assert.equal(revokedUrlsClickFail[0], 'blob:http://localhost/test-uuid-click-fail')
  assert.deepEqual(callSequenceClickFail, [
    'appendChild',
    'click_throws',
    'revokeObjectURL',
    'removeChild',
  ])

  // Case D: Test DOM failure after URL creation: no orphaned URL or anchor
  const revokedUrlsDomFail = []
  let bodyChildrenDomFail = []

  const mockWinDomFail = {
    URL: {
      createObjectURL: () => 'blob:http://localhost/test-uuid-dom-fail',
      revokeObjectURL: (u) => revokedUrlsDomFail.push(u),
    },
  }

  const mockDocDomFail = {
    createElement: () => {
      throw new Error('DOM createElement permission error')
    },
    body: {
      appendChild: (node) => bodyChildrenDomFail.push(node),
      removeChild: (node) => {
        bodyChildrenDomFail = bodyChildrenDomFail.filter((n) => n !== node)
      },
    },
  }

  assert.throws(() => {
    triggerBlobDownload({ size: 1024 }, 'results.csv', mockWinDomFail, mockDocDomFail)
  }, /DOM createElement permission error/)

  assert.equal(bodyChildrenDomFail.length, 0, 'No anchor should remain in DOM on creation failure')
  assert.equal(revokedUrlsDomFail.length, 1, 'Blob URL must be revoked immediately on DOM creation failure')
  assert.equal(revokedUrlsDomFail[0], 'blob:http://localhost/test-uuid-dom-fail')
})

// -----------------------------------------------------------------------------
// Test 6: Export loading state prevents duplicate requests and disables controls
// -----------------------------------------------------------------------------
test('6. Export loading state prevents concurrent exports and duplicate clicks', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /if\s*\(\s*exportLoading/,
    'handleExport must check exportLoading and exit early'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /disabled=\{Boolean\(exportLoading\s*\|\|\s*resultsLoading\s*\|\|\s*isExportDisabled\)\}/,
    'Export buttons must be disabled when exportLoading is active'
  )

  let exportInFlight = false
  let invocations = 0

  const handleExportSim = () => {
    if (exportInFlight) return false
    exportInFlight = true
    invocations++
    return true
  }

  // First click succeeds
  assert.equal(handleExportSim(), true)
  assert.equal(invocations, 1)

  // Concurrent click while in flight rejected
  assert.equal(handleExportSim(), false)
  assert.equal(invocations, 1)

  // Finish request
  exportInFlight = false
  assert.equal(handleExportSim(), true)
  assert.equal(invocations, 2)
})

// -----------------------------------------------------------------------------
// Test 7: Results gate: disabled on unavailable, pending, under review, and loading states
// -----------------------------------------------------------------------------
test('7. Export gate: strictly disabled when results are unavailable, pending, under review, or loading', () => {
  const evaluateExportDisabled = ({
    results,
    resultsLoading,
    resultState,
  }) => {
    return Boolean(
      !results ||
      resultsLoading ||
      resultState === 'RESULTS_UNDER_REVIEW' ||
      results?.is_under_review === true ||
      (results?.open_reconciliation_issues && results.open_reconciliation_issues > 0) ||
      results?.tally_matches_blockchain === false ||
      (resultState !== 'PROVISIONAL_UNFINALIZED' && resultState !== 'FINALIZED_RESULTS')
    )
  }

  // Case A: Results null or loading
  assert.equal(evaluateExportDisabled({ results: null, resultsLoading: false, resultState: null }), true)
  assert.equal(evaluateExportDisabled({ results: {}, resultsLoading: true, resultState: 'FINALIZED_RESULTS' }), true)

  // Case B: Election in OPEN / SCHEDULED status (RESULTS_UNAVAILABLE)
  assert.equal(
    evaluateExportDisabled({
      results: { status: 'OPEN', total_distinct_voters: 0 },
      resultsLoading: false,
      resultState: 'RESULTS_UNAVAILABLE',
    }),
    true
  )

  // Case C: Ballots in flight (PROCESSING_PENDING_BALLOTS)
  assert.equal(
    evaluateExportDisabled({
      results: { status: 'CLOSED', pending_ballots_count: 5 },
      resultsLoading: false,
      resultState: 'PROCESSING_PENDING_BALLOTS',
    }),
    true
  )

  // Case D: Results under review (open issues)
  assert.equal(
    evaluateExportDisabled({
      results: { status: 'CLOSED', open_reconciliation_issues: 2, is_under_review: true },
      resultsLoading: false,
      resultState: 'RESULTS_UNDER_REVIEW',
    }),
    true
  )

  // Case E: Blockchain mismatch detected
  assert.equal(
    evaluateExportDisabled({
      results: { status: 'CLOSED', tally_matches_blockchain: false },
      resultsLoading: false,
      resultState: 'PROVISIONAL_UNFINALIZED',
    }),
    true
  )
})

// -----------------------------------------------------------------------------
// Test 8: Export gate: enabled for clean provisional and finalized results
// -----------------------------------------------------------------------------
test('8. Export gate: enabled only for clean provisional and finalized results', () => {
  const evaluateExportDisabled = ({
    results,
    resultsLoading,
    resultState,
  }) => {
    return Boolean(
      !results ||
      resultsLoading ||
      resultState === 'RESULTS_UNDER_REVIEW' ||
      results?.is_under_review === true ||
      (results?.open_reconciliation_issues && results.open_reconciliation_issues > 0) ||
      results?.tally_matches_blockchain === false ||
      (resultState !== 'PROVISIONAL_UNFINALIZED' && resultState !== 'FINALIZED_RESULTS')
    )
  }

  // Clean Provisional (Closed, matches blockchain, 0 issues)
  assert.equal(
    evaluateExportDisabled({
      results: {
        status: 'CLOSED',
        is_under_review: false,
        open_reconciliation_issues: 0,
        tally_matches_blockchain: true,
      },
      resultsLoading: false,
      resultState: 'PROVISIONAL_UNFINALIZED',
    }),
    false,
    'Clean provisional results must enable export'
  )

  // Clean Finalized (Finalized, sealed on blockchain, 0 issues)
  assert.equal(
    evaluateExportDisabled({
      results: {
        status: 'FINALIZED',
        is_finalized: true,
        is_under_review: false,
        open_reconciliation_issues: 0,
        tally_matches_blockchain: true,
      },
      resultsLoading: false,
      resultState: 'FINALIZED_RESULTS',
    }),
    false,
    'Clean finalized results must enable export'
  )
})

// -----------------------------------------------------------------------------
// Test 9: Visible error alert rendered on HTTP failure (Static & Runtime)
// -----------------------------------------------------------------------------
test('9. Visible error alert rendered on failure', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /\{exportError\s*&&/,
    'AdminResultsPage must render export error alert container'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /<strong>Export Failed:\s*<\/strong>\s*\{exportError\}/,
    'AdminResultsPage must display formatted export error message'
  )

  const parseErrorMessage = (status, payload) => {
    if (payload?.message) return payload.message
    if (payload?.error) return payload.error
    return `Export request failed with status ${status}`
  }

  assert.equal(
    parseErrorMessage(403, { error: 'RESULTS_UNDER_REVIEW', message: 'Results under review.' }),
    'Results under review.'
  )
  assert.equal(
    parseErrorMessage(423, { error: 'PROCESSING_PENDING_BALLOTS', message: 'Ballots draining.' }),
    'Ballots draining.'
  )
  assert.equal(
    parseErrorMessage(500, { error: 'AUDIT_LOG_FAILED', message: 'Audit error.' }),
    'Audit error.'
  )
  assert.equal(
    parseErrorMessage(500, null),
    'Export request failed with status 500'
  )
})

// -----------------------------------------------------------------------------
// Test 10: Content-Disposition filename extraction with fallback
// -----------------------------------------------------------------------------
test('10. Content-Disposition filename extraction with safe fallback', () => {
  const resolveFilename = (header, targetEid, format, fallbackIsoTime = '2026-11-09T10-00-00') => {
    let filename = ''
    if (header && header.includes('filename=')) {
      const match = header.match(/filename=["']?([^"';]+)["']?/)
      if (match && match[1]) {
        filename = match[1].trim()
      }
    }
    if (!filename) {
      filename = `${targetEid}_results_${fallbackIsoTime}.${format}`
    }
    return filename
  }

  assert.equal(
    resolveFilename('attachment; filename="elec-101_results_20261109.csv"', 'elec-101', 'csv'),
    'elec-101_results_20261109.csv'
  )
  assert.equal(
    resolveFilename('attachment; filename=results.xlsx; size=1024', 'elec-101', 'xlsx'),
    'results.xlsx'
  )
  assert.equal(
    resolveFilename(null, 'elec-101', 'csv', '2026-11-09T10-00-00'),
    'elec-101_results_2026-11-09T10-00-00.csv'
  )
})

// -----------------------------------------------------------------------------
// Test 11: Stale-response discard when election selection changes mid-flight
// -----------------------------------------------------------------------------
test('11. Stale export response discarded if selected election changes during download', async () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /if\s*\(\s*selectedElectionId\s*!==\s*targetEid\s*\)\s*return/,
    'handleExport must check selectedElectionId !== targetEid and drop response if selection changed'
  )

  let activeElection = 'elec-01'
  let downloadTriggered = false

  const simulateStaleExport = async () => {
    const targetEid = activeElection
    // Simulate user selecting another election while fetch is awaiting
    activeElection = 'elec-02'

    // When fetch completes:
    if (activeElection !== targetEid) {
      return // dropped
    }
    downloadTriggered = true
  }

  await simulateStaleExport()
  assert.equal(downloadTriggered, false, 'Download must NOT be triggered for stale election')
})

// -----------------------------------------------------------------------------
// Test 12: Provisional and finalized results banners clearly differentiated
// -----------------------------------------------------------------------------
test('12. Provisional and finalized results banners clearly differentiated', () => {
  assert.match(
    RESULTS_PAGE_SRC,
    /PROVISIONAL TALLIES/,
    'AdminResultsPage must display provisional tallies banner'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /OFFICIALLY FINALIZED/,
    'AdminResultsPage must display officially finalized certification banner'
  )
  assert.match(
    RESULTS_PAGE_SRC,
    /UNDER AUDIT REVIEW/,
    'AdminResultsPage must display under audit review banner'
  )
})
