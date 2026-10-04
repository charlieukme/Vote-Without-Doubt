# Phase 0 Checkpoint

> **HISTORICAL RECORD.** This file is the Phase 0 baseline as it stood when Phase 0 finished.
> Any phase status, file list, or "next action" statement below describes that moment only and
> is **not** the current project status.
>
> - Current authoritative phase status: [`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative)
> - Phase 0 outcome and remediation: [`PHASE0_FINAL_REPORT.md`](./PHASE0_FINAL_REPORT.md)
> - Phase 0 implementation audit: [`PHASE0_FOUNDATION_AUDIT.md`](./PHASE0_FOUNDATION_AUDIT.md)
> - This file was originally named `docs/PHASE_0_CHECKPOINT.md`; it was renamed during Phase 0
>   remediation to match the `PHASE<N>_<DOCUMENT>.md` convention. All in-repository references
>   were updated at the same time.

## Project Identity
- **Project Name:** AI & Blockchain-Based Secure E-Voting System for College Elections
- **Product Name:** Vote Without Doubt
- **Academic Prototype Status:** Yes (not legally binding)

## Checkpoint Date
- **Current Date:** 2026-10-04

## Project Root
- **Exact Current Working Directory:** C:\Users\aditya prasad\Downloads\voting-sys

## Starting State
- Project was started from a clean/new directory
- No legacy code was migrated
- No previous project was used
- No old project files were copied
- This project is independent of all previous projects

## Files Created
The following files exist at this checkpoint:

- **PROJECT_MASTER_REPORT.md** - Complete project specification (created in project root)
- **PROJECT_BIBLE.md** - Living engineering source of truth (created in project root)  
- **docs/PHASE0_CHECKPOINT.md** - This checkpoint file (created in docs/)

Verification: All files confirmed present.

## Phase 0 Completed Work

Phase 0 established the following:

1. **Requirements** - Complete project requirements captured from specification
2. **Architecture** - System architecture, two data planes, technology stack defined
3. **Scope Freeze** - In-scope and out-of-scope items explicitly defined and frozen
4. **Threat Model** - Major threat categories identified with THREAT→CONTROL→TEST→RESULT tracking
5. **Repository Structure** - Planned structure for frontend/backend/contracts/scripts/docs/etc.
6. **Development Environment** - Tools, services, and environment configuration defined
7. **Security Baseline** - Core security controls and requirements established
8. **Known Limitations** - Academic, privacy, coercion, biometric, anonymity, scale limitations documented
9. **Project Roadmap** - Complete Phase 0–17 roadmap defined
10. **Master Project Report** - PROJECT_MASTER_REPORT.md created with full specification (40 sections)
11. **Project Bible** - PROJECT_BIBLE.md created as living engineering record

## Architecture Snapshot

The architecture at this checkpoint:

```
React/Vite (Frontend)
    ↓
Flask (Backend, Python)
    ↓
MySQL 8 (Database - Identity Plane + Ballot Plane)
    ↓
Relayer
    ↓
Ganache (Blockchain, Chain ID 1337)
    ↓
Solidity 0.8.19 / Hardhat (Smart Contracts - EVotingBallotBox)
```

Key architectural elements:
- **Identity Plane**: Voter identity, electoral roll, registration, authentication, eligibility, participation data (strictly separated)
- **Ballot Plane**: Pseudonymous voter identifiers, ballot data, candidate selection, ballot sequence, blockchain submission state
- **Pseudonymous Ballots**: Per-election HMAC-SHA256 pseudonyms (domain-separated); keys encrypted in storage, destroyed after finalization
- **MetaMask Challenge Signing**: Wallet signs challenge only; candidate selection never included in signature; nonce-based replay protection
- **Face/Liveness Subsystem**: Enrollment + challenge-based liveness (LEFT/RIGHT, 10–24 frames, ~20s TTL); frames deleted after processing; embeddings protected
- **Audit**: Hash-chained audit logging with on-chain anchoring support; no secrets/candidate choices logged
- **Reconciliation**: Compares queue, blockchain events, ballot sequence, pseudonym counts, tally, audit chain, anchors
- **Public Verification**: Post-close verification with no individual voter choice disclosure

## Security Snapshot

Major security requirements established:

- **Argon2id** password hashing (never plaintext)
- **Secure Sessions**: HttpOnly, Secure, SameSite=Strict, __Host- cookie, rotation after OTP, 10min idle/2hr absolute, 1 active session per voter
- **OTP Protection**: 6-digit crypto-secure, HMAC-SHA256 with server-side pepper, 5min expiry, 5 attempts max, cooldowns, single-use, purpose-bound
- **Replay Protection**: Nonces (single-use, session/purpose-bound), OTP single-use, authorization consumption after use
- **Wallet Security**: Domain separation (chainId, contract, electionId, voter, purpose), nonce, timestamp/expiry, exact message verification
- **Face Security**: Frame deletion immediately after processing, embedding encryption/protection, quality checks, single face
- **Embedding Protection**: Secure storage, access controls
- **RBAC**: Election Officer and Auditor (read-only)
- **Dual Approval**: Minimum two officers for sensitive actions, no self-approval
- **Audit Chain**: Hash-chained, tamper-detectable, append-only
- **Idempotency**: Exactly-once ballot submission semantics
- **Reconciliation**: Mismatch detection and visibility
- **Privacy Separation**: Strict identity–ballot plane separation

## Scope Snapshot

**IN SCOPE (Academic Prototype):**
- Electoral-roll verification, password auth, email OTP
- MetaMask wallet auth/signatures
- Face verification + liveness detection
- Blockchain-backed ballot integrity (Ganache/Hardhat/Solidity)
- Privacy-preserving pseudonymous ballots
- Secure vote submission, revoting/coercion mitigation
- Hash-chained audit logging
- Election lifecycle management
- Recovery and reconciliation
- Public verification
- Security testing

**OUT OF SCOPE (Explicitly Excluded):**
- Kubernetes, microservices, cloud autoscaling, custom blockchain, AI agents, mobile app
- Mixnets, keyless ballot box, commit-reveal (core), blind RSA (core), ZK voting (core), threshold crypto (core)
- HSM/KMS, WebAuthn, public testnet deployment

## Threat Model Snapshot

Major threat categories established:

- **Identity Threats**: Malicious registration, duplicate registration, impersonation
- **Authentication Threats**: Stolen credentials/sessions, OTP replay, wallet replay
- **Biometric Threats**: Face spoofing, face replay, deepfakes, virtual cameras
- **Voting Threats**: Double vote, voter-ballot correlation, coercion, vote buying, receipt abuse
- **Platform Threats**: Modified frontend, direct API manipulation, MITM, DoS, malicious insider
- **Blockchain/Relayer Threats**: Rogue relayer, transaction replay, election manipulation
- **Admin Threats**: Admin abuse, unauthorized lifecycle changes
- **Privacy Threats**: Identity-ballot correlation, metadata leakage

Tracked as: THREAT → CONTROL → TEST → RESULT

## Important Architectural Decisions

Decisions established at Phase 0:

1. **Clean-slate implementation** - Start from zero in current working directory only; no migration/copy from prior projects
2. **Identity/ballot separation (two planes)** - Strict separation; no direct cross-linking via FKs/shared rows/shared ordering/candidate-bearing identity records
3. **Pseudonymous blockchain ballots** - Only HMAC-SHA256 pseudonyms + non-identifying data on-chain; not perfectly anonymous
4. **MetaMask does not submit votes** - MetaMask signs challenge only; actual vote submission handled by backend/relayer
5. **Candidate not included in wallet signature** - Signature contains domain/purpose/voter/election/chainId/contract/nonce/timestamp/expiry only
6. **Minimal privacy-preserving receipts** - Only election title, voter ID last 4, minute-level time, HMAC receipt code; no candidate, pseudonym, tx hash, block, queue ID
7. **Revoting design** - Max 3 ballots, latest valid counts, full re-auth per revote (wallet+face/liveness), ~2min cooldown, optional null revote
8. **Hash-chained audit** - Tamper-evident audit log with on-chain anchoring support; secrets/candidate choices never logged
9. **Reconciliation** - Systematic comparison of queue/blockchain/events with mismatch visibility
10. **Neo-Brutalist UI with security-first priority** - Security > usability > aesthetics; minimal animation in critical flows
11. **Per-election pseudonym keys** - Domain-separated, encrypted in storage, destroyed after election finalization
12. **Authorization consumed after use** - Prevents replay/reuse of voting authorization
13. **Exactly-once semantics** - Durable transaction intent before broadcast, idempotency, crash recovery

## Phase Status

- **Phase 0 = COMPLETE**
- **Phases 1–17 = NOT STARTED**

## Known Limitations

- Academic prototype only (not legally binding)
- Privacy not fully guaranteed against root/backend operator with access during election
- Malicious relayer cannot be fully prevented; must be detectable via reconciliation/audit
- Coercion resistance limited (physical presence, device control, credential handover)
- Biometrics vulnerable to sophisticated attacks (deepfakes/virtual cameras); requires documentation/evaluation
- Pseudonymous but not perfectly anonymous
- Local dev environment only (Ganache localhost); not production-hardened
- Limited scale: ≤500 voters, ≤20 candidates

## Filesystem Safety

"This project is independent of all previous projects. No previous project code, files, repositories, or implementations were used. All work performed exclusively in C:\Users\aditya prasad\Downloads\voting-sys."

## Recovery Purpose

This checkpoint exists so that if a later phase introduces a problem, we can return to this documented state and understand what was known and completed at Phase 0. It serves as the permanent baseline for the entire project.

---

**Checkpoint Created:** 2026-10-04  
**Phase 0 Status:** COMPLETE (Documentation Only - No Implementation Started)  
**Next Action:** Phase 1 (only upon explicit instruction)  
**Project Root:** C:\Users\aditya prasad\Downloads\voting-sys
