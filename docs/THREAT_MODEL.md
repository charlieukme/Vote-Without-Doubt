# Formal Threat Model & Security Analysis

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  
**Framework:** STRIDE-Aligned Threat Analysis  

---

## 1. Threat Actors & Attacker Capabilities

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  THREAT ACTORS                                         │
├─────────────────────────┬───────────────────────────────┬──────────────────────────────┤
│ Actor                   │ Trust Level                   │ Capabilities                 │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ External Attacker       │ Untrusted                     │ Network MITM, API fuzzing,   │
│                         │                               │ brute force, client spoofing │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Malicious Voter         │ Partially Trusted (Auth only) │ Multiple accounts, revote    │
│                         │                               │ racing, client-side bypass   │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Malicious Administrator │ Semi-Trusted (Privileged API) │ Unauthorized election cancel,│
│                         │                               │ audit delete, roll injection │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Compromised Relayer     │ Partially Trusted Worker      │ Gas manipulation, transaction│
│                         │                               │ reordering, dropping ballots │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Database Intruder (DBA) │ Untrusted High-Privilege      │ Direct SQL read/write, schema│
│                         │                               │ tampering, row modification  │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Blockchain Observer     │ Untrusted Public              │ Read full ledger, event logs,│
│                         │                               │ transaction timing/ordering  │
├─────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Coercer / Vote Buyer    │ Untrusted Adversary           │ Demands proof of vote, forces│
│                         │                               │ ballot choice on voter device│
└─────────────────────────┴───────────────────────────────┴──────────────────────────────┘
```

---

## 2. Comprehensive Threat Register

### T-01: Identity Plane Impersonation via Stolen Password
- **Threat Actor:** External Attacker
- **Target:** Voter Account Authentication (`POST /api/auth/login`)
- **Attack Vector:** Credential stuffing or dictionary attack on user passwords.
- **Existing Technical Controls:**
  1. Password hashing via **Argon2id** with memory-hard parameters ($m=65536, t=3, p=4$).
  2. Mandatory Email OTP second factor (HMAC-SHA256 hashed with server pepper, 5 min TTL).
  3. Account lockout after 5 consecutive failed attempts.
- **Verified Evidence:** `backend/tests/test_auth.py`, `backend/tests/test_phase2_otp_security.py` (PASS).
- **Residual Risk:** Compromise of student's college email inbox allows password reset and OTP interception.

---

### T-02: Biometric Spoofing via Photo / Video Replay
- **Threat Actor:** External Attacker / Impersonator
- **Target:** Face Verification Endpoint (`POST /api/face/verify`)
- **Attack Vector:** Holding a printed photograph or tablet displaying a pre-recorded video of the legitimate voter to the webcam.
- **Existing Technical Controls:**
  1. Interactive challenge-response liveness: server randomly orders head rotation prompts (e.g. `LEFT, RIGHT`).
  2. Cryptographic challenge nonce with 60-second time-to-live and HMAC integrity MAC.
  3. Server-side yaw calculation from 3D facial landmarks; static images fail the yaw threshold.
- **Verified Evidence:** `backend/tests/test_phase5_face_security.py`, `backend/tests/test_phase5_face_engine.py` (PASS).
- **Residual Risk:** Advanced real-time deepfake injection via virtual webcams. Project has **no empirical demographic FAR/FRR calibration**.

---

### T-03: Double-Voting via Concurrent Race Condition
- **Threat Actor:** Malicious Voter
- **Target:** Ballot Submission Endpoint (`POST /api/voting/submit`)
- **Attack Vector:** Firing two simultaneous HTTP requests with different candidate choices using the same session token.
- **Existing Technical Controls:**
  1. Database atomic consumption: `VotingAuthorization.consumed` is checked and updated within a single serializable transaction.
  2. Database unique constraint: `uq_ballot_queue_election_pseudonym_seq` on `(election_id, pseudonym, sequence)`.
  3. Smart contract EVM invariant: `require(sequence == lastSequence[pseudonym] + 1)`.
- **Verified Evidence:** `test_phase14_concurrency.py::test_c14_01_two_simultaneous_first_votes` (PASS).
- **Residual Risk:** None. Enforced at database, ORM, and Solidity contract layers.

---

### T-04: Client-Side Security Bypass (Direct API Tampering)
- **Threat Actor:** Malicious Voter / Scripting Attacker
- **Target:** Authorization & Submission APIs (`/api/voting/authorize`, `/api/voting/submit`)
- **Attack Vector:** Crafting direct curl/Postman requests bypassing frontend React validation (submitting on expired elections, omitting face verification).
- **Existing Technical Controls:**
  1. Strict server-side verification: backend checks `election.end_time` before issuing authorizations.
  2. Server verifies `wallet_verified == True` and `face_verified == True` on the database record before queueing ballot.
- **Verified Evidence:** Phase 14 adversarial audit test `check_1_production_fix_and_bypass` (PASS).
- **Residual Risk:** None. Server is authoritative and never trusts client-supplied state flags.

---

### T-05: Unauthorized Administrative State Transition
- **Threat Actor:** Rogue Election Officer
- **Target:** Admin Lifecycle Operations (`/api/admin/election/finalize`, `/api/admin/election/cancel`)
- **Attack Vector:** Single corrupt administrator attempting to unilaterally cancel an election or manipulate candidate lists.
- **Existing Technical Controls:**
  1. **Two-Officer Four-Eyes Rule:** Critical actions require initiation by Officer A and independent approval by Officer B.
  2. Role-Based Access Control (RBAC): `OFFICER` vs `AUDITOR` privilege separation.
  3. Mandatory TOTP two-factor authentication for administrative accounts.
- **Verified Evidence:** `prove_phase11_admin.py` (39/39 PASS), `test_phase14_concurrency.py::test_c14_06` (PASS).
- **Residual Risk:** Collusion between two corrupt administrative officers.

---

### T-06: Relayer Transaction Tampering / Ballot Censorship
- **Threat Actor:** Compromised Relayer Worker Process
- **Target:** Blockchain Broadcast (`Relayer.process_queue`)
- **Attack Vector:** Relayer alters the candidate index in the transaction payload or selectively drops ballots.
- **Existing Technical Controls:**
  1. Automated Reconciliation Service (`ReconciliationService`): compares database `ballot_queue` records against mined on-chain `BallotCast` events.
  2. Mismatches create immutable `ReconciliationIssue` alerts (`CHAIN_EXISTS_DB_FAILED`, `DB_CONFIRMED_BUT_CHAIN_MISSING`).
  3. Public voter receipt: voter can query their receipt code via the dispute service.
- **Verified Evidence:** `prove_phase10_recovery.py` (48/48 PASS), `test_phase14_failure_recovery.py` (21/21 PASS).
- **Residual Risk:** Relayer delay denial-of-service during active voting window until reconciliation detects it.

---

### T-07: Database Compromise & Voter De-Anonymization
- **Threat Actor:** Database Administrator (DBA) or SQL Injection Attacker
- **Target:** Relational Database (`voting-sys` MySQL database)
- **Attack Vector:** Attacker reads all tables and attempts to correlate `users` with `ballot_queue`.
- **Existing Technical Controls:**
  1. **Zero Foreign Keys:** `ballot_queue` has no `user_id` or student identifiers.
  2. **Irreversible Key Shredding:** Per-election pseudonym keys are overwritten with `[DESTROYED]` immediately upon election finalization.
  3. Shuffled queuing: ballots are processed asynchronously by the relayer, breaking chronological timing linkage.
- **Verified Evidence:** `prove_phase8_privacy.py` (30/30 PASS).
- **Residual Risk:** If an active database dump is captured **while voting is live** (before key shredding) AND the attacker obtains `PSEUDONYM_MASTER_KEY` from the server environment, pseudonyms can be recomputed.

---

### T-08: Blockchain Ledger Observability & Correlation
- **Threat Actor:** Public Blockchain Observer
- **Target:** Ethereum Node / Public Ganache Ledger
- **Attack Vector:** Inspecting transactions to identify voter choices.
- **Existing Technical Controls:**
  1. Public transactions contain only `bytes32 pseudonym` (HMAC digest).
  2. Transaction gas is paid entirely by the institutional relayer; voter personal wallet addresses never appear on chain.
- **Verified Evidence:** `prove_phase6_blockchain.py` (119/119 PASS).
- **Residual Risk:** In extremely small elections (e.g. 3 eligible voters), observing transaction timestamps and physical arrival at a computer lab could allow statistical correlation.

---

### T-09: Voter Coercion / Vote Buying
- **Threat Actor:** Coercer / Hostile Peer / Vote Buyer
- **Target:** Student Voter
- **Attack Vector:** Demanding the voter show proof of their vote or standing over their shoulder during voting.
- **Existing Technical Controls:**
  1. **Receipt Privacy:** Voter receipts contain masked identifiers (`REC-1401-XXXX`) and **never include the candidate choice**.
  2. **Revoting Window:** Voter can re-authenticate later from a private device and cast a revote (up to 3 ballots), silently overriding the coerced ballot.
  3. **Null Ballot Option:** Voter can cast a null ballot, removing their previous candidate vote from the tally entirely.
- **Verified Evidence:** `prove_phase9_revoting.py` (28/28 PASS), `test_phase14_concurrency.py::test_c14_03` (PASS).
- **Residual Risk:** If the coercer confiscates the voter's credentials until after election closure, revoting is precluded.
