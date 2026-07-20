"""Item keys + timeline envelopes (multi-source plan 2.1).

An item key is the API-level identifier of one timeline unit:
``tg:{channel_id}:{message_id}`` / ``hn:{story_id}``. Storage uses the integer
triple ``(source, ref1, ref2)`` — see ``read_items`` / ``saved_items`` in db.py;
this module owns the string<->triple mapping and the envelope assembly shared by
the timeline and records renderers.
"""

from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel

SOURCES = ('telegram', 'hn')


class ItemKey(BaseModel):
    source: str  # 'telegram' | 'hn'
    ref1: int  # TG: channel_id, HN: story_id
    ref2: int = 0  # TG: message_id, HN: unused

    @property
    def key(self) -> str:
        if self.source == 'telegram':
            return f'tg:{self.ref1}:{self.ref2}'
        return f'hn:{self.ref1}'

    @property
    def triple(self) -> tuple[str, int, int]:
        return (self.source, self.ref1, self.ref2)


def tg_key(channel_id: int, message_id: int) -> str:
    return f'tg:{channel_id}:{message_id}'


def hn_key(story_id: int) -> str:
    return f'hn:{story_id}'


def parse_key(key: str) -> ItemKey:
    """Parse an item key string; raises ValueError on any malformed input."""
    parts = key.split(':')
    if parts[0] == 'tg' and len(parts) == 3:
        return ItemKey(source='telegram', ref1=int(parts[1]), ref2=int(parts[2]))
    if parts[0] == 'hn' and len(parts) == 2:
        return ItemKey(source='hn', ref1=int(parts[1]))
    raise ValueError(f'invalid item key: {key!r}')


# --- timestamps --------------------------------------------------------------
# TG stores tz-aware strings ('2026-06-01 12:01:00+00:00'), HN naive UTC
# datetimes; both are UTC wall time, so the 19-char normalized form is a
# cross-source sort key and the basis of the envelope's `datetime` field.


def norm_ts(value: Union[str, datetime, None]) -> str:
    """Normalize a UTC timestamp to a sortable 'YYYY-MM-DD HH:MM:SS' string."""
    if value is None:
        return ''
    if isinstance(value, datetime):
        value = value.isoformat(sep=' ')
    return value.replace('T', ' ')[:19]


def iso_utc(value: Union[str, datetime, None]) -> Optional[str]:
    """Render a UTC timestamp as ISO8601 with a Z suffix (the envelope contract)."""
    if value is None:
        return None
    return norm_ts(value).replace(' ', 'T') + 'Z'


# --- envelopes ---------------------------------------------------------------


def tg_envelope(display: dict, is_read: bool, is_saved: bool) -> dict:
    """Wrap a DisplayMessage dict (flags NOT included) into the item envelope."""
    return {
        'source': 'telegram',
        'key': tg_key(display['channel_id'], display['id']),
        'datetime': iso_utc(display['date']),
        'is_read': is_read,
        'is_saved': is_saved,
        'telegram': display,
    }


def hn_payload(row: dict) -> dict:
    """The `hn` payload from an hn_stories row dict (day_rank present query-time only)."""
    return {
        'id': row['id'],
        'title': row.get('title'),
        'url': row.get('url'),
        'domain': row.get('domain'),
        'author': row.get('author'),
        'type': row.get('type'),
        'text': row.get('text'),
        'submitted_at': iso_utc(row.get('submitted_at')),
        'first_seen_at': iso_utc(row.get('first_seen_at')),
        'score': row.get('score') or 0,
        'comments_count': row.get('comments_count') or 0,
        'day_rank': row.get('day_rank'),
        'peak_rank': row.get('peak_rank'),
        'backfilled': bool(row.get('backfilled')),
    }


def hn_envelope(row: dict, is_read: bool, is_saved: bool) -> dict:
    payload = hn_payload(row)
    return {
        'source': 'hn',
        'key': hn_key(row['id']),
        'datetime': payload['first_seen_at'],
        'is_read': is_read,
        'is_saved': is_saved,
        'hn': payload,
    }
