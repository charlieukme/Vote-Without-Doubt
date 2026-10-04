"""
Identity Plane Models - Phase 1 Foundation
Vote Without Doubt - Backend

IDENTITY PLANE: Contains voter identity, registration, eligibility, auth identity.
STRICT SEPARATION from Ballot Plane - no direct FK to ballot tables.

This is foundation structure only - full fields in later phases.
"""

from app.extensions import db
from app.models.base import BaseModel


class VoterIdentity(BaseModel):
    """
    IDENTITY PLANE: Voter identity/eligibility record
    Represents electoral roll entry
    """
    __tablename__ = 'voter_identities'
    __table_args__ = {'mysql_engine': 'InnoDB'}
    
    # Identity fields (foundation)
    voter_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), nullable=True)
    year_of_study = db.Column(db.Integer, nullable=True)
    is_eligible = db.Column(db.Boolean, default=True, nullable=False)
    is_registered = db.Column(db.Boolean, default=False, nullable=False)
    
    # Status tracking (foundation)
    status = db.Column(db.String(50), default='active', nullable=False)
    
    def __repr__(self):
        return f"<VoterIdentity voter_id={self.voter_id}>"
