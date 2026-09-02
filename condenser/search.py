"""Full-text search over every source's items (plan 2026-08-08-full-text-search.md).

This module is the only place that knows FTS5 exists — the ``vectors.py``
arrangement, for the same reason: everything above it sees ``index_item`` /
``search`` / ``rebuild``, so replacing the engine is a rewrite of one file, and a
host where the engine will not load loses search and nothing else.

**Why the text is tokenized in Python before FTS5 ever sees it.** The interesting
half of this archive is Chinese, and neither built-in tokenizer can answer it:
``unicode61`` treats a CJK run as one token (so「模型」only matches a message
whose whole run *is*「模型」), and ``trigram`` needs three characters, which is
one more than most Chinese words have. The tool that does this properly —
wangfenjin/simple — is a C++ extension with no PyPI wheel, i.e. compiled binaries
for macOS arm64 and linux x86_64 plus a CI step, against the same dependency
thrift that picked sqlite-vec over Chroma in Phase 4. So a CJK run is indexed as
its overlapping **character bigrams** and queried as a **phrase** over them:
「中文搜索」indexes as ``中文 文搜 搜索`` and is searched as
``"中文 文搜 搜索"``, where FTS5's position continuity gives back exactly
substring semantics. A single character has no bigram of its own and becomes a
prefix query (``"猫" *``), which reaches every bigram starting with it — so no
second unigram index is needed.

The known cost is stated rather than hidden: substring semantics means「中文」
also matches「其**中文**件」. That is the same noise a character-level index
always has, and the way out (if it ever stops being acceptable) is a real
segmenter, not a threshold.

The index is a **rebuildable cache**, in the ``messages.is_filtered`` /
``x_embeddings`` spirit: every indexed word is still in its source table, so a
tokenizer change is answered by ``rebuild()`` — never by a migration.
"""

import html
import json
import logging
import re
from typing import Iterable, Optional

from telememo import db as tdb

from .items import norm_ts

log = logging.getLogger('condenser.search')

TABLE = 'search_index'
VERSION_META_KEY = 'search_index_version'

# Bumped whenever ``tokenize`` changes what it emits. An index written by the old
# tokenizer answers the new one's queries wrong — not partially, but in ways that
# look like missing data — so the version mismatch triggers a full rebuild at
# startup. One integer rather than embedding.py's ``model_tag`` string, because
# there is only ever one tokenizer in the process.
#
# It is also bumped when a **source joins the index** (4: RSS, 2026-08-20). The
# marker's real meaning is "a rebuild finished under this pipeline", and an
# archive that predates the new source is missing from the index in exactly the
# way a tokenizer change makes it wrong: silently, and only for the rows nobody
# thinks to check.
TOKENIZER_VERSION = 4

# CJK ideographs (including extension A), kana and hangul — the same ranges
# ngram.py uses, so the project has one definition of "CJK" even though the two
# tokenizers serve opposite goals (that one throws away noise, this one keeps it).
_CJK_RANGES = '㐀-鿿぀-ヿ가-힯'

# One pass, in document order. The word branch excludes CJK explicitly: without
# that, a greedy `\w+` would swallow "abc中文" whole and the bigrams would never
# be built. `_` is dropped on both branches because unicode61 treats it as a
# separator, and the two tokenizers have to agree on what a token is.
_RUN_RE = re.compile(f'(?P<cjk>[{_CJK_RANGES}]+)|(?P<word>[^\\W_{_CJK_RANGES}]+)')

# Set by setup(); every entry point checks it, so an environment without FTS5
# degrades to "search returns 503" instead of failing ingest.
_available = False


def available() -> bool:
    return _available


def setup() -> bool:
    """Create the index table. Failure disables search and nothing else."""
    global _available
    _available = False
    try:
        tdb.db.execute_sql(
            f'CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING fts5('
            '  text,'  # the only indexed column: the pre-tokenized document
            '  source UNINDEXED, ref1 UNINDEXED, ref2 UNINDEXED,'  # the items.py triple
            '  ts UNINDEXED'  # norm_ts of the item's timeline sort key
            ')'
        )
    except Exception as e:  # noqa: BLE001 - a missing FTS5 build is a degraded mode, not a crash
        log.warning('FTS5 unavailable, search is disabled: %s', e)
        return False
    _available = True
    return True


# --- tokenizer ----------------------------------------------------------------


def _runs(text: str) -> Iterable[tuple[bool, str]]:
    """(is_cjk, run) pairs in document order."""
    for match in _RUN_RE.finditer(text.lower()):
        yield match.lastgroup == 'cjk', match.group()


def _bigrams(run: str) -> list[str]:
    """A CJK run as its overlapping character bigrams (a lone character stays one)."""
    if len(run) == 1:
        return [run]
    return [run[i : i + 2] for i in range(len(run) - 1)]


def _index_bigrams(run: str) -> list[str]:
    """What a run contributes to the **index**: its bigrams, plus its final character.

    The trailing unigram is not decoration. A single-character query is answered
    by a prefix match, which only reaches tokens that *start* with the character —
    so a character sitting last in its run had nothing to match at all: 「猫」
    could not find 「我买了一只猫」, whose only 猫 token is 「只猫」.

    It is added on the index side **only**. Putting it in the query too would turn
    「中文搜索」 into the phrase ``"中文 文搜 搜索 索"``, which then demands a bare
    ``索`` right after ``搜索`` — present only when the run ends there, so the
    common case (「中文搜索工具」) would stop matching. The two sides are asymmetric
    on purpose: the index says everything the text contains, the query asks for the
    least that identifies it.
    """
    return _bigrams(run) if len(run) == 1 else _bigrams(run) + [run[-1]]


def tokenize(text: str) -> list[str]:
    """The searchable form of a document: lowercased words + CJK bigrams, in order.

    Deliberately **lossy in the opposite direction** from ``ngram.py.tokenize``.
    That one feeds a classifier and throws away URLs, @mentions and stopwords
    because they are noise for style. Here they are the query: people search for a
    domain, a handle, a word like "the" inside a phrase. So nothing is dropped
    except what cannot be typed back into a search box — punctuation and emoji.

    Order matters and is not incidental: because a CJK query is a *phrase*, two
    runs separated by other text must not end up adjacent, or「中文abc搜索」would
    answer a search for「中文搜索」.
    """
    tokens: list[str] = []
    for cjk, run in _runs(text or ''):
        tokens.extend(_index_bigrams(run) if cjk else [run])
    return tokens


def _quote(value: str) -> str:
    """A token as an FTS5 string literal.

    Quoting is the whole injection story: inside double quotes, ``AND`` is a word
    and ``*`` is nothing, so a search box one keystroke away from every reader
    cannot compose a query expression by accident. The escape is belt-and-braces —
    ``tokenize`` cannot emit a quote — but it is what makes that safe to rely on.
    """
    return '"' + value.replace('"', '""') + '"'


def build_match(query: str) -> Optional[str]:
    """A user's query as an FTS5 MATCH expression, or None when nothing is searchable.

    Each run becomes its own group and the groups are implicitly ANDed, so word
    order between them does not matter — but *within* a CJK run it does, which is
    what the phrase is for.
    """
    parts = []
    for cjk, run in _runs(query or ''):
        if not cjk:
            parts.append(_quote(run))
        elif len(run) == 1:
            # no bigram to match, so match every bigram that starts with it
            parts.append(f'{_quote(run)} *')
        else:
            parts.append(_quote(' '.join(_bigrams(run))))
    return ' '.join(parts) or None


# --- index maintenance --------------------------------------------------------


_INSERT_SQL = f'INSERT INTO {TABLE}(text, source, ref1, ref2, ts) VALUES (?, ?, ?, ?, ?)'


def index_item(source: str, ref1: int, ref2: int, text: Optional[str], ts) -> None:
    """Upsert one item's document. Empty text deletes the row rather than storing one.

    Delete-then-insert because FTS5 has no upsert: the row is identified by the
    item triple, not by a rowid we keep anywhere.
    """
    if not _available:
        return
    tdb.db.execute_sql(f'DELETE FROM {TABLE} WHERE source = ? AND ref1 = ? AND ref2 = ?', (source, ref1, ref2))
    row = _document_row(source, ref1, ref2, text, ts)
    if row is not None:
        tdb.db.execute_sql(_INSERT_SQL, row)


def _document_row(source: str, ref1: int, ref2: int, text: Optional[str], ts) -> Optional[tuple]:
    """One INSERT's parameters, or None when the item has nothing to index."""
    tokens = tokenize(text or '')
    if not tokens:
        return None
    return (' '.join(tokens), source, ref1, ref2, norm_ts(ts))


def _insert_many(rows: list[tuple]) -> int:
    """Bulk insert, for ``rebuild`` only — it writes into a table it just emptied,
    so it can skip the per-row DELETE ``index_item`` needs. Measured on a
    production snapshot, one ``executemany`` instead of two statements per row
    took a full backfill from 774 ms to 78 ms — i.e. from "this may need a
    background thread" to "it runs inline in ``init_db`` and nobody notices"."""
    if not rows:
        return 0
    tdb.db.cursor().executemany(_INSERT_SQL, rows)
    return len(rows)


def delete_item(source: str, ref1: int, ref2: int = 0) -> None:
    if not _available:
        return
    tdb.db.execute_sql(f'DELETE FROM {TABLE} WHERE source = ? AND ref1 = ? AND ref2 = ?', (source, ref1, ref2))


def delete_telegram_channel(channel_id: int) -> int:
    """Drop a channel's documents; the cascade behind ``db.delete_channel_messages``."""
    if not _available:
        return 0
    return tdb.db.execute_sql(f"DELETE FROM {TABLE} WHERE source = 'telegram' AND ref1 = ?", (channel_id,)).rowcount


def sweep_x_orphans() -> int:
    """Drop X documents whose tweet no longer appears in any feed.

    An anti-join rather than the ids the retention rule just deleted, so this also
    heals rows orphaned before the sweep existed — the ``x_embeddings`` /
    ``x_attributes`` pattern. Against ``x_feed_items`` rather than ``x_tweets``
    on purpose: a body can survive its feed rows (a live tweet still quotes it),
    and such a tweet is no longer a timeline item, so a hit on it would open onto
    nothing.
    """
    if not _available:
        return 0
    return tdb.db.execute_sql(
        f"DELETE FROM {TABLE} WHERE source = 'x' AND ref1 NOT IN (SELECT tweet_id FROM x_feed_items)"
    ).rowcount


def sweep_rss_orphans() -> int:
    """Drop RSS documents whose entry is gone (the retention sweep's cascade)."""
    if not _available:
        return 0
    return tdb.db.execute_sql(
        f"DELETE FROM {TABLE} WHERE source = 'rss' AND ref1 NOT IN (SELECT id FROM rss_entries)"
    ).rowcount


def count() -> int:
    if not _available:
        return 0
    return tdb.db.execute_sql(f'SELECT count(*) FROM {TABLE}').fetchone()[0]


# --- per-source documents -----------------------------------------------------
# What each source contributes as searchable text, and under which item key. The
# three live together because ``rebuild`` has to reproduce exactly what the ingest
# hooks write — splitting them across the source modules is how the two drift.


def index_display_message(dm) -> None:
    """The Telegram hook. One row per display *unit*, keyed by the unit's anchor —
    the same key ``saved_items`` and the item API use, so an album that matches on
    its caption returns one result instead of one per photo, with no query-time
    de-duplication needed to make that true.

    The unit is resolved from the database rather than taken from ``dm``, because
    the two ingest paths hand us different things: backfill yields albums already
    merged, while the realtime handler dispatches **one raw row at a time**
    (telememo's ``_handle_new_message`` groups a single message), so its ``dm.id``
    is a sibling id. Trusting it indexed an album once per photo, and an edit
    added a row beside the stale one instead of replacing it. Both write paths
    persist before dispatching, so the lookup always sees the row.
    """
    index_telegram_unit(dm.channel_id, dm.id)


def index_telegram_unit(channel_id: int, message_id: int) -> None:
    """Index the display unit a raw message belongs to; a no-op if it is gone.

    Also clears any document keyed on a *sibling* id, so a unit indexed wrongly by
    an earlier build heals on the next edit rather than lingering as a duplicate.
    """
    if not _available:
        return
    unit = _telegram_unit(channel_id, message_id)
    if unit is None:
        return
    for sibling in unit['ids']:
        delete_item('telegram', channel_id, sibling)
    index_item('telegram', channel_id, unit['id'], unit['text'], unit['date'])


def _telegram_unit(channel_id: int, message_id: int) -> Optional[dict]:
    """The display unit containing one message, on telememo's own grouping rule:
    the anchor is the album's lowest id and the text is the last sibling that has
    any (``group_messages_to_display``). ``_rebuild_telegram`` applies the same
    rule in bulk — the two must not drift."""
    cur = tdb.db.execute_sql(
        'SELECT sib.id, sib.text, sib.date FROM messages tgt '
        'JOIN messages sib ON sib.channel_id = tgt.channel_id '
        '  AND (sib.id = tgt.id OR (tgt.grouped_id IS NOT NULL AND sib.grouped_id = tgt.grouped_id)) '
        'WHERE tgt.channel_id = ? AND tgt.id = ? ORDER BY sib.id',
        (channel_id, message_id),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    text = next((row[1] for row in reversed(rows) if row[1]), None)
    return {'id': rows[0][0], 'ids': [row[0] for row in rows], 'text': text, 'date': rows[0][2]}


def _strip_html(value: Optional[str]) -> str:
    """HN self-post bodies are HTML fragments; the reader searches the words in them."""
    if not value:
        return ''
    return html.unescape(re.sub(r'<[^>]+>', ' ', value))


def hn_document(row: dict) -> str:
    """Title, self-post body, and — since v19 — the summary, for the reason
    ``rss_document`` gives: it is what the card shows."""
    parts = (row.get('title') or '', _strip_html(row.get('text')), row.get('summary') or '')
    return ' '.join(p for p in parts if p)


def index_hn_story(row: dict) -> None:
    """Index one story — unless HN killed it.

    ``sources/hn.py`` ranks with ``WHERE h.is_dead = 0``, so a dead story is
    invisible on every reading surface; indexing it would make search the only
    place it still turns up. This covers both directions: a story flagged after we
    archived it (``db.mark_hn_story_dead`` deletes the document) and one that
    arrives already dead, which Firebase does serve for submissions still sitting
    in ``topstories``.
    """
    if row.get('is_dead'):
        delete_item('hn', row['id'])
        return
    index_item('hn', row['id'], 0, hn_document(row), row.get('first_seen_at'))


def index_hn_stories(story_ids: list[int]) -> None:
    """Re-index stories by id (``index_rss_entries``' counterpart) — the summary
    pipeline's hook, since a summary lands long after the ingest-time document."""
    if not _available or not story_ids:
        return
    placeholders = ','.join('?' for _ in story_ids)
    cur = tdb.db.execute_sql(
        f'SELECT id, title, text, summary, first_seen_at, is_dead FROM hn_stories WHERE id IN ({placeholders})',
        tuple(story_ids),
    )
    columns = [c[0] for c in cur.description]
    with tdb.db.atomic():
        for values in cur.fetchall():
            index_hn_story(dict(zip(columns, values)))


def rss_document(row: dict) -> str:
    """A feed entry's searchable text: what the card and the pane put on screen.

    The summary is included because it is what the *card* shows (plan §0.4) — the
    reader searches for a phrase they remember reading, and on a summarized entry
    that phrase may exist nowhere else. It arrives later than the entry does, so
    the summary pipeline (Phase 3) re-indexes after writing one.
    """
    parts = (row.get('title') or '', _strip_html(row.get('content')), row.get('summary') or '')
    return ' '.join(p for p in parts if p)


def index_rss_entries(entry_ids: list[int]) -> None:
    """Index entries by id, at the position the timeline sorts them.

    One transaction rather than one per row: a first fetch of an archive-style feed
    lands hundreds of entries at once, and outside ``atomic()`` every DELETE and
    INSERT is its own commit (``index_x_tweets``' measurement).
    """
    if not _available or not entry_ids:
        return
    from .sources import rss as rss_source

    rows = rss_source.rows_by_id(entry_ids)
    if not rows:
        return
    with tdb.db.atomic():
        for row in rows:
            index_item('rss', row['id'], 0, rss_document(row), row['sort_at'])


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if value else None
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _url_parts(value) -> list[str]:
    """The expanded + display forms of a tweet's url entities (v13) — what the card
    renders in place of the t.co, and therefore what the reader will search for."""
    try:
        entries = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    parts = []
    for entry in entries:
        if isinstance(entry, dict):
            parts.extend(v for v in (entry.get('expanded_url'), entry.get('display_url')) if v)
    return parts


def x_document(row: dict) -> str:
    """A tweet's searchable text: whatever the card puts on screen.

    A long-form post keeps its body in ``article`` (bird sets ``text`` to the
    title), a quoted tweet is rendered inside the card, and a t.co is rendered as
    its original link (v13 ``urls``) — so all of them are part of the tweet as the
    reader saw it, and all are searchable.
    """
    article = _json_dict(row.get('article'))
    parts = [row.get('text'), article.get('title'), article.get('previewText'), row.get('quote_text')]
    parts += _url_parts(row.get('urls')) + _url_parts(row.get('quote_urls'))
    return ' '.join(p for p in parts if p)


def index_x_tweets(tweet_ids: list[int]) -> None:
    """Index tweets by id, at the position the timeline would sort them.

    Only tweets with a feed appearance are indexed; ids without one are silently
    skipped, which is what keeps embedded quotes and Following's out-of-window
    thread ancestors — bodies with no card — out of the results.
    """
    if not _available or not tweet_ids:
        return
    documents = _x_documents(tweet_ids)
    if not documents:
        return
    # One transaction, not one per row. A probe round re-pushes its whole window
    # (the seen-cache shrinks it, never guarantees it stops), so this runs over ~50
    # tweets four times an hour on the process's only event loop — and outside
    # `atomic()` every DELETE and INSERT is its own commit, i.e. ~100 fsyncs.
    with tdb.db.atomic():
        for row in documents:
            index_item('x', row['id'], 0, row['document'], row['ts'])


def _x_documents(tweet_ids: list[int]) -> list[dict]:
    """``{id, document, ts}`` for the ids that actually appear in some feed."""
    from .sources import x as x_source

    positions = x_source.sort_positions(tweet_ids)
    if not positions:
        return []
    return [
        {'id': row['id'], 'document': x_document(row), 'ts': positions[row['id']]} for row in _x_rows(list(positions))
    ]


def _x_rows(tweet_ids: list[int]) -> list[dict]:
    placeholders = ','.join('?' for _ in tweet_ids)
    cur = tdb.db.execute_sql(
        'SELECT t.id AS id, t.text AS text, t.article AS article, t.urls AS urls, '
        'q.text AS quote_text, q.urls AS quote_urls '
        'FROM x_tweets t LEFT JOIN x_tweets q ON q.id = t.quote_of '
        f'WHERE t.id IN ({placeholders})',
        tuple(tweet_ids),
    )
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


# --- rebuild ------------------------------------------------------------------

_REBUILD_CHUNK = 500


def rebuild() -> dict[str, int]:
    """Re-read every source into a fresh index; returns rows written per source.

    The escape hatch and the upgrade path in one: there is no migration for this
    table, because there is nothing in it that is not derived.
    """
    if not _available:
        return {}
    from . import db

    with tdb.db.atomic():
        tdb.db.execute_sql(f'DELETE FROM {TABLE}')
        counts = {
            'telegram': _rebuild_telegram(),
            'hn': _rebuild_hn(),
            'x': _rebuild_x(),
            'rss': _rebuild_rss(),
        }
        db.set_meta(VERSION_META_KEY, str(TOKENIZER_VERSION))
    log.info('search index rebuilt: %s', counts)
    return counts


def _rebuild_telegram() -> int:
    """Collapse messages into display units the way telememo does, then index them.

    Mirrors ``group_messages_to_display``: an album's anchor is its lowest id and
    its text is the last sibling that has any. Reproduced here rather than reused
    because that helper builds full DisplayMessage objects — media, forwards,
    stats — and a rebuild only needs two columns out of the whole archive.
    """
    cur = tdb.db.execute_sql('SELECT channel_id, id, grouped_id, text, date FROM messages ORDER BY channel_id, id')
    units: dict[tuple, dict] = {}
    for channel_id, message_id, grouped_id, text, date in cur.fetchall():
        key = (channel_id, ('g', grouped_id) if grouped_id else ('m', message_id))
        unit = units.get(key)
        if unit is None:
            units[key] = {'channel_id': channel_id, 'id': message_id, 'text': text, 'date': date}
        elif text:
            unit['text'] = text
    rows = (_document_row('telegram', u['channel_id'], u['id'], u['text'], u['date']) for u in units.values())
    return _insert_many([r for r in rows if r is not None])


def _rebuild_hn() -> int:
    # is_dead = 0 matches sources/hn.py's ranking. Without it every rebuild would
    # silently undo every mark_hn_story_dead deletion.
    cur = tdb.db.execute_sql('SELECT id, title, text, summary, first_seen_at FROM hn_stories WHERE is_dead = 0')
    columns = [c[0] for c in cur.description]
    rows = []
    for values in cur.fetchall():
        story = dict(zip(columns, values))
        row = _document_row('hn', story['id'], 0, hn_document(story), story['first_seen_at'])
        if row is not None:
            rows.append(row)
    return _insert_many(rows)


def _rebuild_x() -> int:
    ids = [row[0] for row in tdb.db.execute_sql('SELECT DISTINCT tweet_id FROM x_feed_items').fetchall()]
    written = 0
    # Chunked because the per-tweet SELECT and the dedup-priority lookup both bind
    # one parameter per id, and SQLite's variable limit is finite.
    for i in range(0, len(ids), _REBUILD_CHUNK):
        rows = (
            _document_row('x', d['id'], 0, d['document'], d['ts']) for d in _x_documents(ids[i : i + _REBUILD_CHUNK])
        )
        written += _insert_many([r for r in rows if r is not None])
    return written


def _rebuild_rss() -> int:
    from .sources import rss as rss_source

    ids = [row[0] for row in tdb.db.execute_sql('SELECT id FROM rss_entries').fetchall()]
    written = 0
    # Chunked for the same reason ``_rebuild_x`` is: the row lookup binds one
    # parameter per id and SQLite's variable limit is finite.
    for i in range(0, len(ids), _REBUILD_CHUNK):
        rows = rss_source.rows_by_id(ids[i : i + _REBUILD_CHUNK])
        documents = (_document_row('rss', r['id'], 0, rss_document(r), r['sort_at']) for r in rows)
        written += _insert_many([d for d in documents if d is not None])
    return written


def ensure_index() -> Optional[dict[str, int]]:
    """Rebuild at startup when the stored tokenizer version is not this one.

    The version marker *is* the trigger, because ``rebuild`` is the only thing that
    writes it — so "version matches" already means "a rebuild finished under this
    tokenizer". That covers both cases the plan needs: an upgrade from a database
    that predates the index (no marker at all) and any edit to ``tokenize``.

    Deliberately **not** also "rebuild when the index is empty but the sources are
    not". That reads like free self-healing and is not: an archive whose indexable
    text is genuinely empty — media-only channels, an install holding nothing but
    dead HN placeholders — would re-scan everything on every boot, forever, and
    ``git push`` to master is a deploy here. A table emptied underneath us is a
    manual act, and ``rebuild()`` is the documented answer to it.

    Failure never reaches the caller: this reads every row of three tables inside
    one write transaction, and a transient ``database is locked`` must cost the app
    its search, not its startup (``setup``'s contract, and ``vectors.setup``'s).
    The marker stays unwritten, so the next boot tries again.
    """
    if not _available:
        return None
    from . import db

    if db.get_meta(VERSION_META_KEY) == str(TOKENIZER_VERSION):
        return None
    try:
        return rebuild()
    except Exception as e:  # noqa: BLE001 - a failed backfill is a degraded search, not a dead app
        log.exception('search index rebuild failed, search will be incomplete until the next start: %s', e)
        return None


# --- query --------------------------------------------------------------------

SORTS = ('recent', 'relevance')
STATUSES = ('unread', 'saved')

# Excluded from every search, for the same reason every timeline surface excludes
# them: hiding an item means never seeing it again, and a keyword filter is a
# standing instruction about its text — which is precisely what a search matches.
#
# The filter test covers **any row of the display unit**, not just the anchor the
# index is keyed by. `is_filtered` is computed per raw row, and an album's caption
# usually sits on a sibling — so an anchor-only test let a banned caption through,
# and the card then rendered the very text the rule exists to suppress. This is
# deliberately stricter than the timeline, which drops the filtered row and still
# shows the rest of the album: a filter that does not answer a search for its own
# banned word is not a filter.
_EXCLUSIONS = (
    f'NOT EXISTS (SELECT 1 FROM hidden_items h '
    f'  WHERE h.source = {TABLE}.source AND h.ref1 = {TABLE}.ref1 AND h.ref2 = {TABLE}.ref2)',
    f'NOT EXISTS (SELECT 1 FROM messages a JOIN messages m ON m.channel_id = a.channel_id '
    f'  AND (m.id = a.id OR (a.grouped_id IS NOT NULL AND m.grouped_id = a.grouped_id)) '
    f"  WHERE {TABLE}.source = 'telegram' AND a.channel_id = {TABLE}.ref1 AND a.id = {TABLE}.ref2 "
    f'  AND m.is_filtered = 1)',
)

_STATUS_SQL = {
    'unread': f'NOT EXISTS (SELECT 1 FROM read_items r '
    f'  WHERE r.source = {TABLE}.source AND r.ref1 = {TABLE}.ref1 AND r.ref2 = {TABLE}.ref2)',
    # ``is_saved = 1`` (v18): a row held up by a note/annotation alone is not a
    # bookmark, and this filter answers "what did I save".
    'saved': f'EXISTS (SELECT 1 FROM saved_items s '
    f'  WHERE s.source = {TABLE}.source AND s.ref1 = {TABLE}.ref1 AND s.ref2 = {TABLE}.ref2 AND s.is_saved = 1)',
}

_ORDER_SQL = {'recent': 'ts DESC, rowid DESC', 'relevance': 'rank, ts DESC'}


def _where(
    match: str,
    source: Optional[str],
    channel_id: Optional[int],
    feed: Optional[str],
    status: Optional[str],
) -> tuple[list[str], list]:
    """The scope, as SQL. Deliberately **not** scoped by subscription state: search
    reads the archive, so a paused channel and a For You tweet the aggregate mode
    keeps out of the timeline are both still findable. Hidden and keyword-filtered
    items are the exception, because those are judgements about the item itself."""
    where = [f'{TABLE} MATCH ?', *_EXCLUSIONS]
    params: list = [match]
    if source:
        where.append(f'{TABLE}.source = ?')
        params.append(source)
    if channel_id is not None:
        where.append(f"{TABLE}.source = 'telegram' AND {TABLE}.ref1 = ?")
        params.append(channel_id)
    if feed:
        # A feed key is only meaningful inside its own source, and the two that
        # have feeds key on different things (an X handle, an RSS feed URL) — hence
        # the dispatch, and the endpoint's 422 when ``feed`` arrives without one of
        # them named.
        if source == 'rss':
            where.append(
                f"{TABLE}.source = 'rss' AND EXISTS (SELECT 1 FROM rss_entries e "
                f'  WHERE e.id = {TABLE}.ref1 AND e.feed_url = ?)'
            )
        else:
            where.append(
                f"{TABLE}.source = 'x' AND EXISTS (SELECT 1 FROM x_feed_items f "
                f'  WHERE f.tweet_id = {TABLE}.ref1 AND f.channel_id = ?)'
            )
        params.append(feed)
    if status in _STATUS_SQL:
        where.append(_STATUS_SQL[status])
    return where, params


def search(
    match: str,
    source: Optional[str] = None,
    channel_id: Optional[int] = None,
    feed: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = 'recent',
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[dict], int]:
    """One page of hits as ``(source, ref1, ref2, ts)`` dicts, plus the total.

    The total is a **second scan of the same predicate**, which is a real cost and
    was measured rather than waved through (``tmp/search_query_timing.py``, 2561
    documents): a typical query costs 0.2–4 ms for the whole page, and the worst
    case anyone can construct — 「的」, a character in a fifth of the corpus —
    costs 28 ms *including* the count. So it stays: the header's "45 results" and
    ``has_more`` are both worth that, and paging through a search that will not say
    how much there is to page through is worse. Revisit if the corpus grows an
    order of magnitude; the fix is to count only at ``offset == 0``.
    """
    if not _available:
        return [], 0
    where, params = _where(match, source, channel_id, feed, status)
    clause = ' AND '.join(where)
    cur = tdb.db.execute_sql(
        f'SELECT source, ref1, ref2, ts FROM {TABLE} WHERE {clause} '
        f'ORDER BY {_ORDER_SQL.get(sort, _ORDER_SQL["recent"])} LIMIT ? OFFSET ?',
        (*params, limit, offset),
    )
    columns = [c[0] for c in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    total = tdb.db.execute_sql(f'SELECT count(*) FROM {TABLE} WHERE {clause}', tuple(params)).fetchone()[0]
    return rows, total


# --- hits -> envelopes --------------------------------------------------------
# The index stores item keys, not content, so a page of hits is rendered by asking
# each source for the same rows the timeline would have shown. Batched per source
# rather than per hit: a page mixes three sources and would otherwise be twenty
# round trips.


def render(rows: list[dict]) -> list[dict]:
    """Hits as item envelopes, in the order the query returned them.

    A hit whose item has since vanished from its source table is dropped rather
    than rendered as a hole. That can only happen in the window between a delete
    and the cascade that follows it, and the honest answer for one stale row is
    to show one fewer result — the ``total`` beside it is off by the same one.
    """
    from . import forwards, records
    from .items import hn_envelope, rss_envelope, x_envelope
    from .sources import hn as hn_source
    from .sources import rss as rss_source
    from .sources import telegram as tg_source
    from .sources import x as x_source

    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row['source'], []).append(row)

    units = tg_source.units_by_key([(r['ref1'], r['ref2']) for r in by_source.get('telegram', [])])
    stories = hn_source.rows_by_id([r['ref1'] for r in by_source.get('hn', [])])
    tweets = {t['id']: t for t in x_source.rows_by_id([r['ref1'] for r in by_source.get('x', [])])}
    entries = {e['id']: e for e in rss_source.rows_by_id([r['ref1'] for r in by_source.get('rss', [])])}

    out = []
    for row in rows:
        if row['source'] == 'telegram':
            envelope = units.get((row['ref1'], row['ref2']))
        elif row['source'] == 'hn':
            story = stories.get(row['ref1'])
            envelope = hn_envelope(story, bool(story['is_read']), bool(story['is_saved'])) if story else None
        elif row['source'] == 'rss':
            entry = entries.get(row['ref1'])
            envelope = rss_envelope(entry, bool(entry['is_read']), bool(entry['is_saved'])) if entry else None
        else:
            tweet = tweets.get(row['ref1'])
            envelope = (
                x_envelope(
                    tweet,
                    bool(tweet['is_read']),
                    bool(tweet['is_saved']),
                    tweet['feedback'],
                    tweet['feedback_reason'],
                )
                if tweet
                else None
            )
        if envelope is not None:
            out.append(envelope)
    return records.stamp_notes(forwards.stamp(out))
