"""
Ballot Plane Models for FIX 3 V2 - Isolated from V1.
Preserves strict identity/ballot separation.
Contains no voter identity, no plaintext candidate index, and no unencrypted choice data.
"""

import hashlib
import hmac
import os
from typing import Any, List, Optional

from app.extensions import db
from app.models.base import BaseModel

VALID_V2_FINAL_STATES = ('CONFIRMED', 'FINALIZED')
IN_FLIGHT_V2_STATES = ('QUEUED', 'SUBMITTED', 'PENDING', 'UNCERTAIN')
FAILED_V2_STATES = ('FAILED', 'REVERTED')


class BallotQueueV2(BaseModel):
    """
    V2 Encrypted Ballot record (ballot plane) - NO identity FKs, NO plaintext candidate choices.
    Stores ElGamal ciphertext vector and non-circular CDS zero-knowledge validity proof.
    """
    __tablename__ = 'ballot_queue_v2'
    __table_args__ = (
        db.UniqueConstraint('election_id', 'pseudonym', 'sequence', name='uq_ballot_queue_v2_election_pseudonym_seq'),
        {'mysql_engine': 'InnoDB', 'extend_existing': True}
    )

    election_id = db.Column(db.Integer, nullable=False, index=True)
    pseudonym = db.Column(db.String(128), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False, default=1)
    
    # Encrypted Choice Vectors & Non-Circular CDS Proof (JSON serialized)
    ciphertexts_json = db.Column(db.Text, nullable=False)
    proof_json = db.Column(db.Text, nullable=False)

    state = db.Column(db.String(30), nullable=False, default='QUEUED')
    tx_hash = db.Column(db.String(128), nullable=True)
    block_number = db.Column(db.Integer, nullable=True)
    receipt_code = db.Column(db.String(64), nullable=True)
    error = db.Column(db.Text, nullable=True)

    tx_broadcast_at = db.Column(db.DateTime, nullable=True)
    tx_confirmed_at = db.Column(db.DateTime, nullable=True)
    tx_failed_at = db.Column(db.DateTime, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    superseded = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<BallotQueueV2 election={self.election_id} pseudo={self.pseudonym[:10]} seq={self.sequence} state={self.state}>"


class OfficerRegistrationV2(BaseModel):
    """
    Officer Key Registration record for FIX 3 V2.
    Stores officer public key share and Schnorr PoP.
    Private shares are NEVER stored in the database or transmitted to backend.
    """
    __tablename__ = 'officer_registrations_v2'
    __table_args__ = (
        db.UniqueConstraint('election_id', 'officer_id', name='uq_officer_v2_election_id'),
        {'mysql_engine': 'InnoDB', 'extend_existing': True}
    )

    election_id = db.Column(db.Integer, nullable=False, index=True)
    officer_id = db.Column(db.Integer, nullable=False)  # 1 or 2
    officer_address = db.Column(db.String(64), nullable=False)
    
    # Public Key Y_i = (x, y)
    pubkey_x = db.Column(db.String(100), nullable=False)
    pubkey_y = db.Column(db.String(100), nullable=False)

    # Schnorr PoP: R = (x, y), z
    pop_r_x = db.Column(db.String(100), nullable=False)
    pop_r_y = db.Column(db.String(100), nullable=False)
    pop_z = db.Column(db.String(100), nullable=False)

    registered_on_chain = db.Column(db.Boolean, default=False)
    tx_hash = db.Column(db.String(128), nullable=True)

    def __repr__(self):
        return f"<OfficerRegV2 election={self.election_id} officer={self.officer_id} registered={self.registered_on_chain}>"


def compute_v2_ballot_leaf_hash(ballot: BallotQueueV2) -> str:
    """Compute canonical SHA-256 leaf digest for a V2 ballot record."""
    return hashlib.sha256(
        f"{ballot.election_id}:{ballot.sequence}:{ballot.receipt_code or ''}:{ballot.tx_hash or ''}:{ballot.ciphertexts_json}".encode('utf-8')
    ).hexdigest()


def ensure_v2_receipt_code(ballot: BallotQueueV2, commit: bool = False) -> Optional[str]:
    """Generate and attach deterministic HMAC receipt_code for a confirmed V2 ballot if missing."""
    if not ballot or ballot.state not in VALID_V2_FINAL_STATES:
        return None
    if ballot.receipt_code:
        return ballot.receipt_code

    secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY') or 'default_receipt_secret_key'
    ref_dt = ballot.tx_confirmed_at or ballot.created_at
    ts_str = ref_dt.strftime('%Y-%m-%dT%H:%M:00Z') if ref_dt else '1970-01-01T00:00:00Z'
    if getattr(ballot, 'sequence', 1) and int(ballot.sequence) > 1:
        msg = f"{ballot.election_id}|{ballot.pseudonym}|{int(ballot.sequence)}|{ts_str}"
    else:
        msg = f"{ballot.election_id}|{ballot.pseudonym}|{ts_str}"
    raw_code = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].upper()
    ballot.receipt_code = f"REC-{ballot.election_id}-{raw_code}"
    if commit:
        db.session.commit()
    return ballot.receipt_code


def mark_prior_v2_ballots_superseded(
    election_id: int,
    pseudonym: str,
    confirmed_sequence: int,
) -> int:
    """Mark all earlier confirmed/finalized V2 ballots for this voter in this election as superseded."""
    updated = BallotQueueV2.query.filter(
        BallotQueueV2.election_id == int(election_id),
        BallotQueueV2.pseudonym == str(pseudonym),
        BallotQueueV2.sequence < int(confirmed_sequence),
        BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
        BallotQueueV2.superseded.is_(False),
    ).update({'superseded': True}, synchronize_session='fetch')
    return int(updated or 0)


def get_latest_confirmed_v2_ballot(
    election_id: Any,
    pseudonym: str,
    eid_candidates: Optional[List[Any]] = None,
) -> Optional[BallotQueueV2]:
    """
    Authoritative rule: return the highest-sequence confirmed/finalized V2 ballot
    that is not superseded (falling back to highest-sequence confirmed if historical
    rows were left unmarked).
    """
    eids = eid_candidates or [int(election_id)]
    active = BallotQueueV2.query.filter(
        BallotQueueV2.election_id.in_(eids),
        BallotQueueV2.pseudonym == str(pseudonym),
        BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
        BallotQueueV2.superseded.is_(False),
    ).order_by(BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()).first()
    if active:
        return active
    return BallotQueueV2.query.filter(
        BallotQueueV2.election_id.in_(eids),
        BallotQueueV2.pseudonym == str(pseudonym),
        BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
    ).order_by(BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()).first()


def get_latest_v2_attempt(
    election_id: Any,
    pseudonym: str,
    eid_candidates: Optional[List[Any]] = None,
) -> Optional[BallotQueueV2]:
    """Return the most recent V2 submission attempt across all states (by sequence desc, id desc)."""
    eids = eid_candidates or [int(election_id)]
    return BallotQueueV2.query.filter(
        BallotQueueV2.election_id.in_(eids),
        BallotQueueV2.pseudonym == str(pseudonym),
    ).order_by(BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()).first()


def get_active_v2_election_ballots(election_id: int) -> List[BallotQueueV2]:
    """
    Return the authoritative set of active, non-superseded confirmed V2 ballots for an election,
    guaranteed to contain at most one latest confirmed ballot per voter pseudonym.
    """
    rows = BallotQueueV2.query.filter(
        BallotQueueV2.election_id == int(election_id),
        BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
        BallotQueueV2.superseded.is_(False),
    ).order_by(BallotQueueV2.sequence.asc(), BallotQueueV2.id.asc()).all()

    latest_by_pseudo = {}
    for b in rows:
        prev = latest_by_pseudo.get(b.pseudonym)
        if prev is None or (b.sequence, b.id) > (prev.sequence, prev.id):
            latest_by_pseudo[b.pseudonym] = b

    return sorted(latest_by_pseudo.values(), key=lambda b: b.id)


def is_v2_election(election: Any) -> bool:
    """
    Authoritatively determine whether an election uses the V2 threshold ElGamal protocol.
    Checks explicit persisted protocol_version, V2 deployment checkpoint, provisioning state,
    election-level officer keys, OfficerRegistrationV2, or BallotQueueV2 rows.
    """
    if not election:
        return False
    protocol = (getattr(election, 'protocol_version', None) or '').strip().upper()
    if protocol == 'V2':
        return True
    from app.services.blockchain_v2_service import load_deployment_checkpoint, load_provisioning_state
    if load_deployment_checkpoint(election.id):
        return True
    if load_provisioning_state(election.id):
        return True
    if getattr(election, 'v2_priv_key_1', None) or getattr(election, 'v2_priv_key_2', None):
        return True
    target_ids = [election.id, str(election.id)]
    if getattr(election, 'election_id', None):
        target_ids.append(str(election.election_id))
    if OfficerRegistrationV2.query.filter(OfficerRegistrationV2.election_id.in_(target_ids)).first():
        return True
    if BallotQueueV2.query.filter(BallotQueueV2.election_id.in_(target_ids)).first():
        return True
    return False
