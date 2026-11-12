"""
Electoral Roll Models - Phase 3 (remediated)
Vote Without Doubt - Backend
Identity Plane
"""

from app.extensions import db
from app.models.base import BaseModel

#: Purpose persisted with every registration OTP so it can never be confused
#: with a login OTP (or any future purpose).
REGISTRATION_OTP_PURPOSE = 'registration_email_verification'

#: Registration lifecycle states.
REG_PENDING = 'PENDING'
REG_EMAIL_VERIFIED = 'EMAIL_VERIFIED'
REG_REGISTERED = 'REGISTERED'


class ElectoralRoll(BaseModel):
    """
    Electoral Roll - authoritative list of eligible voters (identity plane).

    Integrity is provided by :class:`RollImportBatch`, which stores a canonical
    SHA-256 digest of the applied roll. The digest is order-independent and
    changes whenever any meaningful field changes.
    """
    __tablename__ = 'electoral_roll'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    usn = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    college_email = db.Column(db.String(255), nullable=False, index=True)
    is_eligible = db.Column(db.Boolean, default=True, nullable=False)
    department = db.Column(db.String(100), nullable=True)
    year_of_study = db.Column(db.Integer, nullable=True)
    import_batch = db.Column(db.String(64), nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ElectoralRoll usn={self.usn} eligible={self.is_eligible}>"


class RollImportBatch(BaseModel):
    """
    Provenance record for one electoral-roll import.

    Supports the dry-run / approval-apply boundary: a batch is first created
    with ``status='DRY_RUN'`` (nothing written to the roll), then explicitly
    applied. ``roll_digest`` is a canonical SHA-256 over the imported rows, so a
    later auditor can recompute it and detect tampering.
    """
    __tablename__ = 'electoral_roll_imports'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    batch_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default='DRY_RUN', nullable=False, index=True)
    roll_digest = db.Column(db.String(64), nullable=False)
    row_count = db.Column(db.Integer, default=0, nullable=False)
    source_filename = db.Column(db.String(255), nullable=True)
    error_count = db.Column(db.Integer, default=0, nullable=False)
    applied_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<RollImportBatch {self.batch_id} {self.status} rows={self.row_count}>"


class RegistrationSession(BaseModel):
    """
    Short-lived registration session (identity plane).

    Deliberately separate from :class:`~app.models.auth_session.AuthSession`:
    it is stored under its own ``reg_session`` key and never authenticates a
    login session. ``purpose`` is persisted on every issued OTP so the code
    cannot be replayed against a different flow.
    """
    __tablename__ = 'registration_sessions'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    session_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    usn = db.Column(db.String(50), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(30), default=REG_PENDING, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    otp_hash = db.Column(db.String(64), nullable=True)
    otp_purpose = db.Column(db.String(64), nullable=True)
    otp_expires_at = db.Column(db.DateTime, nullable=True)
    otp_attempts = db.Column(db.Integer, default=0, nullable=False)
    otp_max_attempts = db.Column(db.Integer, default=5, nullable=False)
    otp_used = db.Column(db.Boolean, default=False, nullable=False)
    otp_consumed_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<RegistrationSession usn={self.usn} state={self.state}>"
