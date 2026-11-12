# Privacy Policy — Vote Without Doubt

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System for College Elections)  
**Classification:** Academic Prototype Policy  
**Effective Date:** October 6, 2026  
**Status:** Living Documentation (Phase 15)  

---

> ### ⚠️ Mandatory Legal Disclaimer
> This document describes the privacy practices of an **academic research and educational prototype**. This document does **not** constitute legal advice, regulatory certification, or a formal claim of statutory compliance with the Digital Personal Data Protection Act (DPDP), the General Data Protection Regulation (GDPR), or any other national or regional data protection framework. Institutional deployment requires formal legal review and institutional policy adoption.

---

## 1. Introduction and Scope

**Vote Without Doubt** is designed for collegiate student-government elections. Its privacy architecture is built upon the principle of **strict two-plane separation**:
- **Identity Plane:** Manages voter verification, multi-factor authentication, and eligibility.
- **Ballot Plane:** Manages pseudonymous ballot queuing, relayer dispatch, and blockchain recording.

This policy informs students, faculty, and administrators of what data is collected, why it is processed, how it is secured, and what residual privacy limitations exist.

---

## 2. Personal Data Collected and Purpose

| Category | Specific Data Elements | Purpose of Collection | Legal / Operational Basis |
|:---|:---|:---|:---|
| **Electoral Identity** | University Seat Number (USN), Full Name, College Email, Department, Year of Study | Determining voter eligibility and importing authoritative roll | Legitimate Institutional Interest (Student Election Administration) |
| **Authentication Credentials** | Username, College Email, Password (Argon2id hash), Login OTP (HMAC-SHA256) | Verifying voter identity during multi-factor login | Explicit User Authentication |
| **Session & Device Metadata** | Session token (cryptographically random hex), IP address, User-Agent, timestamps | Session binding, idle timeout enforcement (10 min), brute-force defense | Security & Integrity Safeguards |
| **Possession Factor (Wallet)** | Ethereum wallet address (`0x...`), single-use nonce signatures | Proving possession of a student-controlled device/key | Multi-Factor Authentication Possession Proof |
| **Biometric Factor** | Ephemeral camera frames (JPEG), head pose yaw angles, ArcFace 512-dim embedding | Anti-spoofing liveness verification & facial identity verification | Explicit Voluntary Consent |
| **Ballot Authorization** | Voter authorization state (`wallet_verified`, `face_verified`, `consumed`) | Ensuring exactly one active voting session per voter per ballot attempt | Election Anti-Fraud Control |
| **Pseudonymous Vote** | Cryptographic Pseudonym (`HMAC-SHA256`), Candidate Choice Index, Ballot Sequence Number (1–3), Null ballot flag | Immutable recording and tallying of cast votes | Electoral Franchise & Democratic Tally |

---

## 3. How Personal Data is Protected

1. **Password Security:** Passwords are hashed using the **Argon2id** key-derivation function. Plaintext passwords are never stored, logged, or retrievable.
2. **OTP Security:** One-Time Passwords are 6-digit cryptographic values valid for 5 minutes. They are stored as HMAC-SHA256 digests with a server-side pepper; raw OTPs are never stored in the database.
3. **Session Cookies:** Stored in browser memory using `HttpOnly`, `SameSite=Strict`, and signed cookies.
4. **Encryption at Rest:** Sensitive biometric templates and administrative TOTP secrets are encrypted at rest using **Fernet authenticated encryption** (AES-128-CBC + HMAC-SHA256).
5. **No Cross-Plane Foreign Keys:** The database strictly enforces separation. The `ballot_queue` table contains **zero foreign keys** pointing to the `users` or `electoral_roll` tables.

---

## 4. Biometric Data Processing & Lifecycle

Biometric processing adheres to data minimization:
1. **In-Memory Frame Analysis:** Uploaded camera frames (JPEG) are admitted via `multipart/form-data`, read directly into server memory, processed by the face analysis engine, and **immediately freed**. Frames are **never written to disk or database tables**.
2. **Deterministic Liveness Defense:** Liveness is verified via interactive head movement challenges (e.g. `LEFT, RIGHT`). Yaw rotation is computed from facial landmarks.
3. **Template Encryption:** Facial embeddings (512-dimensional vectors) are generated via ArcFace, packed with integrity headers, and encrypted using **Fernet authenticated encryption** (AES-128-CBC + HMAC-SHA256) before storage in `face_enrollments`.
4. **Consent Withdrawal & Deletion:** Voters can view their biometric status at `GET /api/face/status` and withdraw consent at any time via `POST /api/face/withdraw-consent`. Calling withdrawal immediately overwrites the stored ciphertext with empty bytes (`b''`), marks `is_enrolled = False`, and sets `template_deleted_at = NOW()`.
5. **Biometric Limitation:** The project possesses protocol-level liveness evidence, but has **NOT EMPIRICALLY ESTABLISHED** real-world demographic False Acceptance Rates (FAR), False Rejection Rates (FRR), or Equal Error Rates (EER).

---

## 5. Wallet & Blockchain Data Handling

1. **Wallet Binding:** The voter's Ethereum address is bound to their identity during registration using an EIP-191 personal sign challenge.
2. **Zero Wallet Exposure on Chain:** The voter's personal wallet address is **never** sent to the smart contract, is never included in the transaction payload, and does not pay gas fees.
3. **Relayer Subsidization:** An institutional Relayer account signs and broadcasts all transactions to the blockchain (`EVotingBallotBox.sol`).
4. **Data on Blockchain:** The public smart contract records:
   - `electionId` (integer)
   - `pseudonym` (`bytes32` HMAC digest)
   - `candidate` (integer index)
   - `sequence` (integer counter 1, 2, or 3)
   - `isNull` (boolean flag)
   **NO student name, USN, email, wallet address, IP, or biometric data is ever stored on the blockchain.**

---

## 6. Access Control and Governance

- **Ordinary Voters:** Can only view their own authentication status, enrollment state, factor verification status, and their masked voter receipt (`REC-<election>-<hash>`). Voters cannot view other voters' ballots or choices.
- **Election Officers:** Can manage elections, import electoral rolls, and trigger tallies via Two-Officer Four-Eyes approvals (`ApprovalRequest`). Officers **cannot** view which candidate a specific student voted for.
- **Auditors:** Can view append-only audit events, verify cryptographic hash chains, inspect reconciliation issues, and query smart contract event logs. Auditors have read-only access.
- **Database Administrators:** Cannot reconstruct voter-ballot linkages after election finalization because per-election pseudonym keys are shredded from the database.

---

## 7. Data Retention and Deletion

| Record Type | Storage Medium | Retention Period | Deletion Trigger / Mechanism |
|:---|:---|:---|:---|
| **Raw Camera Frames** | In-Memory Only | $< 5$ seconds (duration of HTTP request) | Automatically garbage-collected upon request completion |
| **Face Templates** | MySQL Database | Duration of student enrollment or election cycle | Automated upon `POST /api/face/withdraw-consent` |
| **Auth Sessions** | MySQL Database | 2 hours absolute / 10 minutes idle | Expired records revoked and purged |
| **OTP Digests** | MySQL Database | 5 minutes | Single-use consumption or automatic expiration |
| **Pseudonym Master Key** | Environment Secret | Operational lifecycle | Destroyed upon infrastructure teardown |
| **Election Pseudonym Key**| MySQL Database | Duration of active voting | **Shredded / Overwritten** on `POST /api/admin/election/<id>/finalize` |
| **Ballot Records** | MySQL Database | Academic retention period | Requires Institutional Archival Policy |
| **Blockchain Ballots** | Ganache / Ethereum | **Permanent / Immutable** | **Cannot be deleted** (Blockchain ledger property) |

---

## 8. User Rights and Choices

Students participating in elections have the following technical rights:
1. **Right to Information:** Public verification endpoint (`GET /api/elections/<id>/verification`) exposes election parameters, smart contract addresses, candidate lists, and roll hashes.
2. **Right to Withdraw Biometric Consent:** Can be triggered at any time prior to voting.
3. **Revoting Rights (Coercion Defense):** If coerced into casting a specific ballot, a voter may re-authenticate up to two additional times (maximum 3 ballots per voter). The smart contract enforces latest-vote-wins.
4. **Right to Cast Null Ballot:** A voter may cast a formal null revote, invalidating prior votes and registering zero votes for any candidate while recording voter participation.
5. **Data Rectification & Deletion:** Formal requests to correct roll data or purge account data require manual institutional procedures (`REQUIRES INSTITUTIONAL POLICY`).

---

## 9. Limitations & Institutional Dependencies

- **Prototype Status:** Built for evaluation, research, and technical verification. Not certified for statutory public elections.
- **Endpoint Security:** The system assumes the voter's personal device and browser are free from keyloggers, screen recording malware, or browser extensions capable of intercepting inputs.
- **Institutional Governance:** The authenticity of the voter roll relies on the integrity of the college administration's student records department.

---

## 10. Contact and Escalation

Institutional deployments must specify an official Data Protection Officer or Election Committee contact:  
`STATUS: REQUIRES INSTITUTIONAL POLICY (Contact details to be assigned by hosting institution)`
