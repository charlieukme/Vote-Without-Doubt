"""
Session Management - Phase 2
Secure server-side sessions
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional


def generate_session_id() -> str:
    """Generate cryptographically secure session ID (256-bit)"""
    return secrets.token_hex(32)  # 256 bits


def calculate_expiry(absolute_minutes: int = 120, idle_minutes: int = 10) -> tuple:
    """Calculate absolute and idle expiry times"""
    now = datetime.utcnow()
    absolute = now + timedelta(minutes=absolute_minutes)
    idle = now + timedelta(minutes=idle_minutes)
    return absolute, idle


def is_expired(expires_at: datetime, now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.utcnow()
    return now >= expires_at


def is_idle_expired(idle_expires_at: datetime, now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.utcnow()
    return now >= idle_expires_at
