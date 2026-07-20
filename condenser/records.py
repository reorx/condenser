"""Saved records (user assets, source-decoupled — spec §1 / Part B).

A saved record snapshots an item's full data into ``saved_items.raw_data`` so it
renders even if the source cache (telememo ``messages`` / ``hn_stories``) is
later cleared. Telegram snapshots are self-contained: the album's message rows
plus minimal channel info; HN snapshots are the story row as JSON.
"""

import json
from typing import Optional

from telememo import db as tdb
from telememo.utils import group_messages_to_display

from . import db
from .items import ItemKey, hn_envelope, iso_utc, tg_envelope

_MSG_COLS = """
    id, channel_id AS channel, text, date, sender_id, sender_name,
    views, forwards, replies, is_edited, edit_date, media_type, has_media,
    media_width, media_height, grouped_id,
    webpage,
    is_forwarded, fwd_from_channel_id, fwd_from_channel_name, fwd_from_user_id,
    fwd_from_user_name, fwd_from_message_id, fwd_original_date, fwd_post_author
"""


def _rows(sql: str, params: tuple) -> list[dict]:
    cur = tdb.db.execute_sql(sql, params)
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def build_snapshot(channel_id: int, message_id: int) -> Optional[dict]:
    """Snapshot a TG display unit (album-aware) into a self-contained dict, or None if absent."""
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


def _hn_snapshot(story: db.HNStory) -> dict:
    return {
        'id': story.id,
        'title': story.title,
        'url': story.url,
        'domain': story.domain,
        'author': story.author,
        'text': story.text,
        'type': story.type,
        'submitted_at': iso_utc(story.submitted_at),
        'first_seen_at': iso_utc(story.first_seen_at),
        'day': story.day,
        'score': story.score,
        'comments_count': story.comments_count,
        'peak_rank': story.peak_rank,
        'backfilled': bool(story.backfilled),
    }


def save_item(key: ItemKey) -> bool:
    """Snapshot + persist a record for an item key. Returns False if the source item is missing."""
    if key.source == 'telegram':
        snapshot = build_snapshot(key.ref1, key.ref2)
        if snapshot is None:
            return False
        db.add_saved_item('telegram', key.ref1, key.ref2, snapshot)
        return True
    story = db.get_hn_story(key.ref1)
    if story is None:
        return False
    db.add_saved_item('hn', key.ref1, 0, _hn_snapshot(story))
    return True


def _render_tg_display(raw_data: str) -> Optional[dict]:
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
    item['channel'] = snapshot.get('channel')
    return item


def render_item(rec: db.SavedItem) -> Optional[dict]:
    """Render one saved row into an item envelope (is_saved always True)."""
    is_read = db.is_item_read(rec.source, rec.ref1, rec.ref2)
    if rec.source == 'telegram':
        display = _render_tg_display(rec.raw_data)
        if display is None:
            return None
        return tg_envelope(display, is_read, True)
    return hn_envelope(json.loads(rec.raw_data), is_read, True)


def list_rendered_records() -> list[dict]:
    """All saved records rendered from their snapshots, newest first."""
    out = []
    for rec in db.list_saved_items():
        rendered = render_item(rec)
        if rendered is not None:
            out.append(rendered)
    return out
