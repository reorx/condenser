"""Hacker News timeline source provider + its admission judge (plan 2.3, v14).

Archive-everything, read-compressed: ``hn_stories`` holds every story that reached
the front page, and only some of them reach the timeline. Since v14 (plan
2026-08-14 phase 3) *which* ones is decided **once, while polling**, and written
down as ``qualified_at`` — so the read path is a plain
``WHERE qualified_at IS NOT NULL ORDER BY qualified_at DESC``, and the day quota,
the score floor and the peak-rank gate all live in ``qualify()`` below.

That move is the point of the phase, not a refactor. The old rule was a query-time
``ROW_NUMBER()`` over the story's archive day, which made "when it became visible"
and "where it sits" two different instants:

* a story is sorted by ``first_seen_at`` but only becomes visible once its score
  climbs past its day's Nth — an hour or more later, on a formed day — so it
  appeared *behind* the reader's cursor, where paging never reaches it and
  ``/timeline/new`` (which asks for items newer than an anchor) could not report it;
* and the reverse: a story that fell below the cut as the day filled up vanished
  from a timeline the reader had already read.

Admission is therefore **one-way**. A stamped story stays, whatever its score does
next, and the day quota stops meaning "the N best of that day" (a retrospective
view filter) and starts meaning "N a day" (a prospective rate). The two floors
survive unchanged as candidate conditions — see ``qualify``.
"""

import json
import math
from datetime import datetime, time as dtime, timedelta
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
# 'half' has no fixed N to spread over a day, so its rate comes from the archive's
# own recent volume. Median rather than mean: one sampling outage should not halve
# a week of budget.
_HALF_WINDOW_DAYS = 7


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


def stored_config() -> FeedConfig:
    """The front feed's admission settings whether or not the feed is enabled.

    Only history stamping uses this form. A subscription that is paused (or gone)
    at upgrade time still has an archive that *was* visible under some rule, and
    reading the defaults instead would rewrite that history the moment it is
    resumed.
    """
    sub = db.get_hn_subscription('front')
    cfg = json.loads(sub.config) if sub is not None and sub.config else {}
    return FeedConfig(
        mode=cfg.get('display_mode') or DEFAULT_DISPLAY_MODE,
        min_score=_positive_int(cfg.get('min_score'), DEFAULT_MIN_SCORE),
        max_peak_rank=_positive_int(cfg.get('max_peak_rank'), DEFAULT_MAX_PEAK_RANK),
    )


def feed_config() -> Optional[FeedConfig]:
    """The *enabled* front-feed subscription's admission config, or None when inactive.

    A key that is absent falls back to its default, which is what arms the score
    floor on a subscription row written before it existed.
    """
    sub = db.get_hn_subscription('front')
    if sub is None or not sub.enabled:
        return None
    return stored_config()


def active() -> bool:
    return feed_config() is not None


# --- admission (v14): the polling-time judge ---------------------------------


def day_quota(cfg: FeedConfig, day: str) -> Optional[int]:
    """How many stories may be admitted on ``day``. None = no ceiling ('all')."""
    if cfg.mode == 'all':
        return None
    if cfg.mode == 'half':
        counts = sorted(db.hn_daily_archive_counts(_HALF_WINDOW_DAYS, before_day=day))
        if not counts:
            return None
        return math.ceil(counts[len(counts) // 2] / 2)
    return _MODE_TOP.get(cfg.mode, 20)


def budget(quota: Optional[int], now: datetime) -> Optional[int]:
    """Today's cumulative allowance at ``now``: ``ceil(quota * elapsed / 24)``.

    The quota is a *rate*, spread across the day rather than granted at midnight.
    That is what closes the hole this phase exists for: with the whole day's worth
    available from 00:00 UTC — 08:00 Beijing, when the reader opens the app — the
    only thing rationing admissions was the day's own thin population, which is
    how 6-point stories got in. And because admission is one-way, a cumulative
    line is exact rather than approximate: each stamp spends it and nothing gives
    it back (plan §4, §5.3).
    """
    if quota is None:
        return None
    elapsed = (now - datetime.combine(now.date(), dtime.min)).total_seconds() / 3600
    return math.ceil(quota * elapsed / 24)


def qualify(now: datetime, window_hours: int) -> int:
    """Admit as many of today's best unadmitted stories as the budget allows.

    Runs at the tail of every sampling round. Returns how many were stamped.

    Candidates are unadmitted, live, still inside the score-refresh window, and
    past both floors; the best score goes first. Scores are what the floors read,
    which is why this runs *after* the round's snapshot refresh — a story admitted
    on a stale score would be admitted on yesterday's evidence.
    """
    cfg = feed_config()
    if cfg is None:
        return 0
    day = str(now.date())
    quota = day_quota(cfg, day)
    spent = db.hn_qualified_count(day)
    slots = None
    if quota is not None:
        slots = budget(quota, now) - spent
        if slots <= 0:
            return 0
    stories = db.hn_qualification_candidates(
        min_score=cfg.min_score,
        max_peak_rank=cfg.max_peak_rank,
        first_seen_after=now - timedelta(hours=window_hours),
        limit=slots,
    )
    for i, story in enumerate(stories):
        db.stamp_hn_qualified(story.id, now, spent + i + 1)
    return len(stories)


def stamp_history(day: Optional[str] = None) -> int:
    """Stamp a closed day (or the whole archive) where its stories already sit.

    Used by the v14 backfill and by the hckrnews import — both hand us days that
    were over before we could judge them live, and stamping those at ``now`` would
    dump months-old stories at the top of the timeline.
    """
    cfg = stored_config()
    # 'half' caps itself per day inside the rank predicate (it is a share of that
    # day's own population, which a closed day knows exactly), and 'all' has no
    # cap at all — only the fixed modes hand down a number.
    quota = None if cfg.mode in ('all', 'half') else _MODE_TOP.get(cfg.mode, 20)
    return db.stamp_hn_history(cfg, quota, day=day)


# --- read path ---------------------------------------------------------------
#
# One filter, no ranking: a story is on the timeline iff it carries a stamp. The
# hidden-items anti-join used to need a note about hiding leaving a gap rather
# than promoting a below-cut story; that is now trivially true, because there is
# no cut to be below — admission and hiding are fully decoupled.

_HIDDEN_JOIN = "LEFT JOIN hidden_items hd ON hd.source = 'hn' AND hd.ref1 = h.id"
_QUALIFIED_DAY = 'substr(h.qualified_at, 1, 10)'


def _fetch(where: list[str], params: list, descending: bool, limit: int) -> list[dict]:
    order = 'DESC' if descending else 'ASC'
    sql = (
        'SELECT h.*, CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read, '
        'CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved '
        'FROM hn_stories h '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = h.id "
        "LEFT JOIN saved_items si ON si.source = 'hn' AND si.ref1 = h.id "
        f'{_HIDDEN_JOIN} '
        'WHERE ' + ' AND '.join(where) + f' ORDER BY h.qualified_at {order}, h.id {order} LIMIT ?'
    )
    cur = tdb.db.execute_sql(sql, (*params, limit))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _base_where(date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    # is_dead survives the move to one-way admission, and is not an exception to
    # it: it says the submission was flagged or deleted at HN, not that we changed
    # our mind about it. mark_hn_story_dead drops the search document for the same
    # reason, and this keeps the two surfaces offering the same set.
    where = ['h.qualified_at IS NOT NULL', 'h.is_dead = 0', 'hd.ref1 IS NULL']
    params: list = []
    if date:
        # The admission day, not the archive day: a story first seen at 23:50 and
        # admitted at 02:00 is shown on the second day, where it sorts (plan §5.4a).
        where.append(f'{_QUALIFIED_DAY} = ?')
        params.append(date)
    if unread_only:
        where.append('ri.ref1 IS NULL')
    return where, params


def _to_unit(row: dict) -> SourceUnit:
    pos = pack_pos(row['qualified_at'], row['id'])
    return SourceUnit(
        sort_ts=norm_ts(row['qualified_at']),
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
    """Older-direction page of admitted stories after ``cursor`` (admission desc)."""
    if not active():
        return SourcePage(units=[], has_more=False)
    where, params = _base_where(date, unread_only)
    if cursor:
        cts, cid = unpack_pos(cursor)
        where.append('((h.qualified_at < ?) OR (h.qualified_at = ? AND h.id < ?))')
        params.extend([cts, cts, cid])

    rows = _fetch(where, params, descending=True, limit=limit + 1)
    return SourcePage(units=[_to_unit(r) for r in rows[:limit]], has_more=len(rows) > limit)


def fetch_new(after: str, limit: int, unread_only: bool = False) -> list[SourceUnit]:
    """Admitted stories strictly newer than the ``after`` position (newest first).

    This is where phase 3 pays out: a story is stamped at the moment it is admitted,
    so it is always newer than an anchor taken before that moment. Under the old
    query-time rule it became visible at a ``first_seen_at`` that was already older
    than the anchor, and the poll could never report it.
    """
    if not active():
        return []
    cts, cid = unpack_pos(after)
    where, params = _base_where(None, unread_only)
    where.append('((h.qualified_at > ?) OR (h.qualified_at = ? AND h.id > ?))')
    params.extend([cts, cts, cid])
    return [_to_unit(r) for r in _fetch(where, params, descending=True, limit=limit + NEW_COUNT_BUFFER)]


def days() -> dict[str, int]:
    """Per-admission-day visible-story counts."""
    if not active():
        return {}
    sql = (
        f'SELECT {_QUALIFIED_DAY}, COUNT(*) FROM hn_stories h {_HIDDEN_JOIN} '
        f'WHERE h.qualified_at IS NOT NULL AND h.is_dead = 0 AND hd.ref1 IS NULL '
        f'GROUP BY {_QUALIFIED_DAY}'
    )
    return {row[0]: row[1] for row in tdb.db.execute_sql(sql).fetchall()}


def rows_by_id(story_ids: list[int]) -> dict[int, dict]:
    """Stories by id with read/saved flags, for the full-text search assembler.

    Deliberately not scoped to admitted stories: search reads the archive, so a
    story that never earned a slot is still a story that was on the front page.
    Do not "tidy" a ``qualified_at IS NOT NULL`` in here (plan §5.4f).
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
    """Unread admitted stories — must match the page filter or the badge never clears."""
    if not active():
        return 0
    sql = (
        'SELECT COUNT(*) FROM hn_stories h '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = h.id "
        f'{_HIDDEN_JOIN} '
        'WHERE h.qualified_at IS NOT NULL AND h.is_dead = 0 AND ri.ref1 IS NULL AND hd.ref1 IS NULL'
    )
    return tdb.db.execute_sql(sql).fetchone()[0]
