# DUAL-OFFICER INSTITUTIONAL GOVERNANCE & IDENTITY CHARTER

**System:** Vote Without Doubt (VWD) Cryptographic Voting Core (V2)  
**Document Classification:** Operational Governance Specification & Trust Boundary Protocol  
**Effective Date:** November 1, 2026  
**Auditor:** Antigravity Autonomous Security Core  

---

## 1. Executive Summary & Core Principle

In the Vote Without Doubt V2 architecture, privacy and tally integrity rely on a **2-of-2 threshold ElGamal cryptosystem over the BN254 elliptic curve**. Because individual ballots can only be decrypted if both private key shares $s_1$ and $s_2$ are combined ($s_{\text{joint}} = s_1 + s_2$), security mathematically holds **if and only if Officer 01 and Officer 02 are mutually independent and non-colluding**.

This Charter formalizes the institutional, legal, operational, and cryptographic controls required to establish procedural separation and mitigate single-party or coordinated compromise.

> [!IMPORTANT]
> **Zero Decryption Backdoor Mandate & Collusion Disclosure:**  
> There is no administrative bypass, master key, escrow backdoor, or superuser override in the smart contract or backend. If both officers collude, privacy is broken; if either officer permanently loses their key, the election cannot be tallied and must be re-run after the 72-hour `TallyStalled` lockout. Technical protocols enforce mathematical constraints. Institutional governance establishes procedural controls intended to reduce the likelihood of collusion. Actual independence depends on appointment integrity, institutional oversight, conflict-of-interest controls and enforcement. Cryptographic threshold enforcement requires both private key shares but cannot mathematically guarantee that the two officers will not collude.

---

## 2. Institutional Separation of Roles

To prevent shared incentives, organizational leverage, or coercion, Officer 01 and Officer 02 must represent distinct institutional bodies with naturally competing or adversarial responsibilities:

| Parameter | Officer 01 (Voter Representation) | Officer 02 (Institutional Oversight) |
| :--- | :--- | :--- |
| **Institutional Stakeholder** | **Student Government / Student Union** (e.g., Chief Election Commissioner of Student Council) | **Academic / Dean of Student Affairs Oversight** (e.g., Faculty Dean or University Legal Counsel) |
| **Primary Incentive** | Protect student voting rights, ensure voter choice privacy, prevent administrative interference. | Ensure academic integrity, enforce university bylaws, audit computational transparency. |
| **Appointment Authority** | Ratified by Student Senate vote with 2/3 supermajority. | Appointed by University Board of Trustees / Academic Council. |
| **Eligibility Constraints** | Must be an active student; cannot be a candidate or member of an active campaign team. | Tenured faculty or administrative staff; no executive role in student bodies. |
| **Physical Location** | Independent workstation on student union premises or off-campus personal hardware. | University enterprise hardware on administrative subnet. |
| **Identity Separation** | Dedicated personal institutional email (`@student.college.edu`). | Official faculty/administrative email (`@faculty.college.edu`). |

> [!NOTE]
> **Procedural Scope of Operational Credentials:**  
> Distinct email domains (`@student.college.edu` vs. `@faculty.college.edu`) and distinct Ethereum wallet addresses are operational authentication credentials and procedural checks; they do not constitute cryptographic proof of institutional or legal independence.

---

## 3. Technical vs. Governance Enforcement Boundaries

A foundational principle of this charter is the distinction between technical protocol enforcement and institutional identity governance:

1. **Distinct Ethereum Wallet Addresses:** Technical cryptographic keypairs enforced on-chain.
2. **Distinct Authenticated Accounts:** Identity-provider credentials verified at the application layer.
3. **Distinct Legal Persons:** Individual natural persons verified through real-world identity vetting.
4. **Independent Institutional Appointment Authorities:** Separate governing bodies exercising independent oversight.

Smart contract enforcement of distinct wallet addresses prevents the same address from occupying both officer seats. It does not establish that the addresses belong to different legal persons or independent institutions. Institutional identity verification, appointment records and conflict-of-interest checks are governance responsibilities and must be performed outside the cryptographic protocol. Neither email domains nor Ethereum wallet addresses constitute cryptographic proof of institutional independence.

| Control Objective | Technical Smart Contract & Cryptographic Enforcement | Institutional Governance & Legal Enforcement |
| :--- | :--- | :--- |
| **Identity Uniqueness** | `EVotingBallotBoxV2.sol` strictly enforces: `msg.sender != officer1` and `msg.sender != admin`. | University background checks confirm the two Ethereum addresses belong to two distinct legal persons. |
| **Key Generation Integrity** | Schnorr Proof of Possession (PoP) verified on-chain via `BN254.sol` prevents rogue-key attacks ($Y_{\text{joint}} = Y_1 + Y_2$). | Physical key ceremony protocol requires key generation on air-gapped, isolated browsers. |
| **Decryption Verifiability** | Chaum-Pedersen DLEQ proofs verified on-chain via `verifyDecryptionShare()` prevent officers from submitting falsified decryption factors. | Public observation of tally execution on blockchain explorer or audit terminal. |
| **No Single-Officer Decryption** | Threshold ElGamal ciphertext $B - s_i A$ yields noise unless both shares $s_1, s_2$ are evaluated. | Strict criminal/disciplinary liability for cross-sharing private keys or key material. |
| **No Administrative Tally Manipulation** | Smart contract enforces discrete logarithm lookup $M_j = t_j \cdot G$ with strict bound $\sum t_j = N$. | Tally certified by joint signature of both officers following on-chain finalization. |

---

## 4. Key Custody, Backup, and Recovery Protocols

### 4.1 Key Generation Ceremony
1. Each officer opens the officer dashboard on an isolated, malware-scanned device.
2. Each officer generates a cryptographically secure random scalar uniformly sampled from the valid range $s_i \in [1, Q-1]$, using the browser's cryptographically secure random number generator and rejection sampling.
3. The public key share $Y_i = s_i \cdot G$ and Schnorr PoP $(R_i, z_i)$ are computed entirely client-side.
4. The private scalar is held exclusively in volatile browser component memory. It is never written to localStorage, sessionStorage, cookies, or transmitted over HTTP. The scalar is cleared when the component or page context is destroyed. Following a page reload, the officer must restore the key from their encrypted backup.

### 4.2 Encrypted Backup Storage
1. Each officer is prompted to download an encrypted backup file (`vwd-officer-backup-election-<id>-officer-<i>.json`).
2. Encryption utilizes **Argon2id WASM** ($m=64\text{ MB}, t=3, p=4$) and **AES-256-GCM**.
3. **Canonical AAD Binding:** `abi.encode(uint256 electionId, uint256 officerId)` is bound as Additional Authenticated Data, cryptographically locking the backup to the specific election and officer seat.
4. Backups must be stored on physical hardware tokens (e.g., encrypted USB drive) deposited in separate institutional safes.

---

## 5. Lifecycle Contingency & Exception Procedures

### 5.1 Replacement Before Election Opening
- If an appointed officer resigns, is incapacitated, or is disqualified **prior to `openVoting()`**:
  - The admin or institutional authority deploys an updated contract instance or re-provisions the election.
  - The newly ratified officer performs the registration ceremony.
  - No ballots have been cast; state remains clean.

### 5.2 Conflict-of-Interest Disqualification
- If an officer is found to have an active conflict of interest during the election window:
  - The officer cannot decrypt alone. They cannot read or alter cast ballots.
  - If the officer refuses to participate in tally decryption, the 72-hour contingency applies.

### 5.3 Officer Key Loss or Permanent Unavailability
- If either Officer 01 or Officer 02 loses both their volatile device key and their encrypted offline backup passphrase:
  - **No master key can decrypt the ballots.**
  - Once the voting period expires, after 72 hours of inactivity during `TallyPending`, any participant can invoke `markTallyStalled()`.
  - The contract transitions to `TallyStalled`, terminating the election.
  - The institutional authorities declare the election void and schedule a fresh election with new officer credentials.

---

## 6. Prohibited Practices & Compliance Certifications

1. **No Shared Hardware:** Officers must never use the same computer, browser profile, or mobile device.
2. **No Proxy Delegation:** Officer credentials and backup passphrases cannot be delegated to assistants, IT administrators, or election staff.
3. **No Joint Custody:** Both officers must never place their backup keys in a single shared safe or common custody repository.
4. **No Backdoor Implementation:** Any code revision attempting to introduce key-escrow, threshold reduction (1-of-2), or admin tally overrides shall be treated as an immediate security violation and ground for immediate project rejection.

---

## 7. Protocol Limitations & Explicit Non-Claims

To ensure scientific, academic, and legal rigor for research paper finalization, this Charter explicitly articulates the cryptographic and operational boundaries of the V2 architecture:

1. **Collusion Boundary:** If Officer 01 and Officer 02 deliberately collude and combine their private scalars ($s_{\text{joint}} = s_1 + s_2$), individual ballot privacy is compromised. Cryptographic threshold enforcement prevents unilateral decryption, but cannot mathematically prevent mutual collusion between both keyholders.
2. **Coercion & Receipt-Freeness Limitations:** The system provides verifiable ballot casting and ballot secrecy against passive observers and single-officer compromises. The protocol **does not claim complete receipt-freeness or coercion resistance**; an adversary physically observing the voter's screen or coercing authentication credentials cannot be mitigated by threshold cryptography alone.
3. **Anonymity Scope:** Cast ballots are pseudonymously encrypted under the joint public key and verified on-chain via zero-knowledge proofs. The system does not claim complete unconditional anonymity; voter network metadata, relayer submission patterns, and client endpoint telemetry must be defended via separate network-layer mechanisms (e.g., mixnets, VPNs, timing perturbation).
4. **Endpoint & Device Compromise:** If an officer's computing device is compromised by malware, keyloggers, or memory inspection tools while the dashboard is active, the private scalar held in volatile browser component memory can be extracted.
5. **Key Loss Contingency:** If either officer permanently loses their private key share (both volatile component memory and encrypted offline backup passphrase), the election cannot be tallied. No administrative master key or backdoor exists to recover the ballots; the election must be declared void after the 72-hour `TallyStalled` lockout.
