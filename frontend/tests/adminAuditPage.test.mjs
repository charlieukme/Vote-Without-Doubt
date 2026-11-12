import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const AUDIT_SRC = readFileSync(join(HERE, '..', 'src', 'pages', 'admin', 'AdminAuditPage.jsx'), 'utf8')

function resolveAuditChainStatus(chainResult, fallbackEventCount = 0) {
  const isChainIntact = Boolean(
    chainResult.intact ?? chainResult.valid ?? chainResult.chain_intact
  )
  const eventsChecked = chainResult.events_checked ?? chainResult.total_events ?? fallbackEventCount
  return {
    isChainIntact,
    eventsChecked,
    brokenAtId: !isChainIntact && chainResult.broken_at_id != null ? chainResult.broken_at_id : null,
  }
}

test('AdminAuditPage reads backend intact/valid/events_checked fields instead of only chain_intact', () => {
  assert.match(AUDIT_SRC, /chainResult\.intact\s*\?\?\s*chainResult\.valid\s*\?\?\s*chainResult\.chain_intact/)
  assert.match(AUDIT_SRC, /chainResult\.events_checked\s*\?\?\s*chainResult\.total_events/)
  assert.match(AUDIT_SRC, /Broken at Event #/)
})

test('Audit hash-chain status treats backend intact=true payload as INTACT & TAMPER-FREE', () => {
  const backendPayload = {
    events_checked: 42,
    verified_count: 42,
    intact: true,
    valid: true,
    broken_at_id: null,
  }
  const status = resolveAuditChainStatus(backendPayload, 42)
  assert.equal(status.isChainIntact, true)
  assert.equal(status.eventsChecked, 42)
  assert.equal(status.brokenAtId, null)
})

test('Audit hash-chain status treats backend intact=false payload as COMPROMISED with broken_at_id', () => {
  const backendPayload = {
    events_checked: 42,
    verified_count: 17,
    intact: false,
    valid: false,
    broken_at_id: 18,
  }
  const status = resolveAuditChainStatus(backendPayload, 42)
  assert.equal(status.isChainIntact, false)
  assert.equal(status.eventsChecked, 42)
  assert.equal(status.brokenAtId, 18)
})

