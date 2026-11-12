"""
OTP Security - Phase 2
Vote Without Doubt - Backend

6-digit OTP protected with HMAC-SHA256 under a server-side pepper.

Pepper policy (PROJECT_BIBLE Section 7, principle 3):

* ``OTP_PEPPER`` is the only source of the pepper; it is never hard-coded.
* When the pepper is absent the application FAILS CLOSED if it is running in
  production. There is no production fallback of any kind.
* A fixed, explicitly non-production test pepper is used only when the resolved
  environment is not production, so the test suite is deterministic.
* The environment is resolved from the Flask application config first, so a
  stray ``APP_ENV`` shell variable cannot downgrade a production deployment to
  the test pepper.
"""

import hashlib
import hmac
import secrets

#: Deterministic pepper for development and automated tests only. It is named
#: so that it is obviously invalid anywhere else, and it is rejected outright in
#: production by both :func:`get_otp_pepper` and the configuration validator.
NON_PRODUCTION_PEPPER = 'test-otp-pepper-not-for-production-use'


def _resolve_environment(app=None):
    """Resolve the current environment, preferring the Flask app config."""
    if app is None:
        try:
            from flask import current_app
            app = current_app._get_current_object()
        except Exception:
            app = None

    if app is not None:
        return str(app.config.get('APP_ENV', 'production')).lower()

    import os
    return str(os.getenv('APP_ENV', 'production')).lower()


def get_otp_pepper(app=None) -> bytes:
    """Return the OTP pepper, failing closed in production."""
    import os

    pepper = os.getenv('OTP_PEPPER')
    if pepper:
        return pepper.encode('utf-8')

    if _resolve_environment(app) == 'production':
        raise RuntimeError(
            'OTP_PEPPER is not set. Production requires an explicit OTP pepper; '
            'generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    return NON_PRODUCTION_PEPPER.encode('utf-8')


def generate_otp() -> str:
    """Generate a 6-digit cryptographically secure OTP.

    Uses :func:`secrets.randbelow`, so the value is drawn from the operating
    system CSPRNG and is uniformly distributed over 000000-999999.
    """
    return f'{secrets.randbelow(1_000_000):06d}'


def hash_otp(otp: str, pepper: bytes = None) -> str:
    """Return HMAC-SHA256(pepper, otp) as lowercase hex.

    The raw OTP is never stored. The pepper is never transmitted to a client.
    """
    if pepper is None:
        pepper = get_otp_pepper()
    return hmac.new(pepper, msg=str(otp).encode('utf-8'), digestmod=hashlib.sha256).hexdigest()


def verify_otp(otp: str, otp_hash: str, pepper: bytes = None) -> bool:
    """Constant-time comparison of a candidate OTP against a stored hash."""
    if not otp or not otp_hash:
        return False
    expected = hash_otp(otp, pepper)
    return hmac.compare_digest(expected, otp_hash)
