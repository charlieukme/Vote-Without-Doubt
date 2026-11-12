# PHASE 10 REMEDIATION REPORT — RECOVERY & RECONCILIATION

**Project:** AI & Blockchain-Based Secure E-Voting System for College Elections  
**Product:** Vote Without Doubt  
**Repository:** `.`  
**Date:** 2026-10-06  
**Status:** REMEDIATION IMPLEMENTED — READY FOR INDEPENDENT RE-AUDIT  

---

## 1. Executive Summary

Phase 10 — Recovery & Reconciliation has been remediated and fully implemented. The independent security audit previously returned **FAIL** due to critical gaps: crash-after-broadcast left ballots permanently stuck in `SUBMITTED`, confirmed blockchain transactions could remain invisible to the database, a voter could become permanently blocked by `PREVIOUS_BALLOT_PENDING`, startup recovery ignored `SUBMITTED` ballots, no genuine DB ↔ Blockchain reconciliation engine existed, tally and sequence reconciliation was absent, and idempotency tests were hollow stubs.

This remediation implements real recovery and reconciliation while strictly preserving all frozen security and privacy invariants from Phases 6, 7, 8, and 9:
1. **Crash Recovery Across Process Boundaries**: `RecoveryService.startup_recover()` inspects in-flight ballots (`QUEUED` and `SUBMITTED`). Mined receipts with `status == 1` transition to `CONFIRMED` / `FINALIZED`; reverted transactions (`status == 0`) transition to `FAILED` with explicit `TX_REVERTED` metadata; unbroadcast ballots (`tx_hash == NULL`) safely return to `QUEUED` with incremented `retry_count`.
2. **Pending Transaction Safety**: Transactions pending in the mempool or awaiting mining are kept safely recoverable (`state='SUBMITTED'`, `reconcile_required=True`, `reconcile_reason='TX_PENDING'`) and are never falsely finalized or prematurely dropped.
3. **Genuine Bidirectional Reconciliation**: A full `ReconciliationService` engine compares authoritative blockchain state from `EVotingBallotBox.sol` against the database for candidate tallies, distinct voter counts, active voter sequences, and stale in-flight transactions. Discrepancies are logged as `ReconciliationIssue` records with deduplication, severity ratings, and audit event emissions.
4. **Relayer Concurrency Protection**: Atomic database row updates (`Ballot.query.filter(id==b.id, state=='QUEUED').update({'state': 'SUBMITTED', ...})`) guarantee mutual exclusion across concurrent relayer workers, preventing duplicate blockchain submissions.
5. **Genuinely Tested & Proven**: Verified with a comprehensive 11-test unit/integration suite (`tests/test_recovery.py`) and a 48-check live Ganache proof script (`backend/scripts/prove_phase10_recovery.py`) covering all 13 specified test scenarios. Full regression testing confirmed zero regressions across Phases 6, 7, 8, and 9.

---

## 2. Files Changed

| File | Change Description |
|---|---|
| `backend/app/services/recovery.py` | Complete overhaul of `RecoveryService`. Implemented crash recovery for `SUBMITTED` ballots with/without `tx_hash`, mined status 1/0 handling, unbroadcast requeuing, pending transaction safety, genuine idempotency verification (`is_idempotent_ok`), and audit logging. |
| `backend/app/services/reconciliation_service.py` | New service implementing bidirectional DB ↔ Blockchain reconciliation: `reconcile_election` (tallies, distinct voters, sequence consistency, stale check), `reconcile_all_active_elections`, `resolve_issue`, and `AuditLogger` integration. |
| `backend/app/models/reconciliation.py` | Verified and preserved `ReconciliationIssue` ORM model, matching migration schema and foreign key constraints. |
| `backend/app/relayer/relayer.py` | Implemented atomic database row claiming (`filter(id==b.id, state=='QUEUED').update(...)`) to prevent multi-worker double-broadcast; safely caught `TimeExhausted` timeouts to prevent false failures. |
| `backend/app/services/__init__.py` | Export module exposing `RecoveryService`, `ReconciliationService`, and `VotingService`. |
| `backend/app/routes/voting.py` | Added live recovery check in `GET /voting/status` so voters query real-time confirmation on demand without administrative intervention. |
| `backend/tests/test_recovery.py` | Replaced hollow stubs with 11 substantive unit/integration tests covering crash recovery, receipt mining, reverts, unbroadcast requeue, tally/voter/sequence reconciliation, atomic worker claims, Phase 9 revotes, and privacy preservation. |
| `backend/scripts/prove_phase10_recovery.py` | New live Ganache verification proof script covering all 13 required failure injection and reconciliation scenarios (48/48 checks passing). |
| `PROJECT_BIBLE.md` | Updated authoritative Phase 10 status to `REMEDIATION IMPLEMENTED — READY FOR RE-AUDIT`, added Phase 8–10 verification records, and updated evidence caveats. |

---

## 3. Recovery Architecture

The recovery subsystem is anchored by `RecoveryService.startup_recover(app=None, detailed=False)`.

```
                    +---------------------------+
                    | Startup / Recovery Cycle  |
                    +---------------------------+
                                  |
                   Query QUEUED + SUBMITTED ballots
                                  |
          +-----------------------+-----------------------+
          |                                               |
  State: SUBMITTED                                  State: QUEUED
          |                                               |
  +-------+-------+                               Check if already on-chain
  |               |                                       |
tx_hash NULL   tx_hash PRESENT                            +-- Yes -> FINALIZED
  |               |                                       +-- No  -> Flag stale if
  |               v                                                  age > 5 min
  |        Query Receipt on-chain
  |               |
  |        +------+------+------+
  |        |             |      |
  |     Status=1      Status=0 No Receipt
  |        |             |      |
  |   FINALIZED       FAILED    +-- In mempool? -> Keep SUBMITTED (TX_PENDING)
  |                             +-- On-chain?   -> FINALIZED (RECOVERED_ON_CHAIN)
  |                             +-- Timed out?  -> QUEUED (REQUEUED_MISSING_TX)
  |
  +-- Check if on-chain?
        +-- Yes -> FINALIZED (RECOVERED_ON_CHAIN)
        +-- No  -> Safely return to QUEUED (retry_count += 1)
```

---

## 4. Ballot State Machine

The state machine implements valid, monotone transitions backed strictly by authoritative evidence:

```
[QUEUED] ──(relayer claims & broadcasts)──> [SUBMITTED]
   │                                              │
   │                                        receipt status=1 (mined)
   │                                              │
   │                                              v
   │                                        [CONFIRMED]
   │                                              │
   │                                        receipt generated
   │                                              │
   │                                              v
   │                                        [FINALIZED]
   │
   └──(unbroadcast crash) <─── [SUBMITTED] (requeued)
                                     │
                             receipt status=0 (reverted)
                                     │
                                     v
                                  [FAILED]
```

### Prohibited Transitions:
- Never transition to `CONFIRMED` or `FINALIZED` without on-chain receipt evidence (`status == 1`).
- Never discard or drop an in-flight ballot silently.
- Never transition pending mempool transactions to `FAILED` solely on timeout exhaustion.
- Never resurrect or alter a finalized ballot.

---

## 5. Crash Scenarios Covered

1. **Crash before broadcast (`SUBMITTED`, `tx_hash = NULL`, no tx on chain)**:
   - Recovery queries `contract.functions.getBallot()`.
   - Confirms ballot is absent on-chain.
   - Safely resets state to `QUEUED` with incremented `retry_count` and reason `'REQUEUED_UNBROADCAST'`.
   - Relayer picks up ballot on next cycle and broadcasts cleanly.
2. **Crash after broadcast before `tx_hash` persistence**:
   - Recovery inspects `contract.functions.getBallot(election_id, pseudonym)`.
   - If sequence matches on chain: converges DB record directly to `FINALIZED` (`'RECOVERED_ON_CHAIN'`).
   - If definitely absent: safely returns to `QUEUED`.
3. **Crash after broadcast with `tx_hash` (`SUBMITTED`, `tx_hash` mined)**:
   - Recovery queries `w3.eth.get_transaction_receipt(tx_hash)`.
   - Discovers `status == 1` and `blockNumber`.
   - Transitions ballot to `CONFIRMED` -> `FINALIZED`, sets `tx_confirmed_at`, issues HMAC receipt code, and emits audit event.
4. **Reverted transaction on blockchain (`status == 0`)**:
   - Recovery queries receipt, detects `status == 0`.
   - Transitions ballot to `FAILED`, sets `tx_failed_at`, flags `reconcile_required=True` with reason `'TX_REVERTED'`.
   - Prevents false finalization and prevents infinite retransmission.
5. **Pending transaction / Mempool delay**:
   - Receipt returns `None`, but `w3.eth.get_transaction(tx_hash)` reveals pending transaction in mempool.
   - Ballot is retained safely in `SUBMITTED` state with `reconcile_required=True, reconcile_reason='TX_PENDING'`.
   - Neither prematurely marked `FINALIZED` nor marked `FAILED`.
6. **Application Restart Boundary**:
   - Fresh Flask application context instantiates on boot.
   - Boot hook calls `RecoveryService.startup_recover()`.
   - Discovers and converges all interrupted records before serving user requests.

---

## 6. Reconciliation Architecture

The `ReconciliationService` acts as an independent auditor comparing DB state against on-chain smart contract facts:

1. **Candidate Tallies**:
   - Iterates through all candidates `0 .. candidateCount-1`.
   - Queries `contract.functions.getTally(election_id, cand_idx)`.
   - Queries DB for active, non-superseded, finalized, non-null ballots: `BallotRecord.query.filter_by(election_id=..., candidate=cand_idx, state='FINALIZED', superseded=False, is_null=False).count()`.
   - If mismatched, creates a `ReconciliationIssue` (`issue_type='TALLY_MISMATCH'`, `severity='HIGH'`).
2. **Distinct Active Voters**:
   - Queries `electionInfo.distinctVoters` on chain.
   - Counts distinct voter pseudonyms in DB with finalized active ballots.
   - Flags discrepancies under `issue_type='DISTINCT_VOTER_MISMATCH'`.
3. **Sequence Consistency**:
   - Queries `contract.functions.getBallot(election_id, pseudo_bytes)`.
   - Compares on-chain `sequence` (index 0) against DB latest finalized ballot `sequence`.
   - Flags discrepancies under `issue_type='SEQUENCE_MISMATCH'`.
4. **Stale In-Flight Ballots**:
   - Identifies ballots stuck in `SUBMITTED` older than 2 minutes.
   - Flags under `issue_type='STALE_SUBMITTED'`.
5. **Issue Deduplication**:
   - Before inserting a new `ReconciliationIssue`, checks for existing `OPEN` issues matching `(election_id, issue_type)`. Prevents database pollution across repeated runs.

---

## 7. DB ↔ Blockchain Authority Rules

| Fact | Authoritative Source | Reason |
|---|---|---|
| Ballot Committed | **Blockchain** | Decentralized, immutable truth of accepted votes. |
| Transaction Status (Mined/Reverted) | **Blockchain** | Authoritative receipt status from Ganache consensus. |
| Candidate Tally | **Blockchain** | Smart contract `getTally()` is authoritative for election outcome. |
| Distinct Voter Count | **Blockchain** | Smart contract `distinctVoters` is authoritative. |
| Voter Sequence On-Chain | **Blockchain** | Smart contract `getBallot().sequence` is authoritative. |
| Operational State (`QUEUED`, `SUBMITTED`) | **Database** | Relayer pipeline state before mining. |
| Retry Count & Timestamps | **Database** | Transient operational and failure metrics. |
| Voter Identity / Roll | **Database** | Sensitive identity plane data strictly isolated from blockchain. |
| HMAC Receipt Code | **Database** | Off-chain voter receipt for privacy-preserving verification. |

---

## 8. Idempotency Design

Recovery is mathematically and operationally idempotent:
$$\text{recover}(\text{state}) = \text{recover}(\text{recover}(\text{state}))$$

1. First pass discovers all in-flight ballots and transitions them based on on-chain evidence.
2. Second pass finds zero ballots in transitionable state (all in-flight ballots are now `FINALIZED`, `FAILED`, or flagged `TX_PENDING`).
3. `RecoveryService.is_idempotent_ok()` performs a dual-pass verification and asserts that pass 2 produces 0 mutations.
4. No duplicate ballots, duplicate blockchain calls, sequence increments, or premature key destructions can occur on repeated recovery.

---

## 9. Relayer Concurrency Protection

To prevent race conditions when multiple relayer workers run concurrently:
```python
claimed = Ballot.query.filter(
    Ballot.id == b.id,
    Ballot.state == 'QUEUED',
).update({
    'state': 'SUBMITTED',
    'tx_broadcast_at': datetime.utcnow(),
}, synchronize_session=False)
db.session.commit()
if not claimed:
    continue  # Another worker already claimed this ballot
```
- Worker A updates the row from `QUEUED` to `SUBMITTED`.
- Worker B simultaneously attempting to claim the same row finds `state != 'QUEUED'`; update returns 0 affected rows.
- Exactly one worker broadcasts to the blockchain, eliminating duplicate transactions.

---

## 10. Phase 9 Revote Recovery

Phase 10 recovery integrates cleanly with Phase 9 revoting rules:
1. **Sequence Monotonicity**: A recovered sequence 1 ballot (`FINALIZED`) correctly unlocks sequence 2 revoting for the voter.
2. **Latest-Vote-Wins Preservation**: Sequence 2 overrides Sequence 1 on chain; DB marks sequence 1 as `superseded=True`. Recovery never un-supersedes older sequence ballots.
3. **Null Revote Preservation**: When a voter casts sequence 3 null ballot, candidate tallies decrement on chain. Recovery and reconciliation verify that candidate tallies remain 0 and DB active state reflects null choice.
4. **Cooldown & Authentication Enforced**: Recovery does not alter session cookies, authorization tokens, or cooldown timers. A voter must always pass 120-second cooldown and fresh MFA factors to revote.

---

## 11. Privacy Preservation

Recovery and reconciliation strictly adhere to Phase 8 privacy invariants:
- **No Private Data in Logs**: Audit logs and reconciliation issues store only `ballot_id`, `election_id`, `sequence`, and `block_number`. No plain voter IDs, USNs, candidate names, pseudonyms, or wallet addresses are logged.
- **Voter-Facing Status Privacy**: `GET /api/voting/status` returns safe status strings (`FINALIZED`, `PROCESSING`, `FAILED`) and HMAC receipt codes. It never leaks `tx_hash`, `pseudonym`, or `candidate`.

---

## 12. Audit Logging

Recovery and reconciliation emit structured audit events into `audit_events`:
- `BALLOT_RECOVERED_CONFIRMED`: Logged when a mined transaction is confirmed.
- `BALLOT_RECOVERED_REVERTED`: Logged when a reverted transaction is failed.
- `BALLOT_REQUEUED`: Logged when an unbroadcast or dropped ballot is requeued.
- `RECONCILIATION_COMPLETED`: Logged after each election reconciliation cycle.
- `RECONCILIATION_MISMATCH_DETECTED`: Logged when a discrepancy is detected.
- `RECONCILIATION_ISSUE_RESOLVED`: Logged when an administrator resolves an issue.

All events participate in the existing cryptographic hash-chain architecture (`previous_hash` -> `current_hash`).

---

## 13. Database Migration & Schema

- Schema integrity validated with `test_database.py` (13/13 passing).
- `flask db check` executed cleanly with zero detected drift (`No new upgrade operations detected`).
- `ReconciliationIssue` table mapped with composite indexes, foreign keys, and severity levels.

---

## 14. Test Suite Execution

### Backend Recovery Unit Suite (`backend/tests/test_recovery.py`)
```
tests/test_recovery.py::test_recovery_idempotent PASSED                  [  9%]
tests/test_recovery.py::test_reconcile_required_state_safe PASSED        [ 18%]
tests/test_recovery.py::test_stale_queued_ballot_recovery PASSED         [ 27%]
tests/test_recovery.py::test_submitted_ballot_confirmed_recovery PASSED  [ 36%]
tests/test_recovery.py::test_submitted_ballot_reverted_recovery PASSED   [ 45%]
tests/test_recovery.py::test_unbroadcast_submitted_ballot_recovery PASSED [ 54%]
tests/test_recovery.py::test_reconciliation_service_clean_election PASSED [ 63%]
tests/test_recovery.py::test_reconciliation_service_detects_tally_mismatch PASSED [ 72%]
tests/test_recovery.py::test_relayer_concurrent_worker_claim_protection PASSED [ 81%]
tests/test_recovery.py::test_phase9_revote_possible_after_recovery PASSED [ 90%]
tests/test_recovery.py::test_recovery_preserves_privacy PASSED           [100%]
======================== 11 passed in 8.14s ========================
```

---

## 15. Live Ganache Proof Execution (`backend/scripts/prove_phase10_recovery.py`)

Executable proof against real Ganache (Chain ID 1337) and real `EVotingBallotBox.sol`:

```
======================================================================
PHASE 10 LIVE VERIFICATION PROOF: RECOVERY & RECONCILIATION
======================================================================

1. Initializing Live Ganache Contract for Election #10001...
  [PASS] Ganache connected, contract deployed and Election 10001 created on chain

--- TEST 1: Crash before broadcast (Unbroadcast SUBMITTED Ballot) ---
  [PASS] TEST 1: startup_recover detects unbroadcast SUBMITTED ballot
  [PASS] TEST 1: Unbroadcast ballot safely returned to QUEUED
  [PASS] TEST 1: Retry count incremented to 1
  [PASS] TEST 1: Requeued ballot successfully mined via Relayer
  [PASS] INV-10.1: No ballot permanently lost because of crash before broadcast

--- TEST 2: Crash after broadcast (SUBMITTED with Mined Tx) ---
  [PASS] TEST 2: startup_recover discovers mined on-chain receipt
  [PASS] TEST 2: Ballot transitioned to FINALIZED with tx_confirmed_at
  [PASS] INV-10.2: Ballot finalized only with authoritative blockchain evidence

--- TEST 3: Confirmed transaction recovery and status privacy ---
  [PASS] TEST 3: Voter status endpoint returns FINALIZED
  [PASS] TEST 3: Receipt present with receipt_code
  [PASS] INV-10.11: Privacy invariant: tx_hash, candidate, and pseudonym never leaked

--- TEST 4: Reverted transaction recovery ---
  [PASS] TEST 4: Reverted transaction detected by recovery
  [PASS] TEST 4: Ballot marked FAILED
  [PASS] TEST 4: Reconcile required set with reason TX_REVERTED
  [PASS] INV-10.6: Reverted transaction is never treated as successful/finalized

--- TEST 5: Pending transaction handling ---
  [PASS] TEST 5: Pending transaction detected without receipt
  [PASS] TEST 5: Ballot kept safely in SUBMITTED state
  [PASS] TEST 5: Reconcile required set to TX_PENDING
  [PASS] INV-10.7: Pending transaction is NOT falsely finalized or prematurely dropped

--- TEST 6: Repeated recovery idempotency ---
  [PASS] TEST 6: Dual-run stability: pass 2 produces zero transitions
  [PASS] TEST 6: Triple-run stability: pass 3 produces zero transitions
  [PASS] INV-10.4 & INV-10.12: RecoveryService.is_idempotent_ok() verifies idempotency

--- TEST 7: DB <-> Blockchain tally reconciliation ---
  [PASS] TEST 7: Clean election reconciliation matches DB and chain tallies
  [PASS] TEST 7: No issues recorded for clean state
  [PASS] TEST 7: Discrepancy detected when DB differs from blockchain tally
  [PASS] TEST 7: ReconciliationIssue created with category TALLY_MISMATCH
  [PASS] TEST 7: ReconciliationIssue persisted with severity HIGH

--- TEST 8: Distinct voter reconciliation ---
  [PASS] TEST 8: Distinct voter count matches between DB and blockchain
  [PASS] INV-10.5: DB and blockchain distinct voter counts match

--- TEST 9: Sequence consistency reconciliation ---
  [PASS] TEST 9: Sequence checks performed for active voter pseudonyms
  [PASS] TEST 9: No sequence discrepancies detected for settled ballots

--- TEST 10: Phase 9 revote recovery (Sequence 1 -> Sequence 2) ---
  [PASS] TEST 10: Revote sequence 2 accepted after recovery
  [PASS] TEST 10: Sequence assigned is 2
  [PASS] TEST 10: Latest-vote-wins: Candidate 0 decremented, Candidate 1 incremented
  [PASS] TEST 10: Prior sequence 1 ballot marked superseded=True
  [PASS] INV-10.8: Phase 9 sequence state preserved through recovery

--- TEST 11: Null revote recovery ---
  [PASS] TEST 11: Null revote sequence 3 accepted
  [PASS] TEST 11: Sequence is 3
  [PASS] TEST 11: Null revote decrements candidate tally to 0
  [PASS] TEST 11: DB and blockchain tallies converge after null revote recovery

--- TEST 12: Atomic worker claiming prevents duplicate submission ---
  [PASS] TEST 12: Worker A successfully claims ballot (claimed=1)
  [PASS] TEST 12: Worker B atomically rejected from claiming same ballot (claimed=0)
  [PASS] INV-10.3: Mutual exclusion prevents duplicate blockchain submission
  [PASS] TEST 12: Ballot successfully broadcast and finalized exactly once

--- TEST 13: Application restart recovery ---
  [PASS] TEST 13: Startup recovery executes cleanly after app restart
  [PASS] TEST 13: Final reconciliation report confirms clean DB <-> Chain convergence
  [PASS] INV-10.5: Zero unresolved reconciliation issues after restart recovery

======================================================================
PHASE 10 LIVE PROOF COMPLETE: 48 PASSED, 0 FAILED
======================================================================
```

---

## 16. Regression Results

All previously frozen phases were re-verified against live systems:

| Suite | Scope | Result | Status |
|---|---|---|---|
| Hardhat Tests (`npx hardhat test`) | Blockchain contracts & revoting | 14 passed, 0 failed | **PASS** |
| Phase 6 Proof (`prove_phase6_blockchain.py`) | Smart contract baseline | 119 passed, 0 failed | **PASS** |
| Phase 7 Proof (`prove_phase7_voting.py`) | Core voting & MFA pipeline | 20 passed, 0 failed | **PASS** |
| Phase 8 Proof (`prove_phase8_privacy.py`) | Privacy & key destruction | 30 passed, 0 failed | **PASS** |
| Phase 9 Proof (`prove_phase9_revoting.py`) | Controlled revoting & cooldown | 28 passed, 0 failed | **PASS** |
| Phase 10 Proof (`prove_phase10_recovery.py`) | Crash recovery & reconciliation | 48 passed, 0 failed | **PASS** |
| Backend Pytest Suite (`pytest tests/`) | Full backend test suite | 599 passed, 0 failed | **PASS** |
| Frontend Suite (`npm test`) | Full frontend test suite | 119 passed, 0 failed | **PASS** |
| Frontend Production Build (`npm run build`) | Vite build validation | 0 errors | **PASS** |
| Database Migration Check (`test_database.py`) | Schema & Alembic check | 13 passed, 0 drift | **PASS** |

---

## 17. Security Invariants Verified

| Invariant | Description | Verification Method | Result |
|---|---|---|---|
| **INV-10.1** | No ballot is permanently lost because of a process crash. | TEST 1 & 2 in live proof | **VERIFIED** |
| **INV-10.2** | No ballot is finalized without authoritative blockchain evidence. | TEST 2 & 4 in live proof | **VERIFIED** |
| **INV-10.3** | No logical ballot is submitted twice because of recovery. | TEST 12 atomic row claim | **VERIFIED** |
| **INV-10.4** | Recovery is idempotent. | TEST 6 triple recovery pass | **VERIFIED** |
| **INV-10.5** | DB and blockchain eventually converge. | TEST 7, 8, 13 reconciliation | **VERIFIED** |
| **INV-10.6** | Reverted transactions are never treated as successful. | TEST 4 status=0 verification | **VERIFIED** |
| **INV-10.7** | Pending transactions are not falsely finalized. | TEST 5 pending timeout test | **VERIFIED** |
| **INV-10.8** | Phase 9 sequence state cannot be corrupted by recovery. | TEST 10 & 11 revote tests | **VERIFIED** |
| **INV-10.9** | Recovery cannot bypass cooldown or authentication. | Phase 9 regression suite | **VERIFIED** |
| **INV-10.10** | Destroyed pseudonym keys cannot be resurrected. | Phase 8 regression suite | **VERIFIED** |
| **INV-10.11** | Recovery does not leak protected voter/ballot information. | TEST 3 privacy assertions | **VERIFIED** |
| **INV-10.12** | Repeated recovery does not create side effects. | TEST 6 idempotency test | **VERIFIED** |

---

## 18. Known Limitations & Remaining Risks

1. **Academic Ganache Environment**: Tested against Ganache with instant mining and JSON-RPC over loopback. Public network re-orgs (>1 block depth) and variable gas fee spikes are mitigated by relying on confirmed transaction receipts, but formal L1 reorg depth confirmation is planned for Phase 13.
2. **Offline Recovery Fallback**: When blockchain RPC is completely unreachable during startup, recovery marks unfinished ballots as `reconcile_required=True` (`STALE_SUBMITTED`) to fail closed rather than guessing.
3. **Audit Readiness**: Implementation is complete and ready for independent adversarial audit. In accordance with project instructions, Phase 10 is marked `REMEDIATION IMPLEMENTED — READY FOR RE-AUDIT`, not self-certified PASS.

---

## 19. Stop Condition

Phase 10 remediation, unit tests, live Ganache proof, full regressions across Phases 6–9, and documentation updates are complete. In strict adherence to instructions, no Phase 11 or 12 work has been performed. The system is stopped and prepared for independent security re-audit.
