"""
Wallet Service - Phase 4 (remediated)
Vote Without Doubt - Backend

Sequence enforced here:

    authorized session -> challenge -> personal_sign -> server reconstructs the
    exact message -> Ethereum recovery -> address compared -> bind -> consume

Every context value comes from server configuration or the stored challenge. The
caller supplies only the nonce, the signature and the wallet address they claim,
and the address they claim must be the address that actually signed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import WalletBinding, WalletChallenge
from app.security.wallet import (
    CHALLENGE_TTL_MINUTES,
    MAX_SIGNATURE_ATTEMPTS,
    NO_CONTRACT_ADDRESS,
    WALLET_AUTH_PURPOSE,
    InvalidWalletAddress,
    WalletVerificationUnavailable,
    create_auth_message,
    generate_challenge_nonce,
    normalize_address,
    verify_signature,
)

#: Externally visible failure strings. Internally the specific reason is logged.
GENERIC_BIND_FAILURE = 'Wallet binding failed'


class WalletService:
    # ------------------------------------------------------------- helpers
    @staticmethod
    def _context() -> dict:
        """Server-authoritative signing context. Never client supplied."""
        config = current_app.config
        return {
            'domain': config['WALLET_AUTH_DOMAIN'],
            'election_id': str(config['WALLET_AUTH_ELECTION_ID']),
            'chain_id': int(config['WALLET_AUTH_CHAIN_ID']),
            'contract_address': str(config['WALLET_AUTH_CONTRACT_ADDRESS']
                                    or NO_CONTRACT_ADDRESS),
        }

    @staticmethod
    def _burn(challenge: WalletChallenge) -> None:
        """Make a challenge permanently unusable."""
        challenge.used = True
        challenge.consumed_at = datetime.utcnow()
        db.session.commit()

    # ----------------------------------------------------------- challenge
    def request_challenge(self, user_id: int,
                          session_id: Optional[str] = None) -> Tuple[bool, Optional[WalletChallenge], str]:
        """Issue a single-use, fully bound authentication challenge."""
        if db.session.execute(
            select(WalletBinding).where(WalletBinding.user_id == user_id)
        ).scalars().first() is not None:
            return False, None, 'Wallet already bound'

        context = self._context()
        issued = datetime.utcnow()
        expires = issued + timedelta(minutes=CHALLENGE_TTL_MINUTES)
        nonce = generate_challenge_nonce()

        message = create_auth_message(
            nonce=nonce,
            user_id=user_id,
            election_id=context['election_id'],
            chain_id=context['chain_id'],
            contract_address=context['contract_address'],
            domain=context['domain'],
            purpose=WALLET_AUTH_PURPOSE,
            issued_at=issued.isoformat() + 'Z',
            expires_at=expires.isoformat() + 'Z',
        )

        challenge = WalletChallenge(
            challenge_id=nonce,
            user_id=user_id,
            session_id=session_id,
            nonce=nonce,
            purpose=WALLET_AUTH_PURPOSE,
            election_id=context['election_id'],
            chain_id=context['chain_id'],
            contract_address=context['contract_address'],
            message=message,
            expires_at=expires,
            used=False,
            attempts=0,
            max_attempts=MAX_SIGNATURE_ATTEMPTS,
        )
        db.session.add(challenge)
        db.session.commit()
        return True, challenge, 'Challenge created'

    # --------------------------------------------------------------- verify
    def verify_and_bind(self, user_id: int, session_id: Optional[str], nonce: str,
                        signature: str, wallet_address: str,
                        chain_id: Optional[int] = None
                        ) -> Tuple[bool, str]:
        """Verify the ownership proof and bind the wallet to the identity."""
        current_app.logger.info(
            'wallet bind attempt: purpose=%s user=%s session_bound=%s',
            WALLET_AUTH_PURPOSE, user_id, bool(session_id),
        )

        # 1. Chain must match the server-configured network.
        expected_chain = int(current_app.config['WALLET_AUTH_CHAIN_ID'])
        if chain_id is not None and int(chain_id) != expected_chain:
            current_app.logger.warning(
                'wallet bind rejected: chain mismatch expected=%s got=%s',
                expected_chain, chain_id)
            return False, 'Unsupported network'

        # 2. Claimed address must be well formed before anything else.
        try:
            claimed = normalize_address(wallet_address)
        except InvalidWalletAddress:
            current_app.logger.warning('wallet bind rejected: malformed address')
            return False, 'Invalid wallet address'

        # 3. Challenge must match nonce + user + session + purpose and be unused.
        challenge = db.session.execute(
            select(WalletChallenge).where(
                WalletChallenge.nonce == nonce,
                WalletChallenge.user_id == user_id,
                WalletChallenge.purpose == WALLET_AUTH_PURPOSE,
                WalletChallenge.used.is_(False),
            ).with_for_update()
        ).scalars().first()

        if challenge is None:
            current_app.logger.warning('wallet bind rejected: no matching challenge')
            return False, 'Invalid challenge'

        if session_id is None or challenge.session_id != session_id:
            current_app.logger.warning('wallet bind rejected: session mismatch')
            return False, 'Invalid challenge'

        if challenge.expires_at < datetime.utcnow():
            self._burn(challenge)
            return False, 'Challenge expired'

        if challenge.attempts_exhausted:
            self._burn(challenge)
            return False, 'Too many attempts'

        # 4. Recover the signer from the real signature over the STORED message.
        try:
            ok, recovered = verify_signature(challenge.message, signature, claimed)
        except WalletVerificationUnavailable:
            # Fail loudly and visibly; never disguise as a bad signature.
            current_app.logger.error(
                'wallet verification unavailable - eth-account is not usable')
            db.session.rollback()
            raise

        if not ok:
            challenge.attempts = (challenge.attempts or 0) + 1
            if challenge.attempts_exhausted:
                challenge.used = True
                challenge.consumed_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info(
                'wallet bind rejected: signature did not recover to the claimed address')
            return False, 'Invalid signature'

        # 5. Bind only when the recovered address is the claimed address.
        if db.session.execute(
            select(WalletBinding).where(WalletBinding.wallet_address == claimed)
        ).scalars().first() is not None:
            self._burn(challenge)
            return False, 'Wallet already bound to another user'
        if db.session.execute(
            select(WalletBinding).where(WalletBinding.user_id == user_id)
        ).scalars().first() is not None:
            self._burn(challenge)
            return False, 'Wallet already bound'

        db.session.add(WalletBinding(
            user_id=user_id,
            wallet_address=claimed,
            is_verified=True,
            binding_method='personal_sign',
        ))
        challenge.used = True
        challenge.consumed_at = datetime.utcnow()
        challenge.wallet_address = claimed
        challenge.signature = signature
        db.session.commit()
        return True, 'Wallet bound successfully'
