"""
Authentication Models - Phase 2
Identity Plane
"""

from app.extensions import db
from app.models.base import BaseModel


class User(BaseModel):
    """
    User account for authentication (Identity Plane)
    """
    __tablename__ = 'users'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)  # Argon2id
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    
    # Link to voter identity (identity plane). Unique so a single electoral-roll
    # USN can never back two accounts, even under a concurrent race.
    voter_id = db.Column(db.String(50), nullable=True, unique=True, index=True)
    
    def __repr__(self):
        return f"<User username={self.username}>"


class OTP(BaseModel):
    """
    OTP for authentication (Identity Plane)
    Raw OTP never stored; only hashed with pepper
    """
    __tablename__ = 'otps'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    purpose = db.Column(db.String(50), nullable=False)  # login, etc
    otp_hash = db.Column(db.String(64), nullable=False)  # HMAC-SHA256
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=5, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    session_id = db.Column(db.String(64), nullable=True, index=True)
    
    def __repr__(self):
        return f"<OTP user_id={self.user_id} purpose={self.purpose} used={self.used}>"
