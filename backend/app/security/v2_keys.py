"""Authenticated encryption at rest for V2 election private key shares."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, has_app_context


class V2KeyEncryptionError(RuntimeError):
    """Raised when V2 officer key material cannot be encrypted or decrypted safely."""


_ENC_PREFIX = "enc:v1:"


def _derive_fernet_from_secret(raw_secret: str, salt_prefix: str) -> Fernet:
    digest = hashlib.sha256(f"{salt_prefix}|{raw_secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _resolve_fernet_candidates() -> list[Fernet]:
    """Return configured Fernet instances in priority order (explicit key, then isolated master derivation)."""
    v2_key = None
    master_key = None

    if has_app_context():
        v2_key = current_app.config.get("V2_KEY_ENCRYPTION_KEY")
        master_key = current_app.config.get("PSEUDONYM_MASTER_KEY")

    v2_key = v2_key or os.getenv("V2_KEY_ENCRYPTION_KEY")
    master_key = master_key or os.getenv("PSEUDONYM_MASTER_KEY")

    ciphers: list[Fernet] = []
    if v2_key and str(v2_key).strip():
        raw_v2 = str(v2_key).strip()
        try:
            ciphers.append(Fernet(raw_v2.encode("utf-8")))
        except Exception:
            ciphers.append(_derive_fernet_from_secret(raw_v2, "VWD_V2_EXPLICIT_KEY_V1"))

    if master_key and str(master_key).strip():
        ciphers.append(_derive_fernet_from_secret(str(master_key).strip(), "VWD_V2_KEY_WRAP_V1"))

    if not ciphers:
        raise V2KeyEncryptionError(
            "V2_KEY_ENCRYPTION_KEY (or PSEUDONYM_MASTER_KEY) must be configured to protect V2 officer keys at rest."
        )
    return ciphers


def encrypt_v2_scalar(scalar: int) -> str:
    """Encrypt a BN254 scalar integer using authenticated Fernet encryption."""
    cipher = _resolve_fernet_candidates()[0]
    token = cipher.encrypt(str(int(scalar)).encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_v2_scalar(stored_value: Any) -> int:
    """Decrypt an encrypted V2 scalar token, or parse legacy plaintext integer/hex strings."""
    if stored_value is None:
        raise V2KeyEncryptionError("Missing V2 private key share.")

    val = str(stored_value).strip()
    if not val:
        raise V2KeyEncryptionError("Empty V2 private key share.")

    if val.startswith(_ENC_PREFIX):
        token = val[len(_ENC_PREFIX):].encode("utf-8")
        ciphers = _resolve_fernet_candidates()
        for cipher in ciphers:
            try:
                plaintext = cipher.decrypt(token).decode("utf-8").strip()
                return int(plaintext, 16) if plaintext.startswith(("0x", "0X")) else int(plaintext)
            except InvalidToken:
                continue
        raise V2KeyEncryptionError("Failed to authenticate or decrypt encrypted V2 private key share.")

    # Legacy compatibility for unencrypted historical Election 9/11/12 records & older test fixtures
    return int(val, 16) if val.startswith(("0x", "0X")) else int(val)

