-- Vote Without Doubt - Database Schema
-- Phase 1 Foundation
-- MySQL 8.0

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
    voter_id VARCHAR(50),
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
    otp_hash VARCHAR(64),
    otp_expires_at DATETIME,
    otp_attempts INT NOT NULL DEFAULT 0,
    otp_used BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    INDEX idx_session_id (session_id),
    INDEX idx_usn (usn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- WALLET AUTHENTICATION TABLES (Phase 4 - Identity Plane)
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
    nonce VARCHAR(128) NOT NULL UNIQUE,
    purpose VARCHAR(50) NOT NULL DEFAULT 'WALLET_AUTHENTICATION',
    message TEXT NOT NULL,
    expires_at DATETIME NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at DATETIME,
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
    INDEX idx_purpose (purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FACE BIOMETRICS (Phase 5 - Identity Plane)
CREATE TABLE IF NOT EXISTS face_enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    encrypted_embedding LONGBLOB NOT NULL,
    embedding_method VARCHAR(50) NOT NULL DEFAULT 'face_recognition',
    is_enrolled BOOLEAN NOT NULL DEFAULT TRUE,
    consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    consent_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS face_challenges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    challenge_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    challenge_type VARCHAR(30) NOT NULL DEFAULT 'LIVENESS',
    challenge_sequence TEXT,
    expires_at DATETIME NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHASE 7
CREATE TABLE IF NOT EXISTS ballots (
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
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_election (election_id),
  INDEX idx_pseudonym (pseudonym),
  INDEX idx_state (state)
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
  INDEX idx_election (election_id)
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

ALTER TABLE ballots ADD COLUMN IF NOT EXISTS tx_broadcast_at DATETIME NULL;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS tx_confirmed_at DATETIME NULL;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS tx_failed_at DATETIME NULL;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS last_retry_at DATETIME NULL;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS reconcile_required TINYINT(1) DEFAULT 0;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS reconcile_reason VARCHAR(255) NULL;
ALTER TABLE ballots ADD COLUMN IF NOT EXISTS superseded TINYINT(1) DEFAULT 0;

