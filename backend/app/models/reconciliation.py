from app.extensions import db
from app.models.base import BaseModel


class ReconciliationIssue(BaseModel):
    __tablename__ = 'reconciliation_issues'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}

    election_id = db.Column(db.Integer, nullable=False, index=True)
    issue_type = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(50), nullable=False, default='INFO')
    # DB-001 Fix: protocol_version discriminates queue references across protocols:
    # 'V1' for ballot_queue.id, 'V2' for ballot_queue_v2.id.
    # Removed invalid historical foreign key to baseline 'ballots.id' table.
    protocol_version = db.Column(db.String(10), nullable=False, default='V1', server_default='V1')
    ballot_tx_id = db.Column(db.Integer, nullable=True)
    observed_state = db.Column(db.Text, nullable=True)
    expected_state = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='OPEN')
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)

    def get_referenced_ballot(self):
        """Resolves the referenced queue record according to protocol_version."""
        if not self.ballot_tx_id:
            return None
        if self.protocol_version == 'V2':
            from app.models.ballot_record_v2 import BallotQueueV2
            return db.session.get(BallotQueueV2, self.ballot_tx_id)
        from app.models import BallotRecord
        return db.session.get(BallotRecord, self.ballot_tx_id)

    def __repr__(self):
        return f'<Recon {self.protocol_version}:{self.issue_type}:{self.status}>'
