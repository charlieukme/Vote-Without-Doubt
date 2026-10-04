from app.extensions import db
from app.models.base import BaseModel


class ReconciliationIssue(BaseModel):
    __tablename__ = 'reconciliation_issues'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}

    election_id = db.Column(db.Integer, nullable=False, index=True)
    issue_type = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(50), nullable=False, default='INFO')
    ballot_tx_id = db.Column(db.Integer, db.ForeignKey('ballots.id'), nullable=True)
    observed_state = db.Column(db.Text, nullable=True)
    expected_state = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='OPEN')
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Recon {self.issue_type}:{self.status}>'
