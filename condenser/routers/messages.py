"""Live message actions: engagement stats + republish to the user's own channel.

Split from ``preview.py`` (same ``/api/messages`` prefix) because everything here goes
through TgManager's real-time Telethon calls, while preview.py has no Telegram dependency.
"""

from fastapi import APIRouter, Depends, HTTPException
from telethon.errors import FloodWaitError, UnauthorizedError

from ..auth import get_tg, require_auth
from ..tg import MessageStats, TelegramMessageNotFound, TgManager
from ..types import ForwardMessageBody

router = APIRouter(prefix='/api/messages', tags=['messages'], dependencies=[Depends(require_auth)])

_UNAUTHORIZED = HTTPException(status_code=503, detail='telegram not authorized')


def _require_authorized(tg: TgManager) -> None:
    if tg.service is None or not tg.service.is_authorized:
        raise _UNAUTHORIZED


def _flood(exc: FloodWaitError) -> HTTPException:
    return HTTPException(status_code=429, detail='rate limited by telegram', headers={'Retry-After': str(exc.seconds)})


@router.get('/{channel_id}/{message_id}/stats')
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


@router.post('/{channel_id}/{message_id}/forward')
async def forward_message(channel_id: int, message_id: int, body: ForwardMessageBody, tg: TgManager = Depends(get_tg)):
    """Forward (empty comment) or quote-post (with comment) into ``app_meta.forward_channel``."""
    _require_authorized(tg)
    try:
        return await tg.forward_message(channel_id, message_id, body.comment)
    except LookupError:
        raise HTTPException(status_code=422, detail='forward target channel not configured')
    except TelegramMessageNotFound:
        raise HTTPException(status_code=404, detail='message not found')
    except FloodWaitError as e:
        raise _flood(e)
    except UnauthorizedError:
        raise _UNAUTHORIZED
