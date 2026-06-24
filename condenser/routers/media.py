"""On-demand media proxy (spec C2 / D4) — streams from Telegram, never persists."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..auth import get_tg, require_auth
from ..tg import TgManager

router = APIRouter(prefix='/api/media', tags=['media'], dependencies=[Depends(require_auth)])


@router.get('/{channel_id}/{message_id}')
async def get_media(channel_id: int, message_id: int, thumb: bool = False, tg: TgManager = Depends(get_tg)):
    service = tg.service
    if service is None or not service.is_authorized:
        raise HTTPException(status_code=503, detail='telegram not authorized')
    # Resolve via @username when available: a bare id fails after a restart because
    # Telethon's StringSession doesn't persist its entity cache (see tg._channel_handle).
    stream, mime = await service.get_media(tg._channel_handle(channel_id), message_id, thumb=thumb)
    # Browser may cache; the server keeps nothing on disk.
    headers = {'Cache-Control': 'private, max-age=86400'}
    return StreamingResponse(stream, media_type=mime, headers=headers)
