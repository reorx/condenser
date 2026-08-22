"""RSS timeline source provider (plan 2026-08-20 §4).

The simplest provider in the project: one row per entry, no album grouping, no
admission judge, no verdict. Every archived entry of an enabled feed is a
timeline item — the plan's §0.2 decision, which is what makes RSS a peer of
Telegram rather than an opt-in like X's For You.

The one thing it does own is **the sort timestamp**. ``rss_entries`` keeps two
times and neither is usable alone: ``published_at`` is what the feed declared
(often absent, occasionally in the future — some publishers post-date, some just
have a broken clock) and ``first_seen_at`` is when we met the entry, which on an
OPML import is "all of them, now". So the sort key is the declared time, clamped
to our own sighting when it is missing or implausibly ahead of it. The clamp is
applied **here**, in SQL, and never to the stored row: the archive keeps the
evidence and the detail pane still shows what the feed claimed.

Because the clamp is an expression rather than a column, the computed value is
selected as ``sort_at`` and carried into the envelope — so a saved snapshot, which
replays without ever touching this table again, records the answer rather than
having to recompute it from a rule that lives in SQL.
"""

from typing import Optional

from telememo import db as tdb

from .. import db
from ..items import norm_ts, rss_envelope
from .base import NEW_COUNT_BUFFER, SourcePage, SourceUnit, pack_pos, unpack_pos

# How far a feed's own timestamp may lead our first sighting before we stop
# believing it. Not zero: we poll every 30 minutes, so an entry published a few
# minutes before the round that found it is legitimately "ahead" of nothing, and
# rewriting those would move real publication times for no gain.
FUTURE_TOLERANCE = '+30 minutes'

# The timeline position of an entry. Kept as one string because four queries share
# it (page, poll, days, bulk read) and a second copy is how they drift apart.
SORT_AT_SQL = (
    'CASE WHEN e.published_at IS NULL '
    f"       OR e.published_at > datetime(e.first_seen_at, '{FUTURE_TOLERANCE}') "
    '     THEN e.first_seen_at ELSE e.published_at END'
)
_DAY_SQL = f'substr({SORT_AT_SQL}, 1, 10)'

# The subscription is LEFT joined so one FROM clause serves both the reading
# surfaces (which add ``s.enabled = 1``) and search's row lookup, which reads the
# archive and must reach a paused feed. ``rss_feeds`` supplies the display title
# for the window before the subscription row has learned one.
_FROM = """
    FROM rss_entries e
    LEFT JOIN subscriptions s ON s.source = 'rss' AND s.channel_id = e.feed_url
    LEFT JOIN rss_feeds f ON f.url = e.feed_url
    LEFT JOIN read_items ri ON ri.source = 'rss' AND ri.ref1 = e.id AND ri.ref2 = 0
    LEFT JOIN saved_items si ON si.source = 'rss' AND si.ref1 = e.id AND si.ref2 = 0
    LEFT JOIN hidden_items hd ON hd.source = 'rss' AND hd.ref1 = e.id AND hd.ref2 = 0
"""

_SELECT = (
    f'SELECT e.*, {SORT_AT_SQL} AS sort_at, COALESCE(s.name, f.title) AS feed_title, '
    'CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read, '
    'CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved'
)


def active() -> bool:
    """Whether RSS participates in the aggregate timeline: any enabled feed."""
    return db.rss_polling_active()


def _rows(sql: str, params: tuple) -> list[dict]:
    cur = tdb.db.execute_sql(sql, params)
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _base_where(feed: Optional[str], date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    where = ['s.enabled = 1', 'hd.ref1 IS NULL']
    params: list = []
    if feed:
        where.append('e.feed_url = ?')
        params.append(feed)
    if date:
        where.append(f'{_DAY_SQL} = ?')
        params.append(date)
    if unread_only:
        where.append('ri.ref1 IS NULL')
    return where, params


def _fetch(where: list[str], params: list, limit: int) -> list[dict]:
    sql = f'{_SELECT} {_FROM} WHERE ' + ' AND '.join(where) + ' ORDER BY sort_at DESC, e.id DESC LIMIT ?'
    return _rows(sql, (*params, limit))


def _to_unit(row: dict) -> SourceUnit:
    pos = pack_pos(row['sort_at'], row['id'])
    return SourceUnit(
        sort_ts=norm_ts(row['sort_at']),
        envelope=rss_envelope(row, bool(row['is_read']), bool(row['is_saved'])),
        boundary=pos,
        head=pos,
    )


def fetch_page(
    cursor: Optional[str],
    limit: int,
    feed: Optional[str] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
) -> SourcePage:
    """Older-direction page of entries after ``cursor`` (sort timestamp desc)."""
    if not active():
        return SourcePage(units=[], has_more=False)
    where, params = _base_where(feed, date, unread_only)
    if cursor:
        cts, cid = unpack_pos(cursor)
        where.append(f'(({SORT_AT_SQL} < ?) OR ({SORT_AT_SQL} = ? AND e.id < ?))')
        params.extend([cts, cts, cid])
    rows = _fetch(where, params, limit + 1)
    return SourcePage(units=[_to_unit(r) for r in rows[:limit]], has_more=len(rows) > limit)


def fetch_new(after: str, limit: int, feed: Optional[str] = None, unread_only: bool = False) -> list[SourceUnit]:
    """Entries strictly newer than the ``after`` position (newest first)."""
    if not active():
        return []
    cts, cid = unpack_pos(after)
    where, params = _base_where(feed, None, unread_only)
    where.append(f'(({SORT_AT_SQL} > ?) OR ({SORT_AT_SQL} = ? AND e.id > ?))')
    params.extend([cts, cts, cid])
    return [_to_unit(r) for r in _fetch(where, params, limit + NEW_COUNT_BUFFER)]


def days(feed: Optional[str] = None) -> dict[str, int]:
    """Per-day visible-entry counts, keyed by the **sort** day.

    Not the archive day: an entry whose declared date puts it on another day sorts
    there, and a calendar that disagrees with the page sends the reader to an empty
    view.
    """
    if not active():
        return {}
    where, params = _base_where(feed, None, False)
    sql = f'SELECT {_DAY_SQL}, COUNT(*) {_FROM} WHERE ' + ' AND '.join(where) + f' GROUP BY {_DAY_SQL}'
    return {row[0]: row[1] for row in tdb.db.execute_sql(sql, tuple(params)).fetchall()}


def unread_counts() -> dict[str, int]:
    """Per-feed unread counts for the sidebar, keyed by feed URL."""
    where, params = _base_where(None, None, True)
    sql = f'SELECT e.feed_url, COUNT(*) {_FROM} WHERE ' + ' AND '.join(where) + ' GROUP BY e.feed_url'
    return {row[0]: row[1] for row in tdb.db.execute_sql(sql, tuple(params)).fetchall()}


def unread_count(feed: Optional[str] = None) -> int:
    counts = unread_counts()
    return counts.get(feed, 0) if feed else sum(counts.values())


def rows_by_id(entry_ids: list[int]) -> list[dict]:
    """Entries by id with read/saved flags and the computed sort timestamp.

    Deliberately **not** subscription-scoped (``telegram.units_by_key``'s rule):
    the callers are full-text search and the saved-record snapshot, and both read
    the archive rather than the reading list.
    """
    if not entry_ids:
        return []
    rows: list[dict] = []
    for i in range(0, len(entry_ids), 500):  # SQLite's bound-variable limit
        chunk = entry_ids[i : i + 500]
        placeholders = ','.join('?' for _ in chunk)
        rows.extend(_rows(f'{_SELECT} {_FROM} WHERE e.id IN ({placeholders})', tuple(chunk)))
    return rows


def get_row(entry_id: int) -> Optional[dict]:
    rows = rows_by_id([entry_id])
    return rows[0] if rows else None


def bulk_read_scope(before_date: Optional[str]) -> tuple[str, list]:
    """The ``WHERE`` a "mark all read" sweep may burn, plus its parameters.

    Enabled feeds only, and by the same sort day the page groups on: the sweep has
    to burn exactly what the view showed. A paused feed's entries are not "already
    invisible so harmless to mark" — resuming it would hand the reader a backlog
    that is already grey.
    """
    where = ["s.enabled = 1 AND s.source = 'rss'"]
    params: list = []
    if before_date:
        where.append(f'{_DAY_SQL} < ?')
        params.append(before_date)
    return ' AND '.join(where), params
