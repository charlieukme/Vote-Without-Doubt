# Vote Without Doubt

**AI & Blockchain-Based Secure E-Voting System for College Elections**

> **ACADEMIC PROTOTYPE — NOT A LEGALLY BINDING ELECTION SYSTEM.**
> This repository is a university/college project prototype built for study, demonstration and
> evaluation. It is not certified, not production-hardened, and must not be relied upon to run
> any statutory, binding or official election.

---

## What this project is

An academic prototype of a college e-voting system that layers several independent controls
together and is explicit about what it does *not* protect against:

- Electoral-roll verification and college-email ownership verification
- Password authentication plus email one-time passwords (OTP)
- MetaMask (desktop) wallet challenge signing as a possession factor
- Face recognition plus challenge-based liveness detection
- Blockchain-anchored pseudonymous ballots (local Ganache chain)
- Privacy-preserving receipts
- Hash-chained, tamper-evident audit logging
- Revoting with a cap of three ballots per voter per election
- Recovery and reconciliation between the database and the chain

The design goal is **verifiable integrity with pseudonymous ballots**, and honest documentation
of the residual risks. It is *pseudonymous*, **not** anonymous.

---

## Architecture

```
React + Vite (frontend)
        |
Flask backend (Python, modular monolith)
        |
MySQL 8  (IDENTITY plane  +  BALLOT plane)
        |
Relayer worker  +  Reconciler
        |
Ganache (local chain, chain ID 1337)
        |
Solidity 0.8.19 smart contract (EVotingBallotBox) via Hardhat
```

### Two data planes

| Plane | Holds |
|---|---|
| **IDENTITY** | voter identity, electoral roll, registration, authentication, eligibility, participation |
| **BALLOT** | pseudonymous voter identifiers, ballot records, candidate selection, ballot sequence, blockchain submission state |

The two planes are kept strictly separate: no direct foreign keys, no shared rows, no shared
ordering, and no candidate-bearing identity records. A controlled server-side bridge is used only
where operationally necessary.

---

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite |
| Backend | Python 3.11+ / Flask |
| Database | MySQL 8 |
| Blockchain | Ganache (chain ID 1337) |
| Smart contracts | Solidity 0.8.19 |
| Contract tooling | Hardhat |
| Email (development) | SMTP / Mailpit |
| Face / liveness | `backend/app/security/face.py`, `backend/app/services/face_service.py` |

---

## Repository structure

```
voting-sys/
|-- README.md                  # this file
|-- PROJECT_MASTER_REPORT.md   # authoritative specification + architecture
|-- PROJECT_BIBLE.md           # living engineering source of truth (current status lives here)
|-- .gitignore
|-- backend/                   # Flask backend
|   |-- app/                   #   config, models, routes, services, security, audit, relayer, email, utils
|   |-- tests/                 #   pytest suite
|   |-- requirements.txt
|   `-- run.py
|-- frontend/                  # React + Vite frontend (src/, package.json, vite.config.js)
|-- blockchain/                # Hardhat project
|   |-- contracts/             #   EVotingBallotBox.sol
|   |-- test/                  #   Hardhat tests
|   `-- scripts/               #   deploy.js, relayer.js
|-- docs/                      # phase documents, setup guides, threat register
`-- scripts/                   # verify_foundation.ps1
```

Solidity sources live in **`blockchain/contracts/`**. There is no top-level `contracts/`
directory.

---

## Current phase status

The single authoritative source is
[`PROJECT_BIBLE.md` Section 3](./PROJECT_BIBLE.md#3-current-phase-status-authoritative).

| Phase | Status |
|---|---|
| Phase 0 - Project Foundation | COMPLETE |
| Phase 1 - Backend + Database Foundation | COMPLETE |
| Phase 2 - Authentication Core | COMPLETE |
| Phase 3 - College Roll + Registration | COMPLETE |
| Phase 4 - MetaMask / Wallet Security | COMPLETE |
| Phase 5 - Face + Liveness | COMPLETE |
| Phase 6 - Blockchain / Smart Contract | COMPLETE |
| Phase 7 - Core Voting Pipeline (Milestone A) | COMPLETE |
| Phase 8 - Privacy Hardening | COMPLETE |
| Phase 9 - Revoting + Coercion Resistance (Milestone B) | COMPLETE |
| Phase 10 - Recovery + Reconciliation | COMPLETE |
| Phase 11 - Admin + Election Management | NOT STARTED |
| Phase 12 - Public Verification + Results | NOT STARTED |
| Phase 13 - Security Hardening | NOT STARTED |
| Phase 14 - Full Failure + Performance Testing | NOT STARTED |
| Phase 15 - Privacy / Legal / Documentation | NOT STARTED |
| Phase 16 - Final UI + Demo | NOT STARTED |
| Phase 17 - Final Release | NOT STARTED |

A phase marked COMPLETE means its deliverables and documents exist. It is **not** a claim that
every designed control is fully implemented and independently verified - see
[`docs/THREAT_MODEL_REGISTER.md`](./docs/THREAT_MODEL_REGISTER.md) for per-control evidence.

---

## Documentation

| Document | Purpose |
|---|---|
| [`PROJECT_MASTER_REPORT.md`](./PROJECT_MASTER_REPORT.md) | Authoritative specification, architecture, frozen scope taxonomy, environment |
| [`PROJECT_BIBLE.md`](./PROJECT_BIBLE.md) | Living source of truth: current phase status, design baselines, decisions, risks |
| [`docs/THREAT_MODEL_REGISTER.md`](./docs/THREAT_MODEL_REGISTER.md) | THREAT -> CONTROL -> TEST -> RESULT -> LIMITATION register |
| [`docs/PHASE0_FINAL_REPORT.md`](./docs/PHASE0_FINAL_REPORT.md) | Phase 0 final / remediation report |
| [`docs/PHASE0_FOUNDATION_AUDIT.md`](./docs/PHASE0_FOUNDATION_AUDIT.md) | Phase 0 implementation audit |
| [`docs/DEV_SETUP.md`](./docs/DEV_SETUP.md) | Development environment setup |
| [`docs/DATABASE_SETUP.md`](./docs/DATABASE_SETUP.md) | MySQL schema application and least-privilege user |
| [`docs/`](./docs) | Per-phase checkpoints and final / retrospective reports |

---

## Development setup

Full instructions: [`docs/DEV_SETUP.md`](./docs/DEV_SETUP.md) and
[`docs/DATABASE_SETUP.md`](./docs/DATABASE_SETUP.md).

Requirements (floors): Python 3.11+, MySQL 8, Node.js 20+, Solidity 0.8.19, Hardhat, Ganache
(chain ID 1337), desktop Chrome/Edge/Firefox, a webcam, and the MetaMask desktop extension.
Mobile MetaMask is out of scope.

Environment variables are read from `backend/.env`. Copy the tracked template
`backend/.env.example` and fill in local values. **Never commit a real `.env`; it is ignored.**

### Backend

```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py            # http://localhost:5000
pytest -v                # test suite
```

Apply the database schema first - see [`docs/DATABASE_SETUP.md`](./docs/DATABASE_SETUP.md).

### Frontend

```powershell
cd frontend
npm install
npm run dev              # http://localhost:5173
npm run build            # production build to dist/
npm run preview          # preview the production build
npm run lint             # oxlint
```

### Blockchain

```powershell
cd blockchain
npm install
npm run compile          # compile contracts
npm test                 # Hardhat test suite
npm run deploy:ganache   # deploy to a running local Ganache node
```

> **Local environment note:** in this working copy `blockchain/node_modules/.bin` is absent, so
> `npm test` / `npm run compile` cannot resolve the `hardhat` shim. The verified equivalent
> invocation is:
>
> ```powershell
> cd blockchain
> node node_modules/hardhat/internal/cli/cli.js test
> ```
>
> Re-running `npm install` in `blockchain/` restores the shims. This is recorded as a known
> environment issue, not a design decision.

### Foundation verification

```powershell
.\scripts\verify_foundation.ps1
```

Verifies required files, directories, scope categories, architecture terminology, encoding
integrity, contamination scan and phase-status consistency. Read-only; exits non-zero on
failure.

---

## Security and privacy limitations

Read these before drawing any conclusion from the system.

- **Academic prototype.** Not legally binding. Not production-ready.
- **Pseudonymous, not anonymous.** Ballots are HMAC-SHA256 pseudonyms. Linkability is reduced,
  not eliminated.
- **Trusted-backend assumption.** Privacy does **not** hold against a root/backend operator with
  access during the election.
- **Coercion resistance is limited.** Revoting lets a voter replace an earlier ballot while
  voting is open. It does not help if an attacker controls the voter's device, the
  authenticated session, the authentication factors, or physically observes the voter.
- **Biometrics are attackable.** Face/liveness can be defeated by deepfakes, replay and virtual
  cameras. No formal FAR/FRR/APCER evaluation is complete.
- **Malicious relayer cannot be fully prevented** - only detected, via reconciliation and audit
  anchoring.
- **Local-only stack.** Ganache on localhost, desktop browsers, small scale (<= 500 voters,
  <= 20 candidates). Not hardened for the public internet.
- **Evidence gaps exist.** Some controls are design-only or thinly tested; the threat register
  states which.

---

## Academic honesty note

This project deliberately records what it does not protect against. Claims of "fully secure",
"anonymous", "uncoercible" or "production-ready" are not supported by this repository and must
not be made on its basis.