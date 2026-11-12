import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')
const readSrc = (relPath) => readFileSync(join(SRC, relPath), 'utf8')

const ROUTER_SRC = readSrc('router/RouterContext.jsx')
const APP_SRC = readSrc('App.jsx')
const ADMIN_ELECTIONS_SRC = readSrc('pages/admin/AdminElectionsPage.jsx')
const ADMIN_CANDIDATES_SRC = readSrc('pages/admin/AdminCandidatesPage.jsx')

test('RouterContext extracts electionId from /admin/candidates/:id route', () => {
  assert.match(ROUTER_SRC, /adminCandidateMatch = pathname\.match/)
  assert.match(ROUTER_SRC, /admin\/candidates/)
  assert.match(ROUTER_SRC, /electionId: adminCandidateMatch\[1\]/)
})

test('RouterContext extracts election_id from query parameters', () => {
  assert.match(ROUTER_SRC, /queryParams\.election_id/)
})

test('App.jsx routes dynamic /admin/candidates/:id paths to AdminCandidatesPage', () => {
  assert.match(APP_SRC, /path\.startsWith\('\/admin\/candidates\/'\)/)
})

test('AdminElectionsPage Candidates button passes exact el.election_id', () => {
  assert.match(ADMIN_ELECTIONS_SRC, /navigate\(`\/admin\/candidates\/\$\{el\.election_id\}`\)/)
  // Ensure no bare /admin/candidates navigation without election id
  assert.doesNotMatch(ADMIN_ELECTIONS_SRC, /navigate\('\/admin\/candidates'\)/)
})

test('AdminCandidatesPage does not hardcode election ID "1"', () => {
  assert.doesNotMatch(ADMIN_CANDIDATES_SRC, /useState\(['"]1['"]\)/)
})

test('AdminCandidatesPage parses route parameter and loads election title', () => {
  assert.match(ADMIN_CANDIDATES_SRC, /useRouter/)
  assert.match(ADMIN_CANDIDATES_SRC, /params\?\.electionId/)
  assert.match(ADMIN_CANDIDATES_SRC, /election\?\.title/)
  assert.match(ADMIN_CANDIDATES_SRC, /\/admin\/elections\/\$\{.*\}\/candidates/)
})
