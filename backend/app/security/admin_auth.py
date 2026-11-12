"""
Admin Authentication & Role-Based Access Control (RBAC) - Phase 11
Vote Without Doubt - Backend

Enforces:
1. Three-Factor Admin Authentication: Admin ID + Password (Argon2id) + TOTP (RFC 6238).
2. Server-side TOTP verification with encrypted secret storage.
3. Brute-force protection: 5 failed attempts locks account for 15 minutes.
4. Server-side session verification, revocation, and inactivity timeout.
5. Strict RBAC: OFFICER and AUDITOR roles.
"""

from datetime import datetime, timedelta
from functools import wraps
import os
import secrets
from typing import List, Optional, Tuple, Union

from flask import current_app, g, jsonify, request

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import AdminSession, AdminUser
from app.security.password import hash_password, verify_password
from app.security.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    verify_totp_code,
    verify_totp_code_with_step,
)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
SESSION_LIFETIME_HOURS = 2


class AdminAuthService:
    @staticmethod
    def create_admin_user(
        admin_id: str,
        name: str,
        email: str,
        password: str,
        role: str = 'OFFICER',
        enable_totp: bool = True,
    ) -> Tuple[AdminUser, str]:
        """
        Create a new administrative user with Argon2id password hash and generated TOTP secret.
        Returns (AdminUser, raw_totp_secret) so secret can be displayed once for enrollment.
        """
        if role not in ('OFFICER', 'AUDITOR'):
            raise ValueError(f"Invalid admin role: {role}. Must be OFFICER or AUDITOR.")

        existing = AdminUser.query.filter(
            (AdminUser.admin_id == admin_id) | (AdminUser.email == email)
        ).first()
        if existing:
            raise ValueError(f"Admin with ID '{admin_id}' or email '{email}' already exists.")

        raw_secret = generate_totp_secret()
        enc_secret = encrypt_totp_secret(raw_secret)
        pwd_hash = hash_password(password)

        admin = AdminUser(
            admin_id=admin_id,
            name=name,
            email=email,
            password_hash=pwd_hash,
            role=role,
            totp_secret_encrypted=enc_secret,
            totp_enabled=enable_totp,
            is_active=True,
            failed_attempts=0,
        )
        db.session.add(admin)
        db.session.commit()

        AuditLogger().log('ADMIN_USER_CREATED', {
            'admin_id': admin_id,
            'role': role,
            'email': email,
        })
        return admin, raw_secret

    create_admin = create_admin_user

    @staticmethod
    def authenticate(
        admin_id: str,
        password: str,
        totp_code: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[AdminSession], Optional[str]]:
        """
        Authenticate an admin using Admin ID + Password + TOTP.
        Returns (success, session_token, session_obj, error_code).
        """
        admin = AdminUser.query.filter_by(admin_id=admin_id).first()
        if not admin:
            AuditLogger().log('ADMIN_LOGIN_FAILED', {
                'admin_id': admin_id,
                'reason': 'USER_NOT_FOUND',
                'ip': ip_address,
            })
            return False, None, None, 'INVALID_CREDENTIALS'

        if not admin.is_active:
            AuditLogger().log('ADMIN_LOGIN_FAILED', {
                'admin_id': admin_id,
                'reason': 'ACCOUNT_INACTIVE',
                'ip': ip_address,
            })
            return False, None, None, 'ACCOUNT_INACTIVE'

        now = datetime.utcnow()
        if admin.is_locked():
            AuditLogger().log('ADMIN_LOGIN_FAILED', {
                'admin_id': admin_id,
                'reason': 'ACCOUNT_LOCKED',
                'locked_until': admin.locked_until.isoformat(),
                'ip': ip_address,
            })
            return False, None, None, 'ACCOUNT_LOCKED'

        # 1. Verify Password
        if not verify_password(password, admin.password_hash):
            admin.failed_attempts += 1
            if admin.failed_attempts >= MAX_FAILED_ATTEMPTS:
                admin.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                AuditLogger().log('ADMIN_ACCOUNT_LOCKED', {
                    'admin_id': admin_id,
                    'failed_attempts': admin.failed_attempts,
                    'locked_until': admin.locked_until.isoformat(),
                })
            db.session.commit()
            AuditLogger().log('ADMIN_LOGIN_FAILED', {
                'admin_id': admin_id,
                'reason': 'INVALID_PASSWORD',
                'failed_attempts': admin.failed_attempts,
                'ip': ip_address,
            })
            return False, None, None, 'INVALID_CREDENTIALS'

        # 2. Verify TOTP
        if admin.totp_enabled:
            if not totp_code:
                return False, None, None, 'TOTP_REQUIRED'

            if not admin.totp_secret_encrypted:
                return False, None, None, 'TOTP_NOT_CONFIGURED'

            raw_secret = decrypt_totp_secret(admin.totp_secret_encrypted)
            totp_valid, matched_step = verify_totp_code_with_step(raw_secret, totp_code)
            if not totp_valid or matched_step is None:
                admin.failed_attempts += 1
                if admin.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    admin.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                db.session.commit()
                AuditLogger().log('ADMIN_LOGIN_FAILED', {
                    'admin_id': admin_id,
                    'reason': 'INVALID_TOTP',
                    'failed_attempts': admin.failed_attempts,
                    'ip': ip_address,
                })
                return False, None, None, 'INVALID_TOTP'

            # SEC-11-02: In-Window TOTP Token Replay Prevention
            if admin.last_totp_step is not None and matched_step <= admin.last_totp_step:
                AuditLogger().log('ADMIN_LOGIN_FAILED', {
                    'admin_id': admin_id,
                    'reason': 'TOTP_REPLAY_REJECTED',
                    'ip': ip_address,
                })
                return False, None, None, 'TOTP_REPLAY_REJECTED'

            # Atomic claim of the TOTP time step to prevent concurrent reuse
            claimed = AdminUser.query.filter(
                AdminUser.id == admin.id,
                (AdminUser.last_totp_step == None) | (AdminUser.last_totp_step < matched_step),
            ).update({'last_totp_step': matched_step}, synchronize_session=False)

            if claimed == 0:
                AuditLogger().log('ADMIN_LOGIN_FAILED', {
                    'admin_id': admin_id,
                    'reason': 'CONCURRENT_TOTP_REPLAY_REJECTED',
                    'ip': ip_address,
                })
                return False, None, None, 'TOTP_REPLAY_REJECTED'

            admin.last_totp_step = matched_step

        # Success - reset lockout & create session
        admin.failed_attempts = 0
        admin.locked_until = None

        token = secrets.token_hex(32)
        session = AdminSession(
            session_token=token,
            admin_id=admin.id,
            role=admin.role,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=now + timedelta(hours=SESSION_LIFETIME_HOURS),
            revoked=False,
        )
        db.session.add(session)
        db.session.commit()

        AuditLogger().log('ADMIN_LOGIN_SUCCESS', {
            'admin_id': admin_id,
            'role': admin.role,
            'ip': ip_address,
        })
        return True, token, session, None

    @staticmethod
    def get_session(token: str) -> Optional[Tuple[AdminUser, AdminSession]]:
        """Validate an active admin session token."""
        if not token or len(token) != 64:
            return None

        sess = AdminSession.query.filter_by(session_token=token, revoked=False).first()
        if not sess or not sess.is_valid():
            return None

        admin = AdminUser.query.get(sess.admin_id)
        if not admin or not admin.is_active or admin.is_locked():
            return None

        return admin, sess

    @staticmethod
    def logout(token: str) -> bool:
        """Revoke an active admin session."""
        sess = AdminSession.query.filter_by(session_token=token).first()
        if sess:
            sess.revoked = True
            db.session.commit()
            AuditLogger().log('ADMIN_LOGOUT', {
                'admin_id': sess.admin.admin_id if sess.admin else None,
            })
            return True
        return False


def require_admin_auth(roles: Optional[Union[str, List[str]]] = None):
    """
    Decorator for endpoints requiring administrative authentication and role checks.
    Supports single role or list of acceptable roles ('OFFICER', 'AUDITOR').
    Extracts session from 'Authorization: Bearer <token>' or 'X-Admin-Session' header.
    """
    if isinstance(roles, str):
        allowed_roles = [roles]
    elif isinstance(roles, (list, tuple)):
        allowed_roles = list(roles)
    else:
        allowed_roles = ['OFFICER', 'AUDITOR']

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = None
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header[7:].strip()
            elif 'X-Admin-Session' in request.headers:
                token = request.headers.get('X-Admin-Session', '').strip()

            if not token:
                return jsonify({'error': 'AUTH_REQUIRED', 'message': 'Admin session required'}), 401

            validated = AdminAuthService.get_session(token)
            if not validated:
                return jsonify({'error': 'INVALID_SESSION', 'message': 'Session expired or invalid'}), 401

            admin_user, admin_sess = validated

            # Server-Side RBAC Enforcement
            if admin_user.role not in allowed_roles:
                AuditLogger().log('ADMIN_ACCESS_DENIED', {
                    'admin_id': admin_user.admin_id,
                    'role': admin_user.role,
                    'required_roles': allowed_roles,
                    'endpoint': request.path,
                })
                return jsonify({
                    'error': 'ROLE_UNAUTHORIZED',
                    'message': f"Operation requires role in {allowed_roles}, but caller has role '{admin_user.role}'."
                }), 403

            g.admin_user = admin_user
            g.admin_session = admin_sess
            return f(*args, **kwargs)

        return decorated

    return decorator
