"""Timeline, read markers, and saved records (spec C2 — timeline / reading)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, records, timeline
from ..auth import require_auth
from ..types import ReadBody, ReadBulkBody, RecordBody

router = APIRouter(prefix='/api', tags=['reading'], dependencies=[Depends(require_auth)])


@router.get('/timeline')
def get_timeline(
    cursor: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
):
    return timeline.query_timeline(channel_id, date, unread_only, cursor, limit)


@router.get('/timeline/days')
def get_timeline_days(channel_id: Optional[int] = None):
    return timeline.query_days(channel_id)


@router.get('/timeline/new')
def get_timeline_new(
    after: str,
    channel_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=200),
):
    return timeline.query_new(channel_id, after, limit)


@router.post('/read')
def post_read(body: ReadBody):
    db.mark_read([(i.channel_id, i.message_id) for i in body.items])
    return {'ok': True}


@router.post('/read/bulk')
def post_read_bulk(body: ReadBulkBody):
    db.mark_read_bulk(body.channel_id, body.before_date)
    return {'ok': True}


@router.get('/records')
def get_records():
    return records.list_rendered_records()


@router.post('/records')
def post_record(body: RecordBody):
    if not records.save_record(body.channel_id, body.message_id):
        raise HTTPException(status_code=404, detail='message not found')
    return {'ok': True}


@router.delete('/records/{channel_id}/{message_id}')
def delete_record(channel_id: int, message_id: int):
    db.delete_record(channel_id, message_id)
    return {'ok': True}
