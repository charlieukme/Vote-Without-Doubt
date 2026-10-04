"""
Electoral Roll Models - Phase 3
Identity Plane
"""

from app.extensions import db
from app.models.base import BaseModel


class ElectoralRoll(BaseModel):
    """
    Electoral Roll - authoritative list of eligible voters
    """
    __tablename__ = 'electoral_roll'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    usn = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    college_email = db.Column(db.String(255), nullable=False, index=True)
    is_eligible = db.Column(db.Boolean, default=True, nullable=False)
    department = db.Column(db.String(100), nullable=True)
    year_of_study = db.Column(db.Integer, nullable=True)
    import_batch = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f"<ElectoralRoll usn={self.usn} eligible={self.is_eligible}>"


class RegistrationSession(BaseModel):
    """
    Short-lived registration session
    """
    __tablename__ = 'registration_sessions'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    session_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    usn = db.Column(db.String(50), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(30), default='PENDING', nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    otp_hash = db.Column(db.String(64), nullable=True)
    otp_expires_at = db.Column(db.DateTime, nullable=True)
    otp_attempts = db.Column(db.Integer, default=0, nullable=False)
    otp_used = db.Column(db.Boolean, default=False, nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    def __repr__(self):
        return f"<RegistrationSession usn={self.usn} state={self.state}>"
