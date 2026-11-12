# Development Setup

Vote Without Doubt - local development environment.

This document describes **how to set up and run the project as it exists in this repository**.
It is not a phase history. For current phase status see
[`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative).

---

## 1. Prerequisites (frozen floors)

| Layer | Requirement | Verified locally |
|---|---|---|
| Python | 3.11+ | 3.11.9 |
| Database | SQLite (dev/test) / MySQL 8.0 | SQLite / MySQL 8.x |
| Node.js | 20+ | v24.19.0 |
| npm | ships with Node | 11.17.0 |
| Solidity | 0.8.19 (pinned in `blockchain/hardhat.config.js`) | 0.8.19 |
| Hardhat | 2.19+ | see `blockchain/package.json` |
| Local EVM | Hardhat Node (`127.0.0.1:8545`, chain ID `1337`) | chain ID 1337 |
| Browser | Desktop Chrome / Edge / Firefox | - |
| Webcam | required for face + liveness | - |
| MetaMask | desktop browser extension | - |
| Mobile | **Mobile MetaMask is out of scope** | - |

Optional: **mkcert** for local TLS if a realistic HTTPS local setup is required.

---

## 2. Repository structure (actual)

```
voting-sys/
|-- README.md
|-- PROJECT_MASTER_REPORT.md
|-- PROJECT_BIBLE.md
|-- .gitignore
|-- backend/
|   |-- app/
|   |   |-- __init__.py          app factory + blueprint registration
|   |   |-- extensions.py        Flask extensions (SQLAlchemy)
|   |   |-- schema.sql           MySQL schema (identity plane + ballot plane + audit)
|   |   |-- config/              environment-based configuration
|   |   |-- models/              SQLAlchemy models
|   |   |-- routes/              HTTP blueprints
|   |   |-- services/            business logic
|   |   |-- security/            password, otp, sessions, wallet, face, pseudonym
|   |   |-- audit/               hash-chained audit
|   |   |-- relayer/             relayer worker
|   |   |-- email/               SMTP / Mailpit delivery
|   |   `-- utils/               CSV roll import
|   |-- tests/                   pytest suite
|   |-- requirements.txt
|   |-- run.py
|   |-- .env.example             tracked template, placeholders only
|   `-- README.md
|-- frontend/
|   |-- src/                     React components
|   |-- index.html
|   |-- package.json
|   |-- vite.config.js
|   |-- .oxlintrc.json
|   `-- README.md
|-- blockchain/
|   |-- contracts/
|   |   |-- BN254.sol
|   |   |-- BN254CDSVerifier.sol
|   |   `-- EVotingBallotBoxV2.sol
|   |-- test/                    Hardhat tests
|   |-- scripts/                 V2 provisioning & relayer scripts
|   |-- hardhat.config.js
|   `-- package.json
|-- docs/                        phase documents, guides, threat register
`-- scripts/
    |-- start_vwd_services.ps1
    `-- verify_foundation.ps1
```

> Note the real paths: Solidity sources are in **`blockchain/contracts/`**. There is no
> top-level `contracts/` directory.

---

## 3. Local services

| Service | Address | Purpose |
|---|---|---|
| Database | `backend/instance/voting.db` (SQLite) or MySQL 8 `localhost:3306` | both data planes + audit |
| Hardhat Node | `127.0.0.1:8545` (chain ID 1337) | local V2 EVM blockchain |
| Mailpit / SMTP | `localhost:1025` | development OTP email |
| Flask backend | `localhost:5000` | API + V2 lifecycle worker & relayer |
| Vite dev server | `localhost:5173` | frontend |

---

## 4. Backend setup

```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure environment variables:

```powershell
Copy-Item .env.example .env      # then edit .env with local values
```

`.env.example` contains placeholders only. The real `.env` is git-ignored - never commit it.

#### Database Schema & Migrations

The authoritative schema lifecycle is managed exclusively through Flask-Migrate (Alembic) located in `backend/migrations/versions/`.

> **IMPORTANT:** Do NOT initialize production or test databases using raw `backend/app/schema.sql`. That file represents the Phase 1 baseline schema and lacks tables, indexes, and columns introduced in subsequent phases (Phase 8 pseudonyms, Phase 9 revoting, Phase 10 recovery, Phase 11 RBAC, Phase 12 tallying, Phase 13 security hardening, and Phase C.11 challenge lease fields).

Apply all database migrations up to the current HEAD:

```powershell
flask db upgrade                  # applies all linear migrations up to HEAD (f1a2b3c4d5e6)
```

Verify that the database schema is synchronized with SQLAlchemy models:

```powershell
flask db check                    # should report "No new upgrade operations detected"
```

Then start the API:

```powershell
python run.py                     # http://localhost:5000
```

Health check: `http://localhost:5000/api/health`

Run the backend test suite:

```powershell
pytest -v
```

> Phase 5 test-suite defect **resolved** during Phase 5 remediation (2026-10-05):
> `tests/test_face_api.py` and `tests/test_face_validation.py` were removed and replaced by
> `test_phase5_face_engine.py`, `test_phase5_face_security.py` and `test_phase5_evaluation.py`,
> which run against the real model stack.

---

## 5. Frontend setup

```powershell
cd frontend
npm install
npm run dev                       # http://localhost:5173
npm run build                     # production build -> dist/
npm run preview                   # serve the production build locally
npm run lint                      # oxlint
```

---

## 6. Blockchain setup and Relayer Authorization

```powershell
cd blockchain
npm install
npm run compile                   # solc 0.8.19
npm test                          # Hardhat test suite (ephemeral in-process network)
npm run deploy:ganache            # deploy to a running local Ganache node (127.0.0.1:8545, chainId 1337)
npm run deploy:hardhat            # deploy to the ephemeral in-process Hardhat network
```

> **Local environment caveat.** In this working copy `blockchain/node_modules/.bin` is missing,
> so the `hardhat` shim cannot be resolved and `npm test` / `npm run compile` fail with
> `'hardhat' is not recognized`. The equivalent invocation that does work here is:
>
> ```powershell
> cd blockchain
> node node_modules/hardhat/internal/cli/cli.js test
> ```
>
> Re-running `npm install` inside `blockchain/` regenerates the `.bin` shims. Recorded as a
> known environment issue.

### Mandatory Relayer Authorization (`setRelayer`)

When `EVotingBallotBox.sol` is deployed, the constructor sets the deploying account as `officer` and initializes `relayer = address(0)`. By smart-contract invariant, any transaction sent to `castBallot` by an unauthorized account will revert with `UNAUTHORIZED_RELAYER`.

Therefore, the contract officer must explicitly authorize the relayer account before any ballots can be submitted.

#### Prerequisites:
1. Local Ganache instance running on `127.0.0.1:8545` with network/chain ID `1337`.
2. `EVotingBallotBox.sol` deployed to Ganache, with the deployed address noted.
3. The designated relayer address (e.g. Account #1 from Ganache accounts).

#### Authorization Steps:

1. Connect to the Hardhat console on the local Ganache network:
   ```powershell
   npx hardhat console --network ganache
   ```
2. Authorize the relayer account via the officer signer:
   ```javascript
   const [officer] = await ethers.getSigners();
   const contractAddress = "<DEPLOYED_CONTRACT_ADDRESS>";
   const relayerAddress = "<DESIGNATED_RELAYER_ADDRESS>";

   const ballotBox = await ethers.getContractAt("EVotingBallotBox", contractAddress, officer);
   const tx = await ballotBox.setRelayer(relayerAddress);
   await tx.wait();
   console.log("Relayer authorization transaction mined:", tx.hash);
   ```
3. Verify authorization on-chain:
   ```javascript
   const activeRelayer = await ballotBox.relayer();
   console.log("Active authorized relayer:", activeRelayer);
   // Must match relayerAddress and not be 0x0000000000000000000000000000000000000000
   ```
4. Configure backend environment:
   Set `BALLOTBOX_CONTRACT_ADDRESS=<DEPLOYED_CONTRACT_ADDRESS>` and `RELAYER_PRIVATE_KEY=<RELAYER_PRIVATE_KEY>` in `backend/.env`.

> **CRITICAL WARNING:** This authorization step must ONLY be executed against the ephemeral local test network (Ganache chainId 1337) or the Hardhat test network. NEVER execute deployment or relayer authorization against any public, testnet, or live blockchain.

---

## 7. Foundation verification

From the repository root:

```powershell
.\scripts\verify_foundation.ps1
```

Read-only. Prints PASS/FAIL per check and exits non-zero if any check fails.

---

## 8. Environment variables

Canonical template: [`../backend/.env.example`](../backend/.env.example). The application distinguishes between development defaults and strict production enforcement (`ProductionConfig`).

### Comprehensive Configuration Reference

| Variable | Scope / Requirement | Format & Validation | Purpose & Generation |
|---|---|---|---|
| `SECRET_KEY` | **Required in Prod** (Dev generates random per-process) | String >= 32 chars. Rejects legacy placeholders. | Flask session signing and CSRF integrity. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `OTP_PEPPER` | **Required in Prod** (Refuses boot if missing) | 64-char hex string (32 bytes entropy). | Phase 2 HMAC-SHA256 secret pepper for email OTP hashes (`app.security.otp`). Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ROLL_ADMIN_TOKEN` | **Required in Prod** (Refuses boot if missing) | High-entropy string (>= 32 chars). | Phase 3 bootstrap credential for electoral-roll import (`X-Admin-Token` header). Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `PSEUDONYM_MASTER_KEY` | **Required in Prod** (Refuses boot if missing) | 44-char url-safe base64 string (`Fernet` key). | Phase 8 envelope key protecting per-election HMAC pseudonym keys at rest (`app.security.pseudonym`). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `FACE_ENCRYPTION_KEY` | **Required in Prod** (Refuses boot if missing) | 44-char base64 `Fernet` key or `id:key` rotation map. | Phase 5 envelope key protecting ArcFace 512-d biometric templates at rest (`app.security.face`). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `FACE_SIMILARITY_THRESHOLD` | **Required in Prod** (Default 0.68 in dev/test) | Float strictly between 0.0 and 1.0. | Calibrated cosine similarity threshold for ArcFace biometric 1:1 matching. Established by empirical benchmark study. |
| `FACE_PAD_MODE` | Optional (Defaults to `'shadow'`) | String: `'shadow'` or `'disabled'`. | Presentation Attack Detection mode. Strictly forced to `'shadow'` (non-enforcing telemetry) unless disabled. Live enforcement prohibited prior to IRB approval. |
| `BALLOTBOX_CONTRACT_ADDRESS` | **Required when relayer active** | 42-char hex Ethereum address (`0x[0-9a-fA-F]{40}`). | Deployed `EVotingBallotBox.sol` smart contract address on Ganache. Obtained from contract deployment output. |
| `RELAYER_PRIVATE_KEY` | **Required when relayer active** | 64-char hex ECDSA private key (or 66-char `0x` hex). | Private key for the Ethereum account authorized via `ballotBox.setRelayer()`. Used by the Python relayer worker to sign transactions. |
| `GANACHE_HOST` / `GANACHE_PORT` | Local blockchain | Hostname and port (default `localhost:8545`). | Local Ethereum RPC endpoint (chain ID 1337). |
| `MYSQL_HOST` / `PORT` / `DATABASE` / `USER` / `PASSWORD` | Database connection | Host, port (3306), database name, credentials. | MySQL 8.0 connection parameters for identity and ballot data planes. Overridden by `DATABASE_URL` if set. |
| `DATABASE_URL` | Optional (Overrides MySQL) | SQLAlchemy database URI (e.g. `sqlite:///...`). | Allows directing backend or migration tooling to isolated SQLite databases without modifying application config. |
| `MAIL_SERVER` / `MAIL_PORT` | Email service | Host and port (default `localhost:1025` for Mailpit). | SMTP delivery configuration for student verification OTP emails. |
| `CORS_ALLOWED_ORIGINS` | Web security | Comma-separated origin URLs. | Permitted frontend cross-origin requests (e.g. `http://localhost:5173`). |
| `LOG_LEVEL` | Application logging | String: `DEBUG`, `INFO`, `WARNING`, `ERROR`. | Controls logging verbosity across backend subsystems. |

---

## 9. Ground rules

- Never commit `.env`, keys, certificates or database dumps.
- Keep identity-plane and ballot-plane separation intact; do not add cross-plane foreign keys.
- Do not add candidate selection to any wallet-signed message.
- Do not begin a new phase without explicit instruction.