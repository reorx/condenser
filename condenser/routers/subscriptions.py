"""Subscription + keyword-filter management (spec C2 — subscriptions)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from telememo import db as tdb

from .. import db, filters, timeline
from ..auth import get_tg, require_auth
from ..tg import TgManager
from ..types import (
    BatchSubscribeBody,
    FilterScopeBody,
    SubscribeBody,
    SubscriptionPatch,
)

# Preview scans the most-recent N messages and runs the live matching function
# against each — keeps the preview semantics identical to materialization.
PREVIEW_SCAN_LIMIT = 1000
PREVIEW_SAMPLE_LIMIT = 20
PREVIEW_TEXT_TRUNCATE = 300

router = APIRouter(prefix='/api', tags=['subscriptions'], dependencies=[Depends(require_auth)])


@router.get('/subscriptions')
def list_subscriptions():
    counts = timeline.unread_counts()
    out = []
    for sub in db.list_subscriptions():
        channel = tdb.get_channel(sub.channel_id)
        out.append(
            {
                'channel_id': sub.channel_id,
                'enabled': bool(sub.enabled),
                'backfill_done': bool(sub.backfill_done),
                'title': channel.title if channel else None,
                'username': channel.username if channel else None,
                'unread': counts.get(sub.channel_id, 0),
            }
        )
    return out


@router.post('/subscriptions')
async def add_subscription(body: SubscribeBody, tg: TgManager = Depends(get_tg)):
    info = await tg.subscribe_channel(body.handle)
    return {'channel_id': info.id, 'title': info.title, 'username': info.username}


@router.post('/subscriptions/batch')
async def add_subscriptions_batch(body: BatchSubscribeBody, tg: TgManager = Depends(get_tg)):
    added, failed = await tg.subscribe_channels(body.channel_ids)
    return {
        'added': [{'channel_id': i.id, 'title': i.title, 'username': i.username} for i in added],
        'failed': failed,
    }


@router.patch('/subscriptions/{channel_id}')
async def patch_subscription(channel_id: int, body: SubscriptionPatch, tg: TgManager = Depends(get_tg)):
    db.set_subscription_enabled(channel_id, body.enabled)
    if tg.service is not None and tg.service.is_authorized:
        await tg.refresh_subscription()
    return {'ok': True}


@router.delete('/subscriptions/{channel_id}')
async def delete_subscription(channel_id: int, tg: TgManager = Depends(get_tg)):
    # Q4: keep ingested messages; only stop tracking + drop from subscription filter.
    db.delete_subscription(channel_id)
    if tg.service is not None and tg.service.is_authorized:
        await tg.refresh_subscription()
    return {'ok': True}


def _channel_titles(channel_ids: set[int]) -> dict[int, Optional[str]]:
    out: dict[int, Optional[str]] = {}
    for cid in channel_ids:
        ch = tdb.get_channel(cid)
        out[cid] = ch.title if ch else None
    return out


@router.get('/filters')
def list_all_filters():
    rows = db.list_all_filters()
    titles = _channel_titles({f.channel_id for f in rows if f.channel_id is not None})
    return [
        {
            'id': f.id,
            'channel_id': f.channel_id,
            'channel_title': titles.get(f.channel_id) if f.channel_id is not None else None,
            'pattern': f.pattern,
        }
        for f in rows
    ]


@router.post('/filters')
def create_filter(body: FilterScopeBody):
    f = db.add_filter(body.channel_id, body.pattern)
    filters.recompute_for_rule_change(body.channel_id)
    title = None
    if body.channel_id is not None:
        ch = tdb.get_channel(body.channel_id)
        title = ch.title if ch else None
    return {'id': f.id, 'channel_id': body.channel_id, 'channel_title': title, 'pattern': f.pattern}


@router.post('/filters/preview')
def preview_filter(body: FilterScopeBody):
    pattern = body.pattern.strip()
    if not pattern:
        return {'scanned': 0, 'matched': 0, 'samples': []}

    if body.channel_id is None:
        cids = db.enabled_channel_ids()
        if not cids:
            return {'scanned': 0, 'matched': 0, 'samples': []}
        placeholders = ','.join('?' for _ in cids)
        sql = (
            f'SELECT m.channel_id, m.id, m.date, m.text FROM messages m '
            f'WHERE m.channel_id IN ({placeholders}) ORDER BY m.date DESC LIMIT ?'
        )
        params: tuple = (*cids, PREVIEW_SCAN_LIMIT)
    else:
        sql = 'SELECT m.channel_id, m.id, m.date, m.text FROM messages m WHERE m.channel_id = ? ORDER BY m.date DESC LIMIT ?'
        params = (body.channel_id, PREVIEW_SCAN_LIMIT)

    rows = tdb.db.execute_sql(sql, params).fetchall()
    # Reuse the live matcher so preview semantics track materialization exactly.
    patterns = [pattern.lower()]
    matched = [r for r in rows if filters.text_is_filtered(r[3], patterns)]

    sample_rows = matched[:PREVIEW_SAMPLE_LIMIT]
    titles = _channel_titles({r[0] for r in sample_rows})
    samples = [
        {
            'channel_id': cid,
            'message_id': mid,
            'channel_title': titles.get(cid),
            'date': date,
            'text': (text or '')[:PREVIEW_TEXT_TRUNCATE],
        }
        for (cid, mid, date, text) in sample_rows
    ]
    return {'scanned': len(rows), 'matched': len(matched), 'samples': samples}


@router.delete('/filters/{filter_id}')
def delete_filter(filter_id: int):
    f = db.get_filter(filter_id)
    if f is None:
        raise HTTPException(status_code=404, detail='filter not found')
    channel_id = f.channel_id
    db.delete_filter(filter_id)
    filters.recompute_for_rule_change(channel_id)
    return {'ok': True}
