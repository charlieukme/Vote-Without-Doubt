"""
Roll-import bootstrap authorization - Phase 3 (remediated)
Vote Without Doubt - Backend

Why this exists
---------------
``POST /api/admin/roll/import`` writes the authoritative electoral roll, which is
the eligibility gate for the whole system. The Phase 3 audit proved the endpoint
was anonymously writable, letting an attacker insert their own USN and register.

PROJECT_BIBLE Section 15 records RBAC and four-eyes as *design only, Phase 11 not
started*, so a full admin subsystem is deliberately out of scope here. This
module is the smallest mechanism that makes the endpoint non-anonymous until
Phase 11 replaces it.

Design
------
* The credential is a bootstrap token read from the environment
  (``ROLL_ADMIN_TOKEN``). It is never hard-coded, never sent to the frontend and
  never logged.
* Comparison uses :func:`hmac.compare_digest`, so it is not timing-attackable.
* A caller-supplied ``is_admin`` flag, role or header is never trusted; the only
  accepted carrier is the ``X-Admin-Token`` request header.
* **Fail closed.** If no token is configured the endpoint is unusable rather
  than open. In production, application start-up additionally refuses to boot
  without one (see :meth:`app.config.config.Config.validate`).
* The request is additionally rate limited.
"""

import hmac
import os
from typing import Optional

from flask import current_app, jsonify, request

ADMIN_TOKEN_ENV = 'ROLL_ADMIN_TOKEN'
ADMIN_TOKEN_HEADER = 'X-Admin-Token'

#: Minimum token length accepted for a bootstrap credential.
MIN_TOKEN_LENGTH = 32


class AdminAuthError(Exception):
    """Raised when a roll-import request is not authorized."""


def configured_admin_token() -> Optional[str]:
    """Return the configured bootstrap token, or ``None`` when unset."""
    token = os.getenv(ADMIN_TOKEN_ENV, '')
    return token or None


def is_admin_configured() -> bool:
    """True when a usable bootstrap token is configured."""
    token = configured_admin_token()
    return bool(token) and len(token) >= MIN_TOKEN_LENGTH


def require_admin() -> None:
    """Authorise the current request or raise :class:`AdminAuthError`.

    Fails closed. Rejects anonymous callers, ordinary voter sessions and any
    attempt to assert privilege from the client side.
    """
    if not is_admin_configured():
        current_app.logger.error(
            'Roll-import refused: no %s is configured. The electoral roll is '
            'read-only until one is provided.', ADMIN_TOKEN_ENV,
        )
        raise AdminAuthError('Roll import is not available')

    presented = request.headers.get(ADMIN_TOKEN_HEADER, '') or ''
    expected = configured_admin_token() or ''

    # Constant-time comparison. A wrong-length token still fails safely because
    # compare_digest handles unequal lengths without raising.
    if not hmac.compare_digest(presented.encode('utf-8'), expected.encode('utf-8')):
        current_app.logger.warning('Roll-import refused: invalid admin credential.')
        raise AdminAuthError('Not authorized')


def admin_guard():
    """Flask view decorator enforcing :func:`require_admin`."""
    def decorator(view):
        def wrapper(*args, **kwargs):
            try:
                require_admin()
            except AdminAuthError as error:
                return jsonify({'error': str(error)}), 403
            return view(*args, **kwargs)
        wrapper.__name__ = getattr(view, '__name__', 'wrapped')
        return wrapper
    return decorator
