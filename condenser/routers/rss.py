"""RSS source endpoints (plan 2026-08-20 §5).

Source-generic paths (``/api/sources/rss/...``), the HN/X router shape. One
deviation, forced by the source: an RSS subscription's key **is a URL**, which
cannot be a path segment (it carries its own slashes and query string), so
PATCH/DELETE identify the feed with a ``url`` query parameter instead of
``/subscriptions/{key}``. Everything else — subscribe-and-enable, pause, the
503 when the source is switched off, unsubscribe-keeps-the-archive — is the
same contract the other sources have.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import db
from ..auth import require_auth
from ..rss import RssManager, describe_subscription, normalize_feed_url, parse_opml
from ..types import RssOpmlBody, RssSubscribeBody, RssSubscriptionPatch

router = APIRouter(prefix='/api', tags=['rss'], dependencies=[Depends(require_auth)])

_URL_QUERY = Query(..., max_length=2000, description='the feed URL (this source keys on it)')


def get_rss(request: Request) -> RssManager:
    """Dependency: the process-wide RssManager from app state."""
    return request.app.state.rss


def _require_source_enabled(rss: RssManager) -> None:
    """With the master switch off the polling loop does not exist — accepting a
    subscribe/enable would archive nothing while reporting success (HN's B2)."""
    if not rss.settings.condenser_rss_enabled:
        raise HTTPException(status_code=503, detail='rss source is disabled by server config (CONDENSER_RSS_ENABLED)')


def _normalize_or_422(url: str) -> str:
    try:
        return normalize_feed_url(url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get('/sources/rss/subscriptions')
def list_rss_subscriptions():
    feeds = {f.url: f for f in db.list_rss_feeds()}
    return [describe_subscription(s, feeds.get(s.channel_id)) for s in db.list_rss_subscriptions()]


@router.post('/sources/rss/subscriptions')
def add_rss_subscription(body: RssSubscribeBody, rss: RssManager = Depends(get_rss)):
    _require_source_enabled(rss)
    url = _normalize_or_422(body.url)
    sub, _ = db.add_rss_subscription(url, name=body.name)
    # fetch without waiting a full interval — also on re-subscribe (resume)
    rss.kick()
    return describe_subscription(sub)


@router.patch('/sources/rss/subscriptions')
def patch_rss_subscription(
    body: RssSubscriptionPatch,
    url: str = _URL_QUERY,
    rss: RssManager = Depends(get_rss),
):
    url = _normalize_or_422(url)
    sub = db.get_rss_subscription(url)
    if sub is None:
        raise HTTPException(status_code=404, detail='rss subscription not found')
    if body.enabled:
        _require_source_enabled(rss)
    db.update_rss_subscription(url, enabled=body.enabled, config=body.config)
    return describe_subscription(db.get_rss_subscription(url))


@router.delete('/sources/rss/subscriptions')
def delete_rss_subscription(url: str = _URL_QUERY):
    url = _normalize_or_422(url)
    if db.get_rss_subscription(url) is None:
        raise HTTPException(status_code=404, detail='rss subscription not found')
    # unsubscribe stops polling; archived entries are kept (TG/HN/X semantics)
    db.delete_rss_subscription(url)
    return {'ok': True}


@router.post('/sources/rss/opml')
def import_opml(body: RssOpmlBody, rss: RssManager = Depends(get_rss)):
    """Bulk-subscribe from an OPML export.

    Every feed goes through the same path a manual add does, so an import cannot
    produce a subscription a manual add could not. The three counts are the whole
    result: ``added`` is new subscriptions, ``skipped_existing`` feeds already
    subscribed (an import is expected to overlap what you have), and ``invalid``
    outlines whose ``xmlUrl`` is not an http(s) URL.
    """
    _require_source_enabled(rss)
    try:
        outlines = parse_opml(body.opml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    counts = {'added': 0, 'skipped_existing': 0, 'invalid': 0}
    for outline in outlines:
        try:
            url = normalize_feed_url(outline['url'])
        except ValueError:
            counts['invalid'] += 1
            continue
        # update_existing=False: an import must not reverse the reader's pause
        # decisions or relabel feeds — it only picks up what is new.
        _, created = db.add_rss_subscription(url, name=outline['title'], update_existing=False)
        counts['added' if created else 'skipped_existing'] += 1
    if counts['added']:
        rss.kick()
    return counts


@router.get('/rss/status')
def rss_status(rss: RssManager = Depends(get_rss)):
    return rss.status()
