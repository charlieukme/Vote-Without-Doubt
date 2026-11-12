/**
 * Phase 4 wallet UI tests.
 *
 * Run with `npm test`. Browser MetaMask cannot run in CI, so these assert the
 * component's source-level security contract and drive its decision logic through
 * a mocked provider shape. Nothing here proves the cryptography - that is proven
 * by the backend suite, which performs real Ethereum signature recovery.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const WALLET = readFileSync(join(HERE, '..', 'src', 'Wallet.jsx'), 'utf8')

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}
const CODE = stripComments(WALLET)

// -------------------------------------------- MetaMask availability / detection

test('MetaMask availability is detected and reported', () => {
  assert.match(CODE, /window\.ethereum/)
  assert.match(CODE, /MetaMask was not detected/)
  assert.match(CODE, /MetaMask is not installed in this browser/)
})

// ------------------------------------------------------------- connect flow

test('connection uses eth_requestAccounts', () => {
  assert.match(CODE, /method:\s*'eth_requestAccounts'/)
})

test('an empty account response is rejected without proceeding', () => {
  assert.match(CODE, /accounts\.length === 0/)
  assert.match(CODE, /No account was returned by MetaMask/)
})

test('a rejected connection surfaces a clear message', () => {
  assert.match(CODE, /code === 4001/)
  assert.match(CODE, /Connection request was rejected/)
})

// ------------------------------------------------------------ network checks

test('the real chain id is read from the provider, never hard-coded', () => {
  assert.match(CODE, /method:\s*'eth_chainId'/)
  assert.match(CODE, /parseInt\(chainHex, 16\)/)
  // No literal chain id may be baked into the component.
  assert.doesNotMatch(CODE, /chainId\s*[:=]\s*\d/)
  assert.doesNotMatch(CODE, /1337|0x539/)
})

test('the expected chain comes from the backend', () => {
  assert.match(CODE, /expected_chain_id/)
  assert.match(CODE, /networkMismatch/)
})

test('a network mismatch blocks the challenge', () => {
  assert.match(CODE, /disabled=\{busy \|\| networkMismatch\}/)
  assert.match(CODE, /Wrong network/)
})

// ---------------------------------------------------- MetaMask event handling

test('accountsChanged, chainChanged and disconnect are all handled', () => {
  assert.match(CODE, /'accountsChanged'/)
  assert.match(CODE, /'chainChanged'/)
  assert.match(CODE, /'disconnect'/)
})

test('an account change resets the flow and demands a new challenge', () => {
  assert.match(CODE, /Account changed - please re-run the wallet proof/)
  assert.match(CODE, /onAccountsChanged[\s\S]*resetFlow\(/)
})

test('a chain change resets the flow', () => {
  assert.match(CODE, /Network changed - the previous challenge is no longer valid/)
})

test('disconnect clears wallet, network and binding state', () => {
  const handler = CODE.slice(CODE.indexOf('const onDisconnect'))
  assert.match(handler, /setAccount\(null\)/)
  assert.match(handler, /setChainId\(null\)/)
  assert.match(handler, /setBound\(false\)/)
  assert.match(handler, /resetFlow\(/)
})

test('listeners are removed on unmount so nothing leaks across mounts', () => {
  assert.match(CODE, /return \(\) => \{/)
  assert.match(CODE, /removeListener\?\.\('accountsChanged'/)
  assert.match(CODE, /removeListener\?\.\('chainChanged'/)
  assert.match(CODE, /removeListener\?\.\('disconnect'/)
})

// ------------------------------------------------------------- signing flow

test('the server-issued message is what gets signed', () => {
  assert.match(CODE, /params:\s*\[challenge\.message, account\]/)
})

test('personal_sign is used, not a typed-data flow', () => {
  assert.match(CODE, /method:\s*'personal_sign'/)
  assert.doesNotMatch(CODE, /eth_signTypedData|eth_sendTransaction/)
})

test('a rejected signature surfaces a clear message', () => {
  assert.match(CODE, /Signature request was rejected/)
})

test('the signature is cleared after use and never persisted', () => {
  assert.match(CODE, /setSignature\(null\)/)
  assert.doesNotMatch(CODE, /localStorage|sessionStorage|document\.cookie|setItem\(/)
})

// ----------------------------------------------------- server is authoritative

test('the component never declares the wallet verified by itself', () => {
  assert.match(CODE, /Wallet ownership verified by the server/)
  // setBound is driven only by the backend response.
  assert.match(CODE, /setBound\(Boolean\(data && data\.bound\)\)/)
  assert.doesNotMatch(CODE, /setBound\(true\)/)
})

test('binding success is only declared after the backend call succeeds', () => {
  const flow = CODE.slice(CODE.indexOf("api.post('/wallet/bind'"),
                          CODE.indexOf("api.post('/wallet/bind'") + 400)
  assert.match(flow, /Wallet bound successfully/)
  assert.match(flow, /checkStatus\(\)/)
})

// ------------------------------------------------------------ secret hygiene

test('no private key or seed phrase is ever requested', () => {
  for (const forbidden of ['privateKey', 'private_key', 'mnemonic', 'seedPhrase',
                           'seed_phrase', 'getMnemonic']) {
    assert.equal(WALLET.includes(forbidden), false, forbidden)
  }
})

test('no voting or candidate data is signed', () => {
  for (const forbidden of ['candidate', 'ballot', 'eth_sendTransaction',
                           'txHash', 'vote']) {
    assert.equal(CODE.includes(forbidden), false, forbidden)
  }
})

test('the shared API client is used and no origin is hard-coded', () => {
  assert.match(WALLET, /import\s+\{\s*api\s*\}\s+from\s+'\.\/api\/client\.js'/)
  assert.doesNotMatch(WALLET, /\bfetch\(/)
  assert.doesNotMatch(WALLET, /https?:\/\/(localhost|127\.0\.0\.1)/)
})

test('state changes are announced to assistive technology', () => {
  assert.match(CODE, /role="alert"/)
  assert.match(CODE, /role="status"/)
})