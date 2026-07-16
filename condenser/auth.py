"""App-level auth: single password gate + signed session cookie, or a device
Bearer token issued via the /authorize flow (spec C4 / D8 + device-token spec)."""

from fastapi import HTTPException, Request

from . import db
from .config import Settings, get_settings
from .crypto import hash_device_token, verify_cookie
from .tg import TgManager

COOKIE_NAME = 'condenser_session'
COOKIE_MAX_AGE = 30 * 24 * 3600


def require_cookie_auth(request: Request) -> None:
    """Dependency: reject requests without a valid signed session cookie.

    Device-management endpoints use this directly so a stolen Bearer token
    cannot mint or revoke tokens.
    """
    settings = get_settings()
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_cookie(settings.condenser_secret_key, token, max_age=COOKIE_MAX_AGE):
        raise HTTPException(status_code=401, detail='unauthorized')


def require_auth(request: Request) -> None:
    """Dependency: accept a cookie session or a device Bearer token.

    A present Bearer header decides alone — no cookie fallback, so a revoked or
    wrong token surfaces as 401 instead of being masked by a browser cookie.
    """
    header = request.headers.get('Authorization')
    if header and header.startswith('Bearer '):
        device = db.get_device_by_token_hash(hash_device_token(header[7:]))
        if device is None:
            raise HTTPException(status_code=401, detail='unauthorized')
        db.touch_device_last_seen(device)
        return
    require_cookie_auth(request)


def get_tg(request: Request) -> TgManager:
    """Dependency: the process-wide TgManager from app state."""
    return request.app.state.tg


def get_settings_dep() -> Settings:
    return get_settings()
