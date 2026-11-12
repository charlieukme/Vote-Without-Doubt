"""
HTTP Security Middleware Foundation - Phase 1
Vote Without Doubt - Backend

Registers, in the application factory:

* ``register_security_headers`` - response hardening headers (Bible Section 7
  principles 9 and 12). Disabled in debug mode so the Werkzeug debugger stays
  usable during local development.
* ``register_trusted_hosts`` - Host-header allow-listing, so a poisoned Host
  header cannot influence generated URLs.
* ``enforce_csrf`` - the CSRF check from :mod:`app.security.csrf`.

Rate limiting is registered separately by :mod:`app.security.rate_limit`.
"""

from __future__ import annotations

from typing import Iterable, Optional

from flask import Flask, current_app, jsonify, request

from .csrf import CsrfError, enforce_csrf

DEFAULT_ALLOWED_HOSTS = ('localhost', '127.0.0.1', '[::1]', 'testserver')

#: Content-Security-Policy for API responses. The backend serves JSON only, so
#: the strictest possible policy is appropriate: nothing may be loaded or
#: framed from an API response.
API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Permissions-Policy': 'geolocation=(), camera=(), microphone=()',
    'Cache-Control': 'no-store',
}


def _normalise_host(host: str) -> str:
    host = (host or '').strip().lower()
    if host.startswith('[') and ']' in host:
        return host[: host.index(']') + 1]
    if host.count(':') == 1:
        host = host.split(':', 1)[0]
    return host.rstrip('.')


def is_trusted_host(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Exact, case-insensitive host match against the allow-list."""
    normalised = _normalise_host(host)
    allowed = {_normalise_host(item) for item in allowed_hosts}
    allowed.discard('')
    return normalised in allowed


def register_security_headers(app: Flask) -> None:
    """Attach hardening headers to every response."""

    @app.after_request
    def _apply_security_headers(response):
        # The debugger requires inline styles and eval; sending a strict CSP in
        # debug mode would break the local developer experience, and debug mode
        # must never be reachable in production.
        if not app.debug:
            for header, value in SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            response.headers.setdefault('Content-Security-Policy', API_CONTENT_SECURITY_POLICY)
        return response


def register_trusted_hosts(app: Flask, allowed_hosts: Optional[Iterable[str]] = None) -> None:
    """Reject requests whose Host header is not allow-listed."""

    @app.before_request
    def _enforce_trusted_host():
        configured = allowed_hosts or app.config.get('TRUSTED_HOSTS') or DEFAULT_ALLOWED_HOSTS
        host = request.host
        if not is_trusted_host(host, configured):
            response = jsonify({
                'error': 'Bad Request',
                'message': 'Host header is not allowed.',
            })
            response.status_code = 400
            return response
        return None


def register_csrf_protection(app: Flask) -> None:
    """Wire the CSRF check into the request pipeline."""

    @app.before_request
    def _enforce_csrf():
        try:
            enforce_csrf()
        except CsrfError as error:
            response = jsonify({
                'error': 'Forbidden',
                'message': error.reason,
            })
            response.status_code = 403
            return response
        return None


class TrustedProxyFix:
    """
    Reverse proxy middleware that only trusts forwarded headers if the immediate
    socket connection (REMOTE_ADDR) originates from an explicitly trusted proxy.

    If the connection arrives from an untrusted source (e.g. direct access bypassing Nginx),
    any client-supplied X-Forwarded-* headers are stripped to prevent IP, protocol,
    and host spoofing.

    If the connection arrives from a trusted proxy (e.g. 127.0.0.1, ::1, or trusted subnet),
    it applies ProxyFix with exact hop counts.
    """

    def __init__(
        self,
        app,
        trusted_proxies: Optional[Iterable[str]] = None,
        x_for: int = 1,
        x_proto: int = 1,
        x_host: int = 1,
        x_port: int = 0,
        x_prefix: int = 0,
    ):
        self.app = app
        self.trusted_proxies = {
            _normalise_host(p) for p in (trusted_proxies or ('127.0.0.1', '::1', 'localhost'))
        }
        self.x_for = x_for
        self.x_proto = x_proto
        self.x_host = x_host
        self.x_port = x_port
        self.x_prefix = x_prefix

        from werkzeug.middleware.proxy_fix import ProxyFix
        self.proxy_fix = ProxyFix(
            app,
            x_for=x_for,
            x_proto=x_proto,
            x_host=x_host,
            x_port=x_port,
            x_prefix=x_prefix,
        )

    def __call__(self, environ, start_response):
        remote_addr = environ.get('REMOTE_ADDR', '')
        normalized_remote = _normalise_host(remote_addr)

        if normalized_remote not in self.trusted_proxies:
            # Untrusted direct connection: strip any client-supplied forwarded headers
            # to prevent spoofing of client identity, HTTPS state, or host.
            for key in (
                'HTTP_X_FORWARDED_FOR',
                'HTTP_X_FORWARDED_PROTO',
                'HTTP_X_FORWARDED_HOST',
                'HTTP_X_FORWARDED_PORT',
                'HTTP_X_FORWARDED_PREFIX',
            ):
                environ.pop(key, None)
            return self.app(environ, start_response)

        # Connection is from trusted proxy: process through ProxyFix
        return self.proxy_fix(environ, start_response)


def register_trusted_proxy(
    app: Flask,
    trusted_proxies: Optional[Iterable[str]] = None,
    num_proxies: int = 1,
) -> None:
    """Attach TrustedProxyFix middleware to Flask WSGI application."""
    app.wsgi_app = TrustedProxyFix(
        app.wsgi_app,
        trusted_proxies=trusted_proxies,
        x_for=num_proxies,
        x_proto=num_proxies,
        x_host=num_proxies,
        x_port=0,
        x_prefix=0,
    )