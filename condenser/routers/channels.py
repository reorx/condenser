"""Channel metadata proxy — avatar images (on-demand, no disk persistence)."""

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import get_tg, require_auth
from ..tg import TgManager

router = APIRouter(prefix='/api/channels', tags=['channels'], dependencies=[Depends(require_auth)])


@router.get('/{channel_id}/avatar')
async def get_channel_avatar(channel_id: int, tg: TgManager = Depends(get_tg)):
    service = tg.service
    if service is None or not service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    # Resolve via @username when available — a bare id fails after a restart because
    # Telethon's StringSession doesn't persist its entity cache (see tg._channel_handle).
    result = await service.get_channel_photo(tg._channel_handle(channel_id))
    if result is None:
        raise HTTPException(status_code=404, detail='no channel photo')
    data, mime = result
    # Avatars are tiny and change rarely; let the browser cache. Server keeps nothing on disk.
    return Response(content=data, media_type=mime, headers={'Cache-Control': 'private, max-age=86400'})
