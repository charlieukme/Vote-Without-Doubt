"""
Wallet Authentication Models - Phase 4
Identity Plane
"""

from app.extensions import db
from app.models.base import BaseModel


class WalletBinding(BaseModel):
    """
    Wallet binding to user (after signature verification)
    """
    __tablename__ = 'wallet_bindings'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True, unique=True)
    wallet_address = db.Column(db.String(42), nullable=False, unique=True, index=True)
    is_verified = db.Column(db.Boolean, default=True, nullable=False)
    binding_method = db.Column(db.String(50), default='signature', nullable=False)
    
    def __repr__(self):
        return f"<WalletBinding user_id={self.user_id} wallet={self.wallet_address}>"


class WalletChallenge(BaseModel):
    """
    Wallet auth challenge/nonce
    """
    __tablename__ = 'wallet_challenges'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    challenge_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    nonce = db.Column(db.String(128), nullable=False, unique=True)
    purpose = db.Column(db.String(50), default='WALLET_AUTHENTICATION', nullable=False)
    message = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    wallet_address = db.Column(db.String(42), nullable=True)
    signature = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f"<WalletChallenge nonce={self.nonce} used={self.used}>"
