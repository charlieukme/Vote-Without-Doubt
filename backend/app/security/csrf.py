"""
CSRF Foundation - Phase 1
Vote Without Doubt - Backend

Implements Bible Section 7 principle 8 ("CSRF / CORS / input validation on all
state-changing endpoints") as a reusable, session-bound token mechanism.

Phase 1 exposes no state-changing endpoint, so enforcement is **not** switched
on by default: :func:`enforce_csrf` is wired into the request pipeline and
activates as soon as ``CSRF_ENABLED`` is true. The phase that introduces the
first state-changing route owns enabling it and its regression test.

Mechanism: a random token is stored in the server-side session and must be
echoed by the client in a header. A cross-site attacker can cause the victim's
browser to send cookies but cannot read the session to obtain the token, so it
cannot forge the header value.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Optional

from flask import current_app, request, session

CSRF_SESSION_KEY = '_csrf_token'
CSRF_TOKEN_BYTES = 32
SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})


class CsrfError(Exception):
    """Raised when a state-changing request fails CSRF validation."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def generate_csrf_token() -> str:
    """Return the session CSRF token, creating it on first use."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        session[CSRF_SESSION_KEY] = token
    return token


def rotate_csrf_token() -> str:
    """Issue a fresh token. Called after privilege changes such as OTP."""
    session[CSRF_SESSION_KEY] = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    return session[CSRF_SESSION_KEY]


def _header_name() -> str:
    return current_app.config.get('CSRF_HEADER_NAME', 'X-CSRF-Token')


def get_submitted_csrf_token() -> Optional[str]:
    """Token supplied by the client, from the configured header or the form."""
    header_value = request.headers.get(_header_name())
    if header_value:
        return header_value
    if request.form:
        return request.form.get('csrf_token') or None
    if request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            value = payload.get('csrf_token')
            return value if isinstance(value, str) else None
    return None


def validate_csrf_token() -> bool:
    """Constant-time comparison of the submitted token with the session token."""
    expected = session.get(CSRF_SESSION_KEY)
    submitted = get_submitted_csrf_token()
    if not expected or not submitted:
        return False
    return hmac.compare_digest(str(expected), str(submitted))


def is_csrf_protected_request() -> bool:
    """True when the current request is a state-changing request."""
    return request.method.upper() not in SAFE_METHODS


def enforce_csrf() -> None:
    """Reject state-changing requests that fail token validation.

    A no-op while ``CSRF_ENABLED`` is false, and for safe methods.
    """
    if not current_app.config.get('CSRF_ENABLED'):
        return
    if not is_csrf_protected_request():
        return
    if not validate_csrf_token():
        raise CsrfError('CSRF token missing or invalid')