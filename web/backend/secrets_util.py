"""Encryption at rest for stored credentials -- Dispatcharr connection API
tokens are real, working credentials (not something we ever need a one-way
hash of, since the app has to send them back out to actually connect), so
this uses reversible Fernet encryption rather than hashing.

Ported near-verbatim from VOD & DVR Manager's secrets_util.py (no
VOD-specific logic in the original). The key lives inside config.json (see
config.get_or_create_encryption_key) rather than its own file, so it rides
along with config's existing backup/restore/reset lifecycle instead of being
a separate thing a restore onto a fresh instance could silently leave
behind.
"""

import base64
import binascii
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

import config

_fernet_instance: Fernet | None = None


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = Fernet(config.get_or_create_encryption_key())
    return _fernet_instance


def encrypt_value(plaintext: str | None) -> str | None:
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(value: str | None) -> str | None:
    """Falls back to returning the raw value on InvalidToken -- covers rows
    written before encryption existed, so upgrading doesn't break existing
    connections."""
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return value


def is_encrypted(value: str | None) -> bool:
    if not value:
        return True  # nothing to migrate
    try:
        _fernet().decrypt(value.encode())
        return True
    except InvalidToken:
        return False


def looks_like_fernet_token(value: str | None) -> bool:
    """Structural check for "is this a Fernet token AT ALL" -- deliberately
    key-INDEPENDENT, unlike is_encrypted() (which only recognizes a token
    encrypted under the CURRENT key). See VOD & DVR Manager's secrets_util.py
    for the full reasoning -- ported unchanged."""
    if not value:
        return False
    try:
        raw = base64.urlsafe_b64decode(value.encode())
    except (binascii.Error, ValueError):
        return False
    return len(raw) >= 73 and raw[0] == 0x80 and (len(raw) - 57) % 16 == 0


# PBKDF2-HMAC-SHA256, 260k iterations -- same scheme/cost config.py's admin
# login uses.
_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Returns (salt, hash). Pass an existing salt to verify against a known
    hash; omit it to generate a new salt for a brand-new password."""
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return salt, hashed


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, candidate = hash_password(password, salt)
    return secrets.compare_digest(candidate.encode(), expected_hash.encode())
