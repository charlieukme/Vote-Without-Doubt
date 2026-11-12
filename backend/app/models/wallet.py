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
    Wallet authentication challenge (identity plane).

    Binds the signed message to everything that makes it single-purpose and
    single-use: the user, the server-side session it was issued to, the
    purpose, the election, the chain and contract context, and an attempt
    counter. A challenge is only usable by the exact (session, user, purpose)
    triple that created it, before it expires, before the attempt budget is
    exhausted, and exactly once.
    """
    __tablename__ = 'wallet_challenges'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    challenge_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_id = db.Column(db.String(64), nullable=True, index=True)
    nonce = db.Column(db.String(128), nullable=False, unique=True)
    purpose = db.Column(db.String(50), default='WALLET_AUTHENTICATION', nullable=False,
                        index=True)
    election_id = db.Column(db.String(64), nullable=True)
    chain_id = db.Column(db.Integer, nullable=True)
    contract_address = db.Column(db.String(42), nullable=True)
    message = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=5, nullable=False)
    wallet_address = db.Column(db.String(42), nullable=True)
    signature = db.Column(db.Text, nullable=True)

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def __repr__(self):
        return f"<WalletChallenge nonce={self.nonce[:8]} used={self.used}>"
