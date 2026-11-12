# Incident Response Plan & Breach Management

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Incident Response Framework

This incident response plan establishes technical containment and manual governance procedures for responding to security events, data compromises, and infrastructure disruptions.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              INCIDENT RESPONSE PHASES                                  │
├───────────────┬────────────────────────────────────────────────────────────────────────┤
│ Phase         │ Objective                                                              │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 1. Detection  │ Identify anomaly via audit logs, reconciliation alerts, or user report │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 2. Containment│ Halt attack progression; isolate services or revoke compromised tokens │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 3. Evidence   │ Preserve forensic snapshots of database, blockchain state, and logs    │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 4. Recovery   │ Patch vulnerability, restart services, rotate keys                     │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 5. Redress    │ Reconcile database and blockchain tallies; notify institutional bodies │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ 6. Post-Mortem│ Root cause analysis; update threat registers and test suites           │
└───────────────┴────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Threat-Specific Playbooks

### IR-01: Voter Credential Compromise / Account Takeover
- **Detection:** Multiple failed login attempts triggering account lock (`failed_login_attempts >= 5`), or student reports unauthorized activity.
- **Immediate Containment (Manual):** Administrator deactivates user (`UPDATE users SET is_active = FALSE WHERE id = :id`), revokes all active sessions (`UPDATE auth_sessions SET revoked = TRUE WHERE user_id = :id`).
- **Evidence Preservation:** Export `audit_events` rows associated with user IP and session IDs.
- **Recovery:** Force password reset via college email; re-bind multi-factor credentials if necessary.
- **Vote Impact Assessment:** Check `voting_authorizations` and `ballot_queue` for unauthorized ballot submissions. If within voting window, legitimate voter can cast a revote to reclaim their ballot choice.

---

### IR-02: Administrative Account Compromise
- **Detection:** Anomalous IP in `admin_sessions`, or failed Four-Eyes approval alerts.
- **Immediate Containment (Manual):** Revoke administrative session (`UPDATE admin_sessions SET revoked = TRUE`); lock admin account (`UPDATE admin_users SET is_active = FALSE`).
- **Evidence Preservation:** Snapshot `approval_requests`, `admin_sessions`, and `audit_events`.
- **Recovery:** Rotate administrative Argon2id password and re-seed TOTP secret.
- **Integrity Verification:** Inspect all `ApprovalRequest` records approved during the window. The Four-Eyes principle prevents a single compromised admin account from unilaterally executing critical state changes.

---

### IR-03: Relayer Key Compromise
- **Detection:** Mined transactions appearing on `EVotingBallotBox.sol` with unexpected nonces or outside application queue processing.
- **Immediate Containment (Manual):** Election Officer calls `setRelayer(newRelayerAddress)` on the smart contract (`EVotingBallotBox.sol`), immediately revoking the compromised address's authority.
- **Evidence Preservation:** Record transaction hashes, sender addresses, and block timestamps from Ganache/EVM node.
- **Recovery:** Generate a new 32-byte Ethereum private key, update `RELAYER_ACCOUNT` and `RELAYER_PRIVATE_KEY` in backend environment, restart relayer worker.
- **Reconciliation:** Run `ReconciliationService.audit_reconciliation()` to detect any forged ballots submitted before the key was revoked.

---

### IR-04: Database Intrusion or Data Leak
- **Detection:** Unauthorized connection alerts, suspicious queries in MySQL logs, or data alteration.
- **Immediate Containment (Manual):** Terminate external network ingress; stop the Flask web application service to freeze state.
- **Evidence Preservation:** Take an immediate raw disk and database snapshot (`mysqldump --all-databases`).
- **Recovery:** Restore from the latest verified backup; rotate all database credentials (`DATABASE_URL`).
- **Privacy Assessment:**
  - *Identity Plane:* Passwords are protected by Argon2id; biometric templates are Fernet-encrypted (AES-128-CBC + HMAC-SHA256).
  - *Ballot Plane:* If finalization had occurred, per-election keys are already shredded (`[DESTROYED]`), rendering ballots completely unlinkable to voters.
- **Notification:** Inform college administration and student body in accordance with institutional policy.

---

### IR-05: Blockchain / JSON-RPC Node Outage
- **Detection:** `RecoveryService` or `Relayer` logs Web3 connection timeout (`mock_w3.is_connected() == False`).
- **Immediate Containment (Automated):** System enters fail-safe queueing mode:
  - Voters can continue to submit ballots to `ballot_queue` (state remains `QUEUED`).
  - No ballots are dropped; the relayer worker halts submission and enters backoff retry.
- **Recovery (Manual):** Restore Ganache / Ethereum node service.
- **Reconciliation (Automated):** Once RPC is restored, `RecoveryService.startup_recover()` processes queued ballots, checks pending transaction receipts, and finalizes records without duplication.

---

### IR-06: Biometric Template Breach
- **Detection:** Discovery of unauthorized access to the `face_enrollments` table.
- **Immediate Containment (Manual):** Revoke database access; rotate the master `FACE_ENCRYPTION_KEY`.
- **Evidence Preservation:** Log all access times and query logs touching `face_enrollments`.
- **Impact Mitigation:**
  - Raw face images were **never stored** (processed transiently in RAM).
  - Stored embeddings are **512-dimensional floating-point vectors**, not photographs. They cannot be reversed into a photo of the student.
  - All vectors are encrypted with **Fernet authenticated envelopes** (AES-128-CBC + HMAC-SHA256); without the master key, ciphertext is mathematically unreadable.
- **Notification:** Disclose breach to the institutional data protection authority.

---

### IR-07: Vote Tally Mismatch (Database vs. Blockchain Divergence)
- **Detection:** `ReconciliationService.audit_reconciliation()` flags a mismatch (`CHAIN_EXISTS_DB_FAILED`, `COUNT_MISMATCH`).
- **Immediate Containment (Automated):** System records an open `ReconciliationIssue` and prevents automatic election closure.
- **Evidence Preservation:** Snapshot the on-chain smart contract `tally` mapping and database `ballot_queue` table.
- **Root Cause Analysis:** Determine whether the discrepancy was caused by an interrupted relayer broadcast or unmined transaction.
- **Resolution (Four-Eyes Manual):** The smart contract is authoritative for vote counts. Officers execute formal reconciliation to update the database record to match the blockchain ledger.

---

### IR-08: Audit Log Hash Chain Corruption
- **Detection:** `AuditLogger.verify_chain()` returns `False` and identifies the specific broken link.
- **Immediate Containment (Automated):** System alerts administrators and flags the election for investigation.
- **Evidence Preservation:** Isolate the tampered row by comparing its `current_hash` and `previous_hash` with the on-chain anchor (`EVotingBallotBox.sol::auditAnchors`).
- **Post-Mortem:** Identify the rogue actor or script that executed direct SQL `UPDATE` or `DELETE` on `audit_events`.
