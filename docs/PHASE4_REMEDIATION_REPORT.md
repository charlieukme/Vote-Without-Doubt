# Phase 4 Remediation Report — MetaMask Wallet Integration

**Date:** 2026-10-04
**Target:** Phase 4 "MetaMask wallet integration" of *Vote Without Doubt*
**Trigger:** Independent Phase 4 implementation audit, verdict `FAIL`
**Scope:** Phase 4 only. No Phase 5 face recognition, Phase 6 blockchain, voting, ballot submission, relayer, tally or revoting work was performed.

---

## 1. Original Findings, Root Causes and Fixes

### CRITICAL

| # | Finding | Root cause | Fix |
|---|---------|-----------|-----|
| C1 | `eth_account` missing from the environment and `requirements.txt`; `verify_signature()` always returned `(False, None)`, so no wallet could ever be bound | The dependency was never declared and the module degraded silently | `eth-account==0.13.7` installed and pinned in `backend/requirements.txt`; `security/wallet.py` imports the primitives and `require_wallet_verification()` raises when unavailable; production refuses to boot without it |
| C2 | Missing dependency failure was silent and indistinguishable from an invalid signature | `if not ETH_ACCOUNT_AVAILABLE: return False, None` | A distinct `WalletVerificationUnavailable` exception is raised and propagated; the route returns `503 WALLET_VERIFICATION_UNAVAILABLE`; an operator-facing `logger.error` is emitted |

### HIGH

| # | Finding | Root cause | Fix |
|---|---------|-----------|-----|
| H1 | Signed message lacked the election identifier | `create_auth_message()` had no election parameter | `ElectionID` added, sourced from server configuration, stored on the challenge and bound into the message |
| H2 | Signed message lacked a contract address | No contract context existed in Phase 4 | `Contract` field added using an explicit zero-address sentinel documented as "no contract deployed until Phase 6"; configurable via `WALLET_AUTH_CONTRACT_ADDRESS` |
| H3 | Chain ID hard-coded and never validated against the wallet's network | `chain_id: int = 1337` default; the client chain was never read or checked | `ChainId` is server-configured, sent to the client as `expected_chain_id`, echoed back on bind and rejected when it differs; the frontend reads `eth_chainId` |
| H4 | No real wallet security tests | Only 3 pure-function unit tests | 70 Phase 4 tests, including real signature recovery |
| H5 | No frontend wallet tests | None existed | `frontend/tests/walletFlow.test.mjs` — 22 tests |
| H6 | No signature/replay/binding integration coverage | The flow was never exercised end to end | `tests/test_phase4_wallet_security.py` drives the real service with real signatures |

### MEDIUM

| # | Finding | Root cause | Fix |
|---|---------|-----------|-----|
| M1 | Wallet address format not validated | `normalize_address` only lower-cased | `^0x[0-9a-fA-F]{40}$` plus `eth_utils.is_hex_address`; raises `InvalidWalletAddress`; constant-time comparison via `addresses_equal` |
| M2 | No `accountsChanged` handling | No provider listeners existed | Listener resets the flow, drops the challenge and demands a new one |
| M3 | No `chainChanged` handling | Same | Listener resets the flow and surfaces a network-changed error |
| M4 | No disconnect/reset handling | Same | `disconnect` clears account, chain, binding and challenge state |
| M5 | Nonce not session-bound | `WalletChallenge` had no session column | `session_id` added and required to match the current server-side session during verification |
| M6 | Purpose stored but not in the challenge lookup | Query filtered nonce and user only | Lookup filters `nonce`, `user_id`, `purpose` and `used=False` |
| M7 | Unlimited signature attempts until expiry | No counter | `attempts` / `max_attempts` (5); each invalid signature increments and the challenge is burned when exhausted |

## 2. Files Changed

**Backend**
- `app/security/wallet.py` (rewritten) — real verification, fail-loud dependency handling, address validation, domain-separated message, purpose/attempt constants.
- `app/services/wallet_service.py` (rewritten) — server-authoritative context, fully bound challenge lookup, chain validation, attempt budget, atomic consumption.
- `app/routes/wallet.py` (rewritten) — session-bound challenge issuance, chain/address/purpose handling, `503` on unavailable verification, non-enumerating status.
- `app/models/wallet.py` — `session_id`, `election_id`, `chain_id`, `contract_address`, `attempts`, `max_attempts`, `attempts_exhausted`.
- `app/config/config.py` — `WALLET_AUTH_DOMAIN`, `WALLET_AUTH_ELECTION_ID`, `WALLET_AUTH_CONTRACT_ADDRESS`, `WALLET_AUTH_CHAIN_ID`; production requires working Ethereum verification.
- `app/schema.sql` — challenge table updated to match.
- `migrations/versions/58781e8f838c_*.py` (new) — the six new challenge columns and two indexes.
- `requirements.txt` — `eth-account==0.13.7` pinned.
- `scripts/prove_phase4_wallet.py` (new) — 26-step proof harness.

**Tests**
- `tests/test_wallet.py` (rewritten) — 37 cryptography unit tests.
- `tests/test_phase4_wallet_security.py` (new) — 33 integration/security tests.
- `tests/test_config.py` — updated for the new production checks.

**Frontend**
- `src/Wallet.jsx` (rewritten) — chain read and validation, `accountsChanged`/`chainChanged`/`disconnect` handling with listener cleanup, server-authoritative state, signature cleared after use.
- `tests/walletFlow.test.mjs` (new) — 22 tests.

## 3. Dependency Verification

```
eth-account 0.13.7 installed via pip
pip show eth-account           -> Version: 0.13.7
from eth_account import Account                       -> OK
from eth_account.messages import encode_defunct       -> OK
ETH_ACCOUNT_AVAILABLE                                  -> True
```
`requirements.txt` pins `eth-account==0.13.7`. `Config.validate()` raises in production if `ETH_ACCOUNT_AVAILABLE` is false, so production cannot start with wallet verification disabled.

## 4. Signed Message Format

```
Domain: votewithoutdoubt.local
Purpose: WALLET_AUTHENTICATION
UserID: 1
ElectionID: GENERAL
ChainId: 1337
Contract: 0x0000000000000000000000000000000000000000
Nonce: 80e36535434d9ab16b759d6d1ec59fb14f0d186790274f486bae10021681a7b5
IssuedAt: 2026-10-05T01:19:42.898210Z
ExpiresAt: 2026-10-05T01:29:42.898210Z

This is a wallet ownership proof for authentication only.
Do NOT sign this to vote.
```

No candidate, ballot or vote data appears. `Contract` is a zero-address sentinel because no voting contract is deployed until Phase 6; it is configurable, so the context cannot silently change later. Every value is server-authoritative: the browser may not define any of them.

## 5. Signature Verification Design

MetaMask `personal_sign` signs the EIP-191 personal-sign hash of a UTF-8 string, so verification uses `encode_defunct(text=...)` + `Account.recover_message` — the matching server-side primitive, and the one the test fixtures exercise through the same production path.

Order of operations in `verify_and_bind`:
1. submitted chain id must equal the server-configured chain;
2. claimed address must be a valid Ethereum address;
3. challenge lookup on `nonce` + `user_id` + `purpose` + `used=False`, with `with_for_update`;
4. challenge `session_id` must equal the current server-side session;
5. expiry and attempt budget;
6. recover the signer from the signature over the **stored** message;
7. recovered must equal the claimed address (constant-time);
8. bind only then, and consume the challenge in the same commit.

## 6. Nonce / Session / Purpose Binding

256-bit `secrets.token_hex(32)`, unique column, server-stored. Lookup requires nonce, user, purpose and unused state; session must match; expiry 10 minutes; five invalid attempts burn the challenge; successful use sets `used` and `consumed_at` in the same transaction as the binding.

## 7. Chain Validation

`WALLET_AUTH_CHAIN_ID` (default 1337, the project's Ganache network) is included in the signed message and advertised to the client as `expected_chain_id`. The frontend reads `eth_chainId` and blocks the flow on mismatch. The bind call rejects a mismatched chain before any signature work.

## 8. Wallet Validation

`is_valid_eth_address` and `normalize_address` require `0x` + exactly 40 hex characters and cross-check with `eth_utils.is_hex_address`. Comparison is lowercased and constant-time, so EIP-55 casing cannot bypass the `wallet_address UNIQUE` or `user_id UNIQUE` constraints.

## 9. Frontend Event Handling

`accountsChanged`, `chainChanged` and `disconnect` are subscribed on mount and removed on unmount. Each resets the challenge and signature so nothing signed under a previous account or network can be submitted. The expected chain is taken from the backend, never hard-coded. No private key or seed phrase is ever requested or stored, and the signature is dropped after use.

## 10. Tests Added

- `tests/test_wallet.py` — 37 tests: dependency presence, real sign/recover, nonce entropy, message field coverage and absence of vote data, address validation matrix, malformed signatures, real verification accept/reject.
- `tests/test_phase4_wallet_security.py` — 33 tests driving the real service: authorization, real binding, wrong wallet, modified message/election/chain/contract, expired challenge, replay, cross-user, cross-session, cross-purpose, logout, attempt limit, malformed signature, invalid address, caller-supplied message ignored, caller-supplied wallet without proof, fake frontend state, wallet uniqueness at the DB level, plane separation, no key material stored, no signature logged.
- `frontend/tests/walletFlow.test.mjs` — 22 tests covering MetaMask detection, connect, empty accounts, rejection codes, chain reading and mismatch, all three events plus cleanup, signing, server-authoritative state and secret hygiene.

## 11. Exact Commands and Results

| # | Command | Collected | Passed | Failed | Skipped | Xfailed |
|---|---------|-----------|--------|--------|---------|---------|
| 1 | `venv/Scripts/python -m pytest tests/ -q` | 409 | 409 | 0 | 0 | 0 |
| 2 | `pytest tests/test_wallet.py tests/test_phase4_wallet_security.py -q` | 70 | 70 | 0 | 0 | 0 |
| 3 | `pytest tests/test_phase3_*.py -q` | 66 | 66 | 0 | 0 | 0 |
| 4 | `pytest` Phase 2 modules | 65 | 65 | 0 | 0 | 0 |
| 5 | `pytest tests/test_config.py tests/test_security_foundation.py tests/test_database.py tests/test_models.py tests/test_audit.py -q` | 176 | 176 | 0 | 0 | 0 |
| 6 | `cd frontend && npm test` | 60 | 60 | 0 | 0 | 0 |
| 7 | `cd frontend && npm run build` | — | built in 153ms | 0 | — | — |
| 8 | `pytest tests/ -q -rsx` | 409 | 409 | 0 | 0 | 0 |
| 9 | `venv/Scripts/python -m flake8` on Phase 4 files | — | 0 F/W29/E9 findings | 0 | — | — |
| 10 | `flask db upgrade` + `db check` | — | applied, `No new upgrade operations detected` | 0 | — | — |
| 11 | `venv/Scripts/python scripts/prove_phase4_wallet.py` | 26 proof steps | 26 | 0 | — | — |

Nothing skipped, xfailed, disabled or weakened. Two Phase 2 config tests were updated because production now legitimately requires `ROLL_ADMIN_TOKEN` and working wallet verification.

## 12. End-to-End Proof

`scripts/prove_phase4_wallet.py` uses per-run test-only key material (generated in-process, never committed, never printed) and the real app, database, service and `eth-account` recovery. Observed output:

```
1. eth-account importable                          True
2. challenge issued                                200
3. nonce hex characters (256 bits)                 64
4. purpose stored                                  WALLET_AUTHENTICATION
5. expected chain id                               1337
6. election context                                GENERAL
7. contract context                                0x0000...0000
8. session binding stored                          True
   stored message == served message                True
9. signature produced (bytes)                      64
10. server verification + bind                     200 {'message': 'Wallet bound successfully'}
11. recovered address                              0xf8108e9c5ea9d6e10df16cdc23159366bccf384a
    addresses match                                True
12. binding method                                 personal_sign
13. challenge consumed                             True
14. replay rejected                                400 Invalid challenge
15. wrong wallet rejected                          400 Invalid signature
16. modified message rejected                      400 Invalid signature
17. wrong chain rejected                           400 Unsupported network
18. invalid address rejected                       400 Invalid wallet address
19. cross-session challenge rejected               400 Invalid challenge
20. cross-purpose challenge rejected               400 Invalid challenge
20b. election context (A -> B) rejected            400 Invalid signature
    A-signature still valid for its own nonce      200 Wallet bound successfully
21. attempt limit: invalid codes [400 x5]          correct signature after exhaustion -> 400
22. bind after logout                              401 Unauthorized
23. expired challenge rejected                     400 Challenge expired
24. bound wallets (identity plane)                 2
25. ballot / ballot_queue rows                     0 / 0
26. no private key material persisted              True
```

No private key or raw signature is printed.

## 13. Requirement A–AG Verification

| ID | Requirement | Verdict | Evidence |
|----|-------------|---------|----------|
| A | Wallet detection | PASS | `Wallet.jsx` `window.ethereum`; messages for absent provider; frontend tests |
| B | MetaMask connection | PASS | `eth_requestAccounts`; rejection code 4001 handled; tests |
| C | Correct account retrieval | PASS | Empty-array guard; tests |
| D | Wallet address normalization | PASS | `normalize_address` validates and lowercases; `addresses_equal`; matrix tests |
| E | Registration wallet binding | PASS | End-to-end binding through the real service |
| F | Wallet ownership proof | PASS | Real `eth-account` recovery; proof steps 9–13 |
| G | Signature-based authentication | PASS | Same path; replay/tamper negatives |
| H | `personal_sign` usage | PASS | `personal_sign` with `[challenge.message, account]`; frontend test |
| I | Domain-separated message | PASS | `Domain:` field; config-driven |
| J | Message contents | PASS | All nine fields present; no vote data; unit tests |
| K | Server reconstructs exact message | PASS | Verifies the stored message; client-supplied `message` ignored; test |
| L | Signature verification server-side | PASS | `verify_signature`; proof; `503` when unavailable |
| M | Nonce cryptographically random | PASS | `secrets.token_hex(32)`; 32-byte assertion |
| N | Nonce single-use | PASS | `used`/`consumed_at`; replay test |
| O | Nonce purpose/session bound | PASS | Lookup includes purpose; `session_id` equality enforced; cross-session and cross-purpose tests |
| P | Signature cannot be replayed | PASS | Replay test; proof step 14 |
| Q | Candidate never in signature | PASS | Message contains no vote data; explicit disclaimer; test |
| R | Private key never requested | PASS | No `privateKey`/`mnemonic` in Phase 4 code or UI; frontend test |
| S | Private key never stored | PASS | No key columns; DB-blob test; proof step 26 |
| T | Wallet address identity plane only | PASS | `wallet_bindings.user_id → users.id`; separation test |
| U | Wallet address not caller-controlled | PASS | Recovered must equal claimed; wrong-wallet test |
| V | Wallet account-switch handling | PASS | `accountsChanged` resets flow; cleanup on unmount |
| W | Chain ID validation | PASS | Server-configured, echoed, enforced on bind; mismatch tests |
| X | Contract address validation | PASS | `Contract` in message; tamper test; zero-address sentinel documented |
| Y | Network mismatch handling | PASS | `eth_chainId` read and compared; `Unsupported network` |
| Z | Disconnect handling | PASS | `disconnect` clears account, chain, binding, challenge |
| AA | Backend authorization | PASS | `AUTHORIZED` session required; 401 without |
| AB | Frontend wallet UI | PASS | Full flow with network validation and events; 22 tests |
| AC | Error handling | PASS | Generic messages; `503` + operator log when verification unavailable; no key material in logs |
| AD | Security tests | PASS | 70 Phase 4 tests, real cryptography |
| AE | Integration tests | PASS | 33 tests through the real Flask app, DB and service |
| AF | Phase boundary enforcement | PASS | No `eth_sendTransaction`, typed data, candidate or ballot in Phase 4; frontend test |
| AG | No fake/unsafe implementation | PASS | Real recovery only; dependency failure raises; production boot check |

## 14. Remaining Limitations

1. **No deployed voting contract.** `Contract` is a zero-address sentinel until Phase 6; the field is bound and validated, but it is not yet a real address.
2. **Single election context.** The election in the message comes from configuration because election management arrives in Phase 6/7. It is server-authoritative, but not yet per-election dynamic.
3. **Domain is a constant**, configurable via `WALLET_AUTH_CHAIN_ID`-style env rather than derived from the request host.
4. **`SELECT ... FOR UPDATE` is advisory on SQLite**, so the anti-race guarantee is exercised logically, not under a real row lock; MySQL/InnoDB enforces it.
5. **Frontend tests are source-contract and mocked-provider tests.** They cannot run a real MetaMask extension in CI, so they assert wiring and decisions, not browser behaviour.
6. **The proof harness generates key material per run**, so signatures differ between runs; determinism is by construction, not by a fixed committed key.
7. Wallet binding stores the submitted signature on the challenge record for audit purposes. It is public data, but it is retained rather than discarded.

## 15. Final Verdict

Both CRITICAL findings and all six HIGH findings are resolved with real, executed verification: `eth-account` is installed and pinned, genuine `personal_sign`-compatible signatures verify through the production path, the message binds domain/purpose/identity/election/chain/contract/nonce/timestamps, the challenge is user-, session- and purpose-bound, single-use, expiring and attempt-limited, addresses are validated, and account/chain/disconnect events are handled. 409 backend and 60 frontend tests pass with nothing skipped, and the 26-step proof passes without leaking secrets.

**PHASE 4 REMEDIATION COMPLETE — PASS**