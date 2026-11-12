# Residual Risk Register & Threat Assessment

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Formal Residual Risk Register

The following register documents the real, unmitigated residual risks that remain after the completion and verification of Phases 0 through 14. Risks are evaluated honestly without artificial downgrading.

| Risk ID | Risk Description | Likelihood | Impact | Current Implemented Mitigation | Residual Risk Assessment | Recommended Future Mitigation | Phase / Scope |
|:---|:---|:---:|:---:|:---|:---|:---|:---:|
| **RR-01** | **Biometric Demographic Calibration:** ArcFace model lacks empirical FAR/FRR/EER calibration across diverse student cohorts. | **HIGH** | **HIGH** | Protocol-level interactive liveness prompts (`LEFT, RIGHT`); yaw pose validation; cosine similarity threshold $\ge 0.65$. | Model may exhibit higher False Rejection Rates (FRR) for specific lighting, cameras, or demographic groups. | Conduct large-scale empirical evaluation on institutional student cohort; calibrate threshold. | Phase 5 / Future |
| **RR-02** | **Client Endpoint Compromise:** Keyloggers, screen recorders, or malware on voter's personal device intercepting choices. | **MEDIUM** | **HIGH** | Masked receipts (no candidate name on receipt); revoting window allows overriding coerced ballots. | Malware active during live voting session can record voter choice or steal session tokens. | Institutional supervised voting kiosks with hardened Linux OS and dedicated cameras. | Client / Deployment |
| **RR-03** | **Production MySQL Scalability Gap:** High-concurrency benchmarks verified SQLite (~36 req/s); MySQL horizontal scaling not measured. | **MEDIUM** | **MEDIUM** | Asynchronous ballot queueing (`ballot_queue`); batched relayer processing; row-level locking design. | Under massive concurrent voter load (e.g., 2,000 voters in 5 minutes), unmeasured database lock contention may delay queues. | Conduct production load tests on a dedicated multi-node MySQL 8.0 cluster with connection pooling. | Phase 14 / Deployment |
| **RR-04** | **Static Security Tooling Limitations:** Formal verification scanners (Slither, OWASP ZAP) were unavailable during audit environment. | **LOW** | **MEDIUM** | Comprehensive Hardhat and Pytest unit/integration test suites (1,207 tests, 100% pass rate); manual code audit. | Undiscovered subtle Solidity compiler edge cases or esoteric framework vulnerabilities. | Integrate automated Slither and ZAP scans into CI/CD pipeline in Linux build runners. | Phase 13 / Deployment |
| **RR-05** | **Relayer Centralization & Availability:** Single relayer worker constitutes a temporary throughput bottleneck. | **MEDIUM** | **MEDIUM** | Asynchronous queue preserves ballots; `RecoveryService` discovers unmined txs upon restart; no ballots lost. | If relayer crashes during active voting, on-chain mining pauses until restart, though DB queue preserves ballots safely. | Deploy redundant multi-relayer worker pool with leader election or distributed nonce manager. | Phase 10 / Architecture |
| **RR-06** | **Institutional Roll Falsification:** Malicious insider in college registrar department inserts fake students into CSV roll. | **LOW** | **HIGH** | Two-Officer Four-Eyes approval required to apply roll import; canonical SHA-256 digest anchored on blockchain. | If both officers approve a fraudulent registrar file, illegitimate accounts can register. | Multi-departmental cryptographic roll attestation and public voter roll audit period. | Governance / Institutional |
| **RR-07** | **Timing Correlation in Small Polls:** Observing physical voter arrival alongside on-chain transaction mining times. | **LOW** | **MEDIUM** | Asynchronous relayer worker decouples user submission from blockchain broadcast; per-election key shredding. | In ultra-low-turnout elections (e.g., $< 10$ voters), temporal correlation between submission and mining is statistically possible. | Implement random batch delay and dummy transaction injection in relayer worker. | Phase 8 / Relayer |
| **RR-08** | **Coercer Credential Confiscation:** Coercer physically confiscates student's phone and credentials throughout entire election. | **LOW** | **HIGH** | Multi-factor requirements (MetaMask wallet + face match) make proxy voting difficult; revoting window. | If the coercer forces the student to authenticate in person and prevents subsequent access, revoting is blocked. | Institutional in-person polling stations with private voting booths. | Physical / Election Ops |
| **RR-09** | **Dependency Vulnerabilities (Node / Python):** Third-party packages (Flask, Web3.py, React, Vite) develop zero-day CVEs. | **MEDIUM** | **MEDIUM** | Pinned versions in `requirements.txt` and `package.json`; minimal external library surface. | Known CVEs in dependencies could be exploited if server packages are not regularly updated. | Implement automated Dependabot / Snyk dependency scanning and periodic container rebuilds. | Maintenance / DevOps |
| **RR-10** | **Blockchain Gas Exhaustion:** Institutional relayer account runs out of ETH to pay transaction gas fees. | **LOW** | **HIGH** | Relayer monitors balance; transactions remain safely queued in database until gas is replenished. | Voting submissions continue to queue in DB, but blockchain mining halts until relayer is re-funded. | Automated relayer balance alerting and hot-wallet replenishment threshold daemon. | Operations / Blockchain |

---

## 2. Risk Acceptance Governance

In an academic and collegiate context, the risks cataloged above are **formally acknowledged and accepted** under the following operational provisions:
1. **Academic Scope:** The system is deployed for student government elections where the threat actor profile consists of students and collegiate adversaries, not nation-state intelligence agencies.
2. **Layered Compensating Controls:** No single vulnerability allows undetectable election rigging. Compromising an account requires breaking four factors; altering tallies requires breaking EVM consensus; tampering with logs breaks SHA-256 hash chains.
