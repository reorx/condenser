"""Hacker News timeline source provider (plan 2.3).

Archive-everything, read-compressed: ``hn_stories`` holds every story that
reached the front page; the query only surfaces each day's top-N per the
subscription's ``display_mode`` (top10/top20/half/all). Rank is computed
query-time (scores keep moving while a day is live), so the visible set —
and with it unread counts — can shift slightly between polls; that's accepted
(plan 2.3). Sort key is ``first_seen_at`` (append-only timeline semantics).

Two floors are ANDed onto that rank (plan 2026-08-14, phases A + B). A day's
top-N is a *relative* bar and it does not exist yet at the start of a UTC day:
with nine rows in the partition, "top 10" is "everything", and UTC midnight is
08:00 Beijing — the bar hits zero exactly when the reader opens the app. That is
how 6- and 7-point stories reached the timeline. ``min_score`` is the absolute
guardrail for that window (a mature day cuts at 243-476 points, so it is never
binding there), and ``max_peak_rank`` aims at what no score floor can see: the
second-chance-pool repost that carries a decent score but never climbed past the
front page's tail. Both are AND-only — see ``_admission_where``. The peak-rank
gate ships **off**: measured on production it only ever hit stories the score
floor had already taken, plus three of the archive's biggest hits (see
``DEFAULT_MAX_PEAK_RANK``).
"""

import json
from typing import NamedTuple, Optional

from telememo import db as tdb

from .. import db
from ..items import hn_envelope, norm_ts
from .base import NEW_COUNT_BUFFER, SourcePage, SourceUnit, pack_pos, unpack_pos

DEFAULT_DISPLAY_MODE = 'top20'
# Deliberately below any mature day's real cut (243-476 over 30 days of
# production), so this only ever binds on a day that has not formed yet.
DEFAULT_MIN_SCORE = 50
# Off by default, and that is a measurement, not caution (2026-08-14, on a 32-day
# production snapshot — tmp/2026-08-14-hn-admission/). At 20 the gate drops four
# stories: one 14-pointer the score floor already rejects, and three of the whole
# archive's biggest hits (1235 / 708 / 703 points, sitting at #2, #8 and #2 of
# their day). Zero true positives, three false ones.
#
# The reason is that peak_rank is the best rank we *observed*, not the best rank
# the story *reached*: sampling is 10-minutely and every deploy restarts the
# process, so a story whose peak falls in a gap is recorded on its way down. All
# three were first seen 1.5-24h after submission. And the case the gate was meant
# for — a second-chance-pool repost — is by construction also a story we meet
# late, so no "did we watch it early" test separates the two. Score does, and
# that is DEFAULT_MIN_SCORE's job.
DEFAULT_MAX_PEAK_RANK = 0
_MODE_TOP = {'top10': 10, 'top20': 20}

# Rank every live story within its archive day; day_total feeds the 'half' mode.
_RANKED = """
    SELECT h.*, ROW_NUMBER() OVER (PARTITION BY h.day ORDER BY h.score DESC, h.id ASC) AS day_rank,
           COUNT(*) OVER (PARTITION BY h.day) AS day_total
    FROM hn_stories h
    WHERE h.is_dead = 0
"""


class FeedConfig(NamedTuple):
    """The front feed's admission settings — one config read per query."""

    mode: str
    min_score: int  # 0 = off
    max_peak_rank: int  # 0 = off


def _positive_int(value, default: int) -> int:
    """Coerce a config value to a non-negative int, else fall back to the default.

    The config column is a free-form JSON dict any PATCH can write into, so this
    is what keeps junk out of the SQL. Falling back to the *default* rather than
    to 0 matters: a typo must not silently disarm the floor.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def feed_config() -> Optional[FeedConfig]:
    """The enabled front-feed subscription's admission config, or None when inactive.

    A key that is absent falls back to its default, which is what arms the score
    floor on a subscription row written before it existed.
    """
    sub = db.get_hn_subscription('front')
    if sub is None or not sub.enabled:
        return None
    cfg = json.loads(sub.config) if sub.config else {}
    return FeedConfig(
        mode=cfg.get('display_mode') or DEFAULT_DISPLAY_MODE,
        min_score=_positive_int(cfg.get('min_score'), DEFAULT_MIN_SCORE),
        max_peak_rank=_positive_int(cfg.get('max_peak_rank'), DEFAULT_MAX_PEAK_RANK),
    )


def active() -> bool:
    return feed_config() is not None


def _mode_where(mode: str) -> tuple[str, list]:
    if mode == 'all':
        return '1 = 1', []
    if mode == 'half':
        # ceil(day_total / 2): a single-story day stays visible
        return 'r.day_rank * 2 <= r.day_total + 1', []
    return 'r.day_rank <= ?', [_MODE_TOP.get(mode, 20)]


def _admission_where(cfg: FeedConfig) -> tuple[list[str], list]:
    """What is allowed on the timeline: the day's top-N AND both floors.

    Every surface that counts HN items derives from this one function — the page,
    the poll, the calendar and the unread badge — because a floor applied to the
    page alone leaves the badge promising a backlog no view can produce.

    ``peak_rank IS NULL`` passes: the hckrnews backfill stores no rank, and 593
    production rows are that shape. Rejecting NULL would drop the entire imported
    history in one deploy.

    Both are AND-only, never an OR fast lane. 689 of the 2679 stories that never
    made a day's top 10 had touched the front page's top 5 at some point, so
    ``score >= floor OR peak_rank <= 5`` would admit ~23 pieces of junk a day.
    """
    mode_sql, params = _mode_where(cfg.mode)
    where = [mode_sql]
    if cfg.min_score > 0:
        where.append('r.score >= ?')
        params.append(cfg.min_score)
    if cfg.max_peak_rank > 0:
        where.append('(r.peak_rank IS NULL OR r.peak_rank <= ?)')
        params.append(cfg.max_peak_rank)
    return where, params


# Hidden stories are excluded after ranking (outer anti-join), so hiding a
# top-N story leaves a gap instead of promoting a below-cut story into view.
_HIDDEN_JOIN = "LEFT JOIN hidden_items hd ON hd.source = 'hn' AND hd.ref1 = r.id"


def _fetch(where: list[str], params: list, descending: bool, limit: int) -> list[dict]:
    order = 'DESC' if descending else 'ASC'
    sql = (
        'SELECT r.*, CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read, '
        'CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved '
        f'FROM ({_RANKED}) r '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = r.id "
        "LEFT JOIN saved_items si ON si.source = 'hn' AND si.ref1 = r.id "
        f'{_HIDDEN_JOIN} '
        'WHERE ' + ' AND '.join(where) + f' ORDER BY r.first_seen_at {order}, r.id {order} LIMIT ?'
    )
    cur = tdb.db.execute_sql(sql, (*params, limit))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _base_where(cfg: FeedConfig, date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    where, params = _admission_where(cfg)
    where.append('hd.ref1 IS NULL')
    if date:
        where.append('r.day = ?')
        params.append(date)
    if unread_only:
        where.append('ri.ref1 IS NULL')
    return where, params


def _to_unit(row: dict) -> SourceUnit:
    pos = pack_pos(row['first_seen_at'], row['id'])
    return SourceUnit(
        sort_ts=norm_ts(row['first_seen_at']),
        envelope=hn_envelope(row, bool(row['is_read']), bool(row['is_saved'])),
        boundary=pos,
        head=pos,
    )


def fetch_page(
    cursor: Optional[str],
    limit: int,
    date: Optional[str] = None,
    unread_only: bool = False,
) -> SourcePage:
    """Older-direction page of visible stories after ``cursor`` (first_seen desc)."""
    cfg = feed_config()
    if cfg is None:
        return SourcePage(units=[], has_more=False)
    where, params = _base_where(cfg, date, unread_only)
    if cursor:
        cts, cid = unpack_pos(cursor)
        where.append('((r.first_seen_at < ?) OR (r.first_seen_at = ? AND r.id < ?))')
        params.extend([cts, cts, cid])

    rows = _fetch(where, params, descending=True, limit=limit + 1)
    return SourcePage(units=[_to_unit(r) for r in rows[:limit]], has_more=len(rows) > limit)


def fetch_new(after: str, limit: int, unread_only: bool = False) -> list[SourceUnit]:
    """Visible stories strictly newer than the ``after`` position (newest first)."""
    cfg = feed_config()
    if cfg is None:
        return []
    cts, cid = unpack_pos(after)
    where, params = _base_where(cfg, None, unread_only)
    where.append('((r.first_seen_at > ?) OR (r.first_seen_at = ? AND r.id > ?))')
    params.extend([cts, cts, cid])
    return [_to_unit(r) for r in _fetch(where, params, descending=True, limit=limit + NEW_COUNT_BUFFER)]


def days() -> dict[str, int]:
    """Per-day visible-story counts (respects the display mode + both floors)."""
    cfg = feed_config()
    if cfg is None:
        return {}
    where, params = _admission_where(cfg)
    sql = (
        f'SELECT r.day, COUNT(*) FROM ({_RANKED}) r {_HIDDEN_JOIN} '
        f'WHERE {" AND ".join(where)} AND hd.ref1 IS NULL GROUP BY r.day'
    )
    cur = tdb.db.execute_sql(sql, tuple(params))
    return {row[0]: row[1] for row in cur.fetchall()}


def rows_by_id(story_ids: list[int]) -> dict[int, dict]:
    """Stories by id with read/saved flags, for the full-text search assembler.

    Neither display-mode scoped nor rank-annotated, and both on purpose: search
    reads the archive, so a story that fell below its day's cut is still a story
    that was on the front page — and ``day_rank`` is a property of the timeline
    view, which is why a saved record carries None there too.
    """
    if not story_ids:
        return {}
    placeholders = ','.join('?' for _ in story_ids)
    cur = tdb.db.execute_sql(
        'SELECT h.*, CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read, '
        'CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved '
        'FROM hn_stories h '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = h.id "
        "LEFT JOIN saved_items si ON si.source = 'hn' AND si.ref1 = h.id "
        f'WHERE h.id IN ({placeholders})',
        tuple(story_ids),
    )
    columns = [c[0] for c in cur.description]
    return {row[0]: dict(zip(columns, row)) for row in cur.fetchall()}


def unread_count() -> int:
    """Unread visible stories — must match the display filter or the badge never clears."""
    cfg = feed_config()
    if cfg is None:
        return 0
    where, params = _admission_where(cfg)
    sql = (
        f'SELECT COUNT(*) FROM ({_RANKED}) r '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = r.id "
        f'{_HIDDEN_JOIN} '
        f'WHERE {" AND ".join(where)} AND ri.ref1 IS NULL AND hd.ref1 IS NULL'
    )
    return tdb.db.execute_sql(sql, tuple(params)).fetchone()[0]
