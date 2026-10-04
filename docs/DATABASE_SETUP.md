# Database Setup Guide

Vote Without Doubt - MySQL 8 database setup.

> **Authoritative schema:** [`../backend/app/schema.sql`](../backend/app/schema.sql).
> The overview below is a convenience summary only. If the two ever disagree, `schema.sql` wins.
>
> Current phase status: [`../PROJECT_BIBLE.md` Section 3](../PROJECT_BIBLE.md#3-current-phase-status-authoritative)

## Prerequisites

- MySQL 8.0 installed and running
- Access to MySQL as root or with create database privileges

## Step 1: Create Database and User

Connect to MySQL as root:

```sql
CREATE DATABASE IF NOT EXISTS voting_sys 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

-- Create dedicated user with least privilege
CREATE USER IF NOT EXISTS 'voting_sys_user'@'localhost' 
    IDENTIFIED BY 'your-secure-password-here';

-- Grant privileges on voting_sys database only
GRANT SELECT, INSERT, UPDATE, DELETE ON voting_sys.* 
    TO 'voting_sys_user'@'localhost';

FLUSH PRIVILEGES;
```

## Step 2: Apply Schema

From the project root, run:

```sql
USE voting_sys;
SOURCE backend/app/schema.sql;
```

Or via command line:

```bash
mysql -u voting_sys_user -p voting_sys < backend/app/schema.sql
```

## Step 3: Configure Environment

Copy backend/.env.example to backend/.env and update:

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=voting_sys
MYSQL_USER=voting_sys_user
MYSQL_PASSWORD=your-secure-password-here
```

## Step 4: Verify Setup

Test connection (from the `backend` directory with the venv activated):

```bash
python -c "
from sqlalchemy import text
from app import create_app
from app.extensions import db
app = create_app()
with app.app_context():
    db.session.execute(text('SELECT 1'))
    print('Database connection successful')
"
```

## Schema Overview

Tables are grouped by data plane. The grouping below reflects the separation constraint. Verify
against `backend/app/schema.sql` for the authoritative definition.

**IDENTITY PLANE (no foreign keys into the ballot plane):**
- `voter_identities` - voter / eligibility records
- `users` - authentication accounts
- `auth_sessions` - server-side sessions
- `otps` - one-time passwords (stored as HMACs, never raw)
- `electoral_roll` - imported electoral roll
- `registration_sessions` - registration workflow state
- `wallet_bindings` - MetaMask address bindings
- `wallet_challenges` - single-use, session/purpose-bound challenge nonces
- `face_enrollments` - protected face embeddings
- `face_challenges` - liveness challenge state
- `voting_authorizations` - voting authorization lifecycle (identity context; `user_id` FK to `users`)

**BALLOT PLANE (pseudonymous; carries no identity columns):**
- `elections` - election metadata
- `ballots` - ballot records (see warning below)
- `election_pseudonym_keys` - per-election pseudonym key material

**AUDIT:**
- `audit_events` - hash-chained audit log (sanitized; no secrets, no candidate choices)

### Known schema-file defects (recorded, not fixed during Phase 0 remediation)

These are implementation defects in `backend/app/schema.sql`. They are **documented here rather
than fixed**, because Phase 0 remediation is not permitted to change application or schema
logic. They must be resolved in the owning phase.

1. **`ballots` is declared twice with different columns.** The Phase 1 declaration
   (`ballot_id`, `ballot_state`, `ballot_sequence`, `blockchain_tx_hash`, ...) appears first;
   the Phase 7 declaration (`pseudonym`, `candidate`, `sequence`, `state`, `tx_hash`,
   `receipt_code`, ...) appears later. Because both use `CREATE TABLE IF NOT EXISTS`, MySQL
   applies only the **first** declaration and silently ignores the second. The first declaration
   has **no `pseudonym` and no `candidate` column**, so a fresh `SOURCE schema.sql` will not
   produce the column set the Phase 7/8/10 code expects.
2. **Phase 10 `ALTER TABLE ballots ADD COLUMN ...` statements target that same table**, so their
   effect depends on which declaration won.
3. **`reconciliation_issues` has no DDL in `schema.sql`**, even though a SQLAlchemy model with
   that table name exists in `backend/app/models/reconciliation.py`.
4. The file header comments still say "This is Phase 1 foundation only", which no longer
   describes the file.

Consequence: a from-scratch database built strictly from `schema.sql` may not match the ORM
models. Existing local databases may have been created by other means. Verify before relying on
a fresh build.

## Important Notes

- **Strict Separation**: No foreign keys between identity-plane tables and ballot-plane tables
- **Privacy by Design**: No table stores voter identity together with candidate choice
- **Least Privilege**: Dedicated application user restricted to this schema
- **Security**: Never commit real credentials; `.env` is git-ignored
- **Authoritative file**: `backend/app/schema.sql`

## Troubleshooting

- Check MySQL is running: `mysqladmin ping`
- Check user permissions: `SHOW GRANTS FOR 'voting_sys_user'@'localhost';`
- Ensure correct charset/collation for Unicode support
