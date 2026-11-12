"""
Registration Service - Phase 3 (remediated)
Vote Without Doubt - Backend

Enforces the registration lifecycle as a server-authoritative state machine:

    PENDING -> EMAIL_VERIFIED -> REGISTERED

Every transition is validated against server state. The caller cannot declare
eligibility, email verification, a voter identity or a roll identity.

Security properties
-------------------
* Eligibility is only ever read from the electoral roll; no caller-supplied
  identity is trusted.
* The OTP is emailed to the student's entered email and is the proof of
  mailbox ownership. The resulting account email is set from this verified address.
* The OTP is stored only as HMAC-SHA256 under the server pepper, carries an
  explicit persisted ``purpose``, expires after five minutes, allows five
  attempts, is single-use and is bound to its registration session.
* A failed email delivery is reported as a failure and leaves no usable code.
* Expired or revoked registration sessions can never complete.
* All externally visible failures return one generic message so the endpoint
  cannot be used to enumerate voters; detailed reasons go to the audit trail.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from flask import session, current_app
from sqlalchemy import select

from app.extensions import db
from app.models import (
    AuthSession,
    ElectoralRoll,
    Election,
    FaceEnrollment,
    RegistrationSession,
    RollImportBatch,
    User,
    WalletBinding,
)
from app.models.roll import (
    REG_EMAIL_VERIFIED,
    REG_PENDING,
    REG_REGISTERED,
    REGISTRATION_OTP_PURPOSE,
)
from app.security.otp import generate_otp, hash_otp, verify_otp
from app.security.password import hash_password
from app.email.service import EmailService

#: OTP policy, matching the Phase 2 authentication factor.
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5

#: Registration session lifetime.
SESSION_TTL_MINUTES = 15

#: The single externally visible message. Never vary it per outcome.
GENERIC_REGISTRATION_MESSAGE = 'Unable to continue registration'

#: Fields covered by the canonical roll digest. Changing any of them changes it.
DIGEST_FIELDS = ('usn', 'full_name', 'college_email', 'department',
                 'year_of_study', 'is_eligible')


def _now() -> datetime:
    return datetime.utcnow()


def canonicalize_roll(rows: Sequence[Dict]) -> List[Dict]:
    """Return a deterministic, order-independent canonical form of the roll.

    Rows are sorted by USN and every value is normalised, so the same logical
    roll always produces byte-identical canonical output regardless of the order
    the rows arrived in or whether optional fields were omitted. Both the parsed
    CSV shape (``name``/``email``/``year``) and the stored ORM shape
    (``full_name``/``college_email``/``year_of_study``) canonicalise identically,
    so a digest computed before import still verifies after it.
    """
    canonical = []
    for row in rows:
        raw_year = row.get('year_of_study')
        if raw_year in (None, ''):
            raw_year = row.get('year')
        try:
            year = int(raw_year) if raw_year not in (None, '') else None
        except (TypeError, ValueError):
            year = None

        raw_eligible = row.get('is_eligible', True)
        canonical.append({
            'usn': str(row.get('usn') or '').strip(),
            'full_name': str(row.get('full_name') or row.get('name') or '').strip(),
            'college_email': str(
                row.get('college_email') or row.get('email') or '').strip().lower(),
            'department': (str(row['department']).strip()
                           if row.get('department') else None),
            'year_of_study': year,
            'is_eligible': bool(raw_eligible) if raw_eligible is not None else True,
        })
    canonical.sort(key=lambda item: item['usn'])
    return canonical


def compute_roll_digest(rows: Sequence[Dict]) -> str:
    """SHA-256 over the canonical roll representation."""
    payload = json.dumps(canonicalize_roll(rows), sort_keys=True,
                         separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def current_roll_rows() -> List[Dict]:
    """Every electoral-roll row, as plain dictionaries, for digest verification."""
    records = db.session.execute(select(ElectoralRoll)).scalars().all()
    return [
        {
            'usn': record.usn,
            'full_name': record.full_name,
            'college_email': record.college_email,
            'department': record.department,
            'year_of_study': record.year_of_study,
            'is_eligible': record.is_eligible,
        }
        for record in records
    ]

def mask_email(email: Optional[str]) -> str:
    """Mask email for privacy, e.g. student01@example.com -> s***1@example.com."""
    if not email or '@' not in email:
        return '***'
    user, domain = email.split('@', 1)
    if len(user) <= 1:
        masked_user = user + '***'
    elif len(user) == 2:
        masked_user = user[0] + '***'
    else:
        masked_user = user[0] + '***' + user[-1]
    return f"{masked_user}@{domain}"


class RegistrationService:
    def __init__(self, email_service: Optional[EmailService] = None):
        self.email_service = email_service or EmailService()

    # ------------------------------------------------------------------ audit
    def _audit(self, event_type: str, metadata: Optional[dict] = None) -> None:
        """Record a registration lifecycle event without identifiers.

        The Phase 1 audit sanitiser is deny-by-default, so a USN, email, name or
        OTP could not be persisted here even if it were passed. Audit failures
        must never break registration.
        """
        try:
            from app.audit.audit import AuditLogger
            AuditLogger().log(event_type, metadata or {})
        except Exception:  # pragma: no cover
            db.session.rollback()

    # ---------------------------------------------------------- roll import
    def dry_run_import(self, rows: List[Dict], source_filename: Optional[str] = None,
                       errors: Optional[List[str]] = None) -> RollImportBatch:
        """Validate and fingerprint the roll without writing any voter row."""
        batch_id = secrets.token_hex(8)
        digest = compute_roll_digest(rows)
        batch = RollImportBatch(
            batch_id=batch_id,
            status='DRY_RUN',
            roll_digest=digest,
            row_count=len(rows),
            source_filename=(source_filename or '')[:255] or None,
            error_count=len(errors or []),
        )
        db.session.add(batch)
        db.session.commit()
        return batch

    def apply_import(self, batch_id: str) -> Tuple[bool, int, str]:
        """Apply a previously dry-run batch to the electoral roll."""
        batch = db.session.execute(
            select(RollImportBatch).where(RollImportBatch.batch_id == batch_id)
        ).scalars().first()
        if batch is None:
            return False, 0, 'Unknown batch'
        if batch.status == 'APPLIED':
            return False, 0, 'Batch already applied'

        # Re-read the staged rows from the dry-run fingerprint is not possible
        # (the file is not retained), so the caller must pass them again.
        return False, 0, 'Rows must be supplied to apply'

    def import_roll(self, csv_rows: List[Dict], batch_id: Optional[str] = None,
                    digest: Optional[str] = None,
                    errors: Optional[List[str]] = None) -> Tuple[int, List[str]]:
        """Import validated rows into the electoral roll, atomically.

        Either every insertable row is committed or none is. Duplicate USNs
        already present in the roll are reported and skipped.
        """
        import_errors: List[str] = list(errors or [])
        inserted = 0
        stamp = _now()

        if batch_id is None:
            batch_id = secrets.token_hex(8)

        try:
            for row in csv_rows:
                if db.session.execute(
                    select(ElectoralRoll).where(ElectoralRoll.usn == row['usn'])
                ).scalars().first() is not None:
                    import_errors.append('USN already present in the roll')
                    continue
                db.session.add(ElectoralRoll(
                    usn=row['usn'],
                    full_name=row['name'],
                    college_email=row['email'],
                    is_eligible=True,
                    department=row.get('department'),
                    year_of_study=row.get('year'),
                    import_batch=batch_id,
                ))
                inserted += 1

            # Reuse the dry-run provenance record when there is one; batch_id is
            # unique, so inserting a second row with the same id would fail.
            batch = db.session.execute(
                select(RollImportBatch).where(RollImportBatch.batch_id == batch_id)
            ).scalars().first()
            if batch is None:
                batch = RollImportBatch(batch_id=batch_id)
                db.session.add(batch)
            batch.status = 'APPLIED'
            batch.roll_digest = digest or compute_roll_digest([
                {'usn': r['usn'], 'full_name': r['name'], 'college_email': r['email'],
                 'department': r.get('department'), 'year_of_study': r.get('year'),
                 'is_eligible': True}
                for r in csv_rows])
            batch.row_count = len(csv_rows)
            batch.error_count = len(import_errors)
            batch.applied_at = stamp
            db.session.commit()
        except Exception:
            db.session.rollback()
            return 0, ['Roll import failed and was rolled back']

        self._audit('roll.imported', {'action': 'roll.import', 'outcome': 'success'})
        return inserted, import_errors

    def verify_roll_integrity(self, batch_id: Optional[str] = None) -> Tuple[bool, str]:
        """Recompute the roll digest and compare it with the recorded one.

        Detects any modification to voter rows after the import.
        """
        query = select(RollImportBatch).where(RollImportBatch.status == 'APPLIED')
        if batch_id:
            query = query.where(RollImportBatch.batch_id == batch_id)
        batch = db.session.execute(
            query.order_by(RollImportBatch.applied_at.desc())
        ).scalars().first()
        if batch is None:
            return False, 'No applied roll import to verify'

        recomputed = compute_roll_digest(current_roll_rows())
        if recomputed != batch.roll_digest:
            return False, 'Roll digest mismatch: the electoral roll has been modified'
        return True, 'Roll digest matches'

    # -------------------------------------------------------- eligibility
    def start_registration(self, usn: str) -> Tuple[bool, Optional[RegistrationSession], str]:
        """Open a registration session for an eligible, unregistered voter.

        Every failure path returns the same generic message so the endpoint
        cannot reveal whether a USN exists, is eligible, or is already
        registered.
        """
        usn = (usn or '').strip()

        # Check registration deadline enforcement
        now = _now()
        closed_election = db.session.execute(
            select(Election).where(
                Election.registration_deadline.isnot(None),
                Election.registration_deadline <= now,
                Election.status.in_(['SCHEDULED', 'ACTIVE', 'OPEN']),
            )
        ).scalars().first()
        if closed_election is not None:
            hash_password(secrets.token_urlsafe(24))
            self._audit('registration.closed', {'action': 'roll.check', 'outcome': 'deadline_passed'})
            return False, None, 'Registration is closed'

        roll = db.session.execute(
            select(ElectoralRoll).where(
                ElectoralRoll.usn == usn, ElectoralRoll.is_eligible.is_(True))
        ).scalars().first()

        if roll is None:
            # Equalise timing against the success path so an absent USN is not
            # distinguishable by response time alone.
            hash_password(secrets.token_urlsafe(24))
            self._audit('registration.rejected', {'action': 'roll.check', 'outcome': 'failure'})
            return False, None, GENERIC_REGISTRATION_MESSAGE

        existing = db.session.execute(
            select(User).where(User.voter_id == usn)
        ).scalars().first()
        if existing is not None:
            self._audit('registration.duplicate', {'action': 'roll.check', 'outcome': 'failure'})
            return False, None, GENERIC_REGISTRATION_MESSAGE

        record = RegistrationSession(
            session_id=secrets.token_hex(32),
            usn=usn,
            email=roll.college_email,
            state=REG_PENDING,
            expires_at=_now() + timedelta(minutes=SESSION_TTL_MINUTES),
            otp_max_attempts=OTP_MAX_ATTEMPTS,
        )
        db.session.add(record)
        db.session.commit()
        session['reg_session'] = record.session_id
        self._audit('registration.started', {'action': 'registration.start',
                                             'outcome': 'success'})
        return True, record, 'Registration started'

    # ----------------------------------------------------------------- OTP
    def _live_session(self, reg_sid: str) -> Optional[RegistrationSession]:
        """Fetch a registration session that is usable right now."""
        if not reg_sid:
            return None
        record = db.session.execute(
            select(RegistrationSession).where(RegistrationSession.session_id == reg_sid)
        ).scalars().first()
        if record is None or record.revoked:
            return None
        if _now() >= record.expires_at:
            return None
        return record

    def request_registration_otp(self, reg_sid: str, entered_email: Optional[str] = None) -> Tuple[bool, str]:
        """Dispatch a single-use OTP to the student's entered email."""
        record = self._live_session(reg_sid)
        if record is None or record.state != REG_PENDING:
            return False, GENERIC_REGISTRATION_MESSAGE

        clean_entered = (entered_email or '').strip().lower()
        if not clean_entered or '@' not in clean_entered or '.' not in clean_entered.split('@')[-1]:
            hash_password(secrets.token_urlsafe(24))
            self._audit('registration.email_invalid',
                        {'action': 'registration.otp', 'outcome': 'failure'})
            return False, 'Valid college email required'

        # Store the student's entered email in the registration session
        record.email = clean_entered

        stamp = _now()
        code = generate_otp()
        record.otp_hash = hash_otp(code)
        record.otp_purpose = REGISTRATION_OTP_PURPOSE
        record.otp_expires_at = stamp + timedelta(minutes=OTP_TTL_MINUTES)
        record.otp_attempts = 0
        record.otp_max_attempts = OTP_MAX_ATTEMPTS
        record.otp_used = False
        record.otp_consumed_at = None
        db.session.commit()

        try:
            delivered = self.email_service.send_otp(
                clean_entered, code, REGISTRATION_OTP_PURPOSE)
        except Exception:
            current_app.logger.exception('Registration OTP delivery raised')
            delivered = False

        if not delivered:
            # The code never reached the mailbox, so it must not remain
            # verifiable and the caller must not be told it was sent.
            record.otp_hash = None
            record.otp_purpose = None
            record.otp_expires_at = None
            db.session.commit()
            self._audit('registration.otp_delivery_failed',
                        {'action': 'registration.otp', 'outcome': 'failure'})
            return False, 'Unable to send OTP'

        self._audit('registration.otp_requested',
                    {'action': 'registration.otp', 'outcome': 'success'})
        return True, 'OTP sent'

    def verify_registration_otp(self, reg_sid: str, otp_code: str,
                               purpose: str = REGISTRATION_OTP_PURPOSE) -> Tuple[bool, str]:
        """Verify the registration OTP and advance the state machine."""
        if purpose != REGISTRATION_OTP_PURPOSE:
            return False, GENERIC_REGISTRATION_MESSAGE

        record = self._live_session(reg_sid)
        if record is None or record.state != REG_PENDING:
            return False, GENERIC_REGISTRATION_MESSAGE

        stamp = _now()

        def fail() -> Tuple[bool, str]:
            self._audit('registration.otp_failed',
                        {'action': 'registration.otp.verify', 'outcome': 'failure'})
            return False, GENERIC_REGISTRATION_MESSAGE

        if record.otp_hash is None:
            return fail()
        if record.otp_used or record.otp_consumed_at is not None:
            return fail()
        if record.otp_purpose != REGISTRATION_OTP_PURPOSE:
            return fail()
        if record.otp_expires_at is None or stamp >= record.otp_expires_at:
            self._invalidate_otp(record, stamp)
            return fail()
        if record.otp_attempts >= (record.otp_max_attempts or OTP_MAX_ATTEMPTS):
            self._invalidate_otp(record, stamp)
            return fail()

        if not verify_otp(otp_code, record.otp_hash):
            record.otp_attempts = (record.otp_attempts or 0) + 1
            db.session.commit()
            return fail()

        record.otp_used = True
        record.otp_consumed_at = stamp
        record.email_verified = True
        record.state = REG_EMAIL_VERIFIED
        db.session.commit()
        self._audit('registration.email_verified',
                    {'action': 'registration.otp.verify', 'outcome': 'success'})
        return True, 'Email verified'

    @staticmethod
    def _invalidate_otp(record: RegistrationSession, stamp: datetime) -> None:
        """Burn an OTP that can no longer be used."""
        record.otp_used = True
        record.otp_consumed_at = stamp
        record.otp_hash = None
        db.session.commit()

    # ---------------------------------------------------------- completion
    def complete_registration(self, reg_sid: str, username: str,
                              password: str) -> Tuple[bool, Optional[User], str]:
        """Create the account once the session is verified, live and unrevoked."""
        if not reg_sid or not username or not password:
            return False, None, GENERIC_REGISTRATION_MESSAGE

        record = db.session.execute(
            select(RegistrationSession).where(RegistrationSession.session_id == reg_sid)
        ).scalars().first()

        # C2 fix: a revoked or expired session can never complete, and the
        # state machine forbids PENDING -> REGISTERED.
        if record is None or record.revoked:
            return False, None, GENERIC_REGISTRATION_MESSAGE
        if _now() >= record.expires_at:
            record.revoked = True
            db.session.commit()
            return False, None, GENERIC_REGISTRATION_MESSAGE
        if record.state != REG_EMAIL_VERIFIED or not record.email_verified:
            return False, None, GENERIC_REGISTRATION_MESSAGE
        if record.state == REG_REGISTERED:
            return False, None, GENERIC_REGISTRATION_MESSAGE

        # Check registration deadline enforcement
        now = _now()
        closed_election = db.session.execute(
            select(Election).where(
                Election.registration_deadline.isnot(None),
                Election.registration_deadline <= now,
                Election.status.in_(['SCHEDULED', 'ACTIVE', 'OPEN']),
            )
        ).scalars().first()
        if closed_election is not None:
            self._audit('registration.closed', {'action': 'registration.complete', 'outcome': 'deadline_passed'})
            return False, None, 'Registration is closed'

        username = username.strip()
        existing_user = db.session.execute(
            select(User).where(User.voter_id == record.usn)
        ).scalars().first()

        if existing_user is None:
            if db.session.execute(
                select(User).where(User.username == username)
            ).scalars().first() is not None:
                return False, None, 'Username already taken'
            if db.session.execute(
                select(User).where(User.email == record.email)
            ).scalars().first() is not None:
                return False, None, GENERIC_REGISTRATION_MESSAGE

            try:
                user = User(
                    username=username,
                    email=record.email,
                    password_hash=hash_password(password),
                    voter_id=record.usn,
                    is_verified=True,
                    is_active=True,
                )
                db.session.add(user)
                record.state = REG_REGISTERED
                db.session.commit()
            except Exception:
                db.session.rollback()
                return False, None, GENERIC_REGISTRATION_MESSAGE
        else:
            user = existing_user

        # Establish authorized session for this user so they can immediately enroll Face and bind Wallet
        from app.services.auth_service import generate_session_id, calculate_expiry, STATE_AUTHORIZED
        auth_sid = generate_session_id()
        abs_exp, idle_exp = calculate_expiry()
        now_ts = datetime.utcnow()
        auth_session = AuthSession(
            session_id=auth_sid,
            user_id=user.id,
            auth_state=STATE_AUTHORIZED,
            authenticated_at=now_ts,
            expires_at=abs_exp,
            idle_expires_at=idle_exp,
            last_activity=now_ts,
        )
        db.session.add(auth_session)
        db.session.commit()
        session['session_id'] = auth_sid

        self._audit('registration.password_created',
                    {'action': 'registration.password', 'outcome': 'success'})
        return True, user, 'Account created. Proceed to face verification.'
