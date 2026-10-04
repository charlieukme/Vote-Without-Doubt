from datetime import datetime, timedelta
from app.extensions import db
from app.models import BallotRecord as Ballot, ReconciliationIssue


class RecoveryService:
    @staticmethod
    def startup_recover():
        ballots = Ballot.query.filter(Ballot.state.in_(['QUEUED', 'SUBMITTED'])).all()
        for b in ballots:
            if b.state == 'QUEUED' and b.reconcile_required is False:
                b.reconcile_required = True
                b.reconcile_reason = 'UNFINISHED_QUEUED'
        db.session.commit()
        return len(ballots)

    @staticmethod
    def record_mismatch(election_id, issue_type, severity='INFO', observed=None, expected=None):
        ri = ReconciliationIssue(
            election_id=election_id,
            issue_type=issue_type,
            severity=severity,
            observed_state=str(observed) if observed is not None else None,
            expected_state=str(expected) if expected is not None else None,
            status='OPEN'
        )
        db.session.add(ri)
        db.session.commit()
        return ri

    @staticmethod
    def is_idempotent_ok():
        return True
