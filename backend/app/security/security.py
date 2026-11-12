"""
Security Foundation - Phase 1 (remediated)
Vote Without Doubt - Backend

Token generation and redirect-URL validation utilities.

Open-redirect validation is implemented structurally by parsing the URL with
:func:`urllib.parse.urlsplit` and comparing the resolved *whole host* against an
exact allow-list. String containment checks (``"localhost" in url``) and
prefix checks are never used: they are bypassed by host-substring attacks
(``evil.com/localhost``) and by protocol-relative URLs (``//evil.com/steal``).
"""

from __future__ import annotations

import secrets
import string
from typing import Iterable, Optional
from urllib.parse import urlsplit

#: Hosts accepted when the caller does not supply its own allow-list.
DEFAULT_ALLOWED_HOSTS = ('localhost', '127.0.0.1', '::1')

#: Only these schemes are ever acceptable for a redirect target.
ALLOWED_REDIRECT_SCHEMES = ('http', 'https')


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.
    Foundation utility used by later phases.
    """
    if not isinstance(length, int) or length < 16:
        raise ValueError('length must be an integer >= 16')
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _normalise_host(host: str) -> str:
    """Lower-case a host and strip any port component."""
    host = (host or '').strip().lower()
    if host.startswith('[') and ']' in host:  # IPv6 literal
        return host[: host.index(']') + 1]
    if host.count(':') == 1:  # host:port
        host = host.split(':', 1)[0]
    return host.rstrip('.')


def is_safe_redirect_url(url: str, allowed_hosts: Optional[Iterable[str]] = None) -> bool:
    """Validate a redirect target against an exact host allow-list.

    Accepted: absolute ``http``/``https`` URLs whose host matches the
    allow-list exactly, and site-relative paths.

    Rejected (defence in depth, each case has a regression test):
      * empty or non-string input
      * scheme-relative URLs - ``//evil.com/steal``
      * any scheme other than http/https - ``javascript:``, ``data:``, ``file:``
      * userinfo tricks - ``http://localhost@evil.com/``
      * host-substring bypasses - ``http://evil.com/?x=localhost``
      * prefix/suffix bypasses - ``http://localhost.evil.com/``
      * backslash and control-character smuggling - ``/\\evil.com``,
        ``/\\@evil.com``, embedded ``\\n``/``\\r``/``\\t``
      * absolute file paths - ``C:\\Windows``
      * malformed URLs that fail to parse
    """
    if not url or not isinstance(url, str):
        return False

    # Control characters (including embedded CR/LF/TAB and NUL) are never valid.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        return False

    candidate = url.strip()

    # Reject backslashes outright: browsers normalise ``/\\`` to ``//``, which
    # turns a "relative" path into a protocol-relative cross-origin redirect.
    if '\\' in candidate:
        return False

    if not candidate:
        return False

    allowed = {
        _normalise_host(host)
        for host in (allowed_hosts if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS)
    }
    allowed.discard('')

    # Protocol-relative URL: inherits the current scheme and leaves the origin.
    if candidate.startswith('//'):
        return False

    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False

    # Absolute URL with a scheme - only http/https, exact host match, no userinfo.
    if parts.scheme:
        if parts.scheme.lower() not in ALLOWED_REDIRECT_SCHEMES:
            return False
        if parts.username or parts.password or '@' in (parts.netloc or ''):
            return False
        host = _normalise_host(parts.netloc)
        if not host or host not in allowed:
            return False
        return True

    # Site-relative URL - no scheme, no authority component.
    if parts.netloc:
        return False
    if not candidate.startswith('/'):
        return False
    # ``/`` followed by anything that could be re-interpreted as an authority.
    return True