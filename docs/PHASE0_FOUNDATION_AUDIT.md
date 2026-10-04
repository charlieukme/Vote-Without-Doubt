# PHASE 0 FOUNDATION AUDIT (PRE-REMEDIATION RECORD)

**Document type:** Historical audit record. This file preserves the audit that was performed
before Phase 0 remediation. It is **not** the current status. For current status see
`PROJECT_BIBLE.md` Section 3.

- **Audit scope:** Phase 0 foundation only (documentation, repository hygiene, threat model,
  verification tooling, development environment freeze).
- **Audit boundary:** This repository only. No parent, sibling or external directory was inspected.
- **Audit method:** Direct file inspection, `git` state inspection, and execution of the existing
  backend, blockchain and frontend test/build commands.
- **Files inspected:** all root files, all `docs/*.md`, `backend/`, `frontend/`, `blockchain/`.
- **Audit verdict:** **PARTIAL** — the specification substance existed, but the foundation was not
  verifiable or internally consistent.
- **Findings raised:** 17

---

## 1. Evidence gathered during the audit

| Command | Result |
|---|---|
| `python -m pytest` (backend) | 49 passed, 6 errors |
| `node node_modules/hardhat/internal/cli/cli.js test` (blockchain) | 11 passing |
| `npm test` (blockchain) | FAILED — `'hardhat' is not recognized` (no `node_modules/.bin`) |
| `npm run build` (frontend) | SUCCESS |
| `npm run lint` (frontend) | SUCCESS with warnings (`Registration.jsx`, `Auth.jsx`) |
| `git status` (repository root) | Not a git repository |
| Old-project contamination scan (repository only) | NOT FOUND |

## 2. Findings

| # | Finding | Severity |
|---|---|---|
| 1 | `docs/PHASE0_FINAL_REPORT.md` absent — Phase 0 completion was never recorded in the required format. | Major |
| 2 | `PROJECT_BIBLE.md` was not machine-recoverable: literal `\n` escape sequences instead of real line breaks, plus mojibake. | Critical |
| 3 | `PROJECT_BIBLE.md` declared contradictory statuses (e.g. a checklist marking Phase 0 "IN PROGRESS" alongside a status table marking it "COMPLETE"). | Critical |
| 4 | No frozen scope taxonomy (CORE / STRONG / OPTIONAL / FUTURE / DO NOT BUILD) existed in an authoritative specification. | Major |
| 5 | No repository root `README.md`. | Major |
| 6 | No repository root `.gitignore`; only `frontend/.gitignore` existed. Secrets and `venv/` were unignored. | Critical |
| 7 | The project was not a git repository, so integrity was unverifiable. | Major |
| 8 | Documentation repeatedly described Solidity sources as a top-level `contracts/` directory; the real path is `blockchain/contracts/`. | Major |
| 9 | `docs/DEV_SETUP.md` declared "Phase 2: NOT STARTED", contradicting the real state. | Critical |
| 10 | Required development environment floors were never frozen in any authoritative document. | Major |
| 11 | No executable verification script existed; all verification was self-attested prose. | Critical |
| 12 | Phase documents used inconsistent naming and placement (`PHASE_0_CHECKPOINT.md`; final reports for Phases 5–10 stored in the repository root). | Minor |
| 13 | Phase reports asserted verification results that no script could reproduce. | Major |
| 14 | `docs/PHASE1_CHECKPOINT.md` contains mojibake and a self-contradicting test-count paragraph. | Minor |
| 15 | Phases 0–4 had no final report at all. | Major |
| 16 | No threat model / threat register existed anywhere in the repository. | Major |
| 17 | General documentation consistency: no single authoritative status source; README/Bible/report statuses could not be reconciled. | Major |

## 3. What the audit explicitly did NOT find

- No old-project contamination inside the repository: no foreign absolute paths, no agent-memory
  files (`.claude/`, `AGENTS.md`, `CLAUDE.md`), no foreign package or project names.
- The two-plane privacy design (identity plane vs ballot plane) was substantively documented.
- The DO NOT BUILD exclusions and the required architecture were substantively present in
  `PROJECT_MASTER_REPORT.md`.

## 4. Implementation defects observed but NOT remediated in Phase 0

These were recorded during the audit. They are implementation concerns belonging to later phases
and were deliberately left untouched by Phase 0 remediation, which is documentation and
hygiene only.

1. `backend/app/schema.sql` declares `ballots` twice with incompatible column sets; the first
   declaration lacks `pseudonym` and `candidate`, so a fresh install does not match the ORM.
2. `reconciliation_issues` has an ORM model but no DDL in `schema.sql`.
3. `backend/tests/test_face_api.py` fails collection (6 errors) because the `client` fixture is
   not defined.
4. `backend/tests/test_revoting.py` and `backend/tests/test_recovery.py` are structural rather than
   end-to-end; they do not prove the revoting or recovery guarantees.
5. `blockchain/node_modules/.bin` is absent, so `npm test` cannot resolve the Hardhat binary.

---

**Audit verdict:** PARTIAL
**Remediation of these findings is recorded in `docs/PHASE0_FINAL_REPORT.md`.**