"""Subscription + keyword-filter management (spec C2 — subscriptions)."""

from fastapi import APIRouter, Depends, HTTPException

from telememo import db as tdb

from .. import db, filters, timeline
from ..auth import get_tg, require_auth
from ..tg import TgManager
from ..types import FilterBody, SubscribeBody, SubscriptionPatch

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


@router.get('/subscriptions/{channel_id}/filters')
def list_filters(channel_id: int):
    return [{'id': f.id, 'channel_id': f.channel_id, 'pattern': f.pattern} for f in db.list_filters(channel_id)]


@router.post('/subscriptions/{channel_id}/filters')
def add_filter(channel_id: int, body: FilterBody):
    f = db.add_filter(channel_id, body.pattern)
    filters.recompute_for_rule_change(channel_id)
    return {'id': f.id, 'channel_id': channel_id, 'pattern': f.pattern}


@router.delete('/filters/{filter_id}')
def delete_filter(filter_id: int):
    f = db.get_filter(filter_id)
    if f is None:
        raise HTTPException(status_code=404, detail='filter not found')
    channel_id = f.channel_id
    db.delete_filter(filter_id)
    filters.recompute_for_rule_change(channel_id)
    return {'ok': True}
