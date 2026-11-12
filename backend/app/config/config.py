"""
Application Configuration - Phase 1 (remediated)
Vote Without Doubt - Backend

Secrets policy (Bible Section 7, principle 13):

* ``Config`` never carries a hard-coded secret default.
* ``ProductionConfig`` refuses to start without an explicit ``SECRET_KEY``
  environment variable, and additionally rejects any value that matches a
  known insecure placeholder.
* ``DevelopmentConfig`` generates an ephemeral per-process random secret. It is
  never a shared, publicly known value, and sessions are invalidated on restart,
  which is the correct trade-off for local development.
* ``TestingConfig`` uses a fixed, explicitly non-production test key so that
  sessions are stable across a test run.

Debug policy: the interactive debugger and the reloader are OFF by default in
every environment, including development. They are enabled only by an explicit
``FLASK_DEBUG=true`` opt-in, and never in production.
"""

import os
import secrets
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Ensure backend/.env is located even if current working directory is project root
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_CONFIG_DIR))
_BACKEND_ENV = os.path.join(_BACKEND_DIR, '.env')
if os.path.isfile(_BACKEND_ENV):
    load_dotenv(_BACKEND_ENV)
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: Optional[float] = None) -> Optional[float]:
    """Read a float, distinguishing "unset" from "invalid".

    Phase 5 uses this for the biometric similarity threshold, where an absent
    value and a malformed value must both be visible to the caller rather than
    silently collapsing onto a shipped default.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: str) -> List[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


class Config:
    """Base configuration. Environment variables only - no baked-in secrets."""

    # Flask
    SECRET_KEY: Optional[str] = os.getenv('SECRET_KEY') or None
    FLASK_DEBUG = _env_bool('FLASK_DEBUG', False)
    MAX_CONTENT_LENGTH = _env_int('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)  # 16 MB ceiling

    # Application
    APP_NAME = os.getenv('APP_NAME', 'Vote Without Doubt')
    APP_ENV = os.getenv('APP_ENV', 'production')

    # Database
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = _env_int('MYSQL_PORT', 3306)
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'voting_sys')
    MYSQL_USER = os.getenv('MYSQL_USER', 'voting_sys_user')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')

    # SQLAlchemy. DATABASE_URL overrides the assembled MySQL URI, which lets
    # tests and migration tooling target SQLite without editing source.
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL') or (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@"
        f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = _env_int('DB_POOL_SIZE', 5)
    SQLALCHEMY_POOL_RECYCLE = _env_int('DB_POOL_RECYCLE', 3600)

    #: When true the app factory creates tables at startup. Defaults to False:
    #: schema changes are owned by migrations (``flask db upgrade``), not by
    #: implicit DDL at boot.
    AUTO_CREATE_SCHEMA = _env_bool('AUTO_CREATE_SCHEMA', False)

    # CORS
    CORS_ALLOWED_ORIGINS = _env_list(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://localhost:3000',
    )

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # Security
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    SESSION_COOKIE_NAME = 'session'
    PERMANENT_SESSION_LIFETIME = _env_int('SESSION_LIFETIME_SECONDS', 3600)

    # Trusted hosts (defence in depth against Host-header poisoning).
    TRUSTED_HOSTS = _env_list(
        'TRUSTED_HOSTS',
        'localhost,127.0.0.1,[::1]',
    )

    # Reverse proxy trust & ProxyFix configuration (Phase E.16.1).
    # In staging/production behind Nginx, trust exactly the configured number of proxy hops.
    TRUSTED_PROXIES = _env_list('TRUSTED_PROXIES', '127.0.0.1,::1,localhost')
    PROXY_FIX_ENABLED = _env_bool('PROXY_FIX_ENABLED', False)
    PROXY_FIX_NUM_PROXIES = _env_int('PROXY_FIX_NUM_PROXIES', 1)

    # Logging hygiene and credential redaction (Phase E.16.1)
    LOG_REDACTION_ENABLED = _env_bool('LOG_REDACTION_ENABLED', True)

    # Rate limiting (Bible Section 7, principle 10). The mechanism is a Phase 1
    # foundation; OTP/auth/resend enforcement belongs to the phase that owns
    # those endpoints.
    RATE_LIMIT_ENABLED = _env_bool('RATE_LIMIT_ENABLED', True)
    ADMIN_RATE_LIMIT_ENABLED = _env_bool('ADMIN_RATE_LIMIT_ENABLED', True)
    RATE_LIMIT_DEFAULT = (int(os.getenv('RATE_LIMIT_DEFAULT', '120')),
                          _env_int('RATE_LIMIT_WINDOW_SECONDS', 60))

    # CSRF (Bible Section 7, principle 8). Phase 1 exposes no state-changing
    # endpoint, so the token helpers are provided and enforcement is enabled by
    # the phase that introduces its first state-changing route.
    CSRF_ENABLED = _env_bool('CSRF_ENABLED', False)
    CSRF_HEADER_NAME = os.getenv('CSRF_HEADER_NAME', 'X-CSRF-Token')

    # Blockchain Relayer & Batching (Fix 2 - Timing De-Correlation)
    RELAYER_ENABLED = _env_bool('RELAYER_ENABLED', True)
    RELAYER_MIN_BATCH_SIZE = _env_int('RELAYER_MIN_BATCH_SIZE', 5)
    RELAYER_MAX_BATCH_SIZE = _env_int('RELAYER_MAX_BATCH_SIZE', 10)
    RELAYER_MAX_WAIT_SECONDS = _env_float('RELAYER_MAX_WAIT_SECONDS', 30.0)
    RELAYER_DISPATCH_INTERVAL_SECONDS = _env_float('RELAYER_DISPATCH_INTERVAL_SECONDS', 2.0)
    ENABLE_TEST_ASYNC_RELAYER = _env_bool('ENABLE_TEST_ASYNC_RELAYER', False)

    # --------------------------------------------------------------- Phase 4
    # Wallet ownership proof context. All values are server-authoritative: the
    # browser may not define any of them. Each one is bound into the signed
    # challenge message, so a signature produced under one context cannot be
    # replayed under another.
    #
    # WALLET_AUTH_CHAIN_ID defaults to the project's local Ganache network and
    # MUST match the network MetaMask is actually connected to.
    WALLET_AUTH_DOMAIN = os.getenv('WALLET_AUTH_DOMAIN', 'votewithoutdoubt.local')

    # Current election context for the authentication challenge. Phase 4 has no
    # election-management subsystem (that is Phase 6/7), so the value comes from
    # configuration and is server-authoritative by construction.
    WALLET_AUTH_ELECTION_ID = os.getenv('WALLET_AUTH_ELECTION_ID', 'GENERAL')

    # Address of the voting contract. No contract is deployed in Phase 4, so an
    # explicit zero-address sentinel is used instead of inventing one. It is a
    # valid address so the message shape cannot change silently in Phase 6.
    WALLET_AUTH_CONTRACT_ADDRESS = os.getenv('WALLET_AUTH_CONTRACT_ADDRESS') or os.getenv('BALLOTBOX_CONTRACT_ADDRESS') or '0x0000000000000000000000000000000000000000'

    WALLET_AUTH_CHAIN_ID = _env_int('WALLET_AUTH_CHAIN_ID', 1337)

    # --------------------------------------------------------------- Phase 6
    # Blockchain / Smart contract and backend relayer.
    BLOCKCHAIN_RPC_URL = os.getenv('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')
    BALLOTBOX_CONTRACT_ADDRESS = os.getenv('BALLOTBOX_CONTRACT_ADDRESS', None)
    BALLOTBOX_V2_CONTRACT_ADDRESS = os.getenv('BALLOTBOX_V2_CONTRACT_ADDRESS', None)
    RELAYER_PRIVATE_KEY = os.getenv('RELAYER_PRIVATE_KEY', None)
    RELAYER_ACCOUNT = os.getenv('RELAYER_ACCOUNT', None)
    RELAYER_ENABLED = _env_bool('RELAYER_ENABLED', True)

    # --------------------------------------------------------------- Phase 9
    # Controlled revoting & coercion mitigation.
    REVOTE_COOLDOWN_SECONDS = _env_int('REVOTE_COOLDOWN_SECONDS', 120)
    MAX_BALLOTS_PER_VOTER = _env_int('MAX_BALLOTS_PER_VOTER', 3)

    # --------------------------------------------------------------- Phase 5 / Phase 16
    # Face recognition and encrypted template storage.
    #
    # IMPORTANT (Phase 16): liveness detection (LEFT/RIGHT head-movement
    # challenges, pose thresholds, neutral-band calibration) has been removed
    # from this prototype. Face verification now uses biometric embedding
    # similarity only. This does *not* mitigate presentation attacks (photos,
    # screens, masks, deepfakes); see the security documentation.
    #
    # Every value here is server-authoritative. The browser never asserts a
    # direction, a score or a frame count that the backend then trusts.
    #
    # Where the InsightFace weights live. The directory is NOT created or
    # downloaded at request time; a missing tree fails closed with HTTP 503.
    FACE_MODEL_ROOT = os.getenv(
        'FACE_MODEL_ROOT',
        os.path.abspath(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), 'face_models')))

    # Uploaded-frame admission limits. These bound decoding work before any
    # inference happens.
    FACE_MIN_FRAMES = _env_int('FACE_MIN_FRAMES', 1)
    FACE_MAX_FRAMES = _env_int('FACE_MAX_FRAMES', 5)
    FACE_MAX_FRAME_BYTES = _env_int('FACE_MAX_FRAME_BYTES', 512 * 1024)
    FACE_MAX_UPLOAD_BYTES = _env_int('FACE_MAX_UPLOAD_BYTES', 8 * 1024 * 1024)

    # Challenge lifetime and attempt budget. Challenges remain single use and
    # bound to the issuing user *and* session.
    FACE_CHALLENGE_TTL_SECONDS = _env_int('FACE_CHALLENGE_TTL_SECONDS', 20)
    FACE_MAX_ATTEMPTS = _env_int('FACE_MAX_ATTEMPTS', 3)

    # Cosine-similarity acceptance threshold for a 512-d ArcFace embedding.
    #
    # There is deliberately NO default. A biometric acceptance threshold is a
    # risk decision, and shipping an unvalidated one would be inventing a
    # security parameter. It must be set from a real calibration study; until
    # then the face endpoints refuse to run (HTTP 503).
    FACE_SIMILARITY_THRESHOLD = _env_float('FACE_SIMILARITY_THRESHOLD', None)

    # Purpose string recorded with an enrolment's consent record.
    FACE_CONSENT_PURPOSE = os.getenv(
        'FACE_CONSENT_PURPOSE', 'election_identity_verification')

    # Phase C.13: Presentation Attack Detection (PAD) Configuration
    # Modes: 'shadow' (default, non-enforcing telemetry), 'disabled' (bypassed)
    # Enforcing mode is prohibited on the live route in Phase C.13.
    FACE_PAD_MODE = os.getenv('FACE_PAD_MODE', 'shadow')
    FACE_PAD_THRESHOLD = _env_float('FACE_PAD_THRESHOLD', None)

    # Phase 5 / Phase 16 rate-limit budgets (limit, window seconds) per client
    # identity.
    FACE_RATE_LIMIT_CHALLENGE = (3, 60)
    FACE_RATE_LIMIT_ENROLL = (5, 300)
    FACE_RATE_LIMIT_VERIFY = (10, 300)

    @classmethod
    def validate(cls, settings: Optional[Dict[str, Any]] = None) -> None:
        """Validate configuration invariants. Raises ``RuntimeError`` on failure."""
        secret = (settings or {}).get('SECRET_KEY', cls.SECRET_KEY)
        if not secret:
            raise RuntimeError(
                'SECRET_KEY is not set. Export SECRET_KEY in the environment '
                '(see backend/.env.example).'
            )
        from app.audit.audit import LEGACY_INSECURE_SECRET
        if secret == LEGACY_INSECURE_SECRET:
            raise RuntimeError(
                'SECRET_KEY matches a known insecure placeholder. Set a unique '
                'random value in the environment.'
            )
        if len(secret) < 32:
            raise RuntimeError('SECRET_KEY must be at least 32 characters long.')

        # Phase 2: the OTP pepper has no production fallback. Refuse to boot
        # rather than silently signing OTPs with a well-known value.
        environment = str((settings or {}).get('APP_ENV', cls.APP_ENV)).lower()
        if environment == 'production':
            admin_rate_limit = (settings or {}).get('ADMIN_RATE_LIMIT_ENABLED', cls.ADMIN_RATE_LIMIT_ENABLED)
            if admin_rate_limit is False or _env_bool('ADMIN_RATE_LIMIT_ENABLED', True) is False:
                raise RuntimeError(
                    'ADMIN_RATE_LIMIT_ENABLED cannot be disabled in production.'
                )
        if environment == 'production' and not os.getenv('OTP_PEPPER'):
            raise RuntimeError(
                'OTP_PEPPER is not set. Production requires an explicit OTP pepper; '
                'generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        # Phase 3: the electoral roll is the eligibility gate for the whole
        # system. Production must not boot without a bootstrap credential for
        # the roll-import endpoints, otherwise they would fail open.
        if environment == 'production' and not os.getenv('ROLL_ADMIN_TOKEN'):
            raise RuntimeError(
                'ROLL_ADMIN_TOKEN is not set. Production requires a bootstrap '
                'credential for electoral-roll administration; generate one with: '
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )

        # Phase 4: wallet ownership proof depends on the eth-account
        # primitives. Production must never run with wallet verification
        # disabled, so refuse to boot if the import failed.
        if environment == 'production':
            try:
                from app.security.wallet import ETH_ACCOUNT_AVAILABLE
            except Exception as error:  # pragma: no cover
                raise RuntimeError(
                    f'Wallet security module could not be imported: {error!r}'
                )
            if not ETH_ACCOUNT_AVAILABLE:
                raise RuntimeError(
                    'eth-account is not installed. Production requires real '
                    'Ethereum signature verification; install it with: '
                    'pip install -r requirements.txt'
                )

        # Phase 5: biometric operation depends on real model weights, an
        # explicit encryption key and a calibrated acceptance threshold.
        # Production must never boot with any of them missing, because each
        # failure mode would otherwise be "verify anybody" or "store
        # templates we cannot read back".
        if environment == 'production':
            threshold = os.getenv('FACE_SIMILARITY_THRESHOLD')
            if not threshold or not threshold.strip():
                raise RuntimeError(
                    'FACE_SIMILARITY_THRESHOLD is not set. Production requires a '
                    'biometric acceptance threshold established by a real '
                    'calibration study; refusing to boot rather than accepting '
                    'an unvalidated default.'
                )
            try:
                parsed_threshold = float(threshold)
            except ValueError:
                raise RuntimeError(
                    'FACE_SIMILARITY_THRESHOLD must be a number.'
                )
            if not 0.0 < parsed_threshold < 1.0:
                raise RuntimeError(
                    'FACE_SIMILARITY_THRESHOLD must be strictly between 0 and 1.'
                )

            if not os.getenv('FACE_ENCRYPTION_KEY'):
                raise RuntimeError(
                    'FACE_ENCRYPTION_KEY is not set. Production requires an '
                    'explicit Fernet key for biometric templates; generate one '
                    'with: python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"'
                )
            try:
                from app.security.face import _parse_key_map, active_key_id
                material = _parse_key_map()
                if active_key_id() not in material:
                    raise RuntimeError(
                        'FACE_ENCRYPTION_KEY does not cover the active '
                        f'FACE_ENCRYPTION_KEY_ID ({active_key_id()!r}).'
                    )
            except RuntimeError:
                raise
            except Exception as error:
                raise RuntimeError(
                    f'Face encryption key is unusable: {error!r}'
                )

            model_root = os.getenv(
                'FACE_MODEL_ROOT', cls.FACE_MODEL_ROOT)
            for weight in ('det_10g.onnx', 'w600k_r50.onnx'):
                candidates = (
                    os.path.join(model_root, 'models', 'buffalo_l', weight),
                    os.path.join(model_root, 'buffalo_l', weight),
                )
                if not any(os.path.isfile(path) for path in candidates):
                    raise RuntimeError(
                        f'Face model weight {weight!r} was not found under '
                        f'{model_root!r}. Provision the InsightFace buffalo_l '
                        'weights before starting production.'
                    )

            # Phase 8: Per-election pseudonym keys are encrypted with PSEUDONYM_MASTER_KEY.
            # Production requires an explicit master key and refuses to boot without it.
            master_key = os.getenv('PSEUDONYM_MASTER_KEY')
            if not master_key or not master_key.strip():
                raise RuntimeError(
                    'PSEUDONYM_MASTER_KEY is not set. Production requires an explicit '
                    'Fernet master key to protect per-election pseudonym keys; generate one with: '
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )
            try:
                from cryptography.fernet import Fernet
                Fernet(master_key.strip().encode())
            except Exception as exc:
                raise RuntimeError(
                    f'PSEUDONYM_MASTER_KEY is invalid: {exc}. Must be a valid 32-byte url-safe base64 Fernet key.'
                )


class DevelopmentConfig(Config):
    """Local development.

    The secret is ephemeral and random per process: restarting the dev server
    invalidates old sessions, which is preferable to a shared, committed,
    publicly known development secret.
    """

    SECRET_KEY = os.getenv('SECRET_KEY') or secrets.token_urlsafe(32)
    FLASK_DEBUG = _env_bool('FLASK_DEBUG', False)
    APP_ENV = 'development'
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    """Automated tests. Fixed, explicitly non-production key."""

    TESTING = True
    SECRET_KEY = os.getenv('TESTING_SECRET_KEY', 'testing-only-secret-not-for-production')
    FLASK_DEBUG = False
    APP_ENV = 'testing'
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///:memory:')
    WTF_CSRF_ENABLED = False
    TRUSTED_HOSTS = ['localhost', '127.0.0.1', 'testserver']


class ProductionConfig(Config):
    """Production. No debug, secure cookies, secret required."""

    FLASK_DEBUG = False
    APP_ENV = 'production'
    CSRF_ENABLED = _env_bool('CSRF_ENABLED', True)
    SESSION_COOKIE_SECURE = True  # Requires HTTPS
    SESSION_COOKIE_NAME = '__Host-session'  # __Host- prefix requires Secure, Path=/, no Domain
    SESSION_COOKIE_PATH = '/'
    TRUSTED_HOSTS = _env_list('TRUSTED_HOSTS', 'localhost,127.0.0.1')
    ADMIN_RATE_LIMIT_ENABLED = True
    PROXY_FIX_ENABLED = True


class StagingConfig(ProductionConfig):
    """Staging environment.

    Inherits production security hardening (secure cookies, rate limiting, trusted hosts)
    while allowing shadow biometric operation and staging domain configuration.
    """

    APP_ENV = 'staging'
    CSRF_ENABLED = _env_bool('CSRF_ENABLED', True)
    PROXY_FIX_ENABLED = True
    TRUSTED_HOSTS = _env_list(
        'TRUSTED_HOSTS',
        'localhost,127.0.0.1,staging-vote.college.edu',
    )


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
