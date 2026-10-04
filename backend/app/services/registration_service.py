"""
Registration Service - Phase 3
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

from flask import session
from app.extensions import db
from app.models import ElectoralRoll, RegistrationSession, User
from app.security.otp import generate_otp, hash_otp, verify_otp
from app.email.service import EmailService


class RegistrationService:
    def __init__(self):
        self.email_service = EmailService()
    
    def import_roll(self, csv_rows: List[dict], batch_id: Optional[str] = None) -> Tuple[int, List[str]]:
        imported = 0
        errors = []
        if not batch_id:
            batch_id = secrets.token_hex(8)
        for r in csv_rows:
            try:
                if ElectoralRoll.query.filter_by(usn=r['usn']).first():
                    errors.append(f"USN already exists: {r['usn']}")
                    continue
                rec = ElectoralRoll(
                    usn=r['usn'],
                    full_name=r['name'],
                    college_email=r['email'],
                    is_eligible=True,
                    department=r.get('department'),
                    year_of_study=r.get('year'),
                    import_batch=batch_id
                )
                db.session.add(rec)
                imported += 1
            except Exception as e:
                errors.append(f"Failed to import {r['usn']}")
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            errors.append("Database commit failed")
            imported = 0
        return imported, errors
    
    def start_registration(self, usn: str) -> Tuple[bool, Optional[RegistrationSession], str]:
        roll = ElectoralRoll.query.filter_by(usn=usn, is_eligible=True).first()
        if not roll:
            return False, None, "Not eligible or not found"
        if User.query.filter_by(voter_id=usn).first():
            return False, None, "Already registered"
        sid = secrets.token_hex(32)
        rs = RegistrationSession(
            session_id=sid,
            usn=usn,
            email=roll.college_email,
            state='PENDING',
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        db.session.add(rs)
        db.session.commit()
        session['reg_session'] = sid
        return True, rs, "Registration started"
    
    def request_registration_otp(self, reg_sid: str) -> Tuple[bool, str]:
        rs = RegistrationSession.query.filter_by(session_id=reg_sid).first()
        if not rs or rs.state != 'PENDING':
            return False, "Invalid registration session"
        if rs.expires_at < datetime.utcnow():
            return False, "Session expired"
        otp = generate_otp()
        rs.otp_hash = hash_otp(otp)
        rs.otp_expires_at = datetime.utcnow() + timedelta(minutes=5)
        rs.otp_attempts = 0
        rs.otp_used = False
        db.session.commit()
        self.email_service.send_otp(rs.email, otp, 'registration')
        return True, "OTP sent"
    
    def verify_registration_otp(self, reg_sid: str, otp_code: str) -> Tuple[bool, str]:
        rs = RegistrationSession.query.filter_by(session_id=reg_sid).first()
        if not rs:
            return False, "Invalid session"
        if rs.otp_used or rs.email_verified:
            return False, "OTP already used"
        if rs.otp_expires_at is None or rs.otp_expires_at < datetime.utcnow():
            return False, "OTP expired"
        if rs.otp_attempts >= 5:
            return False, "Too many attempts"
        if not rs.otp_hash or not verify_otp(otp_code, rs.otp_hash):
            rs.otp_attempts += 1
            db.session.commit()
            return False, "Invalid OTP"
        rs.otp_used = True
        rs.email_verified = True
        rs.state = 'EMAIL_VERIFIED'
        db.session.commit()
        return True, "Email verified"
    
    def complete_registration(self, reg_sid: str, username: str, password: str) -> Tuple[bool, Optional[User], str]:
        rs = RegistrationSession.query.filter_by(session_id=reg_sid).first()
        if not rs or rs.state != 'EMAIL_VERIFIED' or not rs.email_verified:
            return False, None, "Email not verified"
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=rs.email).first() or User.query.filter_by(voter_id=rs.usn).first():
            return False, None, "User already exists"
        from app.security.password import hash_password
        user = User(
            username=username,
            email=rs.email,
            password_hash=hash_password(password),
            voter_id=rs.usn,
            is_verified=True,
            is_active=True
        )
        db.session.add(user)
        rs.state = 'REGISTERED'
        db.session.commit()
        if session.get('reg_session') == reg_sid:
            session.pop('reg_session', None)
        return True, user, "Registration complete"
