# Academic Project Report & Viva Defense Guide

**Project Title:** AI & Blockchain-Based Secure E-Voting System for College Elections  
**Product Name:** Vote Without Doubt  
**Academic Level:** Engineering Capstone / Master's Thesis / Security Review  
**Date:** October 6, 2026  

---

## 1. Problem Statement

Collegiate student-government elections in higher education institutions face a profound trilemma:
1. **Trust Deficit & Tampering Suspicions:** Traditional paper ballot boxes and centralized web voting portals are vulnerable to administrative manipulation, untraceable tally alterations, and opaque counting.
2. **Coercion & Proxy Voting:** Unsupervised remote voting allows dorm-room intimidation, password sharing, or vote-buying where students are coerced into voting for specific candidates.
3. **Privacy vs. Verifiability Paradox:** Providing end-to-end cryptographic verifiability typically threatens voter secret-ballot privacy, while achieving privacy often sacrifices public auditability.

---

## 2. Project Objectives

Vote Without Doubt resolves this trilemma through five engineering objectives:
- **Objective 1 (Multi-Factor Proof of Identity):** Layer four independent authentication factors (Password, College Email OTP, MetaMask Wallet Signature, and AI-powered Facial Liveness Verification).
- **Objective 2 (Cryptographic Pseudonymity & Privacy):** Implement strict two-plane database separation (Identity Plane vs. Ballot Plane) with per-election key shredding.
- **Objective 3 (Decentralized Consensus & Tamper-Evident Tally):** Record pseudonymous ballots on an Ethereum smart contract (`EVotingBallotBox.sol`), enabling public mathematical tally verification.
- **Objective 4 (Coercion Resistance via Revoting):** Permit voters to cast up to 3 ballots per election, enforcing a latest-vote-wins state machine to allow coerced students to override coerced votes.
- **Objective 5 (Crash Resilience & Zero Lost Ballots):** Engineer an asynchronous relayer queue with startup recovery and automated reconciliation ensuring zero lost ballots and zero duplicate submissions across system crashes.

---

## 3. High-Level System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                SYSTEM ARCHITECTURE                               │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 1. Frontend: React 18 + Vite (SPA, MetaMask web3 provider, camera capture)       │
│ 2. Backend: Flask 3.0+ Modular Monolith (Python 3.11, SQLAlchemy, Web3.py)       │
│ 3. Database: MySQL 8.0 with InnoDB Row Locking (Identity Plane + Ballot Plane)  │
│ 4. AI Subsystem: InsightFace / ArcFace (ResNet-50) + 3D Yaw Pose Liveness Engine │
│ 5. Relayer: Asynchronous background worker with atomic SQL queue claiming        │
│ 6. Blockchain: Ganache / Ethereum EVM, Solidity 0.8.19 contract (EVotingBallotBox)│
│ 7. Audit: Append-only SHA-256 hash-chained audit log with on-chain anchor headers│
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key Architectural Subsystems & Roles

### A. The Role of the Blockchain (`EVotingBallotBox.sol`)
- **Immutable Ledger:** Once a ballot transaction is mined, it cannot be altered by college administrators, database intruders, or hostile actors.
- **Decentralized Tallying:** Candidate vote counters are incremented and decremented directly inside the EVM bytecode.
- **Audit Anchoring:** Periodically stores the head hash of administrative audit logs, preventing historical log rewrites.
- **Zero PII:** Only receives a 32-byte pseudonym HMAC, candidate index, and sequence number.

### B. The Role of the AI Biometric Subsystem (`ArcFace` + Liveness)
- **Anti-Proxy Defense:** Proves that the registered student is physically present before the camera when authorizing a ballot.
- **Challenge-Response Liveness:** Prompts random head movements (`LEFT, RIGHT`) and measures yaw rotation from 3D facial landmarks to defeat static photographs and screen replays.
- **Privacy Minimization:** Video frames are processed in volatile memory and immediately discarded. Stored 512-dim templates are encrypted with Fernet authenticated envelopes (AES-128-CBC + HMAC-SHA256) and deletable upon consent withdrawal.

### C. The Role of the Email OTP Subsystem
- **Institutional Identity Verification:** Verifies that the voter owns the active `.college.edu` institutional email address assigned on the official registrar roll.
- **Peppered Cryptographic Storage:** OTPs are valid for 5 minutes and stored solely as HMAC-SHA256 digests.

### D. The Role of the Web3 Wallet (MetaMask)
- **Possession Factor:** Proves possession of a distinct cryptographic signing key.
- **EIP-191 Personal Sign:** Uses challenge nonces to prevent replay attacks without exposing the wallet address to the public smart contract.

---

## 5. Defense Mechanisms

### A. Coercion Mitigation & Revoting
- **Mechanism:** Voters can cast up to 3 ballots. Each vote increments the sequence counter.
- **Latest-Vote-Wins:** The smart contract decrements the tally for `sequence - 1` and increments the tally for `sequence`.
- **Null Ballot Option:** A voter can cast a formal null vote, expunging their candidate vote from all tallies.
- **Masked Receipts:** The voter's confirmation receipt (`REC-1401-XXXX`) omits the candidate choice, denying coercers physical proof of how the voter voted.

### B. Crash Recovery & Resilience
- **Crash Post-Broadcast:** If the server crashes after broadcasting to Ganache but before updating the database, `RecoveryService.startup_recover()` inspects on-chain receipts upon restart and finalizes the record with zero duplicate transactions.
- **Crash Post-Claim:** If a relayer worker crashes while holding a ballot claim, the lease expires and recovery requeues the ballot safely.
- **Reconciliation Engine:** Periodically audits the database against the Ethereum event log and records discrepancies (`ReconciliationIssue`).

---

## 6. Public Cryptographic Verification

Any student, candidate, or faculty member can independently audit the election:
1. **Public Verification Endpoint:** `GET /api/elections/<id>/verification` exposes:
   - Smart contract address and block number.
   - Candidate roster and candidate manifest hash (`candidatesHash`).
   - Electoral roll integrity hash (`rollHash`).
   - Audit trail on-chain anchor digest (`auditHash`).
2. **Independent EVM Verification:** An auditor can connect a Web3 client directly to the blockchain node and query `elections(id)` and `tally(id, candidate)` without trusting the Flask web backend.

---

## 7. Project Limitations & Future Work

### Limitations:
1. **Biometric Calibration:** Protocol liveness is verified; empirical demographic FAR/FRR/EER metrics are not measured.
2. **Database Scalability:** Measured at ~36 req/sec under SQLite; production multi-node MySQL scaling is an architectural expectation.
3. **Endpoint Vulnerability:** Personal client devices infected with malware remain a residual risk.

### Future Work:
1. **Zero-Knowledge Proofs (ZKP):** Implement zk-SNARKs (e.g., Semaphore protocol) to eliminate pseudonyms in favor of zero-knowledge membership proofs.
2. **Homomorphic Encryption:** Enable encrypted tally accumulation directly on-chain using Paillier or ElGamal cryptosystems.
3. **Hardware Biometric Modules:** Integrate WebAuthn / FIDO2 biometric authenticators to eliminate server-side facial template storage.
