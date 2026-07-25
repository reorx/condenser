"""Source + subscription listing (multi-source plan 2.4).

``GET /api/sources`` is the single data source for the web sidebar's two-level
structure and the iOS source menu: only sources with at least one subscription
appear. Display names resolve as COALESCE(sub.name, source-side lookup) — one
batched query per source, no per-row N+1.
"""

import json

from fastapi import APIRouter, Depends

from telememo import db as tdb

from .. import db, x
from ..auth import require_auth
from ..sources import hn as hn_source
from ..sources import telegram as tg_source
from ..sources import x as x_source

router = APIRouter(prefix='/api', tags=['sources'], dependencies=[Depends(require_auth)])


def _telegram_entries(subs: list[db.Subscription]) -> list[dict]:
    ids = [int(s.channel_id) for s in subs]
    placeholders = ','.join('?' for _ in ids)
    cur = tdb.db.execute_sql(f'SELECT id, title, username FROM channels WHERE id IN ({placeholders})', tuple(ids))
    channels = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    counts = tg_source.unread_counts()
    out = []
    for s in subs:
        cid = int(s.channel_id)
        title, username = channels.get(cid, (None, None))
        out.append(
            {
                'channel_id': cid,
                'name': s.name or title,
                'username': username,
                'enabled': bool(s.enabled),
                'unread': counts.get(cid, 0),
                'config': None,
            }
        )
    return out


def _hn_entries(subs: list[db.Subscription]) -> list[dict]:
    return [
        {
            'channel_id': s.channel_id,
            'name': s.name,
            'username': None,
            'enabled': bool(s.enabled),
            # v1: only the 'front' feed exists, so the source-wide count is the feed's
            'unread': hn_source.unread_count() if s.enabled else 0,
            'config': json.loads(s.config) if s.config else None,
        }
        for s in subs
    ]


def _x_entries(subs: list[db.Subscription]) -> list[dict]:
    counts = x_source.unread_counts()
    out = []
    for s in subs:
        config = x.sub_config(s)
        out.append(
            {
                'channel_id': s.channel_id,
                # NULL until the first push teaches us the account's real display name
                'name': s.name,
                # the handle labels the row in the meantime (and is what X URLs use)
                'username': config.get('handle'),
                'enabled': bool(s.enabled),
                'unread': counts.get(s.channel_id, 0) if s.enabled else 0,
                'config': config,
            }
        )
    return out


_ENTRY_BUILDERS = {'telegram': _telegram_entries, 'hn': _hn_entries, 'x': _x_entries}


@router.get('/sources')
def list_sources():
    subs = list(db.Subscription.select().order_by(db.Subscription.added_at.desc()))
    by_source: dict[str, list[db.Subscription]] = {}
    for s in subs:
        by_source.setdefault(s.source, []).append(s)

    out = []
    for source in ('telegram', 'hn', 'x'):  # fixed display order
        rows = by_source.get(source)
        if not rows:
            continue
        out.append({'source': source, 'subscriptions': _ENTRY_BUILDERS[source](rows)})
    return out
