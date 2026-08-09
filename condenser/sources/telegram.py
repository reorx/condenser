"""Telegram timeline source provider (plan 2.3).

The pre-Phase-2 query logic from condenser/timeline.py, unchanged in substance:
cross-channel date-desc reads over telememo ``messages`` joined to subscription /
read / saved state, with album rows (same ``grouped_id``) collapsed into one
display unit. Keyword filtering only reads the materialized ``is_filtered``.
"""

import json
from typing import Optional

from telememo import db as tdb
from telememo.utils import group_messages_to_display

from ..items import norm_ts, tg_envelope
from .base import SourcePage, SourceUnit, pack_pos, unpack_pos

# Native + forward columns needed to rebuild a DisplayMessage from a DB row.
_SELECT_COLS = """
    m.id AS id, m.channel_id AS channel, m.text AS text, m.date AS date,
    m.sender_id AS sender_id, m.sender_name AS sender_name,
    m.views AS views, m.forwards AS forwards, m.replies AS replies,
    m.is_edited AS is_edited, m.edit_date AS edit_date,
    m.media_type AS media_type, m.has_media AS has_media,
    m.media_width AS media_width, m.media_height AS media_height,
    m.grouped_id AS grouped_id,
    m.webpage AS webpage,
    m.is_forwarded AS is_forwarded, m.fwd_from_channel_id AS fwd_from_channel_id,
    m.fwd_from_channel_name AS fwd_from_channel_name, m.fwd_from_user_id AS fwd_from_user_id,
    m.fwd_from_user_name AS fwd_from_user_name, m.fwd_from_message_id AS fwd_from_message_id,
    m.fwd_original_date AS fwd_original_date, m.fwd_post_author AS fwd_post_author,
    CASE WHEN rm.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_read,
    CASE WHEN sv.ref1 IS NOT NULL THEN 1 ELSE 0 END AS is_saved
"""

_FROM = """
    FROM messages m
    JOIN subscriptions s ON s.source = 'telegram' AND s.channel_id = m.channel_id AND s.enabled = 1
    LEFT JOIN read_items rm ON rm.source = 'telegram' AND rm.ref1 = m.channel_id AND rm.ref2 = m.id
    LEFT JOIN saved_items sv ON sv.source = 'telegram' AND sv.ref1 = m.channel_id AND sv.ref2 = m.id
    LEFT JOIN hidden_items hd ON hd.source = 'telegram' AND hd.ref1 = m.channel_id AND hd.ref2 = m.id
"""

# Rows hidden by the user are stored album-expanded, so a per-row anti-join
# removes the whole display unit.
_HIDDEN_JOIN = "LEFT JOIN hidden_items hd ON hd.source = 'telegram' AND hd.ref1 = m.channel_id AND hd.ref2 = m.id"

# Buffer extra rows past `limit` so adjacent album items don't split a page.
_ALBUM_BUFFER = 20


def _base_where(channel_id: Optional[int], date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    where = ['(m.is_filtered IS NOT 1)', 'hd.ref1 IS NULL']
    params: list = []
    if channel_id is not None:
        where.append('m.channel_id = ?')
        params.append(channel_id)
    if date:
        where.append('substr(m.date, 1, 10) = ?')
        params.append(date)
    if unread_only:
        where.append('rm.ref1 IS NULL')
    return where, params


def _fetch(where: list[str], params: list, descending: bool, limit: int) -> list[dict]:
    order = 'DESC' if descending else 'ASC'
    sql = (
        f'SELECT {_SELECT_COLS} {_FROM} WHERE '
        + ' AND '.join(where)
        + f' ORDER BY m.date {order}, m.id {order} LIMIT ?'
    )
    cur = tdb.db.execute_sql(sql, (*params, limit))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _group_into_units(rows: list[dict]) -> list[list[dict]]:
    """Collapse rows into display units (album rows share grouped_id), preserving order."""
    units: list[list[dict]] = []
    index: dict[int, list[dict]] = {}
    for r in rows:
        gid = r.get('grouped_id')
        if gid and gid in index:
            index[gid].append(r)
        else:
            unit = [r]
            units.append(unit)
            if gid:
                index[gid] = unit
    return units


def _serialize_unit(unit: list[dict]) -> dict:
    """Build one item envelope from a display unit's raw rows."""
    rows_for_display = []
    flags: dict[tuple, tuple] = {}
    for r in unit:
        d = dict(r)
        d['date'] = tdb._parse_datetime(r['date'])
        d['edit_date'] = tdb._parse_datetime(r['edit_date'])
        d['fwd_original_date'] = tdb._parse_datetime(r['fwd_original_date'])
        d['webpage'] = json.loads(r['webpage']) if r.get('webpage') else None
        rows_for_display.append(d)
        flags[(r['channel'], r['id'])] = (bool(r['is_read']), bool(r['is_saved']))

    dm = group_messages_to_display(rows_for_display)[0]
    is_read, is_saved = flags.get((dm.channel_id, dm.id), (False, False))
    return tg_envelope(dm.model_dump(mode='json'), is_read, is_saved)


def _to_unit(unit: list[dict]) -> SourceUnit:
    oldest = min(unit, key=lambda r: r['id'])
    newest = max(unit, key=lambda r: r['id'])
    return SourceUnit(
        sort_ts=norm_ts(unit[0]['date']),
        envelope=_serialize_unit(unit),
        boundary=pack_pos(oldest['date'], oldest['id']),
        head=pack_pos(newest['date'], newest['id']),
    )


def fetch_page(
    cursor: Optional[str],
    limit: int,
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
) -> SourcePage:
    """Older-direction page of display units after ``cursor`` (date desc)."""
    where, params = _base_where(channel_id, date, unread_only)
    if cursor:
        cdate, cid = unpack_pos(cursor)
        where.append('((m.date < ?) OR (m.date = ? AND m.id < ?))')
        params.extend([cdate, cdate, cid])

    fetch_cap = limit + _ALBUM_BUFFER
    rows = _fetch(where, params, descending=True, limit=fetch_cap)
    units = _group_into_units(rows)
    has_more = len(units) > limit or len(rows) == fetch_cap
    return SourcePage(units=[_to_unit(u) for u in units[:limit]], has_more=has_more)


def fetch_new(
    after: str,
    limit: int,
    channel_id: Optional[int] = None,
    unread_only: bool = False,
) -> list[SourceUnit]:
    """Units strictly newer than the ``after`` position (newest first)."""
    cdate, cid = unpack_pos(after)
    where, params = _base_where(channel_id, None, unread_only)
    where.append('((m.date > ?) OR (m.date = ? AND m.id > ?))')
    params.extend([cdate, cdate, cid])

    rows = _fetch(where, params, descending=True, limit=limit + _ALBUM_BUFFER)
    return [_to_unit(u) for u in _group_into_units(rows)]


def days(channel_id: Optional[int] = None) -> dict[str, int]:
    """Per-day display-unit counts for the calendar component."""
    where = ['(m.is_filtered IS NOT 1)', 'hd.ref1 IS NULL']
    params: list = []
    if channel_id is not None:
        where.append('m.channel_id = ?')
        params.append(channel_id)
    sql = (
        'SELECT substr(m.date, 1, 10) AS day, COUNT(DISTINCT COALESCE(m.grouped_id, m.id)) AS cnt '
        "FROM messages m JOIN subscriptions s ON s.source = 'telegram' AND s.channel_id = m.channel_id AND s.enabled = 1 "
        f'{_HIDDEN_JOIN} '
        'WHERE ' + ' AND '.join(where) + ' GROUP BY day'
    )
    cur = tdb.db.execute_sql(sql, tuple(params))
    return {row[0]: row[1] for row in cur.fetchall()}


# Anchors -> the raw rows of their display units. The album join is why this is a
# query rather than an `id IN (...)` list: a hit names the unit's anchor, and the
# card needs every sibling's media alongside it.
_UNITS_SQL = f"""
    SELECT a.cid AS anchor_cid, a.mid AS anchor_mid, {_SELECT_COLS}
    FROM anchors a
    JOIN messages am ON am.channel_id = a.cid AND am.id = a.mid
    JOIN messages m ON m.channel_id = a.cid
      AND (m.id = a.mid OR (am.grouped_id IS NOT NULL AND m.grouped_id = am.grouped_id))
    LEFT JOIN read_items rm ON rm.source = 'telegram' AND rm.ref1 = m.channel_id AND rm.ref2 = m.id
    LEFT JOIN saved_items sv ON sv.source = 'telegram' AND sv.ref1 = m.channel_id AND sv.ref2 = m.id
    ORDER BY a.cid, a.mid, m.id
"""


def units_by_key(anchors: list[tuple[int, int]]) -> dict[tuple[int, int], dict]:
    """Envelopes for specific display-unit anchors, keyed by ``(channel_id, id)``.

    Deliberately **not** subscription-scoped, unlike every query above it (whose
    ``_FROM`` joins ``subscriptions``): the caller is full-text search, which reads
    the archive rather than the reading list, so a paused or unsubscribed channel's
    messages still render. An anchor whose message is gone is simply absent from
    the result — the caller drops it rather than rendering a hole.
    """
    if not anchors:
        return {}
    values = ','.join('(?,?)' for _ in anchors)
    cur = tdb.db.execute_sql(
        f'WITH anchors(cid, mid) AS (VALUES {values}) {_UNITS_SQL}',
        tuple(v for pair in anchors for v in pair),
    )
    columns = [c[0] for c in cur.description]
    units: dict[tuple[int, int], list[dict]] = {}
    for values_row in cur.fetchall():
        row = dict(zip(columns, values_row))
        units.setdefault((row['anchor_cid'], row['anchor_mid']), []).append(row)
    return {key: _serialize_unit(rows) for key, rows in units.items()}


def unread_counts() -> dict[int, int]:
    """Per-channel unread display-unit counts (not filtered, not read), for enabled subs."""
    sql = (
        'SELECT m.channel_id, COUNT(DISTINCT COALESCE(m.grouped_id, m.id)) '
        'FROM messages m '
        "JOIN subscriptions s ON s.source = 'telegram' AND s.channel_id = m.channel_id AND s.enabled = 1 "
        "LEFT JOIN read_items rm ON rm.source = 'telegram' AND rm.ref1 = m.channel_id AND rm.ref2 = m.id "
        f'{_HIDDEN_JOIN} '
        'WHERE m.is_filtered IS NOT 1 AND rm.ref1 IS NULL AND hd.ref1 IS NULL '
        'GROUP BY m.channel_id'
    )
    cur = tdb.db.execute_sql(sql)
    return {row[0]: row[1] for row in cur.fetchall()}
