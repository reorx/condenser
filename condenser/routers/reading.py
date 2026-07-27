"""Timeline, read markers, and saved records (spec C2 — timeline / reading).

Multi-source since Phase 2: timeline items are envelopes, read/save take item
keys, and ``source`` narrows a query to one source (``channel_id`` implies
telegram).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, records, timeline
from ..auth import require_auth
from ..types import FeedbackBody, HideBody, ReadBody, ReadBulkBody, RecordBody
from .common import parse_key_or_422

router = APIRouter(prefix='/api', tags=['reading'], dependencies=[Depends(require_auth)])

_SOURCE_PATTERN = '^(telegram|hn|x)$'

# A multi-feed source (X) can be narrowed further; the provider normalizes the key,
# so '@Handle' and 'handle' are the same feed.
_FEED_QUERY = Query(None, max_length=64, description='narrow a multi-feed source to one feed (X)')


@router.get('/timeline')
def get_timeline(
    cursor: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
    feed: Optional[str] = _FEED_QUERY,
):
    try:
        return timeline.query_timeline(channel_id, date, unread_only, cursor, limit, source, feed)
    except timeline.InvalidCursor:
        raise HTTPException(status_code=422, detail='invalid cursor')


@router.get('/timeline/days')
def get_timeline_days(
    channel_id: Optional[int] = None,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
    feed: Optional[str] = _FEED_QUERY,
):
    return timeline.query_days(channel_id, source, feed)


@router.get('/timeline/new')
def get_timeline_new(
    after: str,
    channel_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=200),
    unread_only: bool = False,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
    feed: Optional[str] = _FEED_QUERY,
):
    try:
        return timeline.query_new(channel_id, after, limit, unread_only, source, feed)
    except timeline.InvalidCursor:
        raise HTTPException(status_code=422, detail='invalid cursor')


@router.post('/read')
def post_read(body: ReadBody):
    db.mark_read([parse_key_or_422(k) for k in body.keys])
    return {'ok': True}


@router.post('/read/bulk')
def post_read_bulk(body: ReadBulkBody):
    db.mark_read_bulk(body.channel_id, body.before_date, body.source, body.feed)
    return {'ok': True}


@router.post('/hidden')
def post_hidden(body: HideBody):
    db.hide_item(parse_key_or_422(body.key))
    return {'ok': True}


@router.delete('/hidden/{key}')
def delete_hidden(key: str):
    db.unhide_item(parse_key_or_422(key))
    return {'ok': True}


@router.post('/feedback')
def post_feedback(body: FeedbackBody):
    """Label an item up/down (plan Phase 3), optionally with the reason chip (v9).
    Nothing else happens to it — no verdict, no hiding, no read marker; the label is
    training data for Phase 4."""
    db.set_feedback(parse_key_or_422(body.key), body.verdict, body.reason)
    return {'ok': True}


@router.delete('/feedback/{key}')
def delete_feedback(key: str):
    db.clear_feedback(parse_key_or_422(key))
    return {'ok': True}


@router.get('/records')
def get_records():
    return records.list_rendered_records()


@router.post('/records')
def post_record(body: RecordBody):
    if not records.save_item(parse_key_or_422(body.key)):
        raise HTTPException(status_code=404, detail='item not found')
    return {'ok': True}


@router.delete('/records/{key}')
def delete_record(key: str):
    k = parse_key_or_422(key)
    db.delete_saved_item(k.source, k.ref1, k.ref2)
    return {'ok': True}
