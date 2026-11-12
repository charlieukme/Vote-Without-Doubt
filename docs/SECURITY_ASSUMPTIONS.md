# Security Assumptions & Environmental Dependencies

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Explicit Security Assumptions

The correctness, privacy, and integrity guarantees of **Vote Without Doubt** rely on the following explicit environmental and operational assumptions. If any assumption is violated, the corresponding security guarantee may be degraded or compromised.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              TRUST & ASSUMPTION MODEL                                  │
├─────────────────────────┬──────────────────────────────────────────────────────────────┤
│ Component / Boundary    │ Required Assumption                                          │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Voter Client Device     │ Uncompromised OS, untampered browser, absence of keyloggers  │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ MetaMask / Web3 Wallet  │ Voter exclusively controls private key; extension is genuine │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Backend Server Host     │ Protected root access, hardened Linux environment, no breach │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Relayer Private Key     │ Stored securely in HSM / env; not exposed to public or Git   │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Database Infrastructure │ Access restricted to backend application; network firewalled │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Institutional Registrar │ Authoritative student roll CSV is accurate and untampered    │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Administrative Officers │ Non-collusion between two distinct officers (Four-Eyes rule) │
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Transport Layer (TLS)   │ HTTPS termination at reverse proxy (TLS 1.2+); secure cookies│
├─────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Time Synchronization    │ NTP synchronized across server and blockchain nodes          │
└─────────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Assumption Analysis

### A. Voter Endpoint & Client Device Integrity
- **Assumption:** The student's device (laptop or mobile browser) is not infected with malware, screen scrapers, keyloggers, or malicious browser extensions capable of intercepting keystrokes or altering DOM elements.
- **Impact if Violated:** An adversary with root/screen access on the voter's device can observe the voter's candidate selection or steal active session tokens.
- **Architectural Boundary:** The web application cannot defend an already-compromised client endpoint.

### B. Wallet Possession & MetaMask Extension Integrity
- **Assumption:** The voter's Web3 wallet extension is authentic, and the voter possesses the private key corresponding to their bound Ethereum address.
- **Impact if Violated:** An adversary who steals the voter's seed phrase can sign the possession challenge, satisfying the wallet factor.
- **Mitigating Controls:** Wallet signing is only one of multiple factors; the adversary would still require the voter's password, email OTP, and live biometric face match.

### C. Host & Operating System Integrity
- **Assumption:** The server hosting the Flask application, Python virtual environment, and background relayer worker has not suffered root or container escape compromise.
- **Impact if Violated:** A root attacker can read environment variables (`SECRET_KEY`, `PSEUDONYM_MASTER_KEY`, `RELAYER_PRIVATE_KEY`) directly from process memory.

### D. Relayer Key Confidentiality
- **Assumption:** The private key of the institutional Ethereum relayer account is safeguarded and never committed to version control.
- **Impact if Violated:** An attacker with the relayer key could sign arbitrary transactions directly to the smart contract, attempting to bypass backend queue logic (though the smart contract still enforces roll hash and sequence constraints).

### E. Database Access Control & Network Isolation
- **Assumption:** Direct TCP access to the MySQL database port (3306) is firewalled and accessible only by the Flask application and relayer worker services.
- **Impact if Violated:** Direct SQL access allows an attacker to alter tables or inspect live state during active voting.

### F. Administrative Honesty & Non-Collusion
- **Assumption:** At least one of the two administrative officers required for Four-Eyes approval is honest and acts in good faith.
- **Impact if Violated:** If two officers collude, they can approve unauthorized roll imports or prematurely cancel an active election.

### G. Institutional Registrar Integrity
- **Assumption:** The student electoral roll provided by the college administration (registrar / academic office) accurately represents the student body and has not been maliciously manipulated prior to upload.
- **Impact if Violated:** If the registrar provides a fraudulent CSV, unauthorized individuals will be registered as eligible voters.

### H. Transport Layer Security (TLS/HTTPS)
- **Assumption:** In any production deployment, all web traffic is encrypted via TLS 1.2+ using valid certificates, and `SESSION_COOKIE_SECURE=True` is enabled in configuration.
- **Impact if Violated:** Cleartext HTTP traffic would expose session cookies, passwords, and frame payloads to network eavesdroppers on campus Wi-Fi networks.

### I. System Clock Synchronization (NTP)
- **Assumption:** The server running the backend and the blockchain nodes maintain synchronized clocks via Network Time Protocol (NTP) within $\pm 2$ seconds.
- **Impact if Violated:** Clock skew could cause premature expiration of email OTPs (5 min), TOTP verification steps (30 sec), or discrepancies in election start/end boundaries.
