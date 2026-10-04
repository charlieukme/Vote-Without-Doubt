"""
Session Models - Phase 2
"""

from app.extensions import db
from app.models.base import BaseModel


class AuthSession(BaseModel):
    """
    Server-side session for authentication
    """
    __tablename__ = 'auth_sessions'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    session_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    auth_state = db.Column(db.String(30), default='PENDING_FACTORS', nullable=False)
    authenticated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    idle_expires_at = db.Column(db.DateTime, nullable=False)
    last_activity = db.Column(db.DateTime, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    
    def __repr__(self):
        return f"<AuthSession session_id={self.session_id} state={self.auth_state}>"
