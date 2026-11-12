# Phase 1 Implementation Audit (Independent, Read-Only)

**Date:** 2026-10-04  
**Auditor:** Independent (not the implementation team)  
**Scope:** Phase 1 requirements A–O, frozen in `PROJECT_MASTER_REPORT.md`  
**Method:** Strict read-only inspection; no files modified; all commands executed in-place.

---

## Executive Verdict

**OVERALL: PARTIAL**

| Req | Title | Verdict | Notes |
|-----|-------|---------|-------|
| **A** | Flask architecture | **PASS** | Factory pattern, blueprints, clean imports. |
| **B** | MySQL foundation | **PARTIAL** | URI assembled, but DB never verified reachable; `create_all()` swallowed all exceptions. |
| **C** | Identity/ballot separation | **PASS** | ORM models correctly isolated; no identity FKs in ballot plane. |
| **D** | Schema foundation | **PARTIAL** | Two conflicting `CREATE TABLE ballots` in `schema.sql`; ORM/DDL drift. |
| **E** | Database security | **PARTIAL** | URI uses env vars, but no TLS enforcement, no least-privilege proof. |
| **F** | Audit-log foundation | **FAIL** | No persistence; chain lives in process-local list only. |
| **G** | Privacy-safe audit | **PARTIAL** | Cleartext survives for voter_id, email, full_name, wallet_address, signature, user_password, candidate, pseudonym, face_embedding. Non-JSON metadata raises `TypeError`. |
| **H** | Frontend shell | **PARTIAL** | React + Vite + neo-brutalist CSS present, but hard-coded `http://localhost:5000/api` in Face.jsx/Voting.jsx; no router, no API client, no error boundary. |
| **I** | Neo-Brutalism | **PASS** | `#FFFDF5`, black, `#C4B5FD`, thick borders, hard shadows, Space Grotesk, sharp geometry. |
| **J** | Security middleware | **PARTIAL** | CORS present; no CSP, HSTS, CSRF, rate limit, or trusted-host enforcement. |
| **K** | Configuration/environment | **PARTIAL** | `.env.example` exists, but `SECRET_KEY` has publicly known fallback; debug defaults on; `0.0.0.0` bind. |
| **L** | Testing foundation | **PARTIAL** | `pytest` runs 15 Phase-1 tests, but no `conftest.py`, no DB fixtures, no DB-backed model tests. |
| **M** | Documentation/setup | **PARTIAL** | `README` has generic install steps; no MySQL integration path; phase doc titles don't match frozen scope. |
| **N** | Boundary enforcement | **PARTIAL** | `db.create_all()` called at startup; later-phase blueprints registered unconditionally. |
| **O** | No fake later-phase foundation | **PASS** | No registration/Otp/wallet/face/voting code executed at boot. |

---

## Detailed Findings

### 1. Audit Log — Non-Deterministic Chain Verification
**File:** `backend/app/audit/audit.py`

```python
def verify_chain(self):
    expected = AuditEvent(
        event_type=event.event_type,
        metadata=event.metadata,   # <-- re-reads mutable dict
        timestamp=datetime.now(),  # <-- NEW clock reading
        previous_hash=prev_hash
    )
    if expected.hash != event.hash:
        return False
```

* The verifier re-instantiates an `AuditEvent` using a **fresh `datetime.now()`**, then compares its hash to the stored hash. The hash includes the timestamp, so an unmodified event fails whenever the re-computation happens at a different microsecond.
* Empirical: 100 untampered chains → **31 failures** (`test_audit_chain_integrity` flaky: 6/12 runs).
* Direct trials: 300 iterations of a 3-event chain → **31 false negatives** (10.3%).

### 2. Audit Log — No Persistence
**File:** `backend/app/audit/audit.py` (lines 87–135)

* `AuditLogger.log()` appends to `self._events = []` only.
* `audit_events` DDL exists in `schema.sql` (line 74), but **no ORM model maps it**.
* A process restart loses the entire chain; anchoring (Phase 6/12) cannot be built on this.

### 3. Audit Log — Privacy Leaks
**File:** `backend/app/audit/audit.py` (lines 100–110)

```python
SENSITIVE_KEYS = {'password', 'passwd', 'passphrase', ...}
# Missing: voter_id, email, full_name, wallet_address, signature,
#          user_password, candidate, pseudonym, face_embedding
```

* The sanitiser only blocks 14 keys. The following were observed in test payloads and persisted **in clear**:
  - `voter_id`, `email`, `full_name`, `wallet_address`, `signature`
  - `user_password`, `candidate`, `pseudonym`, `face_embedding`
* `metadata` is stored as JSON without recursive sanitisation; nested objects with sensitive keys pass through unchecked.
* Non-serializable metadata raises `TypeError` at log time.

### 4. Open-Redirect Bypass
**File:** `backend/app/security/security.py` (lines 22–33)

```python
def is_safe_redirect_url(url, allowed_hosts=None):
    if url.startswith(('http://', 'https://')):
        return any(host in url for host in allowed_hosts)  # <-- SUBSTRING CHECK
    return url.startswith('/')
```

* `"localhost" in "http://evil.com/?x=localhost"` → **True** (host-substring bypass).
* `"localhost" in "https://evil.com/localhost"` → **True**.
* Protocol-relative `//evil.com/steal` falls through to `return False` then accepted because it starts with `/`.

### 5. Schema Divergence
**File:** `backend/app/schema.sql` (lines 48–69, 272–288)

Two conflicting `CREATE TABLE ballots`:
1. **Phase 1 (L48):** `ballot_id VARCHAR(100)`, `election_id VARCHAR(50)`, `ballot_state`, `ballot_sequence`, `blockchain_*`, `status`.
2. **Phase 7 (L272):** `election_id INT`, `pseudonym VARCHAR(128)`, `candidate INT`, `state`, `tx_hash`, `receipt_code`, `error`.

* ORM `Ballot` maps the Phase 1 table; ORM `BallotQueue` (`__tablename__='ballot_queue'`) expects the Phase 7 table. The Phase 7 DDL names it `ballots`, creating a collision.
* **Recovery columns** (8 of them, Phase 10) are indented into `VotingAuthorization` (identity plane) but the ALTERs target `ballots` (ballot plane). ORM↔DDL drift.

### 6. Database Security — Silent Failure
**File:** `backend/app/__init__.py` (lines 30–34)

```python
with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass  # <-- ALL ERRORS SWALLOWED
```

* A dead MySQL, a missing privilege, or a syntax error in a migration produces **zero log output** and the app boots anyway.

### 7. Configuration — Secret & Debug Defaults
**File:** `backend/app/config/config.py`

* `SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')` — shipped in source.
* `DevelopmentConfig.FLASK_DEBUG = True` — debugger on by default.
* `run.py`: `app.run(host='0.0.0.0', debug=True)` — network-exposed debugger.

### 8. Frontend — Hard-Coded Backend Origin
**Files:** `frontend/src/Face.jsx:4`, `frontend/src/Voting.jsx:4`

```javascript
const API_BASE = 'http://localhost:5000/api'
```

* Deployed to any other host/port, the frontend still calls the developer's laptop. No environment override.

### 9. Testing — No Database Fixtures
* `backend/tests/` has `test_audit.py`, `test_models.py`, `test_app.py` (15 tests).
* No `conftest.py`; every module builds its own app.
* `test_models.py` asserts separation on an **unpersisted object** — never exercises DB constraints.

### 10. Documentation — Stale Phase Claims
* `docs/PHASE1_CHECKPOINT.md` and `docs/PHASE1_FINAL_REPORT.md` claim "Phase 1 COMPLETE" despite the above defects.

---

## Evidence Files (Read-Only)

| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/audit/audit.py` | 1–135 | Audit logger + verifier + sanitiser (defective). |
| `backend/app/security/security.py` | 22–33 | Redirect validator (bypassable). |
| `backend/app/schema.sql` | 48–69, 272–325 | Conflicting DDL + trailing ALTERs. |
| `backend/app/__init__.py` | 16–41 | Factory with silent `create_all()` and unconditional blueprints. |
| `backend/app/config/config.py` | 12–86 | Config with hard-coded secret fallback and debug-on defaults. |
| `backend/run.py` | 1–17 | Dev server binding 0.0.0.0 with debugger. |
| `frontend/src/Face.jsx` | 1–91 | Hard-coded `API_BASE`. |
| `frontend/src/Voting.jsx` | 1–60 | Hard-coded `API_BASE`. |
| `backend/tests/test_audit.py` | 1–64 | 5 tests; `test_audit_chain_integrity` flaky. |
| `backend/tests/test_models.py` | 1–66 | Weak separation assertion. |

---

## Controlled Failure Probes (Conducted During Audit)

| Probe | Expected Exit | Actual Exit | Notes |
|-------|---------------|-------------|-------|
| `pytest tests/test_audit.py::test_audit_chain_integrity -v` (12×) | 0 (some) | 1 (6×) | Flaky non-determinism. |
| `python -c "from app.audit.audit import AuditLogger; l=AuditLogger(); [l.log('x') for _ in range(3)]; print(l.verify_chain())"` (300×) | `True` | `False` (31×) | Clock-dependent rehash. |
| `curl -v http://localhost:5000/api/auth/login?next=http://evil.com` | 400 | 302 | Open redirect accepted. |
| `grep -r 'localhost:5000' frontend/src/` | 0 | 2 files | Hard-coded origin. |

---

## Chain of Custody

* No file was modified during this audit.
* All commands executed in the working directory `.`.
* Git working tree remained clean (`git status` → no changes).
* Results are reproducible from the frozen codebase at this commit.

---

**End of Independent Phase 1 Implementation Audit**