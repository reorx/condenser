"""Timeline querying (spec C3).

Cross-channel, date-desc, cursor-paginated reads over telememo ``messages``,
joined to condenser subscription/read/record state. Keyword filtering is NOT
computed here — the query only reads the materialized ``is_filtered`` boolean.
Albums (same ``grouped_id``) collapse into one DisplayMessage via telememo's
``group_messages_to_display``.
"""

import base64
from typing import Optional

from telememo import db as tdb
from telememo.utils import group_messages_to_display

# Native + forward columns needed to rebuild a DisplayMessage from a DB row.
_SELECT_COLS = """
    m.id AS id, m.channel_id AS channel, m.text AS text, m.date AS date,
    m.sender_id AS sender_id, m.sender_name AS sender_name,
    m.views AS views, m.forwards AS forwards, m.replies AS replies,
    m.is_edited AS is_edited, m.edit_date AS edit_date,
    m.media_type AS media_type, m.has_media AS has_media, m.grouped_id AS grouped_id,
    m.is_forwarded AS is_forwarded, m.fwd_from_channel_id AS fwd_from_channel_id,
    m.fwd_from_channel_name AS fwd_from_channel_name, m.fwd_from_user_id AS fwd_from_user_id,
    m.fwd_from_user_name AS fwd_from_user_name, m.fwd_from_message_id AS fwd_from_message_id,
    m.fwd_original_date AS fwd_original_date, m.fwd_post_author AS fwd_post_author,
    CASE WHEN rm.message_id IS NOT NULL THEN 1 ELSE 0 END AS is_read,
    CASE WHEN tr.message_id IS NOT NULL THEN 1 ELSE 0 END AS is_saved
"""

_FROM = """
    FROM messages m
    JOIN subscriptions s ON s.channel_id = m.channel_id AND s.enabled = 1
    LEFT JOIN read_messages rm ON rm.channel_id = m.channel_id AND rm.message_id = m.id
    LEFT JOIN telegram_records tr ON tr.channel_id = m.channel_id AND tr.message_id = m.id
"""

# Buffer extra rows past `limit` so adjacent album items don't split a page.
_ALBUM_BUFFER = 20


def encode_cursor(date_raw: str, message_id: int) -> str:
    return base64.urlsafe_b64encode(f'{date_raw}\x1f{message_id}'.encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, int]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    date_raw, mid = raw.rsplit('\x1f', 1)
    return date_raw, int(mid)


def _base_where(channel_id: Optional[int], date: Optional[str], unread_only: bool) -> tuple[list[str], list]:
    where = ['(m.is_filtered IS NOT 1)']
    params: list = []
    if channel_id is not None:
        where.append('m.channel_id = ?')
        params.append(channel_id)
    if date:
        where.append('substr(m.date, 1, 10) = ?')
        params.append(date)
    if unread_only:
        where.append('rm.message_id IS NULL')
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


def _serialize_units(units: list[list[dict]]) -> list[dict]:
    """Build DisplayMessage dicts (+ is_read/is_saved) from display units."""
    flat = [r for u in units for r in u]
    if not flat:
        return []
    # Parse the date string into a datetime for DisplayMessage; keep raw for cursors.
    rows_for_display = []
    flags: dict[tuple, tuple] = {}
    for r in flat:
        d = dict(r)
        d['date'] = tdb._parse_datetime(r['date'])
        d['edit_date'] = tdb._parse_datetime(r['edit_date'])
        d['fwd_original_date'] = tdb._parse_datetime(r['fwd_original_date'])
        rows_for_display.append(d)
        flags[(r['channel'], r['id'])] = (bool(r['is_read']), bool(r['is_saved']))

    displays = group_messages_to_display(rows_for_display)
    out = []
    for dm in displays:
        is_read, is_saved = flags.get((dm.channel_id, dm.id), (False, False))
        item = dm.model_dump(mode='json')
        item['is_read'] = is_read
        item['is_saved'] = is_saved
        out.append(item)
    return out


def _unit_boundary(unit: list[dict]) -> tuple[str, int]:
    """Cursor anchor for a display unit: its smallest message id at the unit's date."""
    boundary = min(unit, key=lambda r: r['id'])
    return boundary['date'], boundary['id']


def query_timeline(
    channel_id: Optional[int] = None,
    date: Optional[str] = None,
    unread_only: bool = False,
    cursor: Optional[str] = None,
    limit: int = 30,
) -> dict:
    """Older-direction page: returns ``{items, next_cursor}`` (date desc)."""
    where, params = _base_where(channel_id, date, unread_only)
    if cursor:
        cdate, cid = decode_cursor(cursor)
        where.append('((m.date < ?) OR (m.date = ? AND m.id < ?))')
        params.extend([cdate, cdate, cid])

    fetch_cap = limit + _ALBUM_BUFFER
    rows = _fetch(where, params, descending=True, limit=fetch_cap)
    units = _group_into_units(rows)

    has_more = len(units) > limit or len(rows) == fetch_cap
    page_units = units[:limit]
    items = _serialize_units(page_units)

    next_cursor = None
    if has_more and page_units:
        date_raw, mid = _unit_boundary(page_units[-1])
        next_cursor = encode_cursor(date_raw, mid)

    return {'items': items, 'next_cursor': next_cursor}


def query_new(channel_id: Optional[int], after_cursor: str, limit: int = 100) -> dict:
    """Newer-direction poll: returns ``{count, items}`` strictly newer than the cursor."""
    cdate, cid = decode_cursor(after_cursor)
    where, params = _base_where(channel_id, None, False)
    where.append('((m.date > ?) OR (m.date = ? AND m.id > ?))')
    params.extend([cdate, cdate, cid])

    rows = _fetch(where, list(params), descending=True, limit=limit + _ALBUM_BUFFER)
    units = _group_into_units(rows)
    items = _serialize_units(units[:limit])
    return {'count': len(units), 'items': items}


def query_days(channel_id: Optional[int] = None) -> list[dict]:
    """Days that have messages (+ display-unit counts) for the calendar component."""
    where = ['(m.is_filtered IS NOT 1)']
    params: list = []
    if channel_id is not None:
        where.append('m.channel_id = ?')
        params.append(channel_id)
    sql = (
        'SELECT substr(m.date, 1, 10) AS day, COUNT(DISTINCT COALESCE(m.grouped_id, m.id)) AS cnt '
        'FROM messages m JOIN subscriptions s ON s.channel_id = m.channel_id AND s.enabled = 1 '
        'WHERE ' + ' AND '.join(where) + ' GROUP BY day ORDER BY day DESC'
    )
    cur = tdb.db.execute_sql(sql, tuple(params))
    return [{'date': row[0], 'count': row[1]} for row in cur.fetchall()]


def unread_counts() -> dict[int, int]:
    """Per-channel unread display-unit counts (not filtered, not read), for enabled subs."""
    sql = (
        'SELECT m.channel_id, COUNT(DISTINCT COALESCE(m.grouped_id, m.id)) '
        'FROM messages m '
        'JOIN subscriptions s ON s.channel_id = m.channel_id AND s.enabled = 1 '
        'LEFT JOIN read_messages rm ON rm.channel_id = m.channel_id AND rm.message_id = m.id '
        'WHERE m.is_filtered IS NOT 1 AND rm.message_id IS NULL '
        'GROUP BY m.channel_id'
    )
    cur = tdb.db.execute_sql(sql)
    return {row[0]: row[1] for row in cur.fetchall()}
