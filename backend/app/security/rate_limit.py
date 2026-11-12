"""
Rate Limiting Foundation - Phase 1
Vote Without Doubt - Backend

Implements Bible Section 7 principle 10 ("rate limiting on authentication, OTP
and resend paths") as a reusable mechanism.

Scope note: Phase 1 has no authentication, OTP or resend endpoints. This module
provides and registers the limiter and applies a conservative default budget to
the endpoints Phase 1 actually owns. Enforcement on authentication/OTP/resend
routes belongs to the phase that introduces them; :func:`is_rate_limited` and
:func:`register_rate_limiting` are the integration points.

Implementation: fixed-window counter keyed by client identity. The store is
in-process, which is correct for the single-process local deployment described in
PROJECT_BIBLE Section 13. A multi-process deployment must replace the store with
a shared backend (Redis/Memcached) - documented, not silently assumed.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable, Dict, Optional, Tuple

from flask import Flask, current_app, g, jsonify, request


class RateLimitExceeded(Exception):
    """Raised when a client exceeds its configured budget."""

    def __init__(self, limit: int, retry_after: int):
        super().__init__('rate limit exceeded')
        self.limit = limit
        self.retry_after = retry_after


class InMemoryRateLimiter:
    """Thread-safe fixed-window rate limiter."""

    def __init__(self, clock: Optional[Callable[[], float]] = None):
        self._clock = clock or time.time
        self._hits: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
        """Record a hit. Returns ``(allowed, remaining, retry_after)``."""
        now = self._clock()
        with self._lock:
            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= window_seconds:
                window_start, count = now, 0
            count += 1
            retry_after = max(0, int(window_seconds - (now - window_start)))
            if count > limit:
                self._hits[key] = (window_start, count)
                return False, 0, retry_after
            self._hits[key] = (window_start, count)
            return True, max(0, limit - count), retry_after

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_identity() -> str:
    """Identify the caller.

    ``REMOTE_ADDR`` is used rather than ``X-Forwarded-For`` because trusting the
    forwarded header would let a client spoof its identity and bypass the limit.
    A deployment behind a proxy must set ``ProxyFix`` and rely on the socket
    address it rewrites.
    """
    return request.remote_addr or 'unknown'


def rate_limit_key(scope: str) -> str:
    ip = client_identity()
    # Isolate admin login attempts per (IP, admin_id) so one officer's attempts do not block another
    if scope == '/api/admin/auth/login' or (hasattr(request, 'path') and request.path == '/api/admin/auth/login'):
        data = request.get_json(silent=True)
        if isinstance(data, dict) and data.get('admin_id'):
            aid = str(data['admin_id']).strip().upper()
            return f'{scope}:{ip}:{aid}'
    return f'{scope}:{ip}'


def get_limiter() -> InMemoryRateLimiter:
    limiter = current_app.extensions.get('rate_limiter')
    if limiter is None:
        limiter = InMemoryRateLimiter()
        current_app.extensions['rate_limiter'] = limiter
    return limiter


def is_rate_limited(scope: str, limit: int, window_seconds: int) -> bool:
    """True when the caller has exhausted the budget for ``scope``."""
    if (scope == '/api/admin' or scope.startswith('/api/admin')) and not current_app.config.get('ADMIN_RATE_LIMIT_ENABLED', True):
        return False
    allowed, _, _ = get_limiter().hit(rate_limit_key(scope), limit, window_seconds)
    return not allowed


def _scope_for_request() -> Tuple[str, int, int]:
    """Map the current request to a rate-limit scope and budget.
    
    More specific prefixes take precedence over broader ones (e.g. /api/auth/status
    is evaluated before /api/auth).
    """
    limits: Dict[str, Tuple[int, int]] = current_app.config.get('RATE_LIMIT_RULES', {})
    path = request.path
    for prefix in sorted(limits.keys(), key=len, reverse=True):
        if path.startswith(prefix):
            budget = limits[prefix]
            return prefix, budget[0], budget[1]
    default_limit, window = current_app.config.get(
        'RATE_LIMIT_DEFAULT', (120, 60)
    )
    return 'default', default_limit, window


def register_rate_limiting(app: Flask, clock: Optional[Callable[[], float]] = None) -> None:
    """Install the limiter and enforce it through the request pipeline."""
    app.extensions['rate_limiter'] = InMemoryRateLimiter(clock=clock)

    default_limit, window = app.config.get('RATE_LIMIT_DEFAULT', (120, 60))
    app.config.setdefault('RATE_LIMIT_RULES', {
        '/api/health': (60, 60),
        '/api/auth/status': (60, 60),
        '/api/auth/session': (60, 60),
        '/api/auth': (30, 60),
        '/api/registration': (20, 60),
        # Dedicated admin login rate limit isolated per account and IP
        '/api/admin/auth/login': (10, 300),
        # Administrative roll endpoints write the eligibility gate
        '/api/admin/roll/import': (10, 300),
        # General admin console operations for authenticated officers
        '/api/admin': (60, 60),
        # Dedicated rate limit for read-only wallet and face status checks
        '/api/wallet/status': (120, 60),
        '/api/face/status': (120, 60),
        # Wallet challenge and bind operations
        '/api/wallet': (30, 60),
        '/api/face': (20, 60),
        # Read-only voting status/polling checks isolated from verification & default budgets
        '/api/voting/factors-status': (120, 60),
        '/api/v2/voting/status': (120, 60),
        '/api/v2/officer/key-status': (120, 60),
        # Student voting factor authorization endpoints (throttled per IP)
        '/api/voting/authorize': (30, 60),
        '/api/voting/mark-factors': (30, 60),
        '/api/vote': (30, 60),
        # Public receipt inclusion proof verification rate limit (Task 2)
        '/api/public/receipt': (20, 60),
        '/api/verification/receipt': (20, 60),
        '/api/receipt': (20, 60),
    })

    @app.before_request
    def _apply_rate_limit():
        if not app.config.get('RATE_LIMIT_ENABLED'):
            return None
        if app.config.get('TESTING') and not app.config.get('RATE_LIMIT_TESTING_ENABLED'):
            return None
        scope, limit, window_seconds = _scope_for_request()
        if (scope == '/api/admin' or request.path.startswith('/api/admin')) and not app.config.get('ADMIN_RATE_LIMIT_ENABLED', True):
            return None
        allowed, remaining, retry_after = get_limiter().hit(
            rate_limit_key(scope), limit, window_seconds
        )
        g.rate_limit_remaining = remaining
        g.rate_limit_limit = limit
        if not allowed:
            response = jsonify({
                'error': 'Too Many Requests',
                'message': 'Rate limit exceeded. Please retry later.',
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response
        return None

    @app.after_request
    def _expose_rate_limit_headers(response):
        if hasattr(g, 'rate_limit_remaining'):
            response.headers['X-RateLimit-Limit'] = str(getattr(g, 'rate_limit_limit', ''))
            response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
        return response
