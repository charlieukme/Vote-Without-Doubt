"""
Session Management - Phase 2
Secure server-side sessions
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional


#: Phase 2 session lifetime policy (PROJECT_BIBLE Section 7, principle 2).
#: The absolute deadline is fixed when the session is created and is never
#: extended, so activity cannot prolong a session beyond two hours. The idle
#: deadline is refreshed on activity, giving a true sliding idle window.
ABSOLUTE_TIMEOUT_MINUTES = 120
IDLE_TIMEOUT_MINUTES = 10


def generate_session_id() -> str:
    """Generate cryptographically secure session ID (256-bit)"""
    return secrets.token_hex(32)  # 256 bits


def calculate_expiry(absolute_minutes: int = ABSOLUTE_TIMEOUT_MINUTES,
                     idle_minutes: int = IDLE_TIMEOUT_MINUTES) -> tuple:
    """Calculate absolute and idle expiry times"""
    now = datetime.utcnow()
    absolute = now + timedelta(minutes=absolute_minutes)
    idle = now + timedelta(minutes=idle_minutes)
    return absolute, idle


def refresh_idle_deadline(idle_minutes: int = IDLE_TIMEOUT_MINUTES,
                          now: Optional[datetime] = None) -> datetime:
    """New idle deadline for an active session; the absolute cap is unaffected."""
    now = now or datetime.utcnow()
    return now + timedelta(minutes=idle_minutes)


def is_expired(expires_at: datetime, now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.utcnow()
    return now >= expires_at


def is_idle_expired(idle_expires_at: datetime, now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.utcnow()
    return now >= idle_expires_at
