"""
OTP Security - Phase 2
6-digit OTP with HMAC-SHA256, pepper, expiry, rate limits
"""

import hmac
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Pepper from env in real usage; fallback for dev
import os


def get_otp_pepper() -> bytes:
    pepper = os.getenv('OTP_PEPPER', 'dev-otp-pepper-change-in-production')
    return pepper.encode('utf-8')


def generate_otp() -> str:
    """Generate 6-digit cryptographically secure OTP"""
    return f"{secrets.randbelow(1000000):06d}"


def hash_otp(otp: str, pepper: Optional[bytes] = None) -> str:
    """Hash OTP with HMAC-SHA256 and pepper"""
    if pepper is None:
        pepper = get_otp_pepper()
    mac = hmac.new(pepper, msg=otp.encode('utf-8'), digestmod=hashlib.sha256)
    return mac.hexdigest()


def verify_otp(otp: str, otp_hash: str, pepper: Optional[bytes] = None) -> bool:
    """Verify OTP against stored hash (timing-safe)"""
    expected = hash_otp(otp, pepper)
    return hmac.compare_digest(expected, otp_hash)
