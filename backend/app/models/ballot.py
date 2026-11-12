"""
Ballot Plane Models - Phase 1 Foundation
Vote Without Doubt - Backend

BALLOT PLANE: Contains pseudonymous ballot info, ballot state, blockchain state.
STRICTLY SEPARATED from Identity Plane - NO direct FK to identity tables.

Privacy by design: No voter identity + candidate choice linkage via FKs.
"""

from datetime import datetime

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
    registration_deadline = db.Column(db.DateTime, nullable=True)

    # Phase 11 Governance & Lifecycle attributes
    candidate_count = db.Column(db.Integer, default=0, nullable=False)
    eligible_count = db.Column(db.Integer, default=0, nullable=False)
    roll_hash = db.Column(db.String(66), nullable=True)
    candidates_hash = db.Column(db.String(66), nullable=True)
    max_ballots = db.Column(db.Integer, default=3, nullable=False)
    cancelled = db.Column(db.Boolean, default=False, nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    finalized_at = db.Column(db.DateTime, nullable=True)
    created_by_officer_id = db.Column(db.Integer, nullable=True)
    approved_by_officer_id = db.Column(db.Integer, nullable=True)

    # Merkle Root & Archival Lifecycle
    merkle_root = db.Column(db.String(66), nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    # Automated V2 Homomorphic Key Storage (Encrypted at rest)
    v2_priv_key_1 = db.Column(db.Text, nullable=True)
    v2_priv_key_2 = db.Column(db.Text, nullable=True)
    protocol_version = db.Column(db.String(10), nullable=True)
    
    @property
    def effective_status(self) -> str:
        """
        Authoritative lifecycle status:
        - If stored status is OPEN or ACTIVE:
          - If end_time has passed (now >= end_time): effectively CLOSED.
          - Otherwise: OPEN / ACTIVE.
        - If stored status is SCHEDULED:
          - If end_time has passed (now >= end_time): effectively CLOSED.
          - If start_time has arrived (now >= start_time): effectively OPEN.
          - Otherwise (now < start_time): SCHEDULED.
        - Otherwise: stored status (DRAFT, PENDING_APPROVAL, CLOSED, FINALIZED, CANCELLED).
        """
        now = datetime.utcnow()
        if self.status in ('OPEN', 'ACTIVE'):
            if self.end_time and now >= self.end_time:
                return 'CLOSED'
            return self.status

        if self.status == 'SCHEDULED':
            if self.end_time and now >= self.end_time:
                return 'CLOSED'
            if self.start_time and now >= self.start_time:
                return 'OPEN'
            return 'SCHEDULED'

        return self.status

    def __repr__(self):
        return f"<Election election_id={self.election_id} status={self.status}>"
