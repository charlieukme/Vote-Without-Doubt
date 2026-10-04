"""
Face Biometric Models - Phase 5
Identity Plane
"""

from app.extensions import db
from app.models.base import BaseModel


class FaceEnrollment(BaseModel):
    """
    Face enrollment with encrypted embedding
    """
    __tablename__ = 'face_enrollments'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True, unique=True)
    encrypted_embedding = db.Column(db.LargeBinary, nullable=False)
    embedding_method = db.Column(db.String(50), default='face_recognition', nullable=False)
    is_enrolled = db.Column(db.Boolean, default=True, nullable=False)
    consent_given = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<FaceEnrollment user_id={self.user_id} enrolled={self.is_enrolled}>"


class FaceChallenge(BaseModel):
    """
    Face/liveness challenge
    """
    __tablename__ = 'face_challenges'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}
    
    challenge_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    challenge_type = db.Column(db.String(30), default='LIVENESS', nullable=False)
    challenge_sequence = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<FaceChallenge user_id={self.user_id} type={self.challenge_type}>"


