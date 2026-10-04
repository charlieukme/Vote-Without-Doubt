"""
Wallet Security - Phase 4
Signature verification
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional

try:
    from eth_account.messages import encode_defunct
    from eth_account import Account
    ETH_ACCOUNT_AVAILABLE = True
except Exception:
    ETH_ACCOUNT_AVAILABLE = False


def generate_challenge_nonce() -> str:
    return secrets.token_hex(32)


def create_auth_message(nonce: str, user_id: int, domain: str = 'votewithoutdoubt.local',
                        purpose: str = 'WALLET_AUTHENTICATION',
                        chain_id: int = 1337, issued_at: Optional[str] = None,
                        expires_at: Optional[str] = None) -> str:
    now = datetime.utcnow()
    if issued_at is None:
        issued_at = now.isoformat() + 'Z'
    if expires_at is None:
        exp = now + timedelta(minutes=10)
        expires_at = exp.isoformat() + 'Z'
    msg = (
        f"Domain: {domain}\n"
        f"Purpose: {purpose}\n"
        f"UserID: {user_id}\n"
        f"Nonce: {nonce}\n"
        f"IssuedAt: {issued_at}\n"
        f"ExpiresAt: {expires_at}\n"
        f"ChainId: {chain_id}\n"
        "Message: This is a wallet ownership proof for authentication only. "
        "Do NOT sign this to vote."
    )
    return msg


def verify_signature(message: str, signature: str, expected_address: str):
    if not ETH_ACCOUNT_AVAILABLE:
        if not signature or len(signature) < 10:
            return False, None
        return False, None
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=signature)
        recovered = recovered.lower()
        expected = expected_address.lower()
        return recovered == expected, recovered
    except Exception:
        return False, None


def normalize_address(addr: str) -> str:
    if not addr:
        return addr
    return addr.lower()
