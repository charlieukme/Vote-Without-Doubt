"""
Auth Service - Phase 2
"""

from datetime import datetime, timedelta
from typing import Optional

from flask import session, current_app
from app.extensions import db
from app.models import User, OTP, AuthSession
from app.security.password import hash_password, verify_password
from app.security.otp import generate_otp, hash_otp, verify_otp
from app.security.sessions import generate_session_id, calculate_expiry, is_expired, is_idle_expired
from app.email.service import EmailService


class AuthService:
    def __init__(self):
        self.email_service = EmailService()
    
    def register_user(self, username: str, email: str, password: str, voter_id: Optional[str] = None) -> User:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            voter_id=voter_id
        )
        db.session.add(user)
        db.session.commit()
        return user
    
    def authenticate(self, username: str, password: str, ip_address: str = None, user_agent: str = None):
        user = User.query.filter_by(username=username, is_active=True).first()
        if not user:
            return False, None, "Invalid credentials"
        if user.locked_until and user.locked_until > datetime.utcnow():
            return False, None, "Invalid credentials"
        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=15)
            db.session.commit()
            return False, None, "Invalid credentials"
        user.failed_login_attempts = 0
        user.locked_until = None
        session_id = generate_session_id()
        abs_exp, idle_exp = calculate_expiry()
        auth_session = AuthSession(
            session_id=session_id,
            user_id=user.id,
            auth_state='PENDING_FACTORS',
            expires_at=abs_exp,
            idle_expires_at=idle_exp,
            last_activity=datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(auth_session)
        db.session.commit()
        session['session_id'] = session_id
        return True, auth_session, "Authentication started"
    
    def get_session(self, session_id: str):
        if not session_id:
            return None
        s = AuthSession.query.filter_by(session_id=session_id).first()
        if not s:
            return None
        if is_expired(s.expires_at) or is_idle_expired(s.idle_expires_at):
            s.revoked = True
            db.session.commit()
            return None
        s.last_activity = datetime.utcnow()
        db.session.commit()
        return s
