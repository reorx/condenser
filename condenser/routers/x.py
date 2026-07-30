"""X (Twitter) source endpoints (plan Phase 1).

Subscription paths follow the source-generic shape (``/api/sources/x/...``).
Two of them are the local probe's contract: ``probe-config`` tells it what to
fetch (so the probe carries no local config beyond a server URL + token) and
``ingest`` takes bird's raw JSON. Both accept the device Bearer token the probe
is registered with — it is just another authorized device.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import db, preview, x
from ..auth import require_auth
from ..config import Settings, get_settings
from ..types import XFollowingBody, XIngestBody, XSubscribeBody, XSubscriptionPatch

log = logging.getLogger('condenser.routers.x')

router = APIRouter(prefix='/api', tags=['x'], dependencies=[Depends(require_auth)])

# bird's output carries no avatar URL (Phase 1 finding #8), so author avatars come
# from unavatar's X lookup. `fallback=false` makes a miss a 404 instead of a generic
# placeholder image, which lets the client draw its own letter avatar instead.
UNAVATAR_URL = 'https://unavatar.io/x/{handle}?fallback=false'


def _require_source_enabled(settings: Settings) -> None:
    """With the master switch off nothing should be archived — accepting a subscribe
    or a push would report success while the source is meant to be inert."""
    if not settings.condenser_x_enabled:
        raise HTTPException(status_code=503, detail='x source is disabled by server config (CONDENSER_X_ENABLED)')


def _normalize_or_422(channel_id: str) -> str:
    try:
        return x.normalize_channel_id(channel_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get('/sources/x/subscriptions')
def list_x_subscriptions():
    return [x.describe_subscription(s) for s in db.list_x_subscriptions()]


@router.post('/sources/x/subscriptions')
def add_x_subscription(body: XSubscribeBody, settings: Settings = Depends(get_settings)):
    _require_source_enabled(settings)
    channel_id = _normalize_or_422(body.channel_id)
    config = x.default_config(channel_id)
    if body.n is not None:
        config['n'] = body.n
    name = body.name or x.default_name(channel_id)
    sub, _ = db.add_x_subscription(channel_id, name=name, config=config)
    return x.describe_subscription(sub)


@router.patch('/sources/x/subscriptions/{channel_id}')
def patch_x_subscription(channel_id: str, body: XSubscriptionPatch, settings: Settings = Depends(get_settings)):
    channel_id = _normalize_or_422(channel_id)
    sub = db.get_x_subscription(channel_id)
    if sub is None:
        raise HTTPException(status_code=404, detail='x subscription not found')
    if body.enabled:
        _require_source_enabled(settings)
    config = None
    if body.config is not None:
        # merge, so a partial PATCH cannot drop the learned user_id / handle
        config = {**x.sub_config(sub), **body.config}
    db.update_x_subscription(channel_id, enabled=body.enabled, config=config)
    return x.describe_subscription(db.get_x_subscription(channel_id))


@router.delete('/sources/x/subscriptions/{channel_id}')
def delete_x_subscription(channel_id: str):
    channel_id = _normalize_or_422(channel_id)
    if db.get_x_subscription(channel_id) is None:
        raise HTTPException(status_code=404, detail='x subscription not found')
    # unsubscribe stops the probe fetching it; archived tweets are kept (TG/HN semantics)
    db.delete_x_subscription(channel_id)
    return {'ok': True}


@router.post('/sources/x/following')
def push_following(body: XFollowingBody, settings: Settings = Depends(get_settings)):
    """Replace the followed-accounts list (the Following feed's ad filter).

    Whole-list semantics: the probe crawls ``bird following --all`` and pushes what
    it found, so an unfollowed account disappears by not being mentioned.
    """
    _require_source_enabled(settings)
    try:
        return x.sync_following(body.users)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get('/sources/x/probe-config')
def get_probe_config(settings: Settings = Depends(get_settings)):
    return x.probe_config(settings)


@router.post('/sources/x/ingest')
def ingest(request: Request, body: XIngestBody, settings: Settings = Depends(get_settings)):
    _require_source_enabled(settings)
    channel_id = _normalize_or_422(body.channel_id)
    sub = db.get_x_subscription(channel_id)
    if sub is None or not sub.enabled:
        # the probe fetches strictly what probe-config listed; this means the
        # subscription went away mid-round (or the probe is misconfigured)
        raise HTTPException(status_code=404, detail='no enabled x subscription for this channel_id')
    result = x.ingest_tweets(channel_id, body.tweets, settings)
    _kick_verdict(request)
    return {'channel_id': channel_id, **result.as_dict()}


def _kick_verdict(request: Request) -> None:
    """Ask for a judging round. This endpoint's contract is "the archive took your
    tweets" — a verdict is an async enhancement on top, so nothing it does may turn
    a successful push into an error the probe would report as data loss."""
    manager = getattr(request.app.state, 'verdict', None)
    if manager is None:
        return
    try:
        manager.kick()
    except Exception:  # noqa: BLE001 - see the docstring
        log.exception('x ingest: could not schedule a verdict round')


@router.get('/x/status')
def x_status(settings: Settings = Depends(get_settings)):
    return x.status(settings)


@router.get('/x/avatar/{handle}')
async def get_x_avatar(handle: str):
    """Proxy an author's avatar (see UNAVATAR_URL). 404 = draw a letter avatar."""
    handle = _normalize_or_422(handle)
    if handle == x.FORYOU_FEED:
        raise HTTPException(status_code=404, detail='not an account handle')
    try:
        data, mime = await preview.fetch_image(UNAVATAR_URL.format(handle=handle))
    except (preview.PreviewError, httpx.HTTPError):
        raise HTTPException(status_code=404, detail='no avatar')
    # avatars are tiny and change rarely; the server keeps nothing on disk
    return Response(content=data, media_type=mime, headers={'Cache-Control': 'private, max-age=86400'})
