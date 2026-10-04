"""
Face Security - Phase 5 (Foundation)
Minimal structure; actual detection deferred to environment
"""

import os
import secrets
from datetime import datetime, timedelta
from cryptography.fernet import Fernet


def generate_face_challenge_id() -> str:
    return secrets.token_hex(32)


def get_encryption_key():
    key = os.getenv('FACE_ENCRYPTION_KEY')
    if not key:
        key = Fernet.generate_key()
    if isinstance(key, str):
        try:
            return key.encode()
        except Exception:
            return key
    return key


def encrypt_embedding(embedding_bytes: bytes) -> bytes:
    try:
        f = Fernet(get_encryption_key())
        return f.encrypt(embedding_bytes)
    except Exception:
        return embedding_bytes


def decrypt_embedding(encrypted: bytes) -> bytes:
    try:
        f = Fernet(get_encryption_key())
        return f.decrypt(encrypted)
    except Exception:
        return encrypted
