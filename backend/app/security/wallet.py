"""
Wallet Security - Phase 4 (remediated)
Vote Without Doubt - Backend

Ethereum signature verification for wallet *ownership proof*.

Scope boundary
--------------
This module proves that the user controls a private key. It is deliberately NOT
used to sign a vote. The challenge message contains no candidate, no ballot and
no vote data, and states so explicitly so a signature captured here can never be
replayed as a vote authorisation.

Design
------
* The signed message is domain separated and binds: domain, purpose, voter id,
  election id, chain id, contract context, nonce, issued-at and expires-at. Every
  one of those values is supplied by the server from configuration or persisted
  challenge state - never by the browser.
* Verification recovers the signing address from the real Ethereum signature and
  compares it to the claimed address in constant time.
* If ``eth_account`` cannot be imported, verification raises
  :class:`WalletVerificationUnavailable` instead of quietly reporting an invalid
  signature. A missing cryptographic dependency is an operational fault and must
  be visible; it must never be disguised as a user error.

``personal_sign`` compatibility
-------------------------------
MetaMask's ``personal_sign`` signs the EIP-191 personal-sign hash of a UTF-8
string. Verification therefore uses ``encode_defunct(text=...)`` followed by
``Account.recover_message``, which is the matching server-side primitive.
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

#: Hard failure if the real Ethereum primitives are unavailable.
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from eth_utils import is_hex_address, to_checksum_address

    ETH_ACCOUNT_AVAILABLE = True
    ETH_ACCOUNT_IMPORT_ERROR: Optional[BaseException] = None
except Exception as _exc:  # pragma: no cover - exercised only on a broken env
    Account = None  # type: ignore[assignment]
    encode_defunct = None  # type: ignore[assignment]
    is_hex_address = None  # type: ignore[assignment]
    to_checksum_address = None  # type: ignore[assignment]
    ETH_ACCOUNT_AVAILABLE = False
    ETH_ACCOUNT_IMPORT_ERROR = _exc

#: Explicit purpose constant. Bound into every challenge and required on lookup.
WALLET_AUTH_PURPOSE = 'WALLET_AUTHENTICATION'

#: Maximum invalid signature attempts before a challenge is burned.
MAX_SIGNATURE_ATTEMPTS = 5

#: Challenge lifetime.
CHALLENGE_TTL_MINUTES = 10

#: ``0x`` followed by exactly 40 hex characters.
ETH_ADDRESS_PATTERN = re.compile(r'^0x[0-9a-fA-F]{40}$')

#: Sentinel used until the voting contract exists (Phase 6). It is still a valid
#: address so the context cannot silently change shape later.
NO_CONTRACT_ADDRESS = '0x0000000000000000000000000000000000000000'

DISCLAIMER = (
    'This is a wallet ownership proof for authentication only.\n'
    'Do NOT sign this to vote.'
)


class WalletVerificationUnavailable(RuntimeError):
    """Raised when the Ethereum verification primitives cannot be used.

    Distinct from an invalid signature so the caller can return an operator
    facing 503 instead of a misleading 400.
    """


class InvalidWalletAddress(ValueError):
    """Raised for a malformed Ethereum address."""


def require_wallet_verification() -> None:
    """Raise :class:`WalletVerificationUnavailable` unless verification works."""
    if not ETH_ACCOUNT_AVAILABLE:
        raise WalletVerificationUnavailable(
            'Ethereum signature verification is unavailable: eth-account could not '
            f'be imported ({ETH_ACCOUNT_IMPORT_ERROR!r}). Wallet authentication '
            'is disabled until the dependency is installed.'
        )


def generate_challenge_nonce() -> str:
    """256 bits of cryptographically strong randomness, hex encoded (64 chars)."""
    return secrets.token_hex(32)


def is_valid_eth_address(address: object) -> bool:
    """True for ``0x`` + exactly 40 hex characters (or a valid checksum address)."""
    if not isinstance(address, str):
        return False
    candidate = address.strip()
    if not ETH_ADDRESS_PATTERN.match(candidate):
        return False
    if not ETH_ACCOUNT_AVAILABLE:
        return True
    return bool(is_hex_address(candidate))


def normalize_address(address: object) -> str:
    """Validate and normalise an Ethereum address for comparison and storage.

    Raises :class:`InvalidWalletAddress` for anything malformed, so arbitrary
    strings can never reach the database. Comparison is done on the lowercased
    form, so EIP-55 checksum casing cannot be used to bypass a uniqueness or
    binding check.
    """
    if not isinstance(address, str):
        raise InvalidWalletAddress('Wallet address must be a string')
    candidate = address.strip()
    if not candidate:
        raise InvalidWalletAddress('Wallet address must not be empty')
    if not ETH_ADDRESS_PATTERN.match(candidate):
        raise InvalidWalletAddress(
            'Wallet address must be 0x followed by 40 hexadecimal characters')
    if ETH_ACCOUNT_AVAILABLE and not is_hex_address(candidate):
        raise InvalidWalletAddress('Wallet address is not a valid Ethereum address')
    return candidate.lower()


def addresses_equal(left: str, right: str) -> bool:
    """Constant-time, case-insensitive address comparison."""
    try:
        return hmac.compare_digest(normalize_address(left), normalize_address(right))
    except InvalidWalletAddress:
        return False


def to_checksum(address: str) -> Optional[str]:
    """EIP-55 checksum form for display, or ``None`` when unavailable."""
    if not ETH_ACCOUNT_AVAILABLE:
        return None
    try:
        return to_checksum_address(normalize_address(address))
    except (InvalidWalletAddress, ValueError):
        return None


def create_auth_message(
    nonce: str,
    user_id: int,
    election_id: str,
    chain_id: int,
    contract_address: str = NO_CONTRACT_ADDRESS,
    domain: str = 'votewithoutdoubt.local',
    purpose: str = WALLET_AUTH_PURPOSE,
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> str:
    """Build the exact message the wallet signs.

    Every argument is server-authoritative. Candidate or vote data is never
    included by design.
    """
    now = datetime.utcnow()
    if issued_at is None:
        issued_at = now.isoformat() + 'Z'
    if expires_at is None:
        expires_at = (now + timedelta(minutes=CHALLENGE_TTL_MINUTES)).isoformat() + 'Z'

    return (
        f'Domain: {domain}\n'
        f'Purpose: {purpose}\n'
        f'UserID: {user_id}\n'
        f'ElectionID: {election_id}\n'
        f'ChainId: {chain_id}\n'
        f'Contract: {contract_address}\n'
        f'Nonce: {nonce}\n'
        f'IssuedAt: {issued_at}\n'
        f'ExpiresAt: {expires_at}\n'
        '\n'
        f'{DISCLAIMER}'
    )


def verify_signature(
    message: str,
    signature: str,
    expected_address: str,
) -> Tuple[bool, Optional[str]]:
    """Recover the signer of ``message`` and compare it to ``expected_address``.

    Returns ``(ok, recovered_address)``. Raises
    :class:`WalletVerificationUnavailable` when the verification primitives are
    missing, so a dependency fault is never reported as a bad signature.
    """
    require_wallet_verification()

    if not isinstance(message, str) or not message:
        return False, None
    if not isinstance(signature, str) or not signature:
        return False, None
    # A secp256k1 signature is 65 bytes; reject anything else before decoding.
    raw = signature[2:] if signature.startswith('0x') else signature
    if len(raw) != 130:
        return False, None

    try:
        expected = normalize_address(expected_address)
    except InvalidWalletAddress:
        return False, None

    try:
        encoded = encode_defunct(text=message)
        recovered = Account.recover_message(encoded, signature=signature)
    except Exception:
        # Malformed signature, bad recovery point, or a signature produced over a
        # different message. All are ordinary user errors.
        return False, None

    return addresses_equal(recovered, expected), recovered
