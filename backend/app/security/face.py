"""
Face biometric security primitives - Phase 5

Two responsibilities:

1. Unpredictable liveness-challenge material.
2. Authenticated encryption of face embedding templates at rest.

Security properties enforced here (all fail closed, none fall back):

* ``FACE_ENCRYPTION_KEY`` must be configured explicitly. There is no
  random/ephemeral key generation and no plaintext fallback. Production
  refuses to boot without it (see ``app/config/config.py``).
* Embeddings are stored in a versioned envelope so a key can be rotated
  without losing existing templates.
* ``decrypt_embedding`` raises on a wrong key, a tampered ciphertext or an
  unknown envelope version. It never returns the ciphertext or the
  plaintext-on-error behaviour of the previous implementation.
"""

import hmac
import os
import secrets
from hashlib import sha256
from hmac import compare_digest
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

# Envelope format:  b'VWDF1' | 1-byte key-id length | key-id | Fernet token
_ENVELOPE_MAGIC = b'VWDF1'
_ENVELOPE_VERSION = 1
_KEY_ID_MAX_BYTES = 32

CHALLENGE_ID_BYTES = 32      # 256 bits of entropy
CHALLENGE_NONCE_BYTES = 32   # 256 bits of entropy


class FaceSecurityError(RuntimeError):
    """Base class for biometric security failures."""


class FaceKeyUnavailable(FaceSecurityError):
    """No usable face encryption key is configured."""


class FaceCiphertextError(FaceSecurityError):
    """Ciphertext could not be authenticated (wrong key or tampered data)."""


class FaceIntegrityError(FaceSecurityError):
    """A stored challenge row failed its integrity check."""


def generate_face_challenge_id() -> str:
    """Return a 256-bit hex challenge identifier."""
    return secrets.token_hex(CHALLENGE_ID_BYTES)


def generate_challenge_nonce() -> str:
    """Return a 256-bit hex nonce bound into the challenge integrity MAC."""
    return secrets.token_hex(CHALLENGE_NONCE_BYTES)


# ---------------------------------------------------------------------------
# Key material
# ---------------------------------------------------------------------------

def _parse_key_map() -> Dict[str, bytes]:
    """Return {key_id: fernet_key_bytes} from the environment.

    ``FACE_ENCRYPTION_KEYS`` is an optional JSON object used for rotation,
    e.g. ``{"v1": "<key>", "v2": "<key>"}``. The active key is always the one
    named by ``FACE_ENCRYPTION_KEY_ID`` (default ``v1``), which may live
    either in that map or directly in ``FACE_ENCRYPTION_KEY``.
    """
    key_id = (os.getenv('FACE_ENCRYPTION_KEY_ID') or 'v1').strip()
    material: Dict[str, bytes] = {}

    raw_map = os.getenv('FACE_ENCRYPTION_KEYS')
    if raw_map:
        import json
        try:
            parsed = json.loads(raw_map)
        except ValueError as error:
            raise FaceKeyUnavailable(
                'FACE_ENCRYPTION_KEYS is not valid JSON; refusing to start.'
            ) from error
        if not isinstance(parsed, dict) or not parsed:
            raise FaceKeyUnavailable(
                'FACE_ENCRYPTION_KEYS must be a non-empty JSON object of '
                '{"key_id": "<fernet key>"}.'
            )
        for name, value in parsed.items():
            material[str(name)] = _coerce_key(value)

    active = os.getenv('FACE_ENCRYPTION_KEY')
    if active:
        material[key_id] = _coerce_key(active)

    if key_id not in material:
        raise FaceKeyUnavailable(
            f'FACE_ENCRYPTION_KEY is not set for key id {key_id!r}. Biometric '
            'templates cannot be encrypted; refusing to operate.'
        )
    return material


def _coerce_key(value) -> bytes:
    if isinstance(value, bytes):
        candidate = value
    else:
        candidate = str(value).strip().encode('ascii', 'strict')
    # Validate eagerly so a bad key fails at configuration time, not at the
    # moment a user's biometric template is being written.
    Fernet(candidate)
    return candidate


def active_key_id() -> str:
    return (os.getenv('FACE_ENCRYPTION_KEY_ID') or 'v1').strip()


def _fernet_for(key_id: str) -> Fernet:
    material = _parse_key_map()
    if key_id not in material:
        raise FaceKeyUnavailable(
            f'No face encryption key available for key id {key_id!r}.'
        )
    return Fernet(material[key_id])


# ---------------------------------------------------------------------------
# Embedding envelope
# ---------------------------------------------------------------------------

def encrypt_embedding(plaintext: bytes, key_id: Optional[str] = None) -> bytes:
    """Encrypt an embedding into a versioned envelope.

    Raises ``FaceKeyUnavailable`` when no key is configured. It never
    returns the input unchanged.
    """
    if not isinstance(plaintext, (bytes, bytearray)) or not plaintext:
        raise FaceSecurityError('Embedding payload must be non-empty bytes.')
    key_id = (key_id or active_key_id()).strip()
    if not key_id or len(key_id.encode('utf-8')) > _KEY_ID_MAX_BYTES:
        raise FaceSecurityError('Invalid encryption key id.')
    token = _fernet_for(key_id).encrypt(bytes(plaintext))
    key_bytes = key_id.encode('utf-8')
    return _ENVELOPE_MAGIC + bytes([_ENVELOPE_VERSION, len(key_bytes)]) + key_bytes + token


def decrypt_embedding(blob: bytes) -> bytes:
    """Authenticate and decrypt an envelope.

    Raises on unknown versions, malformed envelopes, wrong keys and any
    modification of the ciphertext.
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) <= len(_ENVELOPE_MAGIC) + 2:
        raise FaceCiphertextError('Encrypted embedding envelope is malformed.')
    raw = bytes(blob)
    if raw[: len(_ENVELOPE_MAGIC)] != _ENVELOPE_MAGIC:
        raise FaceCiphertextError('Encrypted embedding envelope is malformed.')
    cursor = len(_ENVELOPE_MAGIC)
    version = raw[cursor]
    cursor += 1
    if version != _ENVELOPE_VERSION:
        raise FaceCiphertextError(
            f'Unsupported face template envelope version {version}.'
        )
    key_len = raw[cursor]
    cursor += 1
    if key_len == 0 or key_len > _KEY_ID_MAX_BYTES or cursor + key_len > len(raw):
        raise FaceCiphertextError('Encrypted embedding envelope is malformed.')
    key_id = raw[cursor:cursor + key_len].decode('utf-8', 'strict')
    token = raw[cursor + key_len:]
    try:
        return _fernet_for(key_id).decrypt(token)
    except InvalidToken as error:
        raise FaceCiphertextError(
            'Face template failed authentication (wrong key or tampered data).'
        ) from error


def envelope_key_id(blob: bytes) -> str:
    """Return the key id recorded in an envelope without decrypting it."""
    raw = bytes(blob or b'')
    if raw[: len(_ENVELOPE_MAGIC)] != _ENVELOPE_MAGIC or len(raw) < len(_ENVELOPE_MAGIC) + 2:
        raise FaceCiphertextError('Encrypted embedding envelope is malformed.')
    key_len = raw[len(_ENVELOPE_MAGIC) + 1]
    start = len(_ENVELOPE_MAGIC) + 2
    if key_len == 0 or start + key_len > len(raw):
        raise FaceCiphertextError('Encrypted embedding envelope is malformed.')
    return raw[start:start + key_len].decode('utf-8', 'strict')


# ---------------------------------------------------------------------------
# Challenge row integrity
# ---------------------------------------------------------------------------

def _integrity_key() -> bytes:
    """Derive the challenge-MAC key from SECRET_KEY.

    Uses HKDF-style separation so the biometric key and the application
    secret never serve each other's purpose.
    """
    secret = os.getenv('SECRET_KEY') or os.getenv('TESTING_SECRET_KEY')
    if not secret:
        raise FaceSecurityError(
            'SECRET_KEY is not set; cannot authenticate face challenge rows.'
        )
    return sha256(b'vwdf-face-challenge-v1' + str(secret).encode('utf-8')).digest()


def challenge_mac(challenge_id: str, user_id: int, session_id: str,
                  sequence: str, nonce: str, expires_at_iso: str) -> str:
    """MAC over the server-authoritative fields of a challenge row."""
    import hmac as _hmac

    message = '|'.join([
        str(challenge_id), str(int(user_id)), str(session_id), str(sequence),
        str(nonce), str(expires_at_iso),
    ]).encode('utf-8')
    return _hmac.new(_integrity_key(), message, sha256).hexdigest()


def verify_challenge_mac(expected: str, provided: str) -> bool:
    return hmac.compare_digest(str(expected or ''), str(provided or ''))


def constant_time_equals(left: str, right: str) -> bool:
    return compare_digest(str(left or ''), str(right or ''))
