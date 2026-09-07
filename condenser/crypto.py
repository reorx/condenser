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
    return _verify(secret_key, _COOKIE_SALT, token, max_age)


# --- purifier (plan 2026-09-07 §2): a 5-minute ticket buys a 30-day reader cookie ---
#
# Three salts, none interchangeable: a ticket must not pass as the reader cookie
# (it travels in a URL, so it leaks into logs and history), the reader cookie must
# not pass as the app session (it only opens /p and /pa, never /api), and the app
# session cookie is not a ticket. Pinned by tests/test_purifier.py.

_PURIFIER_TICKET_SALT = 'condenser-purifier-ticket'
_PURIFIER_READER_SALT = 'condenser-purifier-reader'
PURIFIER_TICKET_MAX_AGE = 300
READER_COOKIE_MAX_AGE = 30 * 24 * 3600


def sign_purifier_ticket(secret_key: str) -> str:
    """A one-shot, URL-borne ticket the iOS app appends as ``_pt=`` (5-minute lifetime)."""
    return TimestampSigner(secret_key, salt=_PURIFIER_TICKET_SALT).sign(b'ticket').decode('utf-8')


def verify_purifier_ticket(secret_key: str, token: str, max_age: int | None = None) -> bool:
    age = PURIFIER_TICKET_MAX_AGE if max_age is None else max_age
    return _verify(secret_key, _PURIFIER_TICKET_SALT, token, age)


def sign_reader_cookie(secret_key: str) -> str:
    """The ``condenser_reader`` cookie value a valid ticket is exchanged for."""
    return TimestampSigner(secret_key, salt=_PURIFIER_READER_SALT).sign(b'reader').decode('utf-8')


def verify_reader_cookie(secret_key: str, token: str, max_age: int = READER_COOKIE_MAX_AGE) -> bool:
    return _verify(secret_key, _PURIFIER_READER_SALT, token, max_age)


def _verify(secret_key: str, salt: str, token: str, max_age: int) -> bool:
    signer = TimestampSigner(secret_key, salt=salt)
    try:
        signer.unsign(token, max_age=max_age)
    except BadSignature:  # SignatureExpired is a BadSignature too
        return False
    return True
