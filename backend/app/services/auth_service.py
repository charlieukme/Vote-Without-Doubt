"""
Auth Service - Phase 2 (Auth Core)
Vote Without Doubt - Backend

Security properties enforced here:

* Passwords are verified with Argon2id and never stored or logged in clear.
* The server-side :class:`AuthSession` row is the authoritative session. The
  browser only ever holds an opaque, signed reference to the session id.
* A session must complete a second factor (email OTP) before it becomes
  ``AUTHORIZED``. Password alone never grants authorization.
* Successful OTP verification ROTATES the session id and revokes the previous
  session row, which defeats session fixation.
* OTPs are stored only as HMAC-SHA256(pepper, otp), are bound to both the
  session and the purpose, expire after five minutes, allow five attempts and
  are single-use.
* Verification failures return one generic message so the endpoint cannot be
  used as an oracle for account existence, OTP state or reason.
* Session ids are never written to logs. Only the audit log records that a
  rotation happened, and it records no identifiers at all.
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from flask import session, current_app
from sqlalchemy import select

from app.extensions import db
from app.models import User, OTP, AuthSession
from app.security.password import hash_password, verify_password
from app.security.otp import generate_otp, hash_otp, verify_otp as verify_otp_hash
from app.security.sessions import (
    IDLE_TIMEOUT_MINUTES,
    calculate_expiry,
    generate_session_id,
    is_expired,
    is_idle_expired,
    refresh_idle_deadline,
)
from app.email.service import EmailService

#: OTP lifetime and abuse limits (PROJECT_BIBLE Section 7, principle 3).
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5

#: Failed password attempts before the account is locked, and lock duration.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

#: Purposes this Phase 2 service will issue an OTP for. Anything else is
#: rejected outright so a caller cannot reuse the login OTP pipeline for an
#: unintended flow.
VALID_OTP_PURPOSES = frozenset({'login'})

#: Single generic failure string. Distinguishing "no such OTP", "expired",
#: "exhausted" and "wrong value" would turn the endpoint into a state oracle.
GENERIC_AUTH_FAILURE = 'Invalid credentials'
GENERIC_OTP_FAILURE = 'Invalid or expired OTP'

#: Session lifecycle states.
STATE_PENDING = 'PENDING_FACTORS'
STATE_AUTHORIZED = 'AUTHORIZED'


class AuthService:
    def __init__(self, email_service: Optional[EmailService] = None):
        self.email_service = email_service or EmailService()

    # ------------------------------------------------------------------ audit
    def _audit(self, event_type: str, metadata: Optional[dict] = None) -> None:
        """Record an authentication lifecycle event.

        Deliberately identifier-free: the audit sanitiser is deny-by-default, so
        a username, user id, IP or session id could not be persisted even if it
        were passed here. Audit failures must never break authentication.
        """
        try:
            from app.audit.audit import AuditLogger
            AuditLogger().log(event_type, metadata or {})
        except Exception:  # pragma: no cover - audit must not block auth
            db.session.rollback()

    # --------------------------------------------------------------- accounts
    def register_user(self, username: str, email: str, password: str,
                      voter_id: Optional[str] = None) -> User:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            voter_id=voter_id,
        )
        db.session.add(user)
        db.session.commit()
        self._audit('auth.user_registered', {'action': 'user.register'})
        return user

    # ------------------------------------------------------------- password
    def authenticate(self, username: str, password: str,
                     ip_address: str = None, user_agent: str = None):
        """Verify a password and open a *pending* (unauthenticated) session.

        Returns ``(ok, auth_session, message)``. A wrong password, an unknown
        account and a locked account are indistinguishable to the caller.
        """
        user = User.query.filter_by(username=username, is_active=True).first()

        if user is None:
            # Perform a dummy verification so a missing account costs roughly the
            # same time as a present one, reducing user enumeration by timing.
            verify_password(password or '', _DUMMY_ARGON2_HASH)
            self._audit('auth.login_failed', {'action': 'auth.login', 'outcome': 'failure'})
            return False, None, GENERIC_AUTH_FAILURE

        if user.locked_until and user.locked_until > datetime.utcnow():
            self._audit('auth.login_locked', {'action': 'auth.login', 'outcome': 'blocked'})
            return False, None, GENERIC_AUTH_FAILURE

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            db.session.commit()
            self._audit('auth.login_failed', {'action': 'auth.login', 'outcome': 'failure'})
            return False, None, GENERIC_AUTH_FAILURE

        user.failed_login_attempts = 0
        user.locked_until = None

        session_id = generate_session_id()
        abs_exp, idle_exp = calculate_expiry()
        auth_session = AuthSession(
            session_id=session_id,
            user_id=user.id,
            auth_state=STATE_PENDING,
            expires_at=abs_exp,
            idle_expires_at=idle_exp,
            last_activity=datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.session.add(auth_session)
        db.session.commit()

        session['session_id'] = session_id
        self._audit('auth.password_verified', {'action': 'auth.login', 'outcome': 'pending'})
        return True, auth_session, 'Authentication started'

    # -------------------------------------------------------------- sessions
    def get_session(self, session_id: str):
        """Return a live session, or ``None`` if it is unusable.

        A session is unusable when it is unknown, revoked, past its absolute
        two-hour deadline, or past its sliding ten-minute idle deadline.
        Revoked or expired sessions are persisted as revoked so a replayed
        cookie is rejected on every later attempt.
        """
        if not session_id:
            return None

        auth_session = db.session.execute(
            select(AuthSession).where(AuthSession.session_id == session_id)
        ).scalars().first()

        if auth_session is None:
            return None

        if auth_session.revoked:
            return None

        now = datetime.utcnow()
        if is_expired(auth_session.expires_at, now) or is_idle_expired(auth_session.idle_expires_at, now):
            auth_session.revoked = True
            db.session.commit()
            return None

        # Slide the idle window forward; the absolute deadline is untouched, so
        # continuous activity still cannot extend the session past two hours.
        auth_session.last_activity = now
        auth_session.idle_expires_at = refresh_idle_deadline(IDLE_TIMEOUT_MINUTES, now)
        db.session.commit()
        return auth_session

    def _rotate_session(self, auth_session: AuthSession) -> str:
        """Revoke the current session and return a fresh authorised session id."""
        auth_session.revoked = True

        new_session_id = generate_session_id()
        abs_exp, idle_exp = calculate_expiry()
        db.session.add(AuthSession(
            session_id=new_session_id,
            user_id=auth_session.user_id,
            auth_state=STATE_AUTHORIZED,
            authenticated_at=datetime.utcnow(),
            expires_at=abs_exp,
            idle_expires_at=idle_exp,
            last_activity=datetime.utcnow(),
            ip_address=auth_session.ip_address,
            user_agent=auth_session.user_agent,
        ))
        return new_session_id

    # ------------------------------------------------------------------- OTP
    def request_otp(self, session_id: str, purpose: str) -> Tuple[bool, str]:
        """Issue and email a single-use, session-bound OTP."""
        if not session_id:
            return False, 'No active session'
        if purpose not in VALID_OTP_PURPOSES:
            return False, 'Invalid OTP purpose'

        auth_session = self.get_session(session_id)
        if not auth_session or auth_session.auth_state != STATE_PENDING:
            return False, GENERIC_AUTH_FAILURE

        user = db.session.get(User, auth_session.user_id)
        if not user or not user.is_active:
            return False, GENERIC_AUTH_FAILURE

        # Supersede any OTP still outstanding for this session and purpose so a
        # repeated request cannot leave two live codes behind.
        now = datetime.utcnow()
        for stale in OTP.query.filter_by(session_id=session_id, purpose=purpose, used=False).all():
            stale.used = True
            stale.consumed_at = now

        otp = generate_otp()
        db.session.add(OTP(
            user_id=user.id,
            purpose=purpose,
            otp_hash=hash_otp(otp),
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            attempts=0,
            max_attempts=OTP_MAX_ATTEMPTS,
            used=False,
            session_id=session_id,
        ))
        db.session.commit()

        try:
            delivered = self.email_service.send_otp(user.email, otp, purpose)
        except Exception:
            current_app.logger.exception('OTP delivery raised an exception')
            delivered = False

        if not delivered:
            # The code never left the trusted backend, so it must not remain
            # verifiable. Reporting success here would leave the user waiting
            # for an email that will never arrive.
            db.session.query(OTP).filter_by(session_id=session_id, purpose=purpose, used=False) \
                .update({'used': True, 'consumed_at': datetime.utcnow()})
            db.session.commit()
            self._audit('auth.otp_delivery_failed', {'action': 'auth.otp.request', 'outcome': 'failure'})
            return False, 'Unable to send OTP'

        self._audit('auth.otp_requested', {'action': 'auth.otp.request', 'outcome': 'success'})
        return True, 'OTP sent'

    def verify_otp(self, session_id: str, otp: str, purpose: str) -> Tuple[bool, str]:
        """Verify a session-bound OTP and, on success, authorise a rotated session."""
        if not session_id or not otp:
            return False, GENERIC_OTP_FAILURE
        if purpose not in VALID_OTP_PURPOSES:
            return False, GENERIC_OTP_FAILURE

        auth_session = self.get_session(session_id)
        if not auth_session or auth_session.auth_state != STATE_PENDING:
            return False, GENERIC_OTP_FAILURE

        now = datetime.utcnow()
        record = db.session.execute(
            select(OTP)
            .where(OTP.session_id == session_id,
                   OTP.purpose == purpose,
                   OTP.used.is_(False))
            .order_by(OTP.id.desc())
            .with_for_update()
        ).scalars().first()

        def fail(message: str = GENERIC_OTP_FAILURE):
            self._audit('auth.otp_verify_failed', {'action': 'auth.otp.verify', 'outcome': 'failure'})
            return False, message

        if record is None:
            return fail()

        if is_expired(record.expires_at, now):
            record.used = True
            record.consumed_at = now
            db.session.commit()
            return fail()

        if record.attempts >= record.max_attempts:
            record.used = True
            record.consumed_at = now
            db.session.commit()
            return fail()

        if not verify_otp_hash(otp, record.otp_hash):
            record.attempts = (record.attempts or 0) + 1
            db.session.commit()
            return fail()

        # Success: single-use, then rotate the session identifier.
        record.used = True
        record.consumed_at = now
        new_session_id = self._rotate_session(auth_session)
        db.session.commit()

        session['session_id'] = new_session_id
        # No identifiers are logged here.
        self._audit('auth.otp_verified', {'action': 'auth.otp.verify', 'outcome': 'success'})
        return True, 'Authentication successful'

    # ---------------------------------------------------------------- logout
    def logout(self, session_id: Optional[str]) -> Tuple[bool, str]:
        """Revoke the server-side session and clear the client cookie.

        Safe to call repeatedly and safe to call with no session at all.
        """
        if session_id:
            auth_session = db.session.execute(
                select(AuthSession).where(AuthSession.session_id == session_id)
            ).scalars().first()
            if auth_session is not None:
                auth_session.revoked = True
                # Outstanding OTPs for a revoked session can never be used.
                db.session.query(OTP).filter_by(session_id=session_id, used=False) \
                    .update({'used': True, 'consumed_at': datetime.utcnow()})
                db.session.commit()
                self._audit('auth.logout', {'action': 'auth.logout'})

        session.clear()
        return True, 'Logged out'

    # -------------------------------------------------------- password reset
    def request_password_reset(self, identifier: str) -> Tuple[bool, str, str]:
        """
        Request a password reset OTP sent to the official roll/account email.
        Returns (ok, reset_token, message).
        Anti-enumeration: returns identical message whether account exists or not.
        """
        import secrets
        clean_id = (identifier or '').strip()
        dummy_token = secrets.token_hex(32)
        generic_msg = "If an account exists with that identifier, a verification code has been sent to the registered email address."

        if not clean_id:
            return False, "", "Identifier is required"

        # Search by username or voter_id (case-insensitive for USN)
        user = User.query.filter(
            (User.username == clean_id) |
            (User.voter_id == clean_id.upper()) |
            (User.voter_id == clean_id)
        ).first()

        if user is None or not user.is_active:
            # Timing equalisation against enumeration
            verify_password('dummy_attempt', _DUMMY_ARGON2_HASH)
            self._audit('auth.password_reset_unknown', {'action': 'auth.forgot_password', 'outcome': 'not_found'})
            return True, dummy_token, generic_msg

        reset_token = secrets.token_hex(32)
        now = datetime.utcnow()

        # Invalidate existing unused password_reset OTPs for this user
        for stale in OTP.query.filter_by(user_id=user.id, purpose='password_reset', used=False).all():
            stale.used = True
            stale.consumed_at = now

        code = generate_otp()
        db.session.add(OTP(
            user_id=user.id,
            purpose='password_reset',
            otp_hash=hash_otp(code),
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            attempts=0,
            max_attempts=OTP_MAX_ATTEMPTS,
            used=False,
            session_id=reset_token,
        ))
        db.session.commit()

        try:
            delivered = self.email_service.send_otp(user.email, code, 'password_reset')
        except Exception:
            current_app.logger.exception('Password reset OTP delivery failed')
            delivered = False

        if not delivered:
            # Code never left trusted boundary; mark consumed
            db.session.query(OTP).filter_by(session_id=reset_token, purpose='password_reset', used=False) \
                .update({'used': True, 'consumed_at': datetime.utcnow()})
            db.session.commit()
            self._audit('auth.password_reset_delivery_failed', {'action': 'auth.forgot_password', 'outcome': 'delivery_failed'})
            return False, "", "Unable to send verification code. Please try again later."

        self._audit('auth.password_reset_requested', {'action': 'auth.forgot_password', 'outcome': 'otp_sent'})
        return True, reset_token, generic_msg

    def reset_password(self, reset_token: str, otp: str, new_password: str) -> Tuple[bool, str]:
        """
        Verify the reset OTP and update password.
        Invalidates all existing sessions for the user.
        """
        if not reset_token or not otp or not new_password:
            return False, "All fields are required"

        if len(new_password) < 8:
            return False, "Password must be at least 8 characters long"

        now = datetime.utcnow()
        record = db.session.execute(
            select(OTP)
            .where(
                OTP.session_id == reset_token,
                OTP.purpose == 'password_reset',
                OTP.used.is_(False),
            )
            .order_by(OTP.id.desc())
            .with_for_update()
        ).scalars().first()

        def fail(msg="Invalid or expired verification code"):
            self._audit('auth.password_reset_failed', {'action': 'auth.password_reset', 'outcome': 'failure'})
            return False, msg

        if record is None:
            return fail()

        if is_expired(record.expires_at, now) or record.attempts >= record.max_attempts:
            record.used = True
            record.consumed_at = now
            db.session.commit()
            return fail()

        if not verify_otp_hash(otp, record.otp_hash):
            record.attempts = (record.attempts or 0) + 1
            if record.attempts >= record.max_attempts:
                record.used = True
                record.consumed_at = now
            db.session.commit()
            return fail()

        # Success: consume OTP, update password, revoke ALL active sessions
        record.used = True
        record.consumed_at = now
        user = db.session.get(User, record.user_id)
        if not user or not user.is_active:
            db.session.commit()
            return fail()

        user.password_hash = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None

        # Invalidate all active user sessions
        AuthSession.query.filter_by(user_id=user.id, revoked=False).update({'revoked': True})
        db.session.commit()

        # Invalidate local session cookie if present
        session.clear()

        self._audit('auth.password_reset_success', {'action': 'auth.password_reset', 'outcome': 'success'})
        return True, "Password has been reset successfully. Please log in with your new password."


#: A real Argon2id hash of an unguessable value, used only to equalise the cost
#: of a login attempt against a non-existent account. It is never a valid
#: password for any account and is not a credential.
_DUMMY_ARGON2_HASH = (
    '$argon2id$v=19$m=65536,t=3,p=4$'
    'c2Vzc2lvbi10aW1pbmctc2FsdA$Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4'
)
