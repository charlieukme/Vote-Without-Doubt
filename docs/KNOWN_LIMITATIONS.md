# Known Limitations — Do Not Misrepresent

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Absolute Engineering Honesty Mandate

Academic integrity requires that software engineering projects document their boundaries and weaknesses with the same precision as their successes. The following limitations are **inherent to the current implementation of Vote Without Doubt** and must not be misrepresented in academic reports, thesis defenses, viva examinations, or promotional material.

---

## 2. Catalog of Known Limitations

### Limitation 1: Biometric Accuracy Metrics are NOT Empirically Established
- **What is Implemented:** A fully functional protocol-level liveness pipeline using interactive head rotations (`LEFT, RIGHT`), yaw angle calculation from 3D facial landmarks, and ArcFace cosine similarity matching ($\ge 0.65$).
- **What is NOT Implemented / NOT Evidenced:** The project has **NO empirical measurements** for:
  - False Acceptance Rate (FAR)
  - False Rejection Rate (FRR)
  - Equal Error Rate (EER)
  - Attack Presentation Classification Error Rate (APCER / BPCER)
  - Demographic bias calibration (skin tone, lighting variance, facial hair, spectacles).
- **Rule:** Do NOT claim the biometric system is "99.9% accurate" or "spoof-proof." State: *"Protocol-level liveness verification is evidenced; demographic error rates are not empirically established."*

---

### Limitation 2: High-Throughput MySQL Scalability is an Architectural Expectation
- **What is Implemented:** Multi-threaded concurrency testing in SQLite demonstrating 100% data integrity, atomic sequence serialization, and zero deadlocks up to ~36 req/sec.
- **What is NOT Implemented / NOT Evidenced:** The test runner environment executes on local developer machines using SQLite and Ganache. The expectation that MySQL 8 with InnoDB row-level locking will handle 500+ concurrent requests per second is an **ARCHITECTURAL EXPECTATION**, not an empirically measured Phase 14 benchmark result.
- **Rule:** Do NOT claim high-throughput MySQL performance has been proven. State: *"Concurrency correctness is proven under SQLite; production MySQL scaling remains an architectural expectation."*

---

### Limitation 3: Automated Static Security Scanners (Slither / ZAP) Were Unavailable
- **What is Implemented:** Exhaustive unit, integration, failure, and concurrency test suites comprising 1,207 automated assertions with a 100% pass rate, coupled with manual code review.
- **What is NOT Implemented:** Automated static analysis via Slither (Solidity AST analysis) and dynamic application security testing via OWASP ZAP were not executable in the local Windows environment due to tooling dependencies.
- **Rule:** Do NOT claim the contracts or APIs are "scanned and certified by Slither and ZAP." State: *"Verified via comprehensive Hardhat/Pytest test suites; external static scanner reports were not generated."*

---

### Limitation 4: Client Endpoint Security is Outside Application Control
- **What is Implemented:** Server-authoritative state machines, masked receipts, revoting coercion resistance, and encrypted sessions.
- **What is NOT Implemented:** The system cannot detect or prevent malware, hardware keyloggers, screen mirroring software, or compromised browser extensions active on the voter's personal device.
- **Rule:** Do NOT claim the system provides "coercion-free voting from any device." State: *"Revoting mitigates coercion; compromised voter endpoints remain outside software boundary control."*

---

### Limitation 5: Academic Prototype vs. Statutory Election System
- **What is Implemented:** A robust educational prototype demonstrating verifiable collegiate e-voting with AI multi-factor authentication and blockchain anchoring.
- **What is NOT Implemented:** The software is not certified under statutory election standards (e.g., VVSG 2.0, Common Criteria EAL4+, Election Commission of India technical specifications).
- **Rule:** Do NOT claim the system is "ready for state or national public elections." State: *"Designed and evaluated as an academic prototype for collegiate student government elections."*

---

### Limitation 6: Regulatory Compliance Requires Institutional Action
- **What is Implemented:** Privacy-by-design controls: data plane separation, zero PII on chain, per-election key shredding, biometric consent withdrawal, and audit logging.
- **What is NOT Implemented:** Software alone cannot create compliance with the DPDP Act 2023 or GDPR. Compliance requires institutional data protection officers, legal notices, student grievance committees, and formal administrative election rules.
- **Rule:** Do NOT claim the software is "fully DPDP / GDPR compliant." State: *"Technical controls support DPDP and GDPR data minimization principles; formal compliance requires institutional governance."*

---

## 3. Approved Terminology Guide

To maintain academic honesty, all documentation and presentations must adhere to this terminology guide:

| INACCURATE / OVERSTATED CLAIM (DO NOT USE) | ACCURATE / EVIDENCE-BASED STATEMENT (APPROVED) |
|:---|:---|
| *"The system provides complete voter anonymity."* | *"The system provides cryptographic pseudonymity with two-plane data separation."* |
| *"The voting protocol is 100% secure and unhackable."* | *"The protocol has been verified against a formal threat model across 1,207 automated tests."* |
| *"The face biometric system is spoof-proof."* | *"The system implements interactive challenge-based liveness with 3D yaw tracking."* |
| *"Replay attacks are mathematically impossible."* | *"Replay defenses are enforced via single-use nonces, session binding, and sequence counters."* |
| *"The application is certified fully GDPR / DPDP compliant."* | *"The architecture supports statutory privacy principles; legal compliance requires institutional adoption."* |
| *"The voter cannot be de-anonymized by anyone."* | *"Voter-ballot linkage is broken after election closure through irreversible pseudonym key shredding."* |
| *"The blockchain guarantees zero errors."* | *"The blockchain provides decentralized consensus and immutable tally verification."* |
