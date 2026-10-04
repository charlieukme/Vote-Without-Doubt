"""
Wallet Service - Phase 4
"""

from datetime import datetime, timedelta
from typing import Optional

from flask import session
from app.extensions import db
from app.models import User, WalletBinding, WalletChallenge
from app.security.wallet import generate_challenge_nonce, create_auth_message, verify_signature, normalize_address


class WalletService:
    def __init__(self):
        pass

    def request_challenge(self, user_id: int, domain: str = 'votewithoutdoubt.local'):
        if WalletBinding.query.filter_by(user_id=user_id).first():
            return False, None, "Wallet already bound"
        nonce = generate_challenge_nonce()
        msg = create_auth_message(nonce, user_id, domain=domain)
        ch = WalletChallenge(
            challenge_id=nonce,
            user_id=user_id,
            nonce=nonce,
            purpose='WALLET_AUTHENTICATION',
            message=msg,
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        db.session.add(ch)
        db.session.commit()
        return True, ch, "Challenge created"

    def verify_and_bind(self, user_id: int, nonce: str, signature: str, wallet_address: str, domain: str = 'votewithoutdoubt.local'):
        ch = WalletChallenge.query.filter_by(nonce=nonce, user_id=user_id, used=False).first()
        if not ch:
            return False, "Invalid challenge"
        if ch.expires_at < datetime.utcnow():
            return False, "Challenge expired"
        if WalletBinding.query.filter_by(wallet_address=normalize_address(wallet_address)).first():
            return False, "Wallet already bound to another user"
        if WalletBinding.query.filter_by(user_id=user_id).first():
            return False, "Wallet already bound"
        ok, recovered = verify_signature(ch.message, signature, wallet_address)
        if not ok:
            return False, "Invalid signature"
        ch.used = True
        ch.consumed_at = datetime.utcnow()
        ch.wallet_address = normalize_address(wallet_address)
        ch.signature = signature
        wb = WalletBinding(
            user_id=user_id,
            wallet_address=normalize_address(wallet_address),
            is_verified=True,
            binding_method='signature'
        )
        db.session.add(wb)
        db.session.commit()
        return True, "Wallet bound successfully"
