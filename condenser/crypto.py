"""Symmetric encryption + cookie signing derived from CONDENSER_SECRET_KEY.

The StringSession is account-equivalent, so it is encrypted at rest (D2). Both the
Fernet key and the cookie signer derive deterministically from the single secret.
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from itsdangerous import BadSignature, TimestampSigner


def _fernet(secret_key: str) -> Fernet:
    """Build a Fernet from an arbitrary secret string (sha256 -> urlsafe b64 key)."""
    digest = hashlib.sha256(secret_key.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_session(secret_key: str, plaintext: str) -> bytes:
    """Encrypt a StringSession string for storage."""
    return _fernet(secret_key).encrypt(plaintext.encode('utf-8'))


def decrypt_session(secret_key: str, token: bytes) -> str:
    """Decrypt a stored StringSession blob."""
    return _fernet(secret_key).decrypt(bytes(token)).decode('utf-8')


def hash_device_token(token: str) -> str:
    """sha256 hex of a raw device token — only the hash is stored (spec: devices table)."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


_COOKIE_SALT = 'condenser-app-session'


def sign_cookie(secret_key: str, value: str = 'authed') -> str:
    """Produce a signed, timestamped cookie value."""
    signer = TimestampSigner(secret_key, salt=_COOKIE_SALT)
    return signer.sign(value.encode('utf-8')).decode('utf-8')


def verify_cookie(secret_key: str, token: str, max_age: int = 30 * 24 * 3600) -> bool:
    """Validate a signed cookie value (default 30-day lifetime)."""
    signer = TimestampSigner(secret_key, salt=_COOKIE_SALT)
    try:
        signer.unsign(token, max_age=max_age)
    except BadSignature:
        return False
    return True
