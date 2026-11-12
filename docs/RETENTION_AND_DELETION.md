# Data Retention, Deletion & Immutability Matrix

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Complete Retention & Deletion Matrix

The following table documents the exact data retention policy, lifecycle duration, deletion trigger, and automation status across all components:

| Data Category | Stored in DB? | Retention Period | Deletion / Shredding Trigger | Actually Automated in Code? | Audit Verification |
|:---|:---:|:---|:---|:---:|:---|
| **Raw Camera Frames (JPEG)** | **NO** | 0 seconds (In-memory only) | End of HTTP request context | **YES (Automated)** | Frames read via `BytesIO`, never written to disk or database |
| **Face Landmarks & Yaw** | **NO** | 0 seconds (In-memory only) | Discarded after liveness check | **YES (Automated)** | Python objects garbage-collected after frame processing |
| **Encrypted Face Embedding** | **YES** | Active enrollment duration | User calls `POST /api/face/withdraw-consent` | **YES (Automated)** | Overwrites ciphertext with `b''`, sets `template_deleted_at` |
| **Face Challenge Record** | **YES** | 60 seconds (TTL) | Expired challenge; consumed on submission | **YES (Automated)** | Flagged `completed = True`; subsequent submissions rejected |
| **Email OTP Digest** | **YES** | 5 minutes (TTL) | Verification attempt or expiration | **YES (Automated)** | Marked `used = True`, `consumed_at = NOW()` |
| **Voter Session Token** | **YES** | 2 hours absolute / 10 min idle | User logout, timeout, or revocation | **YES (Automated)** | Marked `revoked = True`; rejected by session middleware |
| **Voter Account Credentials** | **YES** | Student academic enrollment | User account deletion | **PARTIAL** | Requires institutional registrar account de-provisioning |
| **Electoral Roll CSV Rows** | **YES** | Election cycle duration | Institutional purge | **MANUAL** | Admin de-provisioning (`REQUIRES INSTITUTIONAL POLICY`) |
| **Wallet Binding (`0x...`)** | **YES** | Voter account duration | Account deletion / unbind | **PARTIAL** | Kept in `wallet_bindings` until account termination |
| **Voting Authorization** | **YES** | Active voting session | Ballot submission | **YES (Automated)** | Marked `consumed = True`, `consumed_at = NOW()` |
| **Election Pseudonym Key** | **YES** | Active election duration | Election finalization (`POST /finalize`) | **YES (Automated)** | **Overwritten with `[DESTROYED]`**; key cache evicted |
| **Ballot Records (`ballot_queue`)**| **YES** | Academic audit duration | Institutional archival policy | **MANUAL** | Retained for audit; contains no direct voter identity |
| **Voter Receipt Codes** | **YES** | Academic audit duration | Institutional archival policy | **MANUAL** | Retained in `ballot_queue.receipt_code` for verification |
| **Audit Events (`audit_events`)** | **YES** | Permanent institutional record| **NEVER (Append-only)** | **NO (Intentional)**| Append-only hash chain; deletion breaks verification |
| **Reconciliation Logs** | **YES** | Permanent institutional record| **NEVER (Append-only)** | **NO (Intentional)**| Retained for discrepancy tracking and audit reviews |
| **Admin Accounts & Sessions** | **YES** | Administrative term | Admin revocation / logout | **YES (Automated)** | Sessions expire in 2 hours; accounts manually deactivated |
| **Blockchain Smart Contract Data**| **NO (Chain)**| **PERMANENT / IMMUTABLE** | **CANNOT BE DELETED** | **NO (EVM Invariant)**| Distributed ledger blocks cannot be edited or deleted |

---

## 2. Irreversible Key Shredding Protocol

Unlike standard database deletions which leave unallocated space recoverable via disk forensics:
1. **Target Table:** `election_pseudonym_keys`
2. **Execution Method:**
   ```python
   record.key_ciphertext = '[DESTROYED]'
   record.key_hash = '0' * 64
   db.session.commit()
   _ACTIVE_KEY_CACHE.pop(election_id, None)
   ```
3. **Cryptographic Impact:**
   - Pseudonyms are derived as: $\text{HMAC-SHA256}(K_{\text{election}}, \text{message})$.
   - Once $K_{\text{election}}$ is overwritten with `[DESTROYED]`, it is **mathematically impossible** to recompute the pseudonym for any voter.
   - Even a full database leak after finalization cannot link `users` to `ballot_queue`.

---

## 3. Blockchain Immutability Notice

> [!WARNING]
> **Immutability of On-Chain Records:**
> Once a transaction is mined into an Ethereum block, it becomes part of the permanent blockchain ledger.
> - `BallotCast` events, `pseudonym` hashes, candidate indices, and sequences **CANNOT BE DELETED, MODIFIED, OR EXPUNGED**.
> - The system does **not** store personally identifying data on chain, ensuring that on-chain immutability does not violate the fundamental principle of data minimization.
> - Any expectation of a "Right to be Forgotten" on the blockchain is technically impossible and must be addressed by ensuring that no personal data ever enters the blockchain.
