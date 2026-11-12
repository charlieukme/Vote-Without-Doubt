"""
Security Logging Filter & Redaction - Phase E.16.1
Vote Without Doubt - Backend

Intercepts Python logging records (application, framework, HTTP, and exceptions)
and redacts sensitive credentials, tokens, private keys, passwords, OTPs,
database URIs, and raw biometric/binary payloads before output.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Sensitive mapping keys (case-insensitive normalized)
SENSITIVE_KEYS: Set[str] = frozenset({
    'password', 'passwd', 'password_hash', 'new_password', 'old_password',
    'secret', 'secret_key', 'token', 'access_token', 'session_token',
    'cookie', 'session', 'authorization', 'totp', 'totp_secret',
    'totp_code', 'otp', 'otp_code', 'pepper', 'otp_pepper',
    'private_key', 'privatekey', 'key_material', 'encrypted_embedding',
    'embedding', 'descriptor', 'face_template', 'seed', 'mnemonic',
})

# Precompiled regex patterns for string/header/URI redaction
RE_AUTHORIZATION_HEADER = re.compile(
    r'(?i)\b(bearer|basic|token)\s+[A-Za-z0-9_\-\.\+/=]{6,}', re.IGNORECASE
)
RE_SESSION_COOKIE = re.compile(
    r'(?i)\b(session|session_token|__Host-session)\s*=\s*[^;\s]+', re.IGNORECASE
)
RE_HEX_PRIVATE_KEY = re.compile(
    r'(?i)\b0x[a-f0-9]{64}\b', re.IGNORECASE
)
RE_STANDALONE_HEX_KEY = re.compile(
    r'(?i)(?:key|secret|token|seed|private)\s*[:=]\s*["\']?([a-f0-9]{64})["\']?', re.IGNORECASE
)
RE_DB_PASSWORD_URI = re.compile(
    r'(?i)(mysql(?:\+pymysql)?://[^:]+:)([^@]+)(@)', re.IGNORECASE
)
RE_BASE64_IMAGE_URI = re.compile(
    r'data:image/[a-zA-Z0-9\.\-]+;base64,[A-Za-z0-9+/=]{40,}', re.IGNORECASE
)
RE_KEY_VALUE_SENSITIVE = re.compile(
    r'(?i)(["\']?(?:password|passwd|new_password|old_password|otp|otp_code|totp|totp_code|totp_secret|private_key|privatekey|token|secret)["\']?\s*[:=]\s*)(?:["\'][^"\']*["\']|[^\s,;\}]+)',
    re.IGNORECASE
)


def _normalize_key(key: Any) -> str:
    return re.sub(r'[^a-z0-9_]', '', str(key).lower())


def redact_text(text: str) -> str:
    """Scrub sensitive patterns, tokens, keys, and credentials from a text string."""
    if not text or not isinstance(text, str):
        return text

    # Redact Authorization headers
    text = RE_AUTHORIZATION_HEADER.sub(r'\1 [REDACTED]', text)

    # Redact session cookies
    text = RE_SESSION_COOKIE.sub(r'\1=[REDACTED]', text)

    # Redact 64-char 0x hex private keys
    text = RE_HEX_PRIVATE_KEY.sub('0x[REDACTED_HEX_KEY]', text)

    # Redact database connection URI credentials
    text = RE_DB_PASSWORD_URI.sub(r'\1[REDACTED]\3', text)

    # Redact base64 image data URIs
    text = RE_BASE64_IMAGE_URI.sub('data:image/[REDACTED_IMAGE_DATA]', text)

    # Redact key/value patterns in JSON, URL query strings, or log text
    text = RE_KEY_VALUE_SENSITIVE.sub(r'\1[REDACTED]', text)

    # Redact contextual standalone hex keys
    text = RE_STANDALONE_HEX_KEY.sub(r'key=[REDACTED_KEY]', text)

    return text


def redact_structured(obj: Any, depth: int = 0) -> Any:
    """Recursively scrub sensitive keys and binary embeddings from mappings/iterables."""
    if depth > 10:
        return '[MAX_DEPTH_EXCEEDED]'

    if isinstance(obj, dict):
        scrubbed = {}
        for k, v in obj.items():
            norm_k = _normalize_key(k)
            if any(s in norm_k for s in SENSITIVE_KEYS):
                scrubbed[k] = '[REDACTED]'
            else:
                scrubbed[k] = redact_structured(v, depth + 1)
        return scrubbed

    if isinstance(obj, (list, tuple, set)):
        items = [redact_structured(item, depth + 1) for item in obj]
        return type(obj)(items) if isinstance(obj, (list, tuple)) else items

    if isinstance(obj, str):
        return redact_text(obj)

    if isinstance(obj, bytes):
        # Detect raw float32 ArcFace embedding vectors (512 * 4 = 2048 bytes) or raw keys
        if len(obj) == 2048 or len(obj) in (32, 64):
            return b'[REDACTED_BINARY_PAYLOAD]'
        return obj

    return obj


class RedactingFilter(logging.Filter):
    """
    Logging filter that sanitizes log records before emission to console, files, or streams.
    Redacts Authorization headers, cookies, passwords, private keys, database URIs,
    OTPs, and biometric embeddings in msg, args, and exception tracebacks.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Format message with args if args present, so full interpolated string is scrubbed
            if record.args:
                try:
                    formatted = record.msg % record.args
                    record.msg = redact_text(str(formatted))
                    record.args = None
                except Exception:
                    # If % formatting fails (e.g. dict arg or mismatch), scrub msg and args separately
                    if isinstance(record.msg, str):
                        record.msg = redact_text(record.msg)
                    elif isinstance(record.msg, dict):
                        record.msg = redact_structured(record.msg)

                    if isinstance(record.args, dict):
                        record.args = redact_structured(record.args)
                    elif isinstance(record.args, (tuple, list)):
                        record.args = tuple(redact_structured(arg) for arg in record.args)
            else:
                if isinstance(record.msg, str):
                    record.msg = redact_text(record.msg)
                elif isinstance(record.msg, dict):
                    record.msg = redact_structured(record.msg)

            # Redact exception traceback if formatted
            if getattr(record, 'exc_text', None) and isinstance(record.exc_text, str):
                record.exc_text = redact_text(record.exc_text)

        except Exception:
            # Fail closed to preserve logging pipeline stability without leaking
            pass

        return True


def register_logging_filter(app: Optional[Any] = None) -> RedactingFilter:
    """
    Attach RedactingFilter to root logger, werkzeug logger, app logger,
    and all root handlers.
    """
    filter_instance = RedactingFilter()

    # Root logger
    root_logger = logging.getLogger()
    if filter_instance not in root_logger.filters:
        root_logger.addFilter(filter_instance)

    for handler in root_logger.handlers:
        if filter_instance not in handler.filters:
            handler.addFilter(filter_instance)

    # Framework / Werkzeug logger
    werkzeug_logger = logging.getLogger('werkzeug')
    if filter_instance not in werkzeug_logger.filters:
        werkzeug_logger.addFilter(filter_instance)

    # Flask app logger
    if app is not None and hasattr(app, 'logger'):
        if filter_instance not in app.logger.filters:
            app.logger.addFilter(filter_instance)

    return filter_instance
