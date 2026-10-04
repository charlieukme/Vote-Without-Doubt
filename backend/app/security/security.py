"""
Security Foundation - Phase 1
Vote Without Doubt - Backend

Basic security utilities and helpers. Authentication/crypto in later phases.
"""

import secrets
import string
from typing import Optional


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token
    Foundation utility
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def is_safe_redirect_url(url: str, allowed_hosts: Optional[list] = None) -> bool:
    """
    Basic redirect URL validation (foundation)
    """
    if not url:
        return False
    allowed_hosts = allowed_hosts or ['localhost']
    # Basic check - prevent open redirects (foundation)
    if url.startswith(('http://', 'https://')):
        # In production, validate host
        return any(host in url for host in allowed_hosts)
    return url.startswith('/')
