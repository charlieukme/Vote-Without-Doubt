"""
Admin & Governance Models - Phase 11
Vote Without Doubt - Backend
"""

from datetime import datetime, timedelta
from app.extensions import db


class AdminUser(db.Model):
    """
    Administrative user with RBAC (OFFICER or AUDITOR)
    and mandatory password + TOTP authentication.
    """
    __tablename__ = 'admin_users'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # Argon2id
    role = db.Column(db.String(20), nullable=False, default='OFFICER', index=True)  # OFFICER, AUDITOR
    totp_secret_encrypted = db.Column(db.LargeBinary, nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_totp_step = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > datetime.utcnow()

    def to_dict(self) -> dict:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self):
        return f"<AdminUser admin_id={self.admin_id} role={self.role}>"


class AdminSession(db.Model):
    """
    Server-side administrative session.
    Cryptographically random session token, strict expiry, and revocation support.
    """
    __tablename__ = 'admin_sessions'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), unique=True, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    admin = db.relationship('AdminUser', backref=db.backref('sessions', lazy=True))

    def is_valid(self) -> bool:
        return not self.revoked and self.expires_at > datetime.utcnow()

    def to_dict(self) -> dict:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self):
        return f"<AdminSession admin_id={self.admin_id} role={self.role} valid={self.is_valid()}>"


class ApprovalRequest(db.Model):
    """
    Two-Officer Approval (Four-Eyes Principle) record.
    Binds critical election operations to exact parameters and distinct officers.
    """
    __tablename__ = 'approval_requests'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.String(50), nullable=False, index=True)
    action_type = db.Column(db.String(50), nullable=False, index=True)
    payload_hash = db.Column(db.String(64), nullable=False)  # SHA-256 of canonical parameters
    payload_json = db.Column(db.Text, nullable=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False, index=True)
    approver_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True, index=True)
    status = db.Column(db.String(20), default='PENDING', nullable=False, index=True)  # PENDING, APPROVED, REJECTED, EXPIRED, INVALIDATED
    rejection_reason = db.Column(db.String(255), nullable=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    requester = db.relationship('AdminUser', foreign_keys=[requester_id], backref=db.backref('requested_approvals', lazy=True))
    approver = db.relationship('AdminUser', foreign_keys=[approver_id], backref=db.backref('granted_approvals', lazy=True))

    def is_pending(self) -> bool:
        if self.status != 'PENDING':
            return False
        if self.expires_at <= datetime.utcnow():
            return False
        return True

    def to_dict(self) -> dict:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self):
        return f"<ApprovalRequest id={self.id} election={self.election_id} action={self.action_type} status={self.status}>"


class Candidate(db.Model):
    """
    Ballot option / candidate configured for an election.
    Immutable once the election is SCHEDULED.
    """
    __tablename__ = 'candidates'
    __table_args__ = (
        db.UniqueConstraint('election_id', 'candidate_index', name='uq_candidate_election_index'),
        {'mysql_engine': 'InnoDB'}
    )

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.String(50), nullable=False, index=True)
    candidate_index = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=True)
    position = db.Column(db.String(100), nullable=True)
    year = db.Column(db.String(20), nullable=True)
    slogan = db.Column(db.String(255), nullable=True)
    manifesto = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self):
        return f"<Candidate election={self.election_id} idx={self.candidate_index} name={self.name}>"


class SupportTicket(db.Model):
    """
    Voter dispute / support ticket logged by the public or voter.
    Strictly forbids storing candidate choice, ballot ID, private keys, or passwords.
    """
    __tablename__ = 'support_tickets'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=False)
    contact_email = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='OPEN', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'reference_id': self.reference_id,
            'category': self.category,
            'details': self.details,
            'status': self.status,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
        }

    def __repr__(self):
        return f"<SupportTicket ref={self.reference_id} cat={self.category} status={self.status}>"
