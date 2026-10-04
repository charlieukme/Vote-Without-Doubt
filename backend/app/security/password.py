"""
Password Security - Phase 2
Argon2id hashing
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash password using Argon2id"""
    if not password:
        raise ValueError("Password cannot be empty")
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    try:
        ph.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False
