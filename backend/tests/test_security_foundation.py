"""
Security foundation tests - Phase 1 (remediated)
Vote Without Doubt - Backend

Covers the Phase 1 security defects found in the independent audit:

* ``is_safe_redirect_url`` accepted ``//evil.com/steal``,
  ``http://evil.com/?x=localhost`` and ``https://evil.com/localhost``;
* no security response headers, no Host-header validation, no CSRF
  enforcement point and no working rate limiter;
* a publicly known ``SECRET_KEY`` fallback shipped in source;
* the development server bound ``0.0.0.0`` with the debugger enabled.
"""

import pytest

from app.security.csrf import (
    CSRF_SESSION_KEY,
    generate_csrf_token,
    validate_csrf_token,
)
from app.security.middleware import is_trusted_host
from app.security.rate_limit import InMemoryRateLimiter, is_rate_limited
from app.security.security import generate_secure_token, is_safe_redirect_url


# ------------------------------------------------------------ redirect safety

@pytest.mark.parametrize('url', [
    '//evil.com/steal',
    '//evil.com',
    '///evil.com',
    'http://evil.com/?x=localhost',
    'https://evil.com/localhost',
    'http://localhost.evil.com/',
    'https://localhost.evil.com/',
    'http://evil.com:8080/',
    'http://user@localhost/',
    'http://localhost@evil.com/',
    'https://attacker:pass@localhost/x',
    'http://localhost@localhost@evil.com/',
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    'data:text/html;base64,PHNjcmlwdD4=',
    'file:///etc/passwd',
    'ftp://localhost/x',
    'vbscript:msgbox(1)',
    'C:\\Windows\\system32',
    'c:temp',
    '/path\nSet-Cookie: admin=1',
    '/path\r\nLocation: http://evil.com',
    '/path\x00evil',
    '/\\evil.com',
    '\\@evil.com',
    '\\\\evil.com',
    '/path\\evil.com',
    '',
    None,
    123,
    '   ',
    'relative/path',
    './relative',
    '#fragment-only',
    'http://',
])
def test_unsafe_redirect_targets_are_rejected(url):
    assert is_safe_redirect_url(url) is False


@pytest.mark.parametrize('url', [
    '/',
    '/api/vote',
    '/api/vote?next=/receipt',
    'http://localhost:5000/api/vote',
    'https://localhost/api/vote',
    'http://LOCALHOST/api/vote',
    'http://127.0.0.1:5000/api/vote',
])
def test_safe_redirect_targets_are_accepted(url):
    assert is_safe_redirect_url(url) is True


def test_redirect_allow_list_is_exact_not_substring():
    assert is_safe_redirect_url('https://trusted.example/x', ['trusted.example']) is True
    assert is_safe_redirect_url('https://trusted.example.evil/x', ['trusted.example']) is False
    assert is_safe_redirect_url('https://evil/x?u=trusted.example', ['trusted.example']) is False
    assert is_safe_redirect_url('https://sub.trusted.example/x', ['trusted.example']) is False


# -------------------------------------------------------------------- tokens

def test_generate_secure_token_is_random_and_long_enough():
    first = generate_secure_token()
    second = generate_secure_token()
    assert len(first) == 32
    assert first != second
    assert first.isalnum()


def test_generate_secure_token_rejects_weak_length():
    with pytest.raises(ValueError):
        generate_secure_token(8)


# ------------------------------------------------------------ trusted hosts

@pytest.mark.parametrize('host', ['localhost', 'LOCALHOST', 'localhost:5000',
                                  '127.0.0.1', 'localhost.', '[::1]'])
def test_trusted_hosts_accepted(host):
    assert is_trusted_host(host, ['localhost', '127.0.0.1', '[::1]']) is True


@pytest.mark.parametrize('host', ['evil.com', 'localhost.evil.com',
                                  'evil.com/localhost', '', '127.0.0.1.evil.com'])
def test_untrusted_hosts_rejected(host):
    assert is_trusted_host(host, ['localhost', '127.0.0.1', '[::1]']) is False


def test_untrusted_host_header_is_rejected_by_the_app(client):
    response = client.get('/api/health', headers={'Host': 'evil.example.com'})
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Bad Request'


# ---------------------------------------------------------- security headers

def test_security_headers_are_present(client):
    response = client.get('/api/health')
    headers = response.headers

    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'DENY'
    assert headers['Referrer-Policy'] == 'no-referrer'
    assert headers['Cross-Origin-Opener-Policy'] == 'same-origin'
    assert headers['Cache-Control'] == 'no-store'
    assert 'frame-ancestors' in headers['Content-Security-Policy']
    assert 'camera=()' in headers['Permissions-Policy']


def test_error_responses_also_carry_security_headers(client):
    response = client.get('/api/nonexistent')
    assert response.status_code == 404
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


# ---------------------------------------------------------------------- csrf

def test_csrf_token_is_stable_within_a_session(app, client):
    with client.session_transaction() as session:
        pass
    first = client.get('/api/health')
    assert first.status_code == 200

    with app.test_request_context():
        from flask import session
        # Token generation happens against the session, exercised via the helper.
        assert generate_csrf_token() == session.get(CSRF_SESSION_KEY)


def test_csrf_validation_accepts_matching_token(app, client):
    with app.test_request_context(headers={'X-CSRF-Token': 'matching-token'}):
        from flask import session
        session[CSRF_SESSION_KEY] = 'matching-token'
        assert validate_csrf_token() is True


def test_csrf_validation_rejects_missing_or_wrong_token(app, client):
    with app.test_request_context():
        from flask import session
        generate_csrf_token()
        assert validate_csrf_token() is False

    with app.test_request_context(headers={'X-CSRF-Token': 'wrong-token'}):
        from flask import session
        session[CSRF_SESSION_KEY] = 'expected-token'
        assert validate_csrf_token() is False


def test_csrf_blocks_state_changing_request_when_enabled(app, client):
    app.config['CSRF_ENABLED'] = True
    response = client.post('/api/health')
    assert response.status_code == 403
    assert response.get_json()['error'] == 'Forbidden'


def test_csrf_allows_safe_methods_when_enabled(app, client):
    app.config['CSRF_ENABLED'] = True
    assert client.get('/api/health').status_code == 200


def test_csrf_is_a_no_op_while_disabled(app, client):
    assert app.config['CSRF_ENABLED'] is False
    assert client.post('/api/health').status_code == 405


# -------------------------------------------------------------- rate limiting

def test_rate_limiter_blocks_after_budget_is_exhausted():
    limiter = InMemoryRateLimiter(clock=lambda: 1000.0)

    for _ in range(3):
        allowed, remaining, _ = limiter.hit('k', 3, 60)
        assert allowed is True

    allowed, remaining, retry_after = limiter.hit('k', 3, 60)
    assert allowed is False
    assert remaining == 0
    assert 0 < retry_after <= 60


def test_rate_limiter_window_resets():
    now = {'t': 1000.0}
    limiter = InMemoryRateLimiter(clock=lambda: now['t'])

    for _ in range(2):
        assert limiter.hit('k', 2, 60)[0] is True
    assert limiter.hit('k', 2, 60)[0] is False

    now['t'] += 61
    assert limiter.hit('k', 2, 60)[0] is True


def test_rate_limiter_keys_are_independent():
    limiter = InMemoryRateLimiter(clock=lambda: 1000.0)
    for _ in range(2):
        limiter.hit('a', 2, 60)
    assert limiter.hit('a', 2, 60)[0] is False
    assert limiter.hit('b', 2, 60)[0] is True


def test_app_enforces_rate_limit_and_returns_429(app, client):
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['RATE_LIMIT_RULES'] = {'/api/health': (2, 60)}
    from app.security.rate_limit import get_limiter
    get_limiter().reset()

    assert client.get('/api/health').status_code == 200
    assert client.get('/api/health').status_code == 200

    blocked = client.get('/api/health')
    assert blocked.status_code == 429
    assert 'Retry-After' in blocked.headers
    assert blocked.get_json()['error'] == 'Too Many Requests'


def test_rate_limit_headers_expose_remaining_budget(app, client):
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    from app.security.rate_limit import get_limiter
    get_limiter().reset()

    # /api/health has its own registered rule of 60/60s, not the global default.
    response = client.get('/api/health')
    assert response.headers['X-RateLimit-Limit'] == '60'
    assert response.headers['X-RateLimit-Remaining'] == '59'


def test_is_rate_limited_uses_the_caller_identity(app):
    from app.security.rate_limit import get_limiter
    with app.test_request_context('/api/vote', environ_base={'REMOTE_ADDR': '10.0.0.9'}):
        get_limiter().reset()
        assert is_rate_limited('probe', 1, 60) is False
        assert is_rate_limited('probe', 1, 60) is True


def test_rate_limit_is_actually_enabled_by_default():
    from app.config.config import Config, ProductionConfig
    assert Config.RATE_LIMIT_ENABLED is True
    assert ProductionConfig.RATE_LIMIT_ENABLED is True
    assert Config.ADMIN_RATE_LIMIT_ENABLED is True
    assert ProductionConfig.ADMIN_RATE_LIMIT_ENABLED is True


def test_admin_rate_limit_enabled_blocks_admin_requests(app, client):
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['ADMIN_RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_RULES'] = {'/api/admin': (2, 60)}
    from app.security.rate_limit import get_limiter
    get_limiter().reset()

    # First two requests hit the endpoint and are not 429 (unauthenticated 401 is expected)
    res1 = client.get('/api/admin/auth/me')
    assert res1.status_code == 401
    res2 = client.get('/api/admin/auth/me')
    assert res2.status_code == 401

    # Third request exceeds budget and returns 429
    blocked = client.get('/api/admin/auth/me')
    assert blocked.status_code == 429
    assert blocked.get_json()['error'] == 'Too Many Requests'


def test_admin_rate_limit_disabled_bypasses_admin_only(app, client):
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['ADMIN_RATE_LIMIT_ENABLED'] = False
    app.config['RATE_LIMIT_RULES'] = {'/api/admin': (2, 60), '/api/health': (2, 60)}
    from app.security.rate_limit import get_limiter
    get_limiter().reset()

    # Admin requests exceed the rule's limit (2) but are NOT blocked
    for _ in range(5):
        res = client.get('/api/admin/auth/me')
        assert res.status_code == 401  # Not 429

    # Non-admin endpoints (/api/health) are STILL strictly rate-limited
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/health').status_code == 200
    blocked_health = client.get('/api/health')
    assert blocked_health.status_code == 429


def test_is_rate_limited_helper_respects_admin_toggle(app):
    from app.security.rate_limit import get_limiter
    with app.test_request_context('/api/admin', environ_base={'REMOTE_ADDR': '10.0.0.9'}):
        get_limiter().reset()
        app.config['ADMIN_RATE_LIMIT_ENABLED'] = False
        assert is_rate_limited('/api/admin', 1, 60) is False
        assert is_rate_limited('/api/admin', 1, 60) is False
        # Non-admin scope is still rate-limited even when admin rate limiter is disabled
        assert is_rate_limited('/api/vote', 1, 60) is False
        assert is_rate_limited('/api/vote', 1, 60) is True

        app.config['ADMIN_RATE_LIMIT_ENABLED'] = True
        get_limiter().reset()
        assert is_rate_limited('/api/admin', 1, 60) is False
        assert is_rate_limited('/api/admin', 1, 60) is True


def test_production_config_rejects_disabled_admin_rate_limit():
    from app.config.config import ProductionConfig
    with pytest.raises(RuntimeError, match='ADMIN_RATE_LIMIT_ENABLED cannot be disabled in production'):
        ProductionConfig.validate({'APP_ENV': 'production', 'ADMIN_RATE_LIMIT_ENABLED': False, 'SECRET_KEY': 's' * 32})


# ---------------------------------------------------------------------- cors

def test_cors_is_restricted_to_configured_origins(client):
    from flask import request
    allowed = client.get(
        '/api/health',
        headers={'Origin': 'http://localhost:5173'},
    )
    assert allowed.headers.get('Access-Control-Allow-Origin') == 'http://localhost:5173'

    blocked = client.get(
        '/api/health',
        headers={'Origin': 'http://evil.example.com'},
    )
    assert blocked.headers.get('Access-Control-Allow-Origin') is None


def test_cors_does_not_default_to_wildcard():
    from app.config.config import Config
    assert '*' not in Config.CORS_ALLOWED_ORIGINS