"""App password login/logout + device-token management (spec C2 — auth)."""

import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import db
from ..auth import COOKIE_MAX_AGE, COOKIE_NAME, get_settings_dep, require_cookie_auth
from ..config import Settings
from ..crypto import hash_device_token, sign_cookie
from ..types import DeviceCreateBody, LoginBody

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


# Device endpoints require the cookie session specifically: a stolen device token
# must not be able to mint or revoke tokens.


@router.post('/device', dependencies=[Depends(require_cookie_auth)])
def create_device(body: DeviceCreateBody):
    """Issue a device Bearer token; the raw token appears in this response only."""
    token = secrets.token_urlsafe(32)
    device = db.create_device(body.name, hash_device_token(token))
    return {'id': device.id, 'name': device.name, 'token': token}


@router.get('/devices', dependencies=[Depends(require_cookie_auth)])
def list_devices():
    return [
        {
            'id': d.id,
            'name': d.name,
            'created_at': d.created_at.isoformat(),
            'last_seen_at': d.last_seen_at.isoformat() if d.last_seen_at else None,
        }
        for d in db.list_devices()
    ]


@router.delete('/devices/{device_id}', dependencies=[Depends(require_cookie_auth)])
def delete_device(device_id: int):
    if not db.delete_device(device_id):
        raise HTTPException(status_code=404, detail='device not found')
    return {'ok': True}
