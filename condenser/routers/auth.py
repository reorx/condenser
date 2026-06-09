"""App password login/logout (spec C2 — auth)."""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import COOKIE_MAX_AGE, COOKIE_NAME, get_settings_dep
from ..config import Settings
from ..crypto import sign_cookie
from ..types import LoginBody

router = APIRouter(prefix='/api/auth', tags=['auth'])


@router.post('/login')
def login(body: LoginBody, response: Response, settings: Settings = Depends(get_settings_dep)):
    """Validate the app password and issue a signed session cookie."""
    if not hmac.compare_digest(body.password, settings.condenser_app_password):
        raise HTTPException(status_code=401, detail='invalid password')
    token = sign_cookie(settings.condenser_secret_key)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite='lax', max_age=COOKIE_MAX_AGE)
    return {'ok': True}


@router.post('/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {'ok': True}
