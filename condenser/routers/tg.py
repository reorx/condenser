"""Telegram step-login endpoints (spec C2 — TG login)."""

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_tg, require_auth
from ..tg import TgManager
from ..types import CodeBody, PasswordBody, PhoneBody

router = APIRouter(prefix='/api/tg', tags=['tg'], dependencies=[Depends(require_auth)])


@router.get('/status')
def status(tg: TgManager = Depends(get_tg)):
    # phone is surfaced additively (only when stored) for the Settings dialog.
    out: dict = {'status': tg.status()}
    row = db.get_tg_session()
    if row is not None and row.phone:
        out['phone'] = row.phone
    return out


@router.post('/send-code')
async def send_code(body: PhoneBody, tg: TgManager = Depends(get_tg)):
    await tg.send_code(body.phone)
    return {'status': tg.status()}


@router.post('/sign-in')
async def sign_in(body: CodeBody, tg: TgManager = Depends(get_tg)):
    res = await tg.sign_in(body.code)
    return {'status': tg.status(), 'result': res.status}


@router.post('/sign-in-2fa')
async def sign_in_2fa(body: PasswordBody, tg: TgManager = Depends(get_tg)):
    res = await tg.sign_in_2fa(body.password)
    return {'status': tg.status(), 'result': res.status}


@router.post('/logout')
async def logout(tg: TgManager = Depends(get_tg)):
    await tg.logout()
    return {'status': tg.status()}
