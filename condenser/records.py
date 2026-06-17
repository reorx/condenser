"""Saved records (user assets, source-decoupled — spec §1 / Part B).

A saved record snapshots a message's full data into ``telegram_records.raw_data``
so it renders even if the telememo ``messages`` cache is later cleared. The
snapshot is self-contained: the album's message rows plus minimal channel info.
"""

import json
from typing import Optional

from telememo import db as tdb
from telememo.utils import group_messages_to_display

from . import db

_MSG_COLS = """
    id, channel_id AS channel, text, date, sender_id, sender_name,
    views, forwards, replies, is_edited, edit_date, media_type, has_media, grouped_id,
    webpage,
    is_forwarded, fwd_from_channel_id, fwd_from_channel_name, fwd_from_user_id,
    fwd_from_user_name, fwd_from_message_id, fwd_original_date, fwd_post_author
"""


def _rows(sql: str, params: tuple) -> list[dict]:
    cur = tdb.db.execute_sql(sql, params)
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def build_snapshot(channel_id: int, message_id: int) -> Optional[dict]:
    """Snapshot a display unit (album-aware) into a self-contained dict, or None if absent."""
    primary = _rows(f'SELECT {_MSG_COLS} FROM messages WHERE channel_id = ? AND id = ?', (channel_id, message_id))
    if not primary:
        return None

    grouped_id = primary[0].get('grouped_id')
    if grouped_id:
        messages = _rows(
            f'SELECT {_MSG_COLS} FROM messages WHERE channel_id = ? AND grouped_id = ? ORDER BY id',
            (channel_id, grouped_id),
        )
    else:
        messages = primary

    channel = tdb.get_channel(channel_id)
    channel_info = None
    if channel:
        channel_info = {'id': channel.id, 'title': channel.title, 'username': channel.username}

    return {'messages': messages, 'channel': channel_info}


def save_record(channel_id: int, message_id: int) -> bool:
    """Snapshot + persist a record. Returns False if the source message is missing."""
    snapshot = build_snapshot(channel_id, message_id)
    if snapshot is None:
        return False
    db.add_record(channel_id, message_id, snapshot)
    return True


def render_record(raw_data: str) -> Optional[dict]:
    """Rebuild a DisplayMessage dict (+ channel) from a stored snapshot, no telememo tables."""
    snapshot = json.loads(raw_data)
    messages = snapshot.get('messages') or []
    if not messages:
        return None
    rows_for_display = []
    for r in messages:
        d = dict(r)
        d['date'] = tdb._parse_datetime(r.get('date'))
        d['edit_date'] = tdb._parse_datetime(r.get('edit_date'))
        d['fwd_original_date'] = tdb._parse_datetime(r.get('fwd_original_date'))
        wp = r.get('webpage')
        d['webpage'] = json.loads(wp) if isinstance(wp, str) else wp
        rows_for_display.append(d)
    displays = group_messages_to_display(rows_for_display)
    if not displays:
        return None
    item = displays[0].model_dump(mode='json')
    item['is_saved'] = True
    item['channel'] = snapshot.get('channel')
    return item


def list_rendered_records() -> list[dict]:
    """All saved records rendered from their snapshots, newest first."""
    out = []
    for rec in db.list_records():
        rendered = render_record(rec.raw_data)
        if rendered is not None:
            out.append(rendered)
    return out
