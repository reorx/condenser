"""Forward records — the read side of "what I republished, and what I said".

``records.py``'s sibling. Forwarding was a one-shot side effect until 2026-08-23:
the message landed in the reader's own channel and condenser kept nothing, so two
questions had no answer short of scrolling the channel — *have I already sent
this*, and *what did I write about it*. The second one matters more than it
looks: the item is somebody else's writing, the comment is the reader's, and it
existed nowhere but inside a Telegram message.

The write side is deliberately **not** here. ``tg.py`` performs the send and
appends the row through ``db.add_forward_record`` directly; putting it in this
module would mean ``tg.py`` importing it, and this module imports ``records`` →
… → nothing that reaches back, but ``forward.py`` (the renderer) is already
imported *by* ``tg.py``, and a second forward-shaped module in that direction is
how cycles start. All the SQL stays in ``db.py`` either way.

Two reads live here:

* ``list_rendered`` — the ``/forwards`` view. A record renders from its own
  snapshot and never touches a source table, so it survives retention (the same
  promise ``records.py`` makes). A record whose snapshot is missing renders
  ``item: null`` rather than disappearing: the comment and the link are the
  record's real body, and the item is the illustration.
* ``stamp`` — the ``forwarded_by_me`` flag on ordinary timeline envelopes.
"""

from typing import Optional

from telememo import db as tdb

from . import db, records
from .items import ItemKey, iso_utc


def _triple_key(source: str, ref1: int, ref2: int) -> str:
    return ItemKey(source=source, ref1=ref1, ref2=ref2).key


def stamp(items: list[dict]) -> list[dict]:
    """Set ``forwarded_by_me`` on every envelope in place, then hand the list back.

    Post-hoc rather than joined into each source's query: ``is_read`` / ``is_saved``
    are five LEFT JOINs across four provider modules, and this is one boolean for a
    single-digits-per-day action. One query for the whole set, matched by rendered
    key — the record stores an int ref1 while X's envelope key carries the id as a
    string, and the key form is where the two agree.

    ⚠️ The name is not ``is_forwarded``: the Telegram payload already has that one
    and it means the *opposite* direction — "this post was forwarded into the
    channel I read". Two same-named fields pointing opposite ways would be read
    wrong exactly once and then trusted.
    """
    if not items:
        return items
    forwarded = {_triple_key(*triple) for triple in db.forwarded_triples()}
    for item in items:
        item['forwarded_by_me'] = item['key'] in forwarded
    return items


def _record_payload(rec: db.ForwardRecord) -> dict:
    """The record's own half of a list entry: what the reader did, not what they read."""
    return {
        'id': rec.id,
        'key': _triple_key(rec.source, rec.ref1, rec.ref2),
        'source': rec.source,
        'comment': rec.comment,
        'mode': rec.mode,
        'target': rec.target,
        'message_id': rec.message_id,
        'link': rec.link,
        'created_at': iso_utc(rec.created_at),
    }


def _joined(table: str, extra: str = '') -> set[tuple[str, int, int]]:
    """The forwarded triples that also appear in ``table``, batched like records.py's.

    Read and saved state stay *live* (they are not in the snapshot) for the same
    reason feedback does in ``records.py``: they are state the reader keeps
    editing, so a record replays the item and joins its current markers.
    ``extra`` narrows the join — saved_items rows exist for note/annotation-only
    items since v18, and only ``is_saved = 1`` is a bookmark.
    """
    cur = tdb.db.execute_sql(
        f'SELECT DISTINCT f.source, f.ref1, f.ref2 FROM forward_records f '
        f'JOIN {table} t ON t.source = f.source AND t.ref1 = f.ref1 AND t.ref2 = f.ref2{extra}'
    )
    return set(cur.fetchall())


def _feedback() -> dict[tuple[str, int, int], tuple[Optional[str], Optional[str]]]:
    cur = tdb.db.execute_sql(
        'SELECT DISTINCT f.source, f.ref1, f.ref2, fb.verdict, fb.reason FROM forward_records f '
        'JOIN item_feedback fb ON fb.source = f.source AND fb.ref1 = f.ref1 AND fb.ref2 = f.ref2'
    )
    return {(source, ref1, ref2): (verdict, reason) for source, ref1, ref2, verdict, reason in cur.fetchall()}


def list_rendered(limit: int = 30, offset: int = 0) -> dict:
    """One page of ``{record, item}`` entries, newest first, plus ``has_more``.

    Offset paging, like search and unlike the timeline: this is a log being
    browsed, not a queue being drained, so the drift a cursor exists to prevent
    costs nothing here.
    """
    rows = db.list_forward_records(limit + 1, offset)
    has_more = len(rows) > limit
    read_triples = _joined('read_items')
    saved_triples = _joined('saved_items', ' AND t.is_saved = 1')
    feedback = _feedback()

    items = []
    for rec in rows[:limit]:
        # A record written when the source row was already gone (a native TG
        # forward needs no archive row to publish) has no snapshot to replay.
        item = None
        if rec.raw_data is not None:
            triple = (rec.source, rec.ref1, rec.ref2)
            item = records.render_item(rec, read_triples, feedback, is_saved=triple in saved_triples)
            # True by construction — the enclosing record *is* a forward — but the
            # flag must still be present: every other list surface stamps it, and
            # the one view made of forwarded items showing no badge reads wrong.
            item['forwarded_by_me'] = True
        items.append({'record': _record_payload(rec), 'item': item})
    records.stamp_notes([entry['item'] for entry in items if entry['item'] is not None])
    return {'items': items, 'has_more': has_more}
