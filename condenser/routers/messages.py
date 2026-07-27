"""Live message actions: engagement stats + republish to the user's own channel.

Split from ``preview.py`` (which shares the ``/api/messages`` prefix) because
everything here goes through TgManager's real-time Telethon calls, while
preview.py has no Telegram dependency.

Forwarding is **source-generic** since 2026-07-27: ``POST /api/forward`` takes an
item key like the rest of the read/hide/feedback family. The old TG-only path is
kept as a thin shell so iOS builds already on people's phones keep working when
the server upgrades ahead of the app.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from telethon.errors import FloodWaitError, UnauthorizedError

from .. import forward
from ..auth import get_tg, require_auth
from ..items import ItemKey
from ..tg import MessageStats, TelegramMessageNotFound, TgManager
from ..types import ForwardItemBody, ForwardMessageBody
from .common import parse_key_or_422

router = APIRouter(prefix='/api', tags=['messages'], dependencies=[Depends(require_auth)])

_UNAUTHORIZED = HTTPException(status_code=503, detail='telegram not authorized')


def _require_authorized(tg: TgManager) -> None:
    if tg.service is None or not tg.service.is_authorized:
        raise _UNAUTHORIZED


def _flood(exc: FloodWaitError) -> HTTPException:
    return HTTPException(status_code=429, detail='rate limited by telegram', headers={'Retry-After': str(exc.seconds)})


async def _forward(tg: TgManager, key: ItemKey, comment: Optional[str]) -> dict:
    """The one forward path; both endpoints translate its failures identically."""
    _require_authorized(tg)
    try:
        return await tg.forward_item(key, comment)
    except LookupError:
        raise HTTPException(status_code=422, detail='forward target channel not configured')
    except forward.ItemNotFound:
        raise HTTPException(status_code=404, detail='item not found')
    except TelegramMessageNotFound:
        raise HTTPException(status_code=404, detail='message not found')
    except FloodWaitError as e:
        raise _flood(e)
    except UnauthorizedError:
        raise _UNAUTHORIZED


@router.get('/messages/{channel_id}/{message_id}/stats')
async def message_stats(channel_id: int, message_id: int, tg: TgManager = Depends(get_tg)) -> MessageStats:
    """Views / forwards / reactions, read live from Telegram (never cached or stored)."""
    _require_authorized(tg)
    try:
        return await tg.get_message_stats(channel_id, message_id)
    except TelegramMessageNotFound:
        raise HTTPException(status_code=404, detail='message not found')
    except FloodWaitError as e:
        raise _flood(e)
    except UnauthorizedError:
        raise _UNAUTHORIZED


@router.post('/forward')
async def forward_item(body: ForwardItemBody, tg: TgManager = Depends(get_tg)) -> dict:
    """Publish any item into ``app_meta.forward_channel`` (TG natively, others rendered)."""
    return await _forward(tg, parse_key_or_422(body.key), body.comment)


@router.post('/messages/{channel_id}/{message_id}/forward')
async def forward_message(
    channel_id: int, message_id: int, body: ForwardMessageBody, tg: TgManager = Depends(get_tg)
) -> dict:
    """Legacy TG-only shell over ``/api/forward`` (pre-2026-07-27 clients)."""
    return await _forward(tg, ItemKey(source='telegram', ref1=channel_id, ref2=message_id), body.comment)
