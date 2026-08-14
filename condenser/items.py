"""Item keys + timeline envelopes (multi-source plan 2.1).

An item key is the API-level identifier of one timeline unit:
``tg:{channel_id}:{message_id}`` / ``hn:{story_id}`` / ``x:{tweet_id}``. Storage
uses the integer triple ``(source, ref1, ref2)`` — see ``read_items`` /
``saved_items`` in db.py; this module owns the string<->triple mapping and the
envelope assembly shared by the timeline and records renderers.
"""

import json
from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel

SOURCES = ('telegram', 'hn', 'x')

# The X feed keys that are not account handles. They live here rather than in x.py
# because the envelope's sort timestamp depends on which feed an item came from
# (see ``x_envelope``) and this module is the one everything can import.
FORYOU_FEED = 'foryou'
FOLLOWING_FEED = 'following'


def x_feed_kind(feed: Optional[str]) -> str:
    """'home' (For You) | 'following' | 'user' (one followed account)."""
    if feed == FORYOU_FEED:
        return 'home'
    if feed == FOLLOWING_FEED:
        return 'following'
    return 'user'


class ItemKey(BaseModel):
    source: str  # 'telegram' | 'hn' | 'x'
    ref1: int  # TG: channel_id, HN: story_id, X: tweet id
    ref2: int = 0  # TG: message_id, others: unused

    @property
    def key(self) -> str:
        if self.source == 'telegram':
            return f'tg:{self.ref1}:{self.ref2}'
        if self.source == 'x':
            return f'x:{self.ref1}'
        return f'hn:{self.ref1}'

    @property
    def triple(self) -> tuple[str, int, int]:
        return (self.source, self.ref1, self.ref2)


def tg_key(channel_id: int, message_id: int) -> str:
    return f'tg:{channel_id}:{message_id}'


def hn_key(story_id: int) -> str:
    return f'hn:{story_id}'


def x_key(tweet_id: Union[int, str]) -> str:
    return f'x:{tweet_id}'


def parse_key(key: str) -> ItemKey:
    """Parse an item key string; raises ValueError on any malformed input."""
    parts = key.split(':')
    if parts[0] == 'tg' and len(parts) == 3:
        return ItemKey(source='telegram', ref1=int(parts[1]), ref2=int(parts[2]))
    if parts[0] == 'hn' and len(parts) == 2:
        return ItemKey(source='hn', ref1=int(parts[1]))
    if parts[0] == 'x' and len(parts) == 2:
        return ItemKey(source='x', ref1=int(parts[1]))
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


def _json_field(value: Union[str, list, dict, None]) -> Union[list, dict, None]:
    """A stored JSON column in its three shapes: absent/None, a JSON str (timeline
    query rows / model ``__data__``), or already parsed (saved-record replay, where
    the snapshot *is* the payload)."""
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _sid(value: Union[int, str, None]) -> Optional[str]:
    """Snowflake ids cross the API as strings: int64 exceeds JS's safe integer range."""
    return None if value is None else str(value)


def hn_payload(row: dict) -> dict:
    """The `hn` payload from an hn_stories row dict.

    ``day_rank`` keeps its name on the wire while the column behind it became
    ``qualified_rank`` in v14 — shipped iOS builds decode this field, and the two
    mean the same thing to a reader ("which of the day's slots this took"). A
    replayed saved snapshot carries the payload's own key instead, hence the two
    lookups; a record saved before v14 has neither and stays null.
    """
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
        'qualified_at': iso_utc(row.get('qualified_at')),
        'score': row.get('score') or 0,
        'comments_count': row.get('comments_count') or 0,
        'day_rank': row.get('qualified_rank', row.get('day_rank')),
        'peak_rank': row.get('peak_rank'),
        'backfilled': bool(row.get('backfilled')),
        'preview': _json_field(row.get('preview')),
    }


def hn_envelope(row: dict, is_read: bool, is_saved: bool) -> dict:
    payload = hn_payload(row)
    return {
        'source': 'hn',
        'key': hn_key(row['id']),
        # The admission stamp is the timeline position (v14). The fallback is not
        # optional: search reaches stories that were never admitted, and a record
        # saved before v14 has no stamp in its snapshot at all.
        'datetime': payload['qualified_at'] or payload['first_seen_at'],
        'is_read': is_read,
        'is_saved': is_saved,
        'hn': payload,
    }


def _x_quote(row: dict) -> Optional[dict]:
    """The quoted tweet, from either a joined query row (``q_*`` columns) or an
    already-assembled payload (saved-record replay)."""
    quote = row.get('quote')
    if isinstance(quote, dict):
        return quote
    if row.get('q_id') is None:
        return None
    return {
        'id': _sid(row['q_id']),
        'author_handle': row.get('q_author_handle'),
        'author_name': row.get('q_author_name'),
        'text': row.get('q_text'),
        'created_at': iso_utc(row.get('q_created_at')),
        'media': _json_field(row.get('q_media')),
        'metrics': _json_field(row.get('q_metrics')),
        'urls': _json_field(row.get('q_urls')),
    }


def x_payload(row: dict) -> dict:
    """The `x` payload from a provider row (or, idempotently, from a stored payload)."""
    feed = row.get('feed')
    return {
        'id': _sid(row['id']),
        'author_id': _sid(row.get('author_id')),
        'author_handle': row.get('author_handle'),
        'author_name': row.get('author_name'),
        'text': row.get('text'),
        'created_at': iso_utc(row.get('created_at')),
        'first_seen_at': iso_utc(row.get('first_seen_at')),
        'media': _json_field(row.get('media')),
        'metrics': _json_field(row.get('metrics')),
        'quote': _x_quote(row),
        # bird flattens retweets into an 'RT @orig:' text prefix — a handle is all
        # that survives, and only for retweets (see plan, bird finding #5)
        'rt_of_handle': row.get('rt_of_handle'),
        'reply_to_id': _sid(row.get('reply_to_id')),
        'article': _json_field(row.get('article')),
        # v13: [{url, expanded_url, display_url, indices}] — the renderers replace a
        # matching t.co by exact string, never by indices (they misalign once the
        # RT prefix or an article title is stripped from the text)
        'urls': _json_field(row.get('urls')),
        'feed': feed,
        'feed_kind': x_feed_kind(feed),
        'verdict': row.get('verdict'),  # Phase 4
        'verdict_meta': _json_field(row.get('verdict_meta')),
    }


def x_envelope(
    row: dict,
    is_read: bool,
    is_saved: bool,
    feedback: Optional[str] = None,
    feedback_reason: Optional[str] = None,
) -> dict:
    """Wrap a tweet row/payload into the item envelope.

    The sort timestamp is feed-dependent: For You uses ``first_seen_at`` (the
    algorithm resurfaces days-old tweets, and ``created_at`` would splice those
    into timeline history), a followed account uses the tweet's own time.

    ``feedback`` ('up' / 'down' / None) is the reader's own label from
    ``item_feedback``. It sits at the envelope level, not inside the payload,
    because the table is source-generic like read/saved/hidden — the field
    appears on the other sources' envelopes when their UI grows the buttons.

    ``feedback_reason`` (v9) is its optional chip, carried as a sibling field
    rather than nested into ``feedback``: shipped iOS builds decode ``feedback``
    as a bare string, and turning it into an object would fail the whole page's
    decode on a binary the user installs separately from the server.
    """
    payload = x_payload(row)
    if payload['feed_kind'] == 'home':
        dt = payload['first_seen_at']
    else:
        dt = payload['created_at'] or payload['first_seen_at']
    return {
        'source': 'x',
        'key': x_key(payload['id']),
        'datetime': dt,
        'is_read': is_read,
        'is_saved': is_saved,
        'feedback': feedback,
        'feedback_reason': feedback_reason,
        'x': payload,
    }
