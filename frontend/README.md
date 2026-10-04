# Vote Without Doubt - Frontend

React + Vite frontend for the Vote Without Doubt e-voting system
(**Academic Prototype - not a legally binding election system**).

Current project phase status:
[`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative)

## Requirements

- Node.js 20+ (local verified: v24.19.0)
- A running backend at `http://localhost:5000` (see [`../backend/README.md`](../backend/README.md))
- MetaMask **desktop** extension for wallet features (mobile MetaMask is out of scope)
- A webcam for face/liveness features

## Scripts

```bash
npm install
npm run dev        # Vite dev server -> http://localhost:5173
npm run build      # production build -> dist/
npm run preview    # serve the production build locally
npm run lint       # oxlint
```

## Source layout (actual)

| File | Purpose |
|---|---|
| `src/main.jsx` | React entry point |
| `src/App.jsx` | Application shell, phase indicator, component composition |
| `src/App.css`, `src/index.css` | Neo-brutalist base styling |
| `src/Auth.jsx` / `Auth.css` | Registration + login + OTP UI |
| `src/Registration.jsx` | Electoral-roll eligibility and registration completion UI |
| `src/Wallet.jsx` | MetaMask challenge signing / wallet binding UI |
| `src/Face.jsx` / `Face.css` | Face enrolment and liveness UI |
| `src/Voting.jsx` / `Voting.css` | Voting authorization, ballot submission and revoting UI |
| `src/assets/` | Images and icons |

There is no `frontend/src/` router, admin UI, results UI or public-verifier UI yet. Admin
management is Phase 11 and public verification is Phase 12 - both NOT STARTED.

## Configuration

The dev server proxies nothing by default; point the UI at the backend by editing the API base
URL used in `src/`. The backend CORS allow-list is configured through
`CORS_ALLOWED_ORIGINS` in `backend/.env` (see `backend/.env.example`), which lists
`http://localhost:5173` by default.

## Privacy notes for frontend work

- Never display or store a ballot pseudonym, a blockchain transaction hash, or a candidate
  selection in any receipt-like view.
- Receipts are intentionally minimal: election title, voter ID last 4, minute-level time and an
  HMAC receipt code.
- Do not add candidate selection to any wallet-signed message.
- Revoting is limited coercion mitigation, not absolute protection. Do not describe it in the UI
  as "coercion proof".

## Lint status

`npm run lint` currently reports warnings (unused variables, `setState` inside an effect) in
`src/Registration.jsx` and `src/Auth.jsx`. Recorded, not fixed during Phase 0 remediation.