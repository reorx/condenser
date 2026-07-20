"""Timeline, read markers, and saved records (spec C2 — timeline / reading).

Multi-source since Phase 2: timeline items are envelopes, read/save take item
keys, and ``source`` narrows a query to one source (``channel_id`` implies
telegram).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, records, timeline
from ..auth import require_auth
from ..items import ItemKey, parse_key
from ..types import ReadBody, ReadBulkBody, RecordBody

router = APIRouter(prefix='/api', tags=['reading'], dependencies=[Depends(require_auth)])

_SOURCE_PATTERN = '^(telegram|hn)$'


def _parse_key_or_422(key: str) -> ItemKey:
    try:
        return parse_key(key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get('/timeline')
def get_timeline(
    cursor: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
):
    try:
        return timeline.query_timeline(channel_id, date, unread_only, cursor, limit, source)
    except timeline.InvalidCursor:
        raise HTTPException(status_code=422, detail='invalid cursor')


@router.get('/timeline/days')
def get_timeline_days(
    channel_id: Optional[int] = None,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
):
    return timeline.query_days(channel_id, source)


@router.get('/timeline/new')
def get_timeline_new(
    after: str,
    channel_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=200),
    unread_only: bool = False,
    source: Optional[str] = Query(None, pattern=_SOURCE_PATTERN),
):
    try:
        return timeline.query_new(channel_id, after, limit, unread_only, source)
    except timeline.InvalidCursor:
        raise HTTPException(status_code=422, detail='invalid cursor')


@router.post('/read')
def post_read(body: ReadBody):
    db.mark_read([_parse_key_or_422(k) for k in body.keys])
    return {'ok': True}


@router.post('/read/bulk')
def post_read_bulk(body: ReadBulkBody):
    db.mark_read_bulk(body.channel_id, body.before_date, body.source)
    return {'ok': True}


@router.get('/records')
def get_records():
    return records.list_rendered_records()


@router.post('/records')
def post_record(body: RecordBody):
    if not records.save_item(_parse_key_or_422(body.key)):
        raise HTTPException(status_code=404, detail='item not found')
    return {'ok': True}


@router.delete('/records/{key}')
def delete_record(key: str):
    k = _parse_key_or_422(key)
    db.delete_saved_item(k.source, k.ref1, k.ref2)
    return {'ok': True}
