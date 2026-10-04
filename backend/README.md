# Vote Without Doubt - Backend

Flask backend for the Vote Without Doubt e-voting system (**Academic Prototype - not a legally
binding election system**).

Current project phase status: [`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative)

## Technology Stack

- **Framework**: Flask 3.0.0 (Python 3.11+)
- **Database**: MySQL 8 (SQLAlchemy ORM, PyMySQL driver)
- **Security**: Argon2id (`argon2-cffi`), HMAC-SHA256 + pepper for OTPs
- **Testing**: pytest

## Prerequisites

- Python 3.11+
- MySQL 8.0
- pip
- Mailpit/SMTP on `localhost:1025` for OTP email
- Ganache on `127.0.0.1:8545` (chain ID 1337) for blockchain features

## Setup

### 1. Create Virtual Environment

```bash
# Windows (PowerShell)
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
# Copy example env file (placeholders only)
cp .env.example .env

# Edit .env with your local configuration
# DO NOT commit .env - it is git-ignored
```

### 4. Database Setup

See [../docs/DATABASE_SETUP.md](../docs/DATABASE_SETUP.md). Note the documented schema-file
defects recorded there before building a database from scratch.

### 5. Run the Application

```bash
# From the backend directory
python run.py            # uses backend/run.py directly

# Or via the Flask CLI (requires FLASK_APP, which .env.example sets)
flask run
```

The backend listens on `http://localhost:5000`. Health check: `GET /api/health`.

## API Endpoints

All blueprints are mounted under `/api` (see `backend/app/__init__.py`).

| Blueprint | Endpoints |
|---|---|
| health | `GET /api/health` |
| auth | `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/request-otp`, `POST /api/auth/verify-otp`, `POST /api/auth/logout`, `GET /api/auth/status` |
| registration | `POST /api/registration/check`, `POST /api/registration/request-otp`, `POST /api/registration/verify-otp`, `POST /api/registration/complete`, `POST /api/admin/roll/import` |
| wallet | `POST /api/wallet/challenge`, `POST /api/wallet/bind`, `GET /api/wallet/status` |
| face | `GET /api/face/status`, `POST /api/face/consent`, `POST /api/face/challenge/enroll`, `POST /api/face/challenge/verify`, `POST /api/face/enroll`, `POST /api/face/verify` |
| voting | `POST /api/voting/authorize`, `POST /api/voting/mark-factors`, `POST /api/voting/submit`, `GET /api/voting/status` |

There is no relayer, reconciliation or admin HTTP surface yet; the relayer is a worker module
(`backend/app/relayer/relayer.py`) and admin management is Phase 11 (not started).

## Testing

```bash
pytest                    # run all tests
pytest -v                 # verbose
pytest tests/test_app.py  # single file
```

> **Known test-suite defect:** `tests/test_face_api.py` errors during collection (6 errors)
> because it requests a `client` fixture not provided by the active pytest/plugin configuration.
> A Phase 5 defect, recorded but deliberately not fixed during Phase 0 remediation.

## Project Structure (actual)

```
backend/
|-- app/
|   |-- __init__.py        app factory + blueprint registration
|   |-- extensions.py      Flask extensions (SQLAlchemy)
|   |-- schema.sql         MySQL schema (identity plane + ballot plane + audit)
|   |-- config/            environment-based configuration
|   |-- models/            SQLAlchemy models
|   |-- routes/            HTTP blueprints (health, auth, registration, wallet, face, voting)
|   |-- services/          business logic
|   |-- security/          password, otp, sessions, wallet, face, pseudonym
|   |-- audit/             hash-chained audit
|   |-- relayer/           relayer worker
|   |-- email/             SMTP / Mailpit delivery
|   `-- utils/             CSV roll import
|-- tests/                 pytest suite
|-- requirements.txt       pinned dependencies
|-- run.py                 entry point
|-- .env.example           tracked template, placeholders only
`-- README.md
```

## Development Notes

- **Identity vs Ballot Planes**: strict separation maintained - no cross-plane foreign keys
- **Security First**: no secrets in code; environment variables only
- **Audit Conscious**: hash-chained, sanitized audit logging
- **Academic Prototype**: not production-ready, for educational purposes only
