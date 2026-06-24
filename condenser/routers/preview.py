"""Link-preview endpoints: a generic single-URL preview, a per-message batch, and
an SSRF-guarded image proxy so preview thumbnails never leak the reader's IP."""

from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse

from .. import preview
from ..auth import require_auth
from ..config import get_settings

router = APIRouter(prefix='/api', tags=['preview'], dependencies=[Depends(require_auth)])


def _require_http_url(url: str) -> None:
    if urlsplit(url).scheme.lower() not in ('http', 'https'):
        raise HTTPException(status_code=400, detail='invalid url')


@router.get('/preview')
async def preview_url(url: str) -> preview.LinkPreview:
    """Unified preview for one URL (cached). Failures come back in-band as ``error``."""
    _require_http_url(url)
    return await preview.get_preview(url)


@router.get('/messages/{channel_id}/{message_id}/previews')
async def message_previews(channel_id: int, message_id: int) -> list[preview.LinkPreview]:
    """Previews for every URL in a message (album-aware, Telegram preview as a bonus)."""
    result = await preview.get_message_previews(channel_id, message_id)
    if result is None:
        raise HTTPException(status_code=404, detail='message not found')
    return result


@router.get('/preview/image')
async def preview_image(url: str):
    """Proxy a preview's thumbnail image through the server (private + hotlink-proof).

    Feature-flagged: when ``condenser_preview_image_proxy`` is off, redirect the browser
    to the origin URL instead of proxying — the simple non-proxied fallback.
    """
    _require_http_url(url)
    if not get_settings().condenser_preview_image_proxy:
        return RedirectResponse(url, status_code=307)
    try:
        data, mime = await preview.fetch_image(url)
    except (preview.PreviewError, httpx.HTTPError):
        raise HTTPException(status_code=502, detail='could not fetch image')
    return Response(content=data, media_type=mime, headers={'Cache-Control': 'private, max-age=86400'})
