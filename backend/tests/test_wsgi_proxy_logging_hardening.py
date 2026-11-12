"""
Tests for WSGI, Reverse-Proxy, and Logging Hardening - Phase E.16.1
Vote Without Doubt - Backend
"""

import io
import logging
import os
import secrets
import threading
import time
from unittest.mock import MagicMock

import pytest
from flask import Flask, jsonify, request
from werkzeug.test import EnvironBuilder

from app import create_app
from app.config.config import StagingConfig, ProductionConfig
from app.security.logging_filter import (
    RedactingFilter,
    redact_text,
    redact_structured,
    register_logging_filter,
)
from app.security.middleware import TrustedProxyFix, is_trusted_host
from app.security.rate_limit import client_identity, get_limiter, rate_limit_key


# ==============================================================================
# 1. WSGI Entry Point & App Factory Tests
# ==============================================================================

def test_wsgi_module_imports_and_creates_app():
    """Verify backend/wsgi.py imports cleanly and produces a valid Flask WSGI app."""
    import wsgi
    assert hasattr(wsgi, 'app')
    assert isinstance(wsgi.app, Flask)
    assert wsgi.app.name == 'app'


def test_staging_config_attributes():
    """Verify StagingConfig inherits production security while permitting staging domains."""
    cfg = StagingConfig()
    assert cfg.APP_ENV == 'staging'
    assert cfg.PROXY_FIX_ENABLED is True
    assert cfg.SESSION_COOKIE_SECURE is True
    assert cfg.ADMIN_RATE_LIMIT_ENABLED is True
    assert 'staging-vote.college.edu' in cfg.TRUSTED_HOSTS


# ==============================================================================
# 2. TrustedProxyFix & Forwarding Header Spoofing Defense
# ==============================================================================

@pytest.fixture
def proxy_app():
    """Flask application wrapped with TrustedProxyFix trusting 127.0.0.1 (1 hop)."""
    app = Flask('proxy_test_app')
    app.config['TESTING'] = True
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True

    from app.security.rate_limit import register_rate_limiting
    register_rate_limiting(app)

    @app.route('/test-ip')
    def get_ip():
        return jsonify({
            'remote_addr': request.remote_addr,
            'is_secure': request.is_secure,
            'host': request.host,
            'client_id': client_identity(),
        })

    app.wsgi_app = TrustedProxyFix(
        app.wsgi_app,
        trusted_proxies=['127.0.0.1', '::1'],
        x_for=1,
        x_proto=1,
        x_host=1,
    )
    return app


def test_trusted_proxy_single_hop_rewrites_identity(proxy_app):
    """When request comes from trusted proxy (127.0.0.1), client IP & proto are trusted."""
    client = proxy_app.test_client()
    resp = client.get(
        '/test-ip',
        environ_base={
            'REMOTE_ADDR': '127.0.0.1',
            'HTTP_X_FORWARDED_FOR': '203.0.113.10',
            'HTTP_X_FORWARDED_PROTO': 'https',
            'HTTP_X_FORWARDED_HOST': 'staging-vote.college.edu',
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['remote_addr'] == '203.0.113.10'
    assert data['is_secure'] is True
    assert data['host'] == 'staging-vote.college.edu'
    assert data['client_id'] == '203.0.113.10'


def test_untrusted_direct_connection_blocks_spoofing(proxy_app):
    """When request connects from untrusted IP directly, forwarded headers are stripped."""
    client = proxy_app.test_client()
    resp = client.get(
        '/test-ip',
        environ_base={
            'REMOTE_ADDR': '198.51.100.5',  # Direct connection from untrusted IP
            'HTTP_X_FORWARDED_FOR': '10.0.0.1',  # Malicious attempt to spoof internal IP
            'HTTP_X_FORWARDED_PROTO': 'https',  # Attempt to spoof HTTPS
            'HTTP_X_FORWARDED_HOST': 'internal-admin.college.edu',
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Spoofed headers must be stripped: socket IP and HTTP scheme are preserved
    assert data['remote_addr'] == '198.51.100.5'
    assert data['is_secure'] is False
    assert data['client_id'] == '198.51.100.5'


def test_trusted_proxy_discards_client_supplied_left_ips(proxy_app):
    """Attacker passing through Nginx cannot spoof by prepending an IP."""
    client = proxy_app.test_client()
    resp = client.get(
        '/test-ip',
        environ_base={
            'REMOTE_ADDR': '127.0.0.1',  # Nginx connection
            # Attacker sent '1.2.3.4', Nginx appended real IP '198.51.100.5'
            'HTTP_X_FORWARDED_FOR': '1.2.3.4, 198.51.100.5',
            'HTTP_X_FORWARDED_PROTO': 'https',
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # With x_for=1, only the rightmost IP appended by Nginx is trusted
    assert data['remote_addr'] == '198.51.100.5'
    assert data['client_id'] == '198.51.100.5'


# ==============================================================================
# 3. Rate Limiter Behind Trusted Proxy
# ==============================================================================

def test_rate_limiter_distinct_clients_behind_trusted_proxy(proxy_app):
    """Different client IPs forwarded by trusted proxy get independent rate-limit budgets."""
    with proxy_app.app_context():
        limiter = get_limiter()
        limiter.reset()

        client = proxy_app.test_client()

        # Client A hits
        for _ in range(5):
            client.get('/test-ip', environ_base={'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_FORWARDED_FOR': '203.0.113.10'})

        # Client B hits
        for _ in range(3):
            client.get('/test-ip', environ_base={'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_FORWARDED_FOR': '203.0.113.20'})

        # Inspect limiter store keys: must have separate keys for 203.0.113.10 and 203.0.113.20
        # and NOT a single key for 127.0.0.1
        with limiter._lock:
            keys = list(limiter._hits.keys())

        ip_10_hits = [k for k in keys if '203.0.113.10' in str(k)]
        ip_20_hits = [k for k in keys if '203.0.113.20' in str(k)]
        shared_127_hits = [k for k in keys if '127.0.0.1' in str(k)]

        assert len(ip_10_hits) >= 1
        assert len(ip_20_hits) >= 1
        assert len(shared_127_hits) == 0, "Rate limiter incorrectly used proxy IP 127.0.0.1!"


# ==============================================================================
# 4. Host Validation Behind Proxy
# ==============================================================================

def test_host_validation_allows_configured_staging_host(app):
    """Staging hostname is accepted when in TRUSTED_HOSTS."""
    allowed = ['localhost', '127.0.0.1', 'staging-vote.college.edu']
    assert is_trusted_host('staging-vote.college.edu', allowed) is True
    assert is_trusted_host('staging-vote.college.edu:443', allowed) is True


def test_host_validation_rejects_untrusted_host(app):
    """Untrusted Host header is rejected."""
    allowed = ['localhost', '127.0.0.1', 'staging-vote.college.edu']
    assert is_trusted_host('attacker.evil.com', allowed) is False
    assert is_trusted_host('vote.college.edu.attacker.com', allowed) is False


# ==============================================================================
# 5. Logging Redaction Tests
# ==============================================================================

def test_redact_authorization_bearer_token():
    msg = "User authenticated with header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"
    redacted = redact_text(msg)
    assert "eyJhbGci" not in redacted
    assert "Bearer [REDACTED]" in redacted


def test_redact_session_cookie():
    msg = "Incoming request with Cookie: session=d3adb33f9988776655; theme=dark"
    redacted = redact_text(msg)
    assert "d3adb33f" not in redacted
    assert "session=[REDACTED]" in redacted
    assert "theme=dark" in redacted


def test_redact_hex_private_key():
    raw_key = "0x" + "a1" * 32
    msg = f"Relayer initialized with signing key: {raw_key}"
    redacted = redact_text(msg)
    assert raw_key not in redacted
    assert "0x[REDACTED_HEX_KEY]" in redacted


def test_redact_database_uri_password():
    uri = "Connecting to mysql+pymysql://vwd_user:super_secret_db_pass@127.0.0.1:3306/voting_sys"
    redacted = redact_text(uri)
    assert "super_secret_db_pass" not in redacted
    assert "mysql+pymysql://vwd_user:[REDACTED]@127.0.0.1:3306/voting_sys" in redacted


def test_redact_base64_image_data():
    img_uri = "data:image/jpeg;base64," + "A" * 60
    msg = f"Received face frame payload: {img_uri}"
    redacted = redact_text(msg)
    assert "A" * 60 not in redacted
    assert "data:image/[REDACTED_IMAGE_DATA]" in redacted


def test_redact_structured_mapping():
    data = {
        'username': 'student_alice',
        'password': 'PlainTextPassword123!',
        'otp_code': '123456',
        'totp_secret': 'JBSWY3DPEHPK3PXP',
        'nested': {
            'private_key': '0x' + 'bb' * 32,
            'public_info': 'safe_value',
        }
    }
    scrubbed = redact_structured(data)
    assert scrubbed['username'] == 'student_alice'
    assert scrubbed['password'] == '[REDACTED]'
    assert scrubbed['otp_code'] == '[REDACTED]'
    assert scrubbed['totp_secret'] == '[REDACTED]'
    assert scrubbed['nested']['private_key'] == '[REDACTED]'
    assert scrubbed['nested']['public_info'] == 'safe_value'


def test_redact_binary_biometric_embedding():
    # 512-dimensional float32 embedding vector = 2048 bytes
    embedding_bytes = b'\x00' * 2048
    scrubbed = redact_structured(embedding_bytes)
    assert scrubbed == b'[REDACTED_BINARY_PAYLOAD]'


def test_redacting_filter_intercepts_log_record():
    logger = logging.getLogger('test_redaction_logger')
    logger.setLevel(logging.INFO)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)

    r_filter = RedactingFilter()
    logger.addFilter(r_filter)
    handler.addFilter(r_filter)

    try:
        secret_token = "0x" + "cc" * 32
        logger.info("Executing contract deployment with key=%s and password=%s", secret_token, "SecretPass123!")
        output = stream.getvalue()

        assert secret_token not in output
        assert "SecretPass123!" not in output
        assert "0x[REDACTED_HEX_KEY]" in output or "[REDACTED]" in output
    finally:
        logger.removeHandler(handler)


# ==============================================================================
# 6. Production WSGI Server (Waitress) Startup & Shutdown
# ==============================================================================

def test_production_wsgi_server_starts_and_serves_health():
    """Verify production WSGI server serves health endpoints and terminates gracefully."""
    from waitress.server import create_server

    app = create_app('testing')
    # Bind to random local port on 127.0.0.1
    server = create_server(app, host='127.0.0.1', port=0, threads=2)
    actual_port = server.effective_port

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    time.sleep(0.5)

    import urllib.request
    try:
        url = f"http://127.0.0.1:{actual_port}/api/health"
        req = urllib.request.Request(url, headers={'Host': 'localhost'})
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200
            content = response.read().decode('utf-8')
            assert '"status":"ok"' in content or '"status": "ok"' in content

        url_ready = f"http://127.0.0.1:{actual_port}/api/health/ready"
        req_ready = urllib.request.Request(url_ready, headers={'Host': 'localhost'})
        with urllib.request.urlopen(req_ready, timeout=5) as response:
            assert response.status == 200
            content_ready = response.read().decode('utf-8')
            assert '"database":"ok"' in content_ready or '"database": "ok"' in content_ready

    finally:
        server.close()
        server_thread.join(timeout=2.0)
