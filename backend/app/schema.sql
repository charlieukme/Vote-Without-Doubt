-- Vote Without Doubt - Database Schema
-- MySQL 8.0
--
-- AUTHORITY: `backend/migrations` (Alembic via Flask-Migrate) is the
-- authoritative, versioned schema. This file is the reviewed human-readable
-- reference that documents the same tables. Where this file and the migrations
-- disagree, the migrations win and this file is the defect.
--
-- Every table below is also mapped by an ORM model, so the application can
-- create the schema for test isolation (`db.create_all()`), but production
-- deployments must apply migrations with `flask db upgrade`.
--
-- Naming note: the ballot-relay queue is `ballot_queue` (Phase 7/10). The
-- `ballots` table below is the Phase 1 ballot-state table. They are distinct
-- tables and are not interchangeable.

-- Create database (run manually or via setup script)
-- CREATE DATABASE IF NOT EXISTS voting_sys CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- IDENTITY PLANE TABLES
-- Note: Strict separation from BALLOT PLANE - no direct foreign keys between planes

CREATE TABLE IF NOT EXISTS voter_identities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    voter_id VARCHAR(50) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    department VARCHAR(100),
    year_of_study INT,
    is_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    is_registered BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_voter_id (voter_id),
    INDEX idx_email (email),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- BALLOT PLANE TABLES

CREATE TABLE IF NOT EXISTS elections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    election_id VARCHAR(50) NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    start_time DATETIME,
    end_time DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    v2_priv_key_1 TEXT,
    v2_priv_key_2 TEXT,
    protocol_version VARCHAR(10),
    INDEX idx_election_id (election_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ballots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ballot_id VARCHAR(100) NOT NULL UNIQUE,
    election_id VARCHAR(50) NOT NULL,
    ballot_state VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    ballot_sequence INT,
    max_ballots_allowed INT DEFAULT 3,
    ballot_attempt INT DEFAULT 1,
    blockchain_tx_hash VARCHAR(66),
    blockchain_block_number BIGINT,
    blockchain_status VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_ballot_id (ballot_id),
    INDEX idx_election_id (election_id),
    INDEX idx_ballot_state (ballot_state),
    INDEX idx_tx_hash (blockchain_tx_hash),
    INDEX idx_blockchain_status (blockchain_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- AUDIT FOUNDATION (Phase 1)
-- Privacy-conscious: no sensitive data stored

CREATE TABLE IF NOT EXISTS audit_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    metadata JSON,
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at),
    INDEX idx_current_hash (current_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Schema Notes:
-- 1. IDENTITY PLANE and BALLOT PLANE are logically separated (no cross-plane FKs)
-- 2. No voter identity + candidate choice stored together
-- 3. Ballots are pseudonymous by design (pseudonym fields added in later phases)
-- 4. Audit events sanitized to prevent logging sensitive data
-- 5. This is Phase 1 foundation only - full schema in later phases

-- AUTHENTICATION TABLES (Phase 2 - Identity Plane)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until DATETIME,
    voter_id VARCHAR(50) UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_voter_id (voter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    auth_state VARCHAR(30) NOT NULL DEFAULT 'PENDING_FACTORS',
    authenticated_at DATETIME,
    expires_at DATETIME NOT NULL,
    idle_expires_at DATETIME NOT NULL,
    last_activity DATETIME NOT NULL,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_session_id (session_id),
    INDEX idx_user_id (user_id),
    INDEX idx_auth_state (auth_state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS otps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    purpose VARCHAR(50) NOT NULL,
    otp_hash VARCHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at DATETIME,
    session_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id),
    INDEX idx_session_id (session_id),
    INDEX idx_purpose (purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ELECTORAL ROLL TABLES (Phase 3 - Identity Plane)
CREATE TABLE IF NOT EXISTS electoral_roll (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usn VARCHAR(50) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    college_email VARCHAR(255) NOT NULL,
    is_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    department VARCHAR(100),
    year_of_study INT,
    import_batch VARCHAR(100),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_usn (usn),
    INDEX idx_college_email (college_email),
    INDEX idx_is_eligible (is_eligible)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS registration_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    usn VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    state VARCHAR(30) NOT NULL DEFAULT 'PENDING',
expires_at DATETIME NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    otp_hash VARCHAR(64),
    otp_purpose VARCHAR(64),
    otp_expires_at DATETIME,
    otp_attempts INT NOT NULL DEFAULT 0,
    otp_max_attempts INT NOT NULL DEFAULT 5,
    otp_used BOOLEAN NOT NULL DEFAULT FALSE,
    otp_consumed_at DATETIME,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_session_id (session_id),
    INDEX idx_usn (usn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHASE 3 PROVENANCE
-- One row per roll import. The dry-run/apply boundary records a canonical
-- SHA-256 digest of the electoral roll so later tampering is detectable.
CREATE TABLE IF NOT EXISTS electoral_roll_imports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'DRY_RUN',
    roll_digest VARCHAR(64) NOT NULL,
    row_count INT NOT NULL DEFAULT 0,
    source_filename VARCHAR(255),
    error_count INT NOT NULL DEFAULT 0,
    applied_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    INDEX idx_batch_id (batch_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- WALLET AUTHENTICATION TABLES (Phase 4 - Identity Plane)
-- wallet_challenges binds each ownership-proof challenge to the user, the
-- server-side session, the purpose, the election and the chain/contract
-- context, with a bounded invalid-signature attempt budget.
CREATE TABLE IF NOT EXISTS wallet_bindings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    wallet_address VARCHAR(42) NOT NULL UNIQUE,
    is_verified BOOLEAN NOT NULL DEFAULT TRUE,
    binding_method VARCHAR(50) NOT NULL DEFAULT 'signature',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id),
    INDEX idx_wallet_address (wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wallet_challenges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    challenge_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    session_id VARCHAR(64),
    nonce VARCHAR(128) NOT NULL UNIQUE,
    purpose VARCHAR(50) NOT NULL DEFAULT 'WALLET_AUTHENTICATION',
    election_id VARCHAR(64),
    chain_id INT,
    contract_address VARCHAR(42),
    message TEXT NOT NULL,
    expires_at DATETIME NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at DATETIME,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    wallet_address VARCHAR(42),
    signature TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_user_id (user_id),
    INDEX idx_nonce (nonce),
    INDEX idx_purpose (purpose),
    INDEX idx_session_id (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FACE BIOMETRICS (Phase 5 - Identity Plane)
-- Templates are stored only as authenticated ciphertext. The per-subject
-- neutral head-pose baseline and template provenance travel inside that
-- ciphertext, so no column holds biometric geometry in cleartext.
CREATE TABLE IF NOT EXISTS face_enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    encrypted_embedding LONGBLOB NOT NULL,
    embedding_method VARCHAR(64) NOT NULL DEFAULT 'arcface_cosine',
    embedding_model VARCHAR(64) NOT NULL DEFAULT 'buffalo_l/w600k_r50',
    embedding_dim INT NOT NULL DEFAULT 512,
    embedding_key_id VARCHAR(32) NOT NULL DEFAULT 'v1',
    is_enrolled BOOLEAN NOT NULL DEFAULT TRUE,
    consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    consent_at DATETIME,
    consent_purpose VARCHAR(64) NOT NULL DEFAULT 'election_identity_verification',
    withdrawn_at DATETIME,
    template_deleted_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A challenge is bound to user AND session, carries a 256-bit nonce and an
-- integrity MAC over its own server-authoritative fields, and is single use.
CREATE TABLE IF NOT EXISTS face_challenges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    challenge_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    challenge_type VARCHAR(30) NOT NULL DEFAULT 'LIVENESS',
    challenge_sequence VARCHAR(32) NOT NULL,
    nonce VARCHAR(64) NOT NULL,
    integrity_mac VARCHAR(64) NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    expires_at DATETIME NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at DATETIME,
    authorization_id INT,
    election_id INT,
    consumed BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (authorization_id) REFERENCES voting_authorizations(id),
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_user_id (user_id),
    INDEX idx_session_id (session_id),
    INDEX idx_authorization_id (authorization_id),
    INDEX idx_election_id (election_id),
    INDEX idx_consumed (consumed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHASE 7
-- NOTE: this is the ballot-relay queue. It is named `ballot_queue` (matching the
-- ORM) so that it does NOT collide with the Phase 1 `ballots` table defined
-- above. The Phase 10 recovery/relay columns are declared inline here rather
-- than as trailing ALTERs, so the table is correct on first creation.
CREATE TABLE IF NOT EXISTS ballot_queue (
  id INT AUTO_INCREMENT PRIMARY KEY,
  election_id INT NOT NULL,
  pseudonym VARCHAR(128) NOT NULL,
  candidate INT NOT NULL,
  sequence INT NOT NULL DEFAULT 1,
  state VARCHAR(30) NOT NULL DEFAULT 'QUEUED',
  tx_hash VARCHAR(128),
  block_number INT,
  receipt_code VARCHAR(64),
  error TEXT,
  -- Phase 10 recovery / relay columns
  tx_broadcast_at DATETIME NULL,
  tx_confirmed_at DATETIME NULL,
  tx_failed_at DATETIME NULL,
  last_retry_at DATETIME NULL,
  retry_count INT DEFAULT 0,
  reconcile_required TINYINT(1) DEFAULT 0,
  reconcile_reason VARCHAR(255) NULL,
  superseded TINYINT(1) DEFAULT 0,
  is_null TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_election (election_id),
  INDEX idx_pseudonym (pseudonym),
  INDEX idx_state (state),
  UNIQUE KEY uq_ballot_queue_election_pseudonym_seq (election_id, pseudonym, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS voting_authorizations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  election_id INT NOT NULL,
  session_id VARCHAR(64),
  wallet_verified BOOLEAN DEFAULT FALSE,
  face_verified BOOLEAN DEFAULT FALSE,
  authorized BOOLEAN DEFAULT FALSE,
  consumed BOOLEAN DEFAULT FALSE,
  expires_at DATETIME NOT NULL,
  authorized_at DATETIME,
  consumed_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_user (user_id),
  INDEX idx_election (election_id),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHASE 8
CREATE TABLE IF NOT EXISTS election_pseudonym_keys (
  id INT AUTO_INCREMENT PRIMARY KEY,
  election_id INT NOT NULL UNIQUE,
  key_hash VARCHAR(128) NOT NULL,
  key_ciphertext TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHASE 10
CREATE TABLE IF NOT EXISTS reconciliation_issues (
  id INT AUTO_INCREMENT PRIMARY KEY,
  election_id INT NOT NULL,
  issue_type VARCHAR(100) NOT NULL,
  severity VARCHAR(50) NOT NULL DEFAULT 'INFO',
  ballot_tx_id INT,
  observed_state TEXT,
  expected_state TEXT,
  status VARCHAR(50) NOT NULL DEFAULT 'OPEN',
  resolved_at DATETIME,
  resolution_note TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_election (election_id),
  INDEX idx_status (status),
  INDEX idx_ballot_tx (ballot_tx_id),
  FOREIGN KEY (ballot_tx_id) REFERENCES ballots(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- PHASE 11: ADMIN, GOVERNANCE & TWO-OFFICER APPROVALS
CREATE TABLE IF NOT EXISTS admin_users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  admin_id VARCHAR(50) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'OFFICER',
  totp_secret_encrypted BLOB,
  totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  failed_attempts INT NOT NULL DEFAULT 0,
  locked_until DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_admin_id (admin_id),
  INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS admin_sessions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  session_token VARCHAR(64) NOT NULL UNIQUE,
  admin_id INT NOT NULL,
  role VARCHAR(20) NOT NULL,
  ip_address VARCHAR(45),
  user_agent VARCHAR(255),
  expires_at DATETIME NOT NULL,
  revoked BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_session_token (session_token),
  INDEX idx_admin_id (admin_id),
  FOREIGN KEY (admin_id) REFERENCES admin_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS approval_requests (
  id INT AUTO_INCREMENT PRIMARY KEY,
  election_id VARCHAR(50) NOT NULL,
  action_type VARCHAR(50) NOT NULL,
  payload_hash VARCHAR(64) NOT NULL,
  payload_json TEXT,
  requester_id INT NOT NULL,
  approver_id INT,
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  rejection_reason VARCHAR(255),
  requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME,
  expires_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_election_id (election_id),
  INDEX idx_action_type (action_type),
  INDEX idx_status (status),
  FOREIGN KEY (requester_id) REFERENCES admin_users(id),
  FOREIGN KEY (approver_id) REFERENCES admin_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS candidates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  election_id VARCHAR(50) NOT NULL,
  candidate_index INT NOT NULL,
  name VARCHAR(100) NOT NULL,
  department VARCHAR(100),
  year VARCHAR(20),
  slogan VARCHAR(255),
  manifesto TEXT,
  photo_url VARCHAR(255),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_candidate_election_index (election_id, candidate_index),
  INDEX idx_election_id (election_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS support_tickets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  reference_id VARCHAR(32) NOT NULL UNIQUE,
  category VARCHAR(50) NOT NULL,
  details TEXT NOT NULL,
  contact_email VARCHAR(255),
  status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_support_tickets_ref (reference_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

