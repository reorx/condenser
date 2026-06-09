"""App-level auth: single password gate + signed session cookie (spec C4 / D8)."""

from fastapi import HTTPException, Request

from .config import Settings, get_settings
from .crypto import verify_cookie
from .tg import TgManager

COOKIE_NAME = 'condenser_session'
COOKIE_MAX_AGE = 30 * 24 * 3600


def require_auth(request: Request) -> None:
    """Dependency: reject requests without a valid signed session cookie."""
    settings = get_settings()
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_cookie(settings.condenser_secret_key, token, max_age=COOKIE_MAX_AGE):
        raise HTTPException(status_code=401, detail='unauthorized')


def get_tg(request: Request) -> TgManager:
    """Dependency: the process-wide TgManager from app state."""
    return request.app.state.tg


def get_settings_dep() -> Settings:
    return get_settings()
