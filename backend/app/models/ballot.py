"""
Ballot Plane Models - Phase 1 Foundation
Vote Without Doubt - Backend

BALLOT PLANE: Contains pseudonymous ballot info, ballot state, blockchain state.
STRICTLY SEPARATED from Identity Plane - NO direct FK to identity tables.

Privacy by design: No voter identity + candidate choice linkage via FKs.
"""

from app.extensions import db
from app.models.base import BaseModel


class Ballot(BaseModel):
    """
    BALLOT PLANE: Ballot record (pseudonymous)
    Foundation structure - pseudonym/keys added in later phases
    """
    __tablename__ = 'ballots'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    # Pseudonymous identifiers (foundation - full pseudonym system in later phases)
    ballot_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    election_id = db.Column(db.String(50), nullable=False, index=True)
    
    # Ballot state
    ballot_state = db.Column(db.String(50), default='QUEUED', nullable=False, index=True)
    ballot_sequence = db.Column(db.Integer, nullable=True)
    max_ballots_allowed = db.Column(db.Integer, default=3)
    ballot_attempt = db.Column(db.Integer, default=1)
    
    # Blockchain state (foundation)
    blockchain_tx_hash = db.Column(db.String(66), nullable=True, index=True)
    blockchain_block_number = db.Column(db.BigInteger, nullable=True)
    blockchain_status = db.Column(db.String(50), nullable=True)
    
    # Privacy: No voter identity, no direct candidate reference in full form yet
    # Candidate choice never stored with identifying info
    status = db.Column(db.String(50), default='active', nullable=False)
    
    def __repr__(self):
        return f"<Ballot ballot_id={self.ballot_id} state={self.ballot_state}>"


class Election(BaseModel):
    """
    BALLOT PLANE: Election record
    Foundation structure
    """
    __tablename__ = 'elections'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    election_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='DRAFT', nullable=False, index=True)
    
    # Timing (foundation)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Election election_id={self.election_id} status={self.status}>"
