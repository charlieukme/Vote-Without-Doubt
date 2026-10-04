from datetime import datetime, timedelta
from app.extensions import db
from app.models import VotingAuthorization, BallotRecord as Ballot
from app.security.pseudonym import derive_pseudonym


class VotingService:
    @staticmethod
    def create_authorization(user_id: int, election_id: int, session_id: str = None, ttl_sec: int = 300):
        va = VotingAuthorization(
            user_id=user_id,
            election_id=election_id,
            session_id=session_id,
            expires_at=datetime.utcnow() + timedelta(seconds=ttl_sec),
            wallet_verified=False,
            face_verified=False,
            authorized=False,
            consumed=False
        )
        db.session.add(va)
        db.session.commit()
        return va
    
    @staticmethod
    def mark_factors(user_id: int, election_id: int, wallet_ok=True, face_ok=True):
        va = VotingAuthorization.query.filter_by(user_id=user_id, election_id=election_id, consumed=False).order_by(VotingAuthorization.id.desc()).first()
        if not va or va.expires_at < datetime.utcnow():
            return None
        va.wallet_verified = wallet_ok
        va.face_verified = face_ok
        if wallet_ok and face_ok:
            va.authorized = True
            va.authorized_at = datetime.utcnow()
        db.session.commit()
        return va
    
    @staticmethod
    def get_authorization(user_id: int, election_id: int):
        return VotingAuthorization.query.filter_by(user_id=user_id, election_id=election_id, consumed=False).order_by(VotingAuthorization.id.desc()).first()
    
    @staticmethod
    def submit_ballot(user_id: int, election_id: int, candidate: int, max_ballots: int = 3) -> tuple:
        va = VotingAuthorization.query.filter_by(user_id=user_id, election_id=election_id, consumed=False).order_by(VotingAuthorization.id.desc()).first()
        if not va or not va.authorized or va.consumed:
            return None, "UNAUTHORIZED"
        if va.expires_at < datetime.utcnow():
            return None, "EXPIRED"
        if va.wallet_verified is False or va.face_verified is False:
            return None, "FACTORS_MISSING"
        pseud = derive_pseudonym(user_id, election_id)
        latest = Ballot.query.filter_by(election_id=election_id, pseudonym=pseud).order_by(Ballot.id.desc()).first()
        if latest and latest.state == 'QUEUED':
            return latest, "DUPLICATE"
        seq = 1
        if latest:
            seq = (latest.sequence or 0) + 1
        if seq > max_ballots:
            return None, "MAX_BALLOTS_EXCEEDED"
        ballot = Ballot(election_id=election_id, pseudonym=pseud, candidate=candidate, sequence=seq, state='QUEUED')
        db.session.add(ballot)
        va.consumed = True
        va.consumed_at = datetime.utcnow()
        db.session.commit()
        return ballot, "OK"
    
    @staticmethod
    def list_queued():
        return Ballot.query.filter_by(state='QUEUED').order_by(Ballot.id.asc()).all()
    
    @staticmethod
    def update_ballot(ballot_id: int, **kwargs):
        b = Ballot.query.get(ballot_id)
        if not b:
            return None
        for k, v in kwargs.items():
            if hasattr(b, k):
                setattr(b, k, v)
        db.session.commit()
        return b
