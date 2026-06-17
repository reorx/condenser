"""Telegram step-login endpoints (spec C2 — TG login)."""

from fastapi import APIRouter, Depends, HTTPException

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


@router.get('/dialogs')
async def list_dialogs(refresh: bool = False, tg: TgManager = Depends(get_tg)):
    """The account's joined broadcast channels (newest-activity first), with subscribed + unread flags."""
    if tg.service is None or not tg.service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    channels = await tg.list_joined_channels(force=refresh)
    subscribed = {s.channel_id for s in db.list_subscriptions()}
    return [
        {
            'channel_id': c.info.id,
            'title': c.info.title,
            'username': c.info.username,
            'subscribed': c.info.id in subscribed,
            'unread': c.unread_count,
        }
        for c in channels
    ]


@router.post('/refresh')
async def refresh_all(tg: TgManager = Depends(get_tg)):
    """Fan out a background recent-window re-pull for every enabled channel."""
    if tg.service is None or not tg.service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    queued = tg.refresh_all()
    return {'status': 'started', 'channels': queued}


@router.post('/refresh/{channel_id}')
async def refresh_channel(channel_id: int, tg: TgManager = Depends(get_tg)):
    """Synchronously re-pull one channel's recent window; returns the new-message count."""
    if tg.service is None or not tg.service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    new_count = await tg.refresh_channel(channel_id)
    return {'status': 'ok', 'new': new_count}


@router.post('/fetch-older/{channel_id}')
async def fetch_older(channel_id: int, count: int = 200, tg: TgManager = Depends(get_tg)):
    """Synchronously page further back into a channel's history; returns rows fetched."""
    if tg.service is None or not tg.service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    fetched = await tg.fetch_older(channel_id, count=count)
    return {'status': 'ok', 'fetched': fetched}


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
