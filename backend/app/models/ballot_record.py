"""
Ballot Plane Models - Phase 7/8
Strict identity/ballot separation
"""

from app.extensions import db
from app.models.base import BaseModel


class BallotQueue(BaseModel):
    """
    Ballot record (ballot plane) - NO identity FKs
    """
    __tablename__ = 'ballot_queue'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}
    
    election_id = db.Column(db.Integer, nullable=False, index=True)
    pseudonym = db.Column(db.String(128), nullable=False, index=True)
    candidate = db.Column(db.Integer, nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=1)
    state = db.Column(db.String(30), nullable=False, default='QUEUED')
    tx_hash = db.Column(db.String(128), nullable=True)
    block_number = db.Column(db.Integer, nullable=True)
    receipt_code = db.Column(db.String(64), nullable=True)
    error = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f"<BallotQueue election={self.election_id} state={self.state}>"

class VotingAuthorization(BaseModel):
    __tablename__ = 'voting_authorizations'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    election_id = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.String(64), nullable=True)
    wallet_verified = db.Column(db.Boolean, default=False)
    face_verified = db.Column(db.Boolean, default=False)
    authorized = db.Column(db.Boolean, default=False)
    consumed = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    authorized_at = db.Column(db.DateTime, nullable=True)
    consumed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<VotingAuth user={self.user_id} elect={self.election_id}>'

# Recovery extensions
    tx_broadcast_at = db.Column(db.DateTime, nullable=True)
    tx_confirmed_at = db.Column(db.DateTime, nullable=True)
    tx_failed_at = db.Column(db.DateTime, nullable=True)
    last_retry_at = db.Column(db.DateTime, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    reconcile_required = db.Column(db.Boolean, default=False)
    reconcile_reason = db.Column(db.String(255), nullable=True)
    superseded = db.Column(db.Boolean, default=False)
