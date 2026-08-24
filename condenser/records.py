"""Saved records (user assets, source-decoupled — spec §1 / Part B).

A saved record snapshots an item's full data into ``saved_items.raw_data`` so it
renders even if the source cache (telememo ``messages`` / ``hn_stories``) is
later cleared. Telegram snapshots are self-contained: the album's message rows
plus minimal channel info; HN snapshots are the story row as JSON.
"""

import json
from typing import Optional

from telememo import db as tdb
from telememo.utils import group_messages_to_display

from . import db
from .items import ItemKey, hn_envelope, hn_payload, rss_envelope, rss_payload, tg_envelope, x_envelope, x_payload
from .sources import rss as rss_source
from .sources import x as x_source

_MSG_COLS = """
    id, channel_id AS channel, text, date, sender_id, sender_name,
    views, forwards, replies, is_edited, edit_date, media_type, has_media,
    media_width, media_height, grouped_id,
    webpage,
    is_forwarded, fwd_from_channel_id, fwd_from_channel_name, fwd_from_user_id,
    fwd_from_user_name, fwd_from_message_id, fwd_original_date, fwd_post_author
"""


def _rows(sql: str, params: tuple) -> list[dict]:
    cur = tdb.db.execute_sql(sql, params)
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def build_snapshot(channel_id: int, message_id: int) -> Optional[dict]:
    """Snapshot a TG display unit (album-aware) into a self-contained dict, or None if absent."""
    primary = _rows(f'SELECT {_MSG_COLS} FROM messages WHERE channel_id = ? AND id = ?', (channel_id, message_id))
    if not primary:
        return None

    grouped_id = primary[0].get('grouped_id')
    if grouped_id:
        messages = _rows(
            f'SELECT {_MSG_COLS} FROM messages WHERE channel_id = ? AND grouped_id = ? ORDER BY id',
            (channel_id, grouped_id),
        )
    else:
        messages = primary

    channel = tdb.get_channel(channel_id)
    channel_info = None
    if channel:
        channel_info = {'id': channel.id, 'title': channel.title, 'username': channel.username}

    return {'messages': messages, 'channel': channel_info}


def _hn_snapshot(story: db.HNStory) -> dict:
    # Single source of truth for the field mapping: the snapshot is exactly the
    # envelope payload plus `day` (the archive day, which the payload doesn't carry).
    payload = hn_payload(story.__data__)
    payload['day'] = story.day
    return payload


def build_item_snapshot(key: ItemKey) -> Optional[dict]:
    """The source-decoupled snapshot for any item key, or None if its row is gone.

    Split out of ``save_item`` (2026-08-23) because saving is no longer the only
    thing that takes one: a forward record snapshots the item it published, for
    the same reason and with the same shape (``forwards.py``).
    """
    if key.source == 'telegram':
        return build_snapshot(key.ref1, key.ref2)
    if key.source == 'x':
        row = x_source.get_row(key.ref1)
        # the snapshot *is* the envelope payload (quote already nested), so the
        # record replays without x_tweets / x_feed_items
        return x_payload(row) if row is not None else None
    if key.source == 'rss':
        row = rss_source.get_row(key.ref1)
        if row is None:
            return None
        # Like X's, the snapshot *is* the envelope payload — including the computed
        # sort timestamp, which no longer exists once the entry row is gone.
        #
        # ``with_content``: the *list* payload stopped carrying the article on
        # 2026-08-23, but a snapshot is not a list — it is this module's promise
        # that a saved record renders without its source tables, and an entry whose
        # article is only in ``rss_entries`` would break that the moment retention
        # (or an unsubscribe-and-purge) took the row. The cost is one query's worth
        # of text at save time; the alternative is a saved article that can go
        # missing. (Plan 2026-08-23 §5, option (a).)
        return rss_payload(row, with_content=True)
    story = db.get_hn_story(key.ref1)
    return _hn_snapshot(story) if story is not None else None


def save_item(key: ItemKey) -> bool:
    """Snapshot + persist a record for an item key. Returns False if the source item is missing.

    An already-existing row (a note/annotation created it, v18) only needs its
    flag flipped, so the snapshot is not rebuilt — and must not be *required*:
    the source row may be long gone while the annotation kept the record alive.
    """
    if db.get_saved_item(*key.triple) is not None:
        db.set_item_saved_flag(key)
        return True
    snapshot = build_item_snapshot(key)
    if snapshot is None:
        return False
    db.add_saved_item(key.source, key.ref1, key.ref2, snapshot)
    return True


def set_note(key: ItemKey, note: str) -> bool:
    """Overwrite the item-level note ('' clears). Returns False = item not found.

    The snapshot is built out here, before ``db.set_note``'s IMMEDIATE
    transaction, and only when the pre-check saw no row — source-table reads do
    not belong inside the write lock, and a lost race merely wastes one build.
    """
    cleaned = note or None
    snapshot = None
    if cleaned is not None and db.get_saved_item(*key.triple) is None:
        snapshot = build_item_snapshot(key)
        if snapshot is None:
            return False
    return db.set_note(key, cleaned, snapshot)


def add_annotation(
    key: ItemKey,
    quote: str,
    prefix: str,
    suffix: str,
    block: Optional[int],
    comment: Optional[str],
) -> Optional[dict]:
    """Append one highlight; returns the stored dict (id + created_at assigned by
    the db layer, inside the lock), or None = item not found."""
    snapshot = None
    if db.get_saved_item(*key.triple) is None:
        snapshot = build_item_snapshot(key)
        if snapshot is None:
            return None
    fields = {'quote': quote, 'prefix': prefix, 'suffix': suffix, 'block': block, 'comment': comment or None}
    return db.add_annotation(key, fields, snapshot)


def stamp_notes(items: list[dict]) -> list[dict]:
    """Set ``note`` / ``annotations`` on every envelope in place (``forwards.stamp``'s
    arrangement, same rationale: one query for a sparse, single-digits-per-day
    kind of row instead of two more columns through every provider query). Like
    feedback, both stay out of the snapshot — they are live state the reader
    keeps editing, so a replayed record joins the current text."""
    if not items:
        return items
    noted = db.noted_saved_items()
    for item in items:
        note, annotations = noted.get(item['key'], (None, None))
        item['note'] = note
        item['annotations'] = annotations
    return items


def _render_tg_display(raw_data: str) -> Optional[dict]:
    """Rebuild a DisplayMessage dict (+ channel) from a stored snapshot, no telememo tables."""
    snapshot = json.loads(raw_data)
    messages = snapshot.get('messages') or []
    if not messages:
        return None
    rows_for_display = []
    for r in messages:
        d = dict(r)
        d['date'] = tdb._parse_datetime(r.get('date'))
        d['edit_date'] = tdb._parse_datetime(r.get('edit_date'))
        d['fwd_original_date'] = tdb._parse_datetime(r.get('fwd_original_date'))
        wp = r.get('webpage')
        d['webpage'] = json.loads(wp) if isinstance(wp, str) else wp
        rows_for_display.append(d)
    displays = group_messages_to_display(rows_for_display)
    if not displays:
        return None
    item = displays[0].model_dump(mode='json')
    item['channel'] = snapshot.get('channel')
    return item


def render_item(
    rec,
    read_triples: set[tuple[str, int, int]],
    feedback: Optional[dict[tuple[str, int, int], tuple[Optional[str], Optional[str]]]] = None,
    is_saved: bool = True,
) -> Optional[dict]:
    """Render one snapshot row into an item envelope.

    ``rec`` is duck-typed on ``source`` / ``ref1`` / ``ref2`` / ``raw_data`` rather
    than typed as ``db.SavedItem``: a ``db.ForwardRecord`` carries the same four
    and replays the same way.

    ``is_saved`` defaults to True because the saved view is where every row *is*
    saved. A forward record is not — the reader published it, which says nothing
    about whether they bookmarked it — so that view passes the real flag; hard-
    coding True there would light the bookmark on every card.
    """
    triple = (rec.source, rec.ref1, rec.ref2)
    is_read = triple in read_triples
    if rec.source == 'telegram':
        display = _render_tg_display(rec.raw_data)
        if display is None:
            return None
        return tg_envelope(display, is_read, is_saved)
    if rec.source == 'x':
        verdict, reason = (feedback or {}).get(triple, (None, None))
        return x_envelope(json.loads(rec.raw_data), is_read, is_saved, verdict, reason)
    if rec.source == 'rss':
        # The snapshot holds the article; this is a *list*, so it goes out with the
        # excerpt like every other list. ``rss_article`` is the way to the body.
        return rss_envelope(json.loads(rec.raw_data), is_read, is_saved)
    return hn_envelope(json.loads(rec.raw_data), is_read, is_saved)


def rss_article(entry_id: int) -> Optional[dict]:
    """A saved entry's full-body envelope, out of its snapshot alone.

    The fallback behind ``GET /api/rss/entries/{id}`` — and the reason the snapshot
    stores the article at all. Retention keeps the rows of entries the reader
    touched, so today this rarely fires; "rarely" is not the contract this module
    makes, though, and a saved article that 404s would be the one failure a reader
    could not work around.
    """
    rec = db.get_saved_item('rss', entry_id, 0)
    if rec is None:
        return None
    is_read = db.is_item_read('rss', entry_id, 0)
    envelope = rss_envelope(json.loads(rec.raw_data), is_read, bool(rec.is_saved), with_content=True)
    return stamp_notes([envelope])[0]


def _saved_read_triples() -> set[tuple[str, int, int]]:
    """The saved items that are also read, in one batched query (no per-row EXISTS)."""
    cur = tdb.db.execute_sql(
        'SELECT s.source, s.ref1, s.ref2 FROM saved_items s '
        'JOIN read_items r ON r.source = s.source AND r.ref1 = s.ref1 AND r.ref2 = s.ref2'
    )
    return set(cur.fetchall())


def _saved_feedback() -> dict[tuple[str, int, int], tuple[Optional[str], Optional[str]]]:
    """Labels (verdict + reason chip) for the saved items that have one, batched like
    the read markers.

    Feedback deliberately stays out of the snapshot: it is live state the user
    keeps editing, so a record replays the tweet but joins its current label.
    """
    cur = tdb.db.execute_sql(
        'SELECT s.source, s.ref1, s.ref2, f.verdict, f.reason FROM saved_items s '
        'JOIN item_feedback f ON f.source = s.source AND f.ref1 = s.ref1 AND f.ref2 = s.ref2'
    )
    return {(source, ref1, ref2): (verdict, reason) for source, ref1, ref2, verdict, reason in cur.fetchall()}


def list_rendered_records() -> list[dict]:
    """All records rendered from their snapshots, newest first — the un-saved rows
    included (v18): an item the reader annotated has to be findable somewhere, and
    this list is that somewhere. ``is_saved`` on each envelope says which is which."""
    # Imported here, not at module scope: forwards.py renders *its* records through
    # this module, so the two only meet at call time (search.py's arrangement).
    from . import forwards

    read_triples = _saved_read_triples()
    feedback = _saved_feedback()
    out = []
    for rec in db.list_saved_items():
        rendered = render_item(rec, read_triples, feedback, is_saved=bool(rec.is_saved))
        if rendered is not None:
            out.append(rendered)
    return stamp_notes(forwards.stamp(out))
