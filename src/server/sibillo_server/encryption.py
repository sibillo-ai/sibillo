"""Encryption of the API keys of model configurations (MOD-002, ADR-0051).

AES-256-GCM under the key of `SIBILLO_SECRET_KEY`. The identifier of the
configuration is the associated data, so a ciphertext copied to another
configuration does not decrypt.
"""

from __future__ import annotations

import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


def encrypt(key: bytes, configuration_id: uuid.UUID, plaintext: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), configuration_id.bytes)


def decrypt(key: bytes, configuration_id: uuid.UUID, ciphertext: bytes) -> str:
    nonce, sealed = ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, sealed, configuration_id.bytes).decode()


def _labelled(row_id: uuid.UUID, label: str) -> bytes:
    return row_id.bytes + b":" + label.encode()


def encrypt_labelled(key: bytes, row_id: uuid.UUID, label: str, plaintext: str) -> bytes:
    """Encrypt one of a row's secrets, with the row's ID and the secret's label as associated data (ADR-0099)."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), _labelled(row_id, label))


def decrypt_labelled(key: bytes, row_id: uuid.UUID, label: str, ciphertext: bytes) -> str:
    nonce, sealed = ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, sealed, _labelled(row_id, label)).decode()
