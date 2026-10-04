# Development Setup

Vote Without Doubt - local development environment.

This document describes **how to set up and run the project as it exists in this repository**.
It is not a phase history. For current phase status see
[`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative).

---

## 1. Prerequisites (frozen floors)

| Component | Requirement | Verified locally |
|---|---|---|
| Python | 3.11+ | 3.11.9 |
| MySQL | 8.0 | 8.x |
| Node.js | 20+ | v24.19.0 |
| npm | ships with Node | 11.17.0 |
| Solidity | 0.8.19 (pinned in `blockchain/hardhat.config.js`) | 0.8.19 |
| Hardhat | 2.19+ | see `blockchain/package.json` |
| Ganache | local chain, chain ID 1337 | chain ID 1337 |
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
|   |   `-- EVotingBallotBox.sol
|   |-- test/                    Hardhat tests
|   |-- scripts/                 deploy.js, relayer.js
|   |-- hardhat.config.js
|   `-- package.json
|-- docs/                        phase documents, guides, threat register
`-- scripts/
    `-- verify_foundation.ps1
```

> Note the real paths: Solidity sources are in **`blockchain/contracts/`**. There is no
> top-level `contracts/` directory.

---

## 3. Local services

| Service | Address | Purpose |
|---|---|---|
| MySQL 8 | `localhost:3306` | both data planes + audit |
| Ganache | `127.0.0.1:8545` (chain ID 1337) | local blockchain |
| Mailpit / SMTP | `localhost:1025` | development OTP email |
| Flask backend | `localhost:5000` | API |
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

Apply the database schema (see [DATABASE_SETUP.md](./DATABASE_SETUP.md)), then start the API:

```powershell
python run.py                     # http://localhost:5000
```

Health check: `http://localhost:5000/api/health`

Run the backend test suite:

```powershell
pytest -v
```

> Known test-suite defect: `tests/test_face_api.py` currently errors during collection (6 errors)
> because it requests a `client` fixture that is not provided by the active pytest/plugin
> configuration. This is a Phase 5 defect, recorded but deliberately not fixed during Phase 0
> remediation.

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

## 6. Blockchain setup

```powershell
cd blockchain
npm install
npm run compile                   # solc 0.8.19
npm test                          # Hardhat test suite
npm run deploy:ganache            # deploy to a running local Ganache node
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

---

## 7. Foundation verification

From the repository root:

```powershell
.\scripts\verify_foundation.ps1
```

Read-only. Prints PASS/FAIL per check and exits non-zero if any check fails.

---

## 8. Environment variables

Canonical template: [`../backend/.env.example`](../backend/.env.example).

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing secret - must be replaced in any real deployment |
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL address |
| `MYSQL_DATABASE` / `MYSQL_USER` / `MYSQL_PASSWORD` | MySQL credentials |
| `MAIL_SERVER` / `MAIL_PORT` | SMTP / Mailpit for OTP delivery |
| `GANACHE_HOST` / `GANACHE_PORT` / `GANACHE_CHAIN_ID` | local chain |
| `CORS_ALLOWED_ORIGINS` | allowed frontend origins |
| `LOG_LEVEL` | logging verbosity |

---

## 9. Ground rules

- Never commit `.env`, keys, certificates or database dumps.
- Keep identity-plane and ballot-plane separation intact; do not add cross-plane foreign keys.
- Do not add candidate selection to any wallet-signed message.
- Do not begin a new phase without explicit instruction.