"""Hacker News source endpoints (multi-source plan Phase 1).

Subscription paths are source-generic (``/api/sources/hn/...``) so later sources
follow the same shape; ``channel_id`` is the feed key within the source (v1:
only ``'front'``). The full ``/api/sources`` listing arrives in Phase 2.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db
from ..auth import require_auth
from ..hn import DEFAULT_FEED_CONFIG, FRONT_FEED_NAME, HNManager
from ..types import HNSubscribeBody, HNSubscriptionPatch

router = APIRouter(prefix='/api', tags=['hn'], dependencies=[Depends(require_auth)])


def get_hn(request: Request) -> HNManager:
    """Dependency: the process-wide HNManager from app state."""
    return request.app.state.hn


@router.post('/sources/hn/subscriptions')
def add_hn_subscription(body: HNSubscribeBody, hn: HNManager = Depends(get_hn)):
    if body.channel_id != 'front':
        raise HTTPException(status_code=422, detail="unsupported hn feed; only 'front' exists in v1")
    sub = db.add_hn_subscription('front', name=FRONT_FEED_NAME, config=DEFAULT_FEED_CONFIG)
    # start filling the recent-history window, then sample without waiting a full interval
    hn.schedule_backfill()
    hn.kick()
    return {'source': 'hn', 'channel_id': 'front', 'name': sub.name, 'enabled': bool(sub.enabled)}


@router.patch('/sources/hn/subscriptions/{feed}')
def patch_hn_subscription(feed: str, body: HNSubscriptionPatch):
    if db.get_hn_subscription(feed) is None:
        raise HTTPException(status_code=404, detail='hn subscription not found')
    db.update_hn_subscription(feed, enabled=body.enabled, config=body.config)
    return {'ok': True}


@router.delete('/sources/hn/subscriptions/{feed}')
def delete_hn_subscription(feed: str):
    # unsubscribe stops sampling; archived stories are kept (same as TG unsubscribe)
    if db.get_hn_subscription(feed) is None:
        raise HTTPException(status_code=404, detail='hn subscription not found')
    db.delete_hn_subscription(feed)
    return {'ok': True}


@router.get('/hn/status')
def hn_status(hn: HNManager = Depends(get_hn)):
    return hn.status()
