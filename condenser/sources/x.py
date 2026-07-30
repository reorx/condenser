"""X (Twitter) timeline source provider (plan Phase 2).

Three feed kinds share the source and they behave very differently:

* **For You** (``foryou``) is a firehose. bird's ``home`` endpoint re-samples on
  every call (Phase 1 measurement: three consecutive calls, zero overlap), so the
  archive grows by ~2400 tweets/day. Dumping that into the aggregate timeline
  would bury Telegram and Hacker News, so For You is **opt-in**: by default it
  only appears in the X-scoped views (``?source=x``). Sorted by ``first_seen_at``
  — the algorithm resurfaces days-old tweets and ``created_at`` would splice them
  into timeline history (same reasoning as the HN front page).

  Since 2026-07-29 the subscription's ``aggregate`` mode can let some of it
  through, because the verdict changed the arithmetic the capacity decision was
  made on: measured on production, For You arrives at 57–136 tweets/day of which
  ~13% are judged positive, against ~50 Telegram messages a day. ``positive``
  therefore adds about a fifth to the aggregate rather than burying it. The mode
  lives in the subscription config (HN's ``display_mode`` pattern) because the
  right setting depends on how good the classifier currently is, and that changes
  with every label — it must be a click, not a deploy.
* **Following** (``following``) is the chronological "accounts you follow"
  timeline — one feed standing in for all of them. Measured, it is *not* a
  firehose: two consecutive calls overlapped 19/20, i.e. a stable window rather
  than a fresh sample, at ~100-200 tweets/day. So it joins the aggregate in full
  by default, and sorts by ``created_at`` like any ordinary time series. The
  entries X pads it with (ads, thread ancestors) are filtered at ingest, not here
  — see ``x._apply_following_rules``.
* **A followed account** is an ordinary time series, like a TG channel: it joins
  the aggregate merge and sorts by the tweet's own ``created_at``.

One tweet can appear in several feeds (For You includes people you follow;
Following overlaps every account subscription), so the query de-duplicates by
tweet id under an explicit priority — the card then keeps the same position, the
same badge and the same unread owner whichever view you open it from.
"""

import json
from typing import Optional

from telememo import db as tdb

from .. import db
from ..items import FOLLOWING_FEED, FORYOU_FEED, norm_ts, x_envelope
from .base import NEW_COUNT_BUFFER, SourcePage, SourceUnit, pack_pos, unpack_pos

# How much of a feed joins the *aggregate* timeline. A feed's own view is never
# filtered by this — For You's view is where the reader labels, and hiding
# candidates there would starve the classifier of the negatives it needs.
#
# Only the two synthetic feeds have a choice to make, and they have different
# ones. For You is a firehose of strangers, so its useful middle setting is "only
# what the verdict recommends" and its default is to stay out. Following is a set
# the reader curated by hand and is never judged at all (the verdict exists to
# filter strangers the algorithm picked), so 'positive' is not offered — it would
# silently hide the whole feed — and the default is to merge in.
AGGREGATE_MODES = {
    FORYOU_FEED: ('none', 'positive', 'all'),
    FOLLOWING_FEED: ('none', 'all'),
}
DEFAULT_AGGREGATE_MODE = {FORYOU_FEED: 'none', FOLLOWING_FEED: 'all'}
# A followed account is a choice already made — subscribing to it *is* the setting.
ACCOUNT_AGGREGATE_MODE = 'all'

# The feed-dependent sort key, as SQL over (x_feed_items f JOIN x_tweets t).
# COALESCE guards a tweet whose timestamp failed to parse (stored NULL, raw kept
# for a re-parse). Exported because bulk-read has to agree on the day boundary.
SORT_AT_SQL = (
    f"COALESCE(CASE WHEN f.channel_id = '{FORYOU_FEED}' THEN f.first_seen_at ELSE t.created_at END, f.first_seen_at)"
)


def _sort_at(channels: list[str]) -> str:
    """``SORT_AT_SQL`` specialized to the scope.

    With For You alone in scope the CASE is constant-true, so the key is just
    ``first_seen_at`` — a plain column, which lets SQLite order the page straight
    off ``x_feed_items(channel_id, first_seen_at)`` instead of sorting the whole
    feed into a temp b-tree. That is the feed the archive actually grows on.
    """
    if channels == [FORYOU_FEED]:
        return 'f.first_seen_at'
    return SORT_AT_SQL


# Same tweet in several feeds -> one row. The winner is not cosmetic: it decides
# the sort timestamp (SORT_AT_SQL), whether the tweet may join the aggregate
# (_scope_where), and which feed owns its verdict badge and unread count.
#
# Explicitly ranked rather than "earliest sighting wins", which is what it was
# while For You and one account were the only pair that could collide. With
# Following in the mix, a tweet by an account you *also* subscribe to sits in two
# non-For-You feeds, and first-sighting would let its unread count drift between
# the two rows depending on which push happened to land first.
_DEDUP_RANK = f"""
    ROW_NUMBER() OVER (
        PARTITION BY f.tweet_id
        ORDER BY CASE f.channel_id
                   WHEN '{FORYOU_FEED}' THEN 2
                   WHEN '{FOLLOWING_FEED}' THEN 1
                   ELSE 0 END ASC,
                 f.first_seen_at ASC
    )
"""


def _visible(where: list[str], dedup: bool = True, sort_at: str = SORT_AT_SQL) -> str:
    """The scoped feed-appearance subquery.

    The scope filter lives INSIDE it, which matters twice: ranking must only
    consider the feeds the query actually reads (else a tweet in two feeds gets
    rank 2 and vanishes from a For You-only view), and it keeps the
    ``x_feed_items(channel_id, …)`` index usable instead of scanning the archive.

    ``dedup=False`` drops the window function for a single-feed scope, where it
    is provably a no-op — ``(channel_id, tweet_id)`` is the primary key, so one
    feed holds a tweet at most once — and the window would otherwise force a
    materialize+sort of the whole feed on every page.
    """
    return f"""
    SELECT f.channel_id AS feed, f.tweet_id AS tweet_id, f.first_seen_at AS first_seen_at,
           f.verdict AS verdict, f.verdict_meta AS verdict_meta,
           {sort_at} AS sort_at,
           {_DEDUP_RANK if dedup else '1'} AS dedup_rank
    FROM x_feed_items f
    JOIN x_tweets t ON t.id = f.tweet_id
    WHERE {' AND '.join(where)}
"""


_COLS = """
    v.feed AS feed, v.first_seen_at AS first_seen_at, v.sort_at AS sort_at,
    v.verdict AS verdict, v.verdict_meta AS verdict_meta,
    t.id AS id, t.author_id AS author_id, t.author_handle AS author_handle,
    t.author_name AS author_name, t.text AS text, t.created_at AS created_at,
    t.media AS media, t.metrics AS metrics,
    t.rt_of_handle AS rt_of_handle, t.reply_to_id AS reply_to_id, t.article AS article,
    q.id AS q_id, q.author_handle AS q_author_handle, q.author_name AS q_author_name,
    q.text AS q_text, q.created_at AS q_created_at, q.media AS q_media, q.metrics AS q_metrics,
    CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read,
    CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved,
    fb.verdict AS feedback, fb.reason AS feedback_reason
"""

_JOINS = """
    JOIN x_tweets t ON t.id = v.tweet_id
    LEFT JOIN x_tweets q ON q.id = t.quote_of
    LEFT JOIN read_items ri ON ri.source = 'x' AND ri.ref1 = v.tweet_id
    LEFT JOIN saved_items si ON si.source = 'x' AND si.ref1 = v.tweet_id
    LEFT JOIN hidden_items hd ON hd.source = 'x' AND hd.ref1 = v.tweet_id
    LEFT JOIN item_feedback fb ON fb.source = 'x' AND fb.ref1 = v.tweet_id
"""


def normalize_feed(feed: Optional[str]) -> Optional[str]:
    """Accept a feed key however the user typed it ('@NovoReorx' -> 'novoreorx')."""
    cleaned = (feed or '').strip().lstrip('@').lower()
    return cleaned or None


def aggregate_mode(feed: str, sub: Optional[db.Subscription] = None) -> str:
    """How much of ``feed`` joins the aggregate timeline.

    Unknown values fall back to the feed's default rather than raising: this reads
    a JSON blob the user can PATCH, and a typo must not decide that the firehose
    joins the main timeline — nor that Following, whose only sensible middle
    setting does not exist, disappears from it.
    """
    allowed = AGGREGATE_MODES.get(feed)
    if allowed is None:
        return ACCOUNT_AGGREGATE_MODE
    if sub is None:
        sub = db.get_x_subscription(feed)
    if sub is None or not sub.enabled:
        return DEFAULT_AGGREGATE_MODE[feed]
    try:
        config = json.loads(sub.config) if sub.config else {}
    except ValueError:
        return DEFAULT_AGGREGATE_MODE[feed]
    mode = config.get('aggregate')
    return mode if mode in allowed else DEFAULT_AGGREGATE_MODE[feed]


def aggregate_modes() -> dict[str, str]:
    """Every enabled feed's aggregate mode, read in one pass."""
    return {sub.channel_id: aggregate_mode(sub.channel_id, sub) for sub in db.enabled_x_subscriptions()}


def is_aggregate(feed: Optional[str], include_foryou: bool) -> bool:
    """Is this the everything-merged view, rather than an X-scoped one?

    The distinction the admission rule turns on: only the aggregate applies the
    per-feed modes, and only the aggregate's "mark all read" obeys them.
    """
    return normalize_feed(feed) is None and not include_foryou


def scope(feed: Optional[str], include_foryou: bool) -> list[str]:
    """The enabled feed keys this query reads (empty = nothing to show).

    The aggregate drops whatever is set to ``none`` — For You's default, and the
    rule that used to be a hardcoded "not For You" inside ``db.enabled_x_feeds``.
    An X-scoped or feed-scoped view reads everything that is subscribed.
    """
    channels = db.enabled_x_feeds(normalize_feed(feed))
    if not is_aggregate(feed, include_foryou):
        return channels
    modes = aggregate_modes()
    return [c for c in channels if modes.get(c, ACCOUNT_AGGREGATE_MODE) != 'none']


def active(feed: Optional[str] = None, include_foryou: bool = False) -> bool:
    return bool(scope(feed, include_foryou))


def _scope_where(channels: list[str], aggregate: bool = False) -> tuple[list[str], list]:
    """The subquery's feed filter — see the note on ``_visible``.

    The admission predicate rides along inside it for the same reason the scope
    filter does: dedup ranking must only see the rows this query may show, or a
    tweet whose For You copy is filtered out could rank second and vanish.
    """
    where = [f'f.channel_id IN ({",".join("?" for _ in channels)})']
    params = list(channels)
    if aggregate:
        modes = aggregate_modes()
        for channel in channels:
            if modes.get(channel) == 'positive':
                where.append('(f.channel_id <> ? OR f.verdict = ?)')
                params.extend([channel, 'positive'])
    return where, params


def _dedup_needed(channels: list[str]) -> bool:
    return len(channels) > 1


def _base_where(date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    where = ['v.dedup_rank = 1', 'hd.ref1 IS NULL']
    params: list = []
    if date:
        where.append('substr(v.sort_at, 1, 10) = ?')
        params.append(date)
    if unread_only:
        where.append('ri.ref1 IS NULL')
    return where, params


def _select(
    projection: str,
    scope_where: list[str],
    where: list[str],
    tail: str,
    dedup: bool = True,
    sort_at: str = SORT_AT_SQL,
) -> str:
    return (
        f'SELECT {projection} FROM ({_visible(scope_where, dedup, sort_at)}) v {_JOINS} WHERE '
        + ' AND '.join(where)
        + tail
    )


def _fetch(
    scope_where: list[str],
    scope_params: list,
    where: list[str],
    params: list,
    descending: bool,
    limit: int,
    dedup: bool = True,
    sort_at: str = SORT_AT_SQL,
) -> list[dict]:
    order = 'DESC' if descending else 'ASC'
    sql = _select(_COLS, scope_where, where, f' ORDER BY v.sort_at {order}, v.tweet_id {order} LIMIT ?', dedup, sort_at)
    cur = tdb.db.execute_sql(sql, (*scope_params, *params, limit))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _to_unit(row: dict) -> SourceUnit:
    pos = pack_pos(row['sort_at'], row['id'])
    return SourceUnit(
        sort_ts=norm_ts(row['sort_at']),
        envelope=x_envelope(row, bool(row['is_read']), bool(row['is_saved']), row['feedback'], row['feedback_reason']),
        boundary=pos,
        head=pos,
    )


def fetch_page(
    cursor: Optional[str],
    limit: int,
    feed: Optional[str] = None,
    include_foryou: bool = False,
    date: Optional[str] = None,
    unread_only: bool = False,
) -> SourcePage:
    """Older-direction page of visible tweets after ``cursor``."""
    channels = scope(feed, include_foryou)
    if not channels:
        return SourcePage(units=[], has_more=False)
    scope_where, scope_params = _scope_where(channels, is_aggregate(feed, include_foryou))
    where, params = _base_where(date, unread_only)
    if cursor:
        cts, cid = unpack_pos(cursor)
        where.append('((v.sort_at < ?) OR (v.sort_at = ? AND v.tweet_id < ?))')
        params.extend([cts, cts, cid])

    rows = _fetch(
        scope_where, scope_params, where, params, True, limit + 1, _dedup_needed(channels), _sort_at(channels)
    )
    return SourcePage(units=[_to_unit(r) for r in rows[:limit]], has_more=len(rows) > limit)


def fetch_new(
    after: str,
    limit: int,
    feed: Optional[str] = None,
    include_foryou: bool = False,
    unread_only: bool = False,
) -> list[SourceUnit]:
    """Visible tweets strictly newer than the ``after`` position (newest first)."""
    channels = scope(feed, include_foryou)
    if not channels:
        return []
    cts, cid = unpack_pos(after)
    scope_where, scope_params = _scope_where(channels, is_aggregate(feed, include_foryou))
    where, params = _base_where(None, unread_only)
    where.append('((v.sort_at > ?) OR (v.sort_at = ? AND v.tweet_id > ?))')
    params.extend([cts, cts, cid])
    rows = _fetch(
        scope_where,
        scope_params,
        where,
        params,
        True,
        limit + NEW_COUNT_BUFFER,
        _dedup_needed(channels),
        _sort_at(channels),
    )
    return [_to_unit(r) for r in rows]


def days(feed: Optional[str] = None, include_foryou: bool = False) -> dict[str, int]:
    """Per-day visible-tweet counts, on the same day key the timeline sorts by."""
    channels = scope(feed, include_foryou)
    if not channels:
        return {}
    scope_where, scope_params = _scope_where(channels, is_aggregate(feed, include_foryou))
    where, params = _base_where(None, False)
    sql = _select(
        'substr(v.sort_at, 1, 10) AS day, COUNT(*)',
        scope_where,
        where,
        ' GROUP BY day',
        _dedup_needed(channels),
        _sort_at(channels),
    )
    cur = tdb.db.execute_sql(sql, (*scope_params, *params))
    return {row[0]: row[1] for row in cur.fetchall()}


def unread_counts() -> dict[str, int]:
    """Per-feed unread counts for the subscription listing (For You included —
    it is hidden from the aggregate, not from its own view)."""
    return _unread_counts(include_foryou=True)


def aggregate_unread_counts() -> dict[str, int]:
    """Per-feed unread counts **as the aggregate timeline would show them**.

    A second number rather than a replacement, because the two mean different
    things and both are on screen: the sidebar row opens the feed's own view (all
    8 unread), while the All/Unread badge above it promises what the aggregate
    holds (the 1 that was recommended). Summing the first into the second is how
    that badge came to advertise a backlog no view could produce.
    """
    return _unread_counts(include_foryou=False)


def _unread_counts(include_foryou: bool) -> dict[str, int]:
    channels = scope(None, include_foryou)
    if not channels:
        return {}
    scope_where, scope_params = _scope_where(channels, is_aggregate(None, include_foryou))
    where, params = _base_where(None, unread_only=True)
    sql = _select(
        'v.feed, COUNT(*)', scope_where, where, ' GROUP BY v.feed', _dedup_needed(channels), _sort_at(channels)
    )
    cur = tdb.db.execute_sql(sql, (*scope_params, *params))
    return {row[0]: row[1] for row in cur.fetchall()}


def bulk_read_scope(feed: Optional[str], include_foryou: bool) -> tuple[list[str], list, list[str]]:
    """(feeds, params, extra WHERE) for the "mark all read" sweep.

    Lives here rather than in db.py for the same reason ``SORT_AT_SQL`` does: the
    sweep must burn exactly what the timeline showed, and the moment those two
    definitions live apart, "mark all read" in the aggregate silently destroys the
    For You backlog the classifier is still learning from.
    """
    channels = scope(feed, include_foryou)
    if not channels:
        return [], [], []
    where, params = _scope_where(channels, is_aggregate(feed, include_foryou))
    return channels, params, where


def get_row(tweet_id: int) -> Optional[dict]:
    """One tweet as a timeline row (for the saved-record snapshot), or None.

    Not feed-scoped: a saved record is the user's asset, so it must still snapshot
    after the feed it came from was paused or unsubscribed.
    """
    rows = _fetch(['f.tweet_id = ?'], [tweet_id], ['v.dedup_rank = 1'], [], True, 1)
    return rows[0] if rows else None
