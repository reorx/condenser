"""Full-text search (plan kb/plans/2026-08-08-full-text-search.md §5).

One endpoint, and it returns the same item envelopes ``/api/timeline`` does — so
a client renders results with the cards it already has, and the iOS app needs an
API change of exactly zero when its UI arrives.

Two decisions are visible in the signature. ``source`` / ``channel_id`` / ``feed``
are the *same* three scope parameters the timeline takes, rather than a new
"subscription" concept, because the frontend's filter control is built from the
same ``GET /api/sources`` tree. And there is no cursor: search is browsing an
archive rather than draining a queue, so offset paging — whose drift between
pages is the reason the timeline does not use it — costs nothing here.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import search
from ..auth import require_auth
from ..sources.x import normalize_feed

router = APIRouter(prefix='/api', tags=['search'], dependencies=[Depends(require_auth)])

_SOURCE_PATTERN = '^(telegram|hn|x|rss)$'
# The sources whose subscriptions are addressed by a feed key rather than by a
# channel id. Their keys look nothing alike (an X handle, an RSS feed URL), so the
# scope is only interpretable once the source is named.
_FEED_SOURCES = ('x', 'rss')
_STATUS_PATTERN = '^(unread|saved)$'
_SORT_PATTERN = '^(recent|relevance)$'


@router.get('/search')
def get_search(
    q: str = Query(..., max_length=200),
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
    channel_id: Optional[int] = None,
    feed: Optional[str] = Query(None, max_length=2000),
    status: Optional[str] = Query(None, pattern=_STATUS_PATTERN),
    sort: str = Query('recent', pattern=_SORT_PATTERN),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    if not search.available():
        raise HTTPException(status_code=503, detail='search is unavailable: this SQLite build has no FTS5')
    # A scope that contradicts itself would otherwise AND into an unsatisfiable
    # predicate and answer 200 with an empty page — which reads as "nothing matched"
    # rather than "you asked for something impossible". Same reasoning as the 422 on
    # an unsearchable query below; the frontend never builds one, but this endpoint
    # is the contract iOS and a bookmarked URL both go through.
    if channel_id is not None and source not in (None, 'telegram'):
        raise HTTPException(
            status_code=422, detail="channel_id is a telegram scope; it cannot be combined with source='%s'" % source
        )
    if feed and source not in _FEED_SOURCES:
        raise HTTPException(
            status_code=422,
            detail='feed narrows a multi-feed source and needs one named: source must be x or rss',
        )
    match = search.build_match(q)
    if match is None:
        # Punctuation and emoji carry no token, so there is nothing to look for.
        # A 422 rather than an empty page: "no results" would read as an answer.
        raise HTTPException(status_code=422, detail='query contains nothing searchable')
    rows, total = search.search(
        match,
        source=source,
        channel_id=channel_id,
        # Only X's keys are normalized ('@Handle' and 'handle' are one feed); an RSS
        # key is a URL, where lowercasing a path can change what it addresses.
        feed=normalize_feed(feed) if source == 'x' else feed,
        status=status,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    return {'items': search.render(rows), 'total': total, 'has_more': offset + len(rows) < total}
