"""Federated timeline merge (multi-source plan 2.3).

Each source keeps an independent query module (``condenser.sources.*``); this
layer k-way merges their unit streams by timestamp. The public cursor is a
composite: base64(json {source: "<ts>\\x1f<id>", ...}) mapping each source to
its own resume position. A source absent from the map has not been consumed yet
and restarts from its newest unit — which is exactly the unconsumed remainder,
so pages stay seamless across sources draining at different rates.
"""

import base64
import json
from typing import Optional

from . import db, forwards, records
from .items import norm_ts
from .sources import hn as hn_source
from .sources import rss as rss_source
from .sources import telegram as tg_source
from .sources import x as x_source
from .sources.base import SourcePage, pack_pos

SOURCES = ('telegram', 'hn', 'x', 'rss')


class InvalidCursor(ValueError):
    """A cursor string that doesn't decode to a composite cursor map (e.g. a
    pre-Phase-2 cursor from a still-open client, or arbitrary garbage)."""


def encode_cursor_map(cursors: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(cursors, separators=(',', ':')).encode()).decode()


def decode_cursor_map(cursor: str) -> dict[str, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except ValueError as e:  # binascii.Error, JSONDecodeError, UnicodeDecodeError
        raise InvalidCursor(str(e))
    if not isinstance(decoded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in decoded.items()):
        raise InvalidCursor('cursor is not a source map')
    return decoded


def _active_sources(channel_id: Optional[int], source: Optional[str]) -> list[str]:
    """Sources participating in this query. ``channel_id`` implies telegram; an
    explicit ``source`` narrows to it; default = telegram + any active others.

    The aggregate view only counts X as active when a *followed account* is
    subscribed: For You is opt-in (see sources/x.py). RSS has no such carve-out —
    every subscribed feed is in (plan §0.2)."""
    if channel_id is not None:
        return ['telegram']
    if source:
        return [source]
    active = ['telegram']
    if hn_source.active():
        active.append('hn')
    if x_source.active(include_foryou=False):
        active.append('x')
    if rss_source.active():
        active.append('rss')
    return active


def _fetch_pages(
    active: list[str],
    cursors: dict[str, str],
    limit: int,
    channel_id: Optional[int],
    date: Optional[str],
    unread_only: bool,
    source: Optional[str],
    feed: Optional[str],
) -> dict[str, SourcePage]:
    pages: dict[str, SourcePage] = {}
    for s in active:
        if s == 'telegram':
            pages[s] = tg_source.fetch_page(
                cursors.get(s), limit, channel_id=channel_id, date=date, unread_only=unread_only
            )
        elif s == 'x':
            pages[s] = x_source.fetch_page(
                cursors.get(s),
                limit,
                feed=feed,
                include_foryou=source == 'x',
                date=date,
                unread_only=unread_only,
            )
        elif s == 'rss':
            # A feed key only means something inside its own source, and RSS's are
            # URLs: handing one to RSS while the caller meant an X handle would
            # silently empty the source out of an aggregate page.
            pages[s] = rss_source.fetch_page(
                cursors.get(s),
                limit,
                feed=feed if source == 'rss' else None,
                date=date,
                unread_only=unread_only,
            )
        else:
            pages[s] = hn_source.fetch_page(cursors.get(s), limit, date=date, unread_only=unread_only)
    return pages


def query_timeline(
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
    cursor: Optional[str] = None,
    limit: int = 30,
    source: Optional[str] = None,
    feed: Optional[str] = None,
) -> dict:
    """Older-direction page: ``{items, next_cursor, end_cursor, head_cursor}`` (date desc).

    ``next_cursor`` is null once every active source is exhausted; ``end_cursor``
    still anchors the page's consumed positions so a client can resume paging after
    fetch-older imports rows older than the local end (iOS pull-up). ``feed`` narrows
    a multi-feed source (X) to one of its feeds.
    """
    active = _active_sources(channel_id, source)
    cursors = decode_cursor_map(cursor) if cursor else {}
    pages = _fetch_pages(active, cursors, limit, channel_id, date, unread_only, source, feed)

    consumed = dict(cursors)
    idx = {s: 0 for s in active}
    taken = []
    while len(taken) < limit:
        # Floor: a source whose page units are drained but has_more may hold
        # unfetched units up to its last unit's timestamp; emitting an older
        # unit from another source would break global order across pages, so
        # the page ends early instead (short page, has_more stays True).
        floor = None
        for s in active:
            if idx[s] >= len(pages[s].units) and pages[s].has_more and pages[s].units:
                last_ts = pages[s].units[-1].sort_ts
                if floor is None or last_ts > floor:
                    floor = last_ts
        best = None
        for s in active:
            if idx[s] < len(pages[s].units) and (
                best is None or pages[s].units[idx[s]].sort_ts > pages[best].units[idx[best]].sort_ts
            ):
                best = s
        if best is None:
            break
        unit = pages[best].units[idx[best]]
        if floor is not None and unit.sort_ts < floor:
            break
        idx[best] += 1
        consumed[best] = unit.boundary
        taken.append(unit)

    has_more = any(idx[s] < len(pages[s].units) or pages[s].has_more for s in active)
    end_cursor = encode_cursor_map(consumed) if taken else None
    next_cursor = end_cursor if (taken and has_more) else None

    # Per-source newest fetched anchors: /timeline/new polls each source from here.
    # A source with zero units this page (nothing sampled yet / all read in the
    # unread view) gets a "now" anchor so its future items still surface in the
    # poll; both sources' stored timestamp formats compare safely against the
    # 19-char normalized form.
    heads = {s: pages[s].units[0].head for s in active if pages[s].units}
    if len(heads) < len(active):
        now_pos = pack_pos(norm_ts(db._now_naive()), 0)
        for s in active:
            heads.setdefault(s, now_pos)
    head_cursor = encode_cursor_map(heads) if heads else None

    return {
        # Post-hoc stamps rather than more LEFT JOINs in every provider — see
        # forwards.stamp / records.stamp_notes for why these are not in the queries.
        'items': records.stamp_notes(forwards.stamp([u.envelope for u in taken])),
        'next_cursor': next_cursor,
        'end_cursor': end_cursor,
        'head_cursor': head_cursor,
    }


def query_new(
    channel_id: Optional[int],
    after_cursor: str,
    limit: int = 100,
    unread_only: bool = False,
    source: Optional[str] = None,
    feed: Optional[str] = None,
) -> dict:
    """Newer-direction poll: ``{count, items}`` strictly newer than each source's anchor.

    ``unread_only`` must mirror the polled view (see the pre-Phase-2 docstring). A
    source with no anchor in the composite (subscribed after the page was loaded)
    is skipped until the client refetches page 1.
    """
    anchors = decode_cursor_map(after_cursor)
    units = []
    for s in _active_sources(channel_id, source):
        if s not in anchors:
            continue
        if s == 'telegram':
            units += tg_source.fetch_new(anchors[s], limit, channel_id=channel_id, unread_only=unread_only)
        elif s == 'x':
            units += x_source.fetch_new(
                anchors[s], limit, feed=feed, include_foryou=source == 'x', unread_only=unread_only
            )
        elif s == 'rss':
            units += rss_source.fetch_new(
                anchors[s], limit, feed=feed if source == 'rss' else None, unread_only=unread_only
            )
        else:
            units += hn_source.fetch_new(anchors[s], limit, unread_only=unread_only)
    units.sort(key=lambda u: u.sort_ts, reverse=True)
    return {'count': len(units), 'items': records.stamp_notes(forwards.stamp([u.envelope for u in units[:limit]]))}


def query_days(
    channel_id: Optional[int] = None,
    source: Optional[str] = None,
    feed: Optional[str] = None,
) -> list[dict]:
    """Days that have visible content (+ unit counts), summed across active sources."""
    totals: dict[str, int] = {}
    for s in _active_sources(channel_id, source):
        if s == 'telegram':
            counts = tg_source.days(channel_id)
        elif s == 'x':
            counts = x_source.days(feed=feed, include_foryou=source == 'x')
        elif s == 'rss':
            counts = rss_source.days(feed=feed if source == 'rss' else None)
        else:
            counts = hn_source.days()
        for day, cnt in counts.items():
            totals[day] = totals.get(day, 0) + cnt
    return [{'date': day, 'count': totals[day]} for day in sorted(totals, reverse=True)]


# Per-TG-channel unread counts, re-exported for the subscription endpoints.
unread_counts = tg_source.unread_counts
