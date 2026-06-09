"""Keyword filter materialization (spec C5 / D9).

Rules live in ``keyword_filters`` (exclude-only, case-insensitive substring for v1).
The *result* is materialized into the telememo extension column ``messages.is_filtered``
so the timeline query only reads a boolean — matching happens here on the write side,
which keeps queries fast and leaves room for regex later without touching the query.
"""

from typing import Iterable, Optional

from telememo import db as tdb

from . import db


def active_patterns(channel_id: int) -> list[str]:
    """Lowercased exclude patterns in effect for a channel (global + channel-specific)."""
    cur = tdb.db.execute_sql(
        'SELECT pattern FROM keyword_filters WHERE channel_id IS NULL OR channel_id = ?',
        (channel_id,),
    )
    return [row[0].lower() for row in cur.fetchall()]


def text_is_filtered(text: Optional[str], patterns: list[str]) -> bool:
    """True if text contains any exclude pattern (case-insensitive substring)."""
    if not text or not patterns:
        return False
    lowered = text.lower()
    return any(p in lowered for p in patterns)


def _chunked(seq: list, size: int = 500) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _recompute(channel_id: int, message_ids: Optional[list[int]]) -> None:
    """Recompute is_filtered for a channel (or a subset of its messages).

    Resets the scope to 0, then sets matched rows to 1 — so deleting a rule
    correctly clears previously-filtered messages.
    """
    patterns = active_patterns(channel_id)

    if message_ids is None:
        cur = tdb.db.execute_sql('SELECT id, text FROM messages WHERE channel_id = ?', (channel_id,))
        rows = cur.fetchall()
        tdb.db.execute_sql('UPDATE messages SET is_filtered = 0 WHERE channel_id = ?', (channel_id,))
    else:
        if not message_ids:
            return
        rows = []
        for chunk in _chunked(message_ids):
            placeholders = ','.join('?' for _ in chunk)
            cur = tdb.db.execute_sql(
                f'SELECT id, text FROM messages WHERE channel_id = ? AND id IN ({placeholders})',
                (channel_id, *chunk),
            )
            rows.extend(cur.fetchall())
            tdb.db.execute_sql(
                f'UPDATE messages SET is_filtered = 0 WHERE channel_id = ? AND id IN ({placeholders})',
                (channel_id, *chunk),
            )

    filtered_ids = [mid for (mid, text) in rows if text_is_filtered(text, patterns)]
    for chunk in _chunked(filtered_ids):
        placeholders = ','.join('?' for _ in chunk)
        tdb.db.execute_sql(
            f'UPDATE messages SET is_filtered = 1 WHERE channel_id = ? AND id IN ({placeholders})',
            (channel_id, *chunk),
        )


def recompute_channel(channel_id: int) -> None:
    """Recompute is_filtered for every message in a channel (used on rule changes)."""
    _recompute(channel_id, None)


def recompute_messages(channel_id: int, message_ids: list[int]) -> None:
    """Recompute is_filtered for specific freshly-ingested messages."""
    _recompute(channel_id, message_ids)


def recompute_for_rule_change(channel_id: Optional[int]) -> None:
    """Recompute the scope affected by adding/removing a rule.

    A channel-specific rule only affects that channel; a global rule
    (``channel_id is None``) affects every subscribed channel.
    """
    if channel_id is not None:
        recompute_channel(channel_id)
        return
    for cid in db.enabled_channel_ids():
        recompute_channel(cid)
