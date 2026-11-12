"""
Face Biometric Models - Phase 5
Identity Plane

Schema notes (Phase 5 remediation):

* ``FaceChallenge`` is bound to ``user_id`` *and* ``session_id`` so a
  challenge issued to one authenticated session cannot be replayed from
  another. It also records ``attempt_count`` (attempts are enforced
  server-side) and an integrity MAC over its own server-authoritative
  fields, which detects tampering with the stored expected sequence.
* ``FaceEnrollment`` records the consent purpose and withdrawal state, plus
  the embedding provenance (model, version, dimension, key id) required to
  audit and rotate biometric templates.
"""

from app.extensions import db
from app.models.base import BaseModel


class FaceEnrollment(BaseModel):
    """Face template plus consent and provenance metadata."""

    __tablename__ = 'face_enrollments'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False,
                        index=True, unique=True)
    encrypted_embedding = db.Column(db.LargeBinary, nullable=False)
    embedding_method = db.Column(db.String(64), default='arcface', nullable=False)
    embedding_model = db.Column(db.String(64), default='buffalo_l/w600k_r50',
                                nullable=False)
    embedding_dim = db.Column(db.Integer, default=512, nullable=False)
    embedding_key_id = db.Column(db.String(32), default='v1', nullable=False)
    is_enrolled = db.Column(db.Boolean, default=True, nullable=False)
    consent_given = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime, nullable=True)
    consent_purpose = db.Column(db.String(64), default='election_verification',
                                nullable=False)
    withdrawn_at = db.Column(db.DateTime, nullable=True)
    template_deleted_at = db.Column(db.DateTime, nullable=True)

    def is_active(self) -> bool:
        """True only when a template exists, consent stands and it is not withdrawn."""
        return bool(
            self.is_enrolled
            and self.consent_given
            and self.withdrawn_at is None
            and self.template_deleted_at is None
            and self.encrypted_embedding
        )

    def __repr__(self):
        return f"<FaceEnrollment user_id={self.user_id} enrolled={self.is_enrolled}>"


class FaceChallenge(BaseModel):
    """Single-use, session-bound LEFT/RIGHT liveness challenge."""

    __tablename__ = 'face_challenges'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}

    challenge_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    challenge_type = db.Column(db.String(30), default='LIVENESS', nullable=False)
    challenge_sequence = db.Column(db.String(32), nullable=False)
    nonce = db.Column(db.String(64), nullable=False)
    integrity_mac = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempt_count = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Authorization and election binding (Phase B.1 remediation)
    authorization_id = db.Column(db.Integer, db.ForeignKey('voting_authorizations.id'), nullable=True, index=True)
    election_id = db.Column(db.Integer, nullable=True, index=True)
    consumed = db.Column(db.Boolean, default=False, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime, nullable=True)

    # Phase C.11I: Two-phase challenge lease primitives (isolated, nullable)
    lease_token = db.Column(db.String(64), nullable=True, index=True)
    lease_expires_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return (f"<FaceChallenge user_id={self.user_id} "
                f"type={self.challenge_type} completed={self.completed} "
                f"consumed={self.consumed} lease={bool(self.lease_token)}>")

