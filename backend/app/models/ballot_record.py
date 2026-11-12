"""
Ballot Plane Models - Phase 7/8/10
Strict identity/ballot separation

Phase 1 remediation note
------------------------
The eight recovery/relay columns were previously indented into
:class:`VotingAuthorization`, which put ballot-relay and reconciliation state
on an identity-bearing authorization record and left ``schema.sql`` out of sync
with the ORM. They are declared here, on :class:`BallotQueue`, which is the
table the Phase 10 DDL actually alters. No recovery or reconciliation
*behaviour* is implemented - this is a structural correction only.

Separation invariant preserved: neither model declares a voter-identity
foreign key pointing at the ballot plane, and :class:`BallotQueue` has no
identity column at all.
"""

from app.extensions import db
from app.models.base import BaseModel


class BallotQueue(BaseModel):
    """
    Ballot record (ballot plane) - NO identity FKs.

    ``candidate`` is an election-local integer index. It is stored here because
    the plaintext choice never leaves the trusted backend until finalization,
    where it is deleted; it is never written to the blockchain, a receipt, a log
    or a notification.
    """
    __tablename__ = 'ballot_queue'
    __table_args__ = (
        db.UniqueConstraint('election_id', 'pseudonym', 'sequence', name='uq_ballot_queue_election_pseudonym_seq'),
        {'mysql_engine': 'InnoDB', 'extend_existing': True}
    )

    election_id = db.Column(db.Integer, nullable=False, index=True)
    pseudonym = db.Column(db.String(128), nullable=False, index=True)
    candidate = db.Column(db.Integer, nullable=False, default=0)
    sequence = db.Column(db.Integer, nullable=False, default=1)
    is_null = db.Column(db.Boolean, nullable=False, default=False)
    state = db.Column(db.String(30), nullable=False, default='QUEUED')
    tx_hash = db.Column(db.String(128), nullable=True)
    block_number = db.Column(db.Integer, nullable=True)
    receipt_code = db.Column(db.String(64), nullable=True)
    error = db.Column(db.Text, nullable=True)

    # Recovery / relay extensions (Phase 10 DDL ALTERs these onto this table).
    tx_broadcast_at = db.Column(db.DateTime, nullable=True)
    tx_confirmed_at = db.Column(db.DateTime, nullable=True)
    tx_failed_at = db.Column(db.DateTime, nullable=True)
    last_retry_at = db.Column(db.DateTime, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    reconcile_required = db.Column(db.Boolean, default=False)
    reconcile_reason = db.Column(db.String(255), nullable=True)
    superseded = db.Column(db.Boolean, default=False)

    # Privacy-Preserving Merkle Tree Ballot Commitments
    commitment = db.Column(db.String(64), nullable=True, index=True)
    commitment_nonce = db.Column(db.String(64), nullable=True)

    def __repr__(self):
        return f"<BallotQueue election={self.election_id} state={self.state}>"


class VotingAuthorization(BaseModel):
    """
    Identity-plane authorization record.

    Consumed once and never replayable. Holds no ballot content: it says a voter
    was authorized for an election, not what they chose.
    """
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