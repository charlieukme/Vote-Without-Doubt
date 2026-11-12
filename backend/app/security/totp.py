"""
TOTP (Time-Based One-Time Password) - RFC 6238 & Envelope Encryption
Phase 11 - Admin + Election Management
Vote Without Doubt - Backend
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional

from cryptography.fernet import Fernet


def _get_encryption_cipher() -> Fernet:
    """Derive a stable 32-byte Fernet key from master environment secrets."""
    raw_key = os.getenv('PSEUDONYM_MASTER_KEY') or os.getenv('SECRET_KEY') or 'default-admin-secret-key-phase11'
    # Derive exactly 32 bytes via SHA-256 and base64-encode for Fernet
    derived_32 = hashlib.sha256(raw_key.encode('utf-8')).digest()
    fernet_key = base64.urlsafe_b64encode(derived_32)
    return Fernet(fernet_key)


def generate_totp_secret() -> str:
    """Generate a random 160-bit (20-byte) Base32-encoded TOTP secret."""
    raw_bytes = os.urandom(20)
    return base64.b32encode(raw_bytes).decode('ascii').rstrip('=')


def encrypt_totp_secret(secret: str) -> bytes:
    """Encrypt TOTP secret using Fernet envelope encryption."""
    cipher = _get_encryption_cipher()
    return cipher.encrypt(secret.encode('utf-8'))


def decrypt_totp_secret(encrypted_secret: bytes) -> str:
    """Decrypt TOTP secret using Fernet envelope encryption."""
    cipher = _get_encryption_cipher()
    return cipher.decrypt(encrypted_secret).decode('utf-8')


def generate_totp_code(secret: str, for_time: Optional[float] = None, time_step: int = 30, digits: int = 6) -> str:
    """
    Generate an RFC 6238 TOTP code using HMAC-SHA1.
    """
    now = for_time if for_time is not None else time.time()
    counter = int(now / time_step)

    # Pad secret if padding stripped
    secret_clean = secret.upper().replace(' ', '')
    missing_padding = len(secret_clean) % 8
    if missing_padding:
        secret_clean += '=' * (8 - missing_padding)

    key = base64.b32decode(secret_clean)
    counter_bytes = struct.pack('>Q', counter)

    hmac_digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = hmac_digest[-1] & 0x0F
    code_int = (struct.unpack('>I', hmac_digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{code_int:0{digits}d}"


def verify_totp_code_with_step(secret: str, code: str, for_time: Optional[float] = None, time_step: int = 30, window: int = 1) -> tuple[bool, Optional[int]]:
    """
    Verify an RFC 6238 TOTP code with time-window tolerance ([-window, +window] steps).
    Constant-time comparison via hmac.compare_digest.
    Returns (is_valid, matched_counter_step).
    """
    if not code or not isinstance(code, str):
        return False, None

    code_clean = code.strip()
    if len(code_clean) != 6 or not code_clean.isdigit():
        return False, None

    now = for_time if for_time is not None else time.time()
    counter = int(now / time_step)

    for offset in range(-window, window + 1):
        step = counter + offset
        step_time = step * time_step
        expected_code = generate_totp_code(secret, for_time=step_time, time_step=time_step)
        if hmac.compare_digest(code_clean, expected_code):
            return True, step

    return False, None


def verify_totp_code(secret: str, code: str, for_time: Optional[float] = None, time_step: int = 30, window: int = 1) -> bool:
    """
    Verify an RFC 6238 TOTP code with time-window tolerance ([-window, +window] steps).
    Constant-time comparison via hmac.compare_digest.
    """
    valid, _ = verify_totp_code_with_step(secret, code, for_time=for_time, time_step=time_step, window=window)
    return valid
