"""Hacker News timeline source provider (plan 2.3).

Archive-everything, read-compressed: ``hn_stories`` holds every story that
reached the front page; the query only surfaces each day's top-N per the
subscription's ``display_mode`` (top10/top20/half/all). Rank is computed
query-time (scores keep moving while a day is live), so the visible set —
and with it unread counts — can shift slightly between polls; that's accepted
(plan 2.3). Sort key is ``first_seen_at`` (append-only timeline semantics).
"""

import json
from typing import Optional

from telememo import db as tdb

from .. import db
from ..items import hn_envelope, norm_ts
from .base import NEW_COUNT_BUFFER, SourcePage, SourceUnit, pack_pos, unpack_pos

DEFAULT_DISPLAY_MODE = 'top20'
_MODE_TOP = {'top10': 10, 'top20': 20}

# Rank every live story within its archive day; day_total feeds the 'half' mode.
_RANKED = """
    SELECT h.*, ROW_NUMBER() OVER (PARTITION BY h.day ORDER BY h.score DESC, h.id ASC) AS day_rank,
           COUNT(*) OVER (PARTITION BY h.day) AS day_total
    FROM hn_stories h
    WHERE h.is_dead = 0
"""


def display_mode() -> Optional[str]:
    """The enabled front-feed subscription's display mode, or None when inactive."""
    sub = db.get_hn_subscription('front')
    if sub is None or not sub.enabled:
        return None
    cfg = json.loads(sub.config) if sub.config else {}
    return cfg.get('display_mode') or DEFAULT_DISPLAY_MODE


def active() -> bool:
    return display_mode() is not None


def _mode_where(mode: str) -> tuple[str, list]:
    if mode == 'all':
        return '1 = 1', []
    if mode == 'half':
        # ceil(day_total / 2): a single-story day stays visible
        return 'r.day_rank * 2 <= r.day_total + 1', []
    return 'r.day_rank <= ?', [_MODE_TOP.get(mode, 20)]


def _fetch(where: list[str], params: list, descending: bool, limit: int) -> list[dict]:
    order = 'DESC' if descending else 'ASC'
    sql = (
        'SELECT r.*, CASE WHEN ri.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read, '
        'CASE WHEN si.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved '
        f'FROM ({_RANKED}) r '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = r.id "
        "LEFT JOIN saved_items si ON si.source = 'hn' AND si.ref1 = r.id "
        'WHERE ' + ' AND '.join(where) + f' ORDER BY r.first_seen_at {order}, r.id {order} LIMIT ?'
    )
    cur = tdb.db.execute_sql(sql, (*params, limit))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _base_where(mode: str, date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    mode_sql, mode_params = _mode_where(mode)
    where = [mode_sql]
    params = list(mode_params)
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
    mode = display_mode()
    if mode is None:
        return SourcePage(units=[], has_more=False)
    where, params = _base_where(mode, date, unread_only)
    if cursor:
        cts, cid = unpack_pos(cursor)
        where.append('((r.first_seen_at < ?) OR (r.first_seen_at = ? AND r.id < ?))')
        params.extend([cts, cts, cid])

    rows = _fetch(where, params, descending=True, limit=limit + 1)
    return SourcePage(units=[_to_unit(r) for r in rows[:limit]], has_more=len(rows) > limit)


def fetch_new(after: str, limit: int, unread_only: bool = False) -> list[SourceUnit]:
    """Visible stories strictly newer than the ``after`` position (newest first)."""
    mode = display_mode()
    if mode is None:
        return []
    cts, cid = unpack_pos(after)
    where, params = _base_where(mode, None, unread_only)
    where.append('((r.first_seen_at > ?) OR (r.first_seen_at = ? AND r.id > ?))')
    params.extend([cts, cts, cid])
    return [_to_unit(r) for r in _fetch(where, params, descending=True, limit=limit + NEW_COUNT_BUFFER)]


def days() -> dict[str, int]:
    """Per-day visible-story counts (respects the display mode)."""
    mode = display_mode()
    if mode is None:
        return {}
    mode_sql, mode_params = _mode_where(mode)
    sql = f'SELECT r.day, COUNT(*) FROM ({_RANKED}) r WHERE {mode_sql} GROUP BY r.day'
    cur = tdb.db.execute_sql(sql, tuple(mode_params))
    return {row[0]: row[1] for row in cur.fetchall()}


def unread_count() -> int:
    """Unread visible stories — must match the display filter or the badge never clears."""
    mode = display_mode()
    if mode is None:
        return 0
    mode_sql, mode_params = _mode_where(mode)
    sql = (
        f'SELECT COUNT(*) FROM ({_RANKED}) r '
        "LEFT JOIN read_items ri ON ri.source = 'hn' AND ri.ref1 = r.id "
        f'WHERE {mode_sql} AND ri.ref1 IS NULL'
    )
    return tdb.db.execute_sql(sql, tuple(mode_params)).fetchone()[0]
