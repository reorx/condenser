"""Condenser data layer (spec Part B).

Condenser shares telememo's single SQLite file. telememo tables (channels,
messages, comments) are owned by telememo's Peewee models and the ``is_filtered``
extension column; the app-state tables below are condenser's own, bound to the
same Peewee database object so everything lives on one connection.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from peewee import (
    SQL,
    AutoField,
    BareField,
    BigIntegerField,
    BlobField,
    BooleanField,
    CharField,
    CompositeKey,
    DateTimeField,
    IntegerField,
    Model,
    TextField,
)

from telememo import db as tdb

from . import search, vectors
from .items import FORYOU_FEED, ItemKey

log = logging.getLogger('condenser.db')

# The condenser is_filtered overlay column declared on telememo's messages table.
MESSAGES_OPTIONAL_FIELDS = {
    'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}],
}

# Bumped when condenser's own table shapes change; recorded in app_meta on init so a
# future startup can detect an upgrade and run a migration. Telememo manages its own
# table migrations separately (init_db optional_fields / ALTER TABLE).
SCHEMA_VERSION = 15

# One-shot marker for the v14 admission backfill (see _migrate_hn_qualified_v14).
# State, not shape: the columns can exist while the stamping has not happened.
BACKFILL_META_KEY = 'hn_qualified_backfilled'


class CondenserBaseModel(Model):
    class Meta:
        database = tdb.db


class Subscription(CondenserBaseModel):
    """A subscription within a source (multi-source since v3).

    ``channel_id`` carries the subscription's id *within its source* (RSS-style
    channel concept) and is typed per source: Telegram rows store an int channel
    id, HN rows store a feed key string (v1: only ``'front'``). ``BareField``
    gives the column no SQLite affinity so both round-trip as inserted.
    """

    # SQL-level DEFAULT keeps INSERTs from pre-v3 code working after a version rollback
    source = CharField(default='telegram', constraints=[SQL("DEFAULT 'telegram'")])  # 'telegram' | 'hn'
    channel_id = BareField()
    enabled = BooleanField(default=True)
    backfill_done = BooleanField(default=False)  # telegram-only
    added_at = DateTimeField(default=datetime.now)
    name = TextField(null=True)  # display name; NULL for TG (resolved from channels)
    config = TextField(null=True)  # per-subscription JSON config (e.g. HN display_mode)

    class Meta:
        table_name = 'subscriptions'
        primary_key = CompositeKey('source', 'channel_id')


class KeywordFilter(CondenserBaseModel):
    id = AutoField()
    channel_id = IntegerField(null=True)  # NULL = global rule
    pattern = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'keyword_filters'


class ReadItem(CondenserBaseModel):
    """Read marker for any source's item, keyed by the (source, ref1, ref2) triple.

    TG: ``ref1=channel_id, ref2=message_id``; HN: ``ref1=story_id, ref2=0``.
    The API layer converts item-key strings <-> triples (see items.py).
    """

    source = CharField()
    ref1 = IntegerField()
    ref2 = IntegerField(default=0)
    read_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'read_items'
        primary_key = CompositeKey('source', 'ref1', 'ref2')


class HiddenItem(CondenserBaseModel):
    """Per-item "never show this again" marker, triple-keyed like read_items.

    Every timeline surface (pages, new-content poll, day counts, unread counts)
    anti-joins this table, so hiding is enforced server-side for every client.
    Telegram rows are stored album-expanded (one row per raw sibling id) so the
    per-row anti-join removes the whole display unit.
    """

    source = CharField()
    ref1 = IntegerField()
    ref2 = IntegerField(default=0)
    hidden_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'hidden_items'
        primary_key = CompositeKey('source', 'ref1', 'ref2')


class SavedItem(CondenserBaseModel):
    """Saved record (user asset): a source-decoupled JSON snapshot, triple-keyed."""

    source = CharField()
    ref1 = IntegerField()
    ref2 = IntegerField(default=0)
    raw_data = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'saved_items'
        primary_key = CompositeKey('source', 'ref1', 'ref2')


class TgSession(CondenserBaseModel):
    id = IntegerField(primary_key=True)
    phone = CharField(null=True)
    session_enc = BlobField(null=True)
    authorized = BooleanField(default=False)
    updated_at = DateTimeField(null=True)

    class Meta:
        table_name = 'tg_session'


class AppMeta(CondenserBaseModel):
    key = CharField(primary_key=True)
    value = TextField(null=True)

    class Meta:
        table_name = 'app_meta'


class LinkPreviewCache(CondenserBaseModel):
    """Cache of self-fetched URL previews, keyed by a normalized URL.

    Condenser-owned (not a telememo table), so the extension-column contract does
    not apply — we may upsert freely. ``ok`` distinguishes successful previews from
    cached failures (negative caching with a shorter TTL). ``fetched_at`` is stored
    naive-UTC so peewee round-trips it in its default datetime format.
    """

    url = TextField(primary_key=True)
    ok = BooleanField()
    title = TextField(null=True)
    description = TextField(null=True)
    image = TextField(null=True)
    site_name = TextField(null=True)
    canonical_url = TextField(null=True)
    error = TextField(null=True)
    fetched_at = DateTimeField()

    class Meta:
        table_name = 'link_previews'


class Device(CondenserBaseModel):
    """An authorized client device (e.g. the iOS reader). Only the token hash is stored."""

    id = AutoField()
    name = TextField()
    token_hash = CharField(unique=True)
    created_at = DateTimeField()
    last_seen_at = DateTimeField(null=True)

    class Meta:
        table_name = 'devices'


class HNStory(CondenserBaseModel):
    """A Hacker News story that has appeared on the front page (append-only archive).

    ``first_seen_at`` (first front-page sighting, naive UTC) is the timeline sort
    key; ``day`` is its UTC date string — the archival day rankings partition on.
    """

    id = IntegerField(primary_key=True)  # HN item id
    title = TextField(null=True)
    url = TextField(null=True)  # NULL = self-post (Ask HN etc.)
    domain = TextField(null=True)
    author = TextField(null=True)
    text = TextField(null=True)  # self-post HTML
    type = CharField(default='story')  # story | job
    submitted_at = DateTimeField(null=True)
    first_seen_at = DateTimeField(index=True)
    day = CharField()  # YYYY-MM-DD (UTC)
    score = IntegerField(default=0)
    comments_count = IntegerField(default=0)
    score_updated_at = DateTimeField(null=True)
    peak_rank = IntegerField(null=True)  # best observed front-page position
    is_dead = BooleanField(default=False)
    backfilled = BooleanField(default=False)  # from hckrnews history (first_seen_at approximate)
    # Prefetched LinkPreview JSON for the story URL — denormalized into the archive
    # so it outlives the TTL'd link_previews cache. NULL until fetched (or forever,
    # for self-posts / URLs that failed preview_attempts real fetches).
    preview = TextField(null=True)
    preview_attempts = IntegerField(default=0)
    # v14: the admission stamp — NULL means "not (yet) on the timeline". Written
    # once by the polling-time judge and never cleared, because the query-time rank
    # it replaces let a story vanish *after* it had been read. It is the timeline's
    # sort key and its day grouping, so "became visible" and "sits at" are the same
    # instant by construction (plan 2026-08-14 phase 3).
    qualified_at = DateTimeField(null=True, index=True)
    # Which admission slot of its day this took — the card's badge. Stored rather
    # than computed, so it stops jumping between two refreshes.
    qualified_rank = IntegerField(null=True)

    class Meta:
        table_name = 'hn_stories'
        indexes = ((('day', 'score'), False),)


class XTweet(CondenserBaseModel):
    """One archived tweet (v7). The bird CLI's output tracks X's internal API and is
    not a stable contract, so ``raw`` keeps the entry verbatim: a format drift can be
    re-parsed from the archive instead of being lost.

    Quoted tweets get their own row here (self-referential via ``quote_of``) but no
    ``x_feed_items`` row — they were never in a feed, they came embedded.
    """

    id = BigIntegerField(primary_key=True)  # snowflake tweet id
    author_id = BigIntegerField(null=True, index=True)
    author_handle = TextField(null=True)
    author_name = TextField(null=True)
    text = TextField(null=True)
    created_at = DateTimeField(null=True)  # naive UTC; NULL = unparseable timestamp
    media = TextField(null=True)  # JSON list (bird shape: type/url/width/height/...)
    metrics = TextField(null=True)  # JSON dict, refreshed on every re-push
    quote_of = BigIntegerField(null=True)
    # bird flattens retweets into an 'RT @orig: ...' text prefix with no structured
    # field, so the original author is only recoverable as a handle (may be NULL).
    rt_of_handle = TextField(null=True)
    reply_to_id = BigIntegerField(null=True)
    article = TextField(null=True)  # JSON dict: X long-form title + truncated preview
    # v13: JSON list [{url, expanded_url, display_url, indices}] — the t.co expansion
    # metadata (xbird >= 1.2.0). A rebuildable derived column in the is_filtered
    # spirit: any row whose raw carries urls can be re-extracted. NULL pre-upgrade.
    urls = TextField(null=True)
    raw = TextField(null=True)
    fetched_at = DateTimeField()

    class Meta:
        table_name = 'x_tweets'


class XFeedItem(CondenserBaseModel):
    """A tweet's appearance in one subscribed feed (v7).

    Split from the tweet body because the same tweet can show up in For You *and*
    in a followed account's feed, while ``verdict`` (the feedback-driven judgement)
    only ever belongs to the For You appearance. ``first_seen_at`` is when the probe
    first pushed it — the For You timeline sort key, and sticky across re-pushes.
    """

    channel_id = CharField()  # the x subscription key: 'foryou' | a followed handle
    tweet_id = BigIntegerField()
    first_seen_at = DateTimeField()
    verdict = CharField(null=True)  # positive | neutral | negative (Phase 4)
    verdict_meta = TextField(null=True)  # JSON: score, neighbours, algo version

    class Meta:
        table_name = 'x_feed_items'
        primary_key = CompositeKey('channel_id', 'tweet_id')
        indexes = ((('channel_id', 'first_seen_at'), False),)


class ItemFeedback(CondenserBaseModel):
    """Explicit up/down feedback on any source's item, triple-keyed like read_items.

    Source-generic on purpose (X in v1, HN later needs no migration). Written by
    Phase 3's feedback endpoints; the table exists from v7 so the data can start
    accumulating as soon as the UI lands.

    ``reason`` (v9) is the optional one-tap chip behind a thumbs-down: *which
    attribute* of the tweet earned it. A bare down labels the whole bag, but the
    cause is usually one instance in it — the topic, the marketing voice, the
    engagement bait, the AI-slop phrasing, the author — and a single embedding
    averages them all into one point, so a down for tone reads as a down for the
    topic. Recording the attribute now means the labels can be routed per channel
    when the model grows them (see
    kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md); NULL is a
    first-class value, since skipping the chip must stay free.
    """

    source = CharField()
    ref1 = IntegerField()  # X: tweet id
    ref2 = IntegerField(default=0)
    verdict = CharField()  # 'up' | 'down'
    reason = CharField(null=True)  # v9; one of FEEDBACK_REASONS, or NULL when skipped
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'item_feedback'
        primary_key = CompositeKey('source', 'ref1', 'ref2')


class XEmbedding(CondenserBaseModel):
    """A tweet's embedding vector (v8) — the storage of record for anything vector.

    A rebuildable cache in the spirit of ``messages.is_filtered``: the text is in
    ``x_tweets``, so any row can be re-embedded. ``model`` records ``name@dims``,
    because vectors from a different model or dimension are not comparable — a
    model change is a re-embed filtered on this column, never an in-place migration.

    Unlabeled rows are pruned after a retention window (they are read once, at
    judge time); labeled rows are the training set and stay.
    """

    tweet_id = BigIntegerField(primary_key=True)
    vector = BlobField()  # float32, L2-normalized (see vectors.pack)
    model = CharField()
    created_at = DateTimeField(index=True)

    class Meta:
        table_name = 'x_embeddings'


class XAttribute(CondenserBaseModel):
    """What a tweet is about and how it talks, as read by an LLM (v10).

    A rebuildable cache, exactly like ``x_embeddings``: the text is in ``x_tweets``,
    so any row can be re-read. ``model`` records ``model@taxonomy`` — a flag read
    under one taxonomy version and one read under the next are not the same
    feature, so a taxonomy edit is a re-extraction, never a migration.

    Channel C scores these against the reader's labels (plan v2 step 3); until then
    the table only accumulates, which is the point of landing it early — attributes
    for already-labeled tweets are the training data, and they can only be
    collected forwards.
    """

    tweet_id = BigIntegerField(primary_key=True)
    topics = TextField()  # JSON list of open slugs
    style_flags = TextField()  # JSON list, closed taxonomy (attributes.STYLE_FLAGS)
    model = CharField(index=True)
    created_at = DateTimeField()

    class Meta:
        table_name = 'x_attributes'


class XFollowing(CondenserBaseModel):
    """The accounts the user follows on X (v11), as pushed by the probe.

    The Following timeline carries injected ads that are structurally
    indistinguishable from ordinary tweets — bird dumps the tweet result object,
    not the timeline entry, so ``promotedMetadata`` never reaches us (measured:
    ``promoted`` / ``advertiser`` / ``socialContext`` hit 0/20). What *is* reliable
    is the author: in a 100-entry sample the follow list caught 7 of 7 ads with no
    false positive.

    A table rather than a JSON blob in ``app_meta`` because every ingest round
    reads it, and because "is this author someone I follow" is a zero-cost prior
    channel A (``authors.py``) is currently blind to.
    """

    handle = CharField(primary_key=True)  # lowercased — the feed's author handle is matched against this
    user_id = CharField(null=True)  # numeric id; survives a rename, unlike the handle
    name = TextField(null=True)  # display name
    synced_at = DateTimeField()  # when this row was last confirmed present

    class Meta:
        table_name = 'x_following'


class RssFeed(CondenserBaseModel):
    """One subscribed feed's *fetch state* (v15), keyed by its URL.

    Split from the subscription row for the same reason ``x_feed_items`` is split
    from ``x_tweets``: this half is machine state that changes every poll round
    (validators, timestamps, a failure streak), while the subscription row is the
    reader's decision. ``url`` is also the subscription's ``channel_id`` — what
    the reader typed is the key, the way an X handle is (``x.py``).

    ``title`` / ``site_url`` are backfilled from the first successful fetch: the
    reader subscribes with a URL and the feed tells us its name.
    """

    url = TextField(primary_key=True)
    title = TextField(null=True)
    site_url = TextField(null=True)
    # Conditional-request validators, echoed back as If-None-Match / If-Modified-Since.
    # Most rounds are a 304 because of them, which is what makes 100 feeds cheap.
    etag = TextField(null=True)
    last_modified = TextField(null=True)
    fetched_at = DateTimeField(null=True)  # last *attempt* that succeeded, 200 or 304
    # Recorded, never acted on: a feed that 404s for a week stays subscribed, because
    # unsubscribing on the reader's behalf loses a decision they never made.
    last_error = TextField(null=True)
    error_count = IntegerField(default=0)  # consecutive failures; a success clears it

    class Meta:
        table_name = 'rss_feeds'


class RssEntry(CondenserBaseModel):
    """One archived feed entry (v15). ``id`` is the item key's ref1 (``rss:{id}``).

    A surrogate key rather than the feed's own ``guid``, because a guid is only
    unique *within* its feed and is a string of arbitrary shape — the item triple
    is three integers. ``(feed_url, guid)`` carries the uniqueness instead, and
    ingest is insert-if-absent on it: an entry is archived as first seen, since RSS
    republishing an edited item is rare enough that v1 does not chase it.

    ``published_at`` is what the feed declared and is stored **verbatim**, missing
    or absurd (some feeds publish future timestamps). Clamping it against
    ``first_seen_at`` is a read-side concern — the provider's sort key — so the
    archive keeps the evidence.
    """

    id = AutoField()
    feed_url = TextField(index=True)
    guid = TextField()
    title = TextField(null=True)
    link = TextField(null=True)
    author = TextField(null=True)
    content = TextField(null=True)  # the feed's own HTML (content:encoded, else description)
    published_at = DateTimeField(null=True)
    first_seen_at = DateTimeField(index=True)
    # The LLM summary (plan §3, Phase 3), denormalized onto the entry the way
    # hn_stories.preview is. ``summary_model`` is the model_tag contract: a model
    # change re-summarizes rather than migrates.
    summary = TextField(null=True)
    summary_model = TextField(null=True)
    summary_attempts = IntegerField(default=0)

    class Meta:
        table_name = 'rss_entries'
        indexes = ((('feed_url', 'guid'), True),)


CONDENSER_TABLES = [
    Subscription,
    KeywordFilter,
    ReadItem,
    HiddenItem,
    SavedItem,
    TgSession,
    AppMeta,
    LinkPreviewCache,
    Device,
    HNStory,
    XTweet,
    XFeedItem,
    ItemFeedback,
    XEmbedding,
    XAttribute,
    XFollowing,
    RssFeed,
    RssEntry,
]


def init_db(db_path: str, vector_dims: int = 256) -> None:
    """Initialize the shared SQLite file: telememo tables (+ is_filtered) then condenser tables.

    ``vector_dims`` sizes the v8 KNN index; the vec0 virtual table is raw SQL and
    has to be created *after* the sqlite-vec extension is loaded, hence the tail
    position. A host that cannot load the extension still gets a working app —
    only the For You verdict goes quiet.

    The v12 search index is the same shape of tail step, minus the extension:
    FTS5 is compiled into every SQLite this runs on, and the v11 upgrade is a
    backfill rather than a migration, because nothing in that table is not
    derived from the source tables (``search.ensure_index``).
    """
    tdb.init_db(db_path, optional_fields=MESSAGES_OPTIONAL_FIELDS)
    # Before the migrations, not with the vec0 table below: an ALTER TABLE makes
    # SQLite reload the whole schema, and a vec0 table it cannot parse reports
    # that as "database disk image is malformed" (see vectors.load).
    vectors.load()
    _migrate_subscriptions_v3()
    _migrate_hn_qualified_v14()
    tdb.db.create_tables(CONDENSER_TABLES)
    _migrate_read_saved_v4()
    _migrate_hn_previews_v5()
    _migrate_feedback_reason_v9()
    _migrate_x_urls_v13()
    _backfill_hn_admission()
    _enable_wal(db_path)
    set_meta('schema_version', str(SCHEMA_VERSION))
    vectors.setup(vector_dims)
    search.setup()
    search.ensure_index()


def _migrate_subscriptions_v3() -> None:
    """Rebuild a pre-v3 ``subscriptions`` table (single-column PK, no source) in place.

    SQLite cannot alter a primary key, so the composite ``(source, channel_id)`` key
    requires create-new -> copy -> swap. Detection is shape-based (missing ``source``
    column) rather than version-based, so it also covers DBs from before version
    tracking. Runs before ``create_tables`` (which would skip the existing table).
    """
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(subscriptions)').fetchall()]
    if not cols or 'source' in cols:
        return
    with tdb.db.atomic():
        tdb.db.execute_sql(
            'CREATE TABLE subscriptions_v3 ('
            "source VARCHAR(255) NOT NULL DEFAULT 'telegram', channel_id NOT NULL, enabled INTEGER NOT NULL, "
            'backfill_done INTEGER NOT NULL, added_at DATETIME NOT NULL, name TEXT, config TEXT, '
            'PRIMARY KEY (source, channel_id))'
        )
        tdb.db.execute_sql(
            'INSERT INTO subscriptions_v3 (source, channel_id, enabled, backfill_done, added_at) '
            "SELECT 'telegram', channel_id, enabled, backfill_done, added_at FROM subscriptions"
        )
        tdb.db.execute_sql('DROP TABLE subscriptions')
        tdb.db.execute_sql('ALTER TABLE subscriptions_v3 RENAME TO subscriptions')


def _migrate_read_saved_v4() -> None:
    """Copy pre-v4 ``read_messages`` / ``telegram_records`` into the unified triple-keyed
    tables (source, ref1, ref2), then rename the old tables ``*_legacy``.

    Shape-based (runs iff an old table still exists) and idempotent. Runs after
    ``create_tables`` so the new tables are in place. The legacy copies are kept for
    one schema version as a rollback net, to be dropped by a future migration.
    """
    tables = {r[0] for r in tdb.db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    with tdb.db.atomic():
        if 'read_messages' in tables:
            tdb.db.execute_sql(
                'INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) '
                "SELECT 'telegram', channel_id, message_id, read_at FROM read_messages"
            )
            tdb.db.execute_sql('DROP TABLE IF EXISTS read_messages_legacy')
            tdb.db.execute_sql('ALTER TABLE read_messages RENAME TO read_messages_legacy')
        if 'telegram_records' in tables:
            tdb.db.execute_sql(
                'INSERT OR IGNORE INTO saved_items (source, ref1, ref2, raw_data, created_at) '
                "SELECT 'telegram', channel_id, message_id, raw_data, created_at FROM telegram_records"
            )
            tdb.db.execute_sql('DROP TABLE IF EXISTS telegram_records_legacy')
            tdb.db.execute_sql('ALTER TABLE telegram_records RENAME TO telegram_records_legacy')


def _migrate_hn_previews_v5() -> None:
    """Add the preview columns to a pre-v5 ``hn_stories`` table.

    Shape-based (missing ``preview`` column) and idempotent; plain ADD COLUMNs, so
    unlike the v3/v4 table rebuilds no copy is needed. Runs after ``create_tables``
    (a fresh table already has the columns and is skipped by the pragma check).
    """
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(hn_stories)').fetchall()]
    if not cols or 'preview' in cols:
        return
    with tdb.db.atomic():
        tdb.db.execute_sql('ALTER TABLE hn_stories ADD COLUMN preview TEXT')
        tdb.db.execute_sql('ALTER TABLE hn_stories ADD COLUMN preview_attempts INTEGER NOT NULL DEFAULT 0')


def _migrate_feedback_reason_v9() -> None:
    """Add the reason column to a pre-v9 ``item_feedback`` table.

    Shape-based and idempotent like the v5 preview columns — a plain ADD COLUMN,
    since NULL is the correct value for every label collected before the chips
    existed (they were bag-level, and pretending otherwise would invent data).
    """
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(item_feedback)').fetchall()]
    if not cols or 'reason' in cols:
        return
    tdb.db.execute_sql('ALTER TABLE item_feedback ADD COLUMN reason VARCHAR(255)')


def _migrate_x_urls_v13() -> None:
    """Add the urls column to a pre-v13 ``x_tweets`` table.

    Shape-based and idempotent, the v5/v9 ADD COLUMN pattern. Historical rows stay
    NULL — the column is derived, and any row whose ``raw`` carries urls can be
    re-extracted (tmp/backfill_x_urls.py).
    """
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(x_tweets)').fetchall()]
    if not cols or 'urls' in cols:
        return
    tdb.db.execute_sql('ALTER TABLE x_tweets ADD COLUMN urls TEXT')


def _migrate_hn_qualified_v14() -> None:
    """Add the admission-stamp columns to a pre-v14 ``hn_stories`` table.

    Shape-based ADD COLUMNs, the v5/v9/v13 pattern — but it runs **before**
    ``create_tables``, which the other three do not, and that ordering is
    load-bearing rather than tidy. ``HNStory.qualified_at`` is declared
    ``index=True``, so ``create_tables`` issues
    ``CREATE INDEX IF NOT EXISTS hnstory_qualified_at ON hn_stories (qualified_at)``
    for the existing table. On a connection that has seen this table's schema
    change, SQLite **accepts** that statement against a column that is not there
    (a bare connection rejects it with "no such column"), and the moment the
    column is then added, ``PRAGMA integrity_check`` reports
    ``row 1 missing from index hnstory_qualified_at`` and every write to the table
    fails with ``database disk image is malformed``. Measured, not theorised —
    it is what the upgrade test caught. Put this call back after ``create_tables``
    and production's first restart corrupts its own hn_stories.

    The **backfill** is deliberately not here — see ``_backfill_hn_admission``.
    """
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(hn_stories)').fetchall()]
    if not cols or 'qualified_at' in cols:
        return
    with tdb.db.atomic():
        tdb.db.execute_sql('ALTER TABLE hn_stories ADD COLUMN qualified_at DATETIME')
        tdb.db.execute_sql('ALTER TABLE hn_stories ADD COLUMN qualified_rank INTEGER')


def _backfill_hn_admission() -> None:
    """Stamp what the pre-v14 query-time rule would have shown (plan §5.4d).

    Unlike the v5/v9/v13 columns, these cannot stay NULL: the read path now shows
    exactly what carries a stamp, so an un-backfilled upgrade empties the HN
    timeline. The backfill replays the old rule once and stamps each story it
    would have shown at that story's own ``first_seen_at`` — position for
    position, badge for badge — so the upgrade is invisible to the reader.

    Keyed on its own marker rather than on the columns' presence, because this is
    *state*, not shape: a crash between the ALTER and the stamping would otherwise
    satisfy the shape check forever and leave the timeline permanently empty. It
    also has to run after ``create_tables`` (it reads the subscription's config),
    which is the other reason it is not part of the migration above.

    ⚠️ One-shot on purpose. ``stamp_hn_history`` reproduces history; running it
    again under a later config would apply that config retroactively and move
    items the reader has already read past.
    """
    if get_meta(BACKFILL_META_KEY):
        return
    # deferred: condenser.sources.hn imports this module. The admission rule and its
    # config live with the provider, so this asks it rather than restating the floors.
    from .sources import hn as hn_source

    with tdb.db.atomic():
        stamped = hn_source.stamp_history()
        set_meta(BACKFILL_META_KEY, '1')
    log.info('hn v14 admission backfill stamped %s stories', stamped)


def _enable_wal(db_path: str) -> None:
    """Switch the database to WAL journaling so a writer and readers can coexist.

    Realtime ingest writes from the event-loop thread while user requests run on
    uvicorn's sync threadpool — multiple connections to one file. WAL lets readers
    proceed during a write instead of hitting ``database is locked``. The mode is a
    persistent property stored in the file header, so setting it once is enough; new
    per-thread connections inherit it. In-memory databases don't support WAL (each
    ``:memory:`` connection is a distinct db), so we skip them.
    """
    if db_path == ':memory:':
        return
    tdb.db.execute_sql('PRAGMA journal_mode=WAL')


def close_db() -> None:
    tdb.close_db()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """Current UTC time as a naive datetime (peewee round-trips naive datetimes cleanly)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- tg_session (single row, id=1) ------------------------------------------


def get_tg_session() -> Optional[TgSession]:
    return TgSession.get_or_none(TgSession.id == 1)


def save_tg_session(phone: Optional[str], session_enc: Optional[bytes], authorized: bool) -> None:
    """Upsert the single tg_session row."""
    TgSession.insert(id=1, phone=phone, session_enc=session_enc, authorized=authorized, updated_at=_now()).on_conflict(
        conflict_target=[TgSession.id],
        update={
            TgSession.phone: phone,
            TgSession.session_enc: session_enc,
            TgSession.authorized: authorized,
            TgSession.updated_at: _now(),
        },
    ).execute()


def clear_tg_session() -> None:
    TgSession.delete().where(TgSession.id == 1).execute()


# --- subscriptions (telegram) ------------------------------------------------
# The table is multi-source since v3; the TG-named helpers below keep their old
# signatures but scope every query to source='telegram'.

_TG = Subscription.source == 'telegram'


def list_subscriptions() -> list[Subscription]:
    return list(Subscription.select().where(_TG).order_by(Subscription.added_at.desc()))


def get_subscription(channel_id: int) -> Optional[Subscription]:
    return Subscription.get_or_none(_TG & (Subscription.channel_id == channel_id))


def add_subscription(channel_id: int) -> Subscription:
    # channel_id lost its SQLite affinity in v3 (BareField); coerce so '123' and 123
    # can never coexist as distinct rows
    channel_id = int(channel_id)
    sub, _ = Subscription.get_or_create(
        source='telegram',
        channel_id=channel_id,
        defaults={'enabled': True, 'backfill_done': False, 'added_at': _now()},
    )
    return sub


def set_subscription_enabled(channel_id: int, enabled: bool) -> None:
    Subscription.update(enabled=enabled).where(_TG & (Subscription.channel_id == channel_id)).execute()


def set_backfill_done(channel_id: int, done: bool = True) -> None:
    Subscription.update(backfill_done=done).where(_TG & (Subscription.channel_id == channel_id)).execute()


def delete_subscription(channel_id: int) -> None:
    Subscription.delete().where(_TG & (Subscription.channel_id == channel_id)).execute()


def enabled_channel_ids() -> list[int]:
    return [s.channel_id for s in Subscription.select().where(_TG & (Subscription.enabled == True))]  # noqa: E712


def pending_backfill_channel_ids() -> list[int]:
    return [
        s.channel_id
        for s in Subscription.select().where(
            _TG & (Subscription.enabled == True) & (Subscription.backfill_done == False)  # noqa: E712
        )
    ]


# --- subscriptions (hacker news) ---------------------------------------------

_HN = Subscription.source == 'hn'


def get_hn_subscription(feed: str = 'front') -> Optional[Subscription]:
    return Subscription.get_or_none(_HN & (Subscription.channel_id == feed))


def add_hn_subscription(feed: str, name: str, config: Optional[dict] = None) -> tuple[Subscription, bool]:
    """Subscribe-and-enable. A paused existing row is re-enabled (POST semantics);
    returns ``(sub, created)`` so callers can skip one-shot work on re-subscribes."""
    sub, created = Subscription.get_or_create(
        source='hn',
        channel_id=feed,
        defaults={
            'enabled': True,
            'backfill_done': False,
            'added_at': _now(),
            'name': name,
            'config': json.dumps(config) if config is not None else None,
        },
    )
    if not created and not sub.enabled:
        Subscription.update(enabled=True).where(_HN & (Subscription.channel_id == feed)).execute()
        sub.enabled = True
    return sub, created


def update_hn_subscription(feed: str, enabled: Optional[bool] = None, config: Optional[dict] = None) -> None:
    fields = {}
    if enabled is not None:
        fields[Subscription.enabled] = enabled
    if config is not None:
        fields[Subscription.config] = json.dumps(config)
    if fields:
        Subscription.update(fields).where(_HN & (Subscription.channel_id == feed)).execute()


def delete_hn_subscription(feed: str) -> None:
    Subscription.delete().where(_HN & (Subscription.channel_id == feed)).execute()


def hn_sampling_active() -> bool:
    """Whether any enabled HN feed subscription exists (the sampling gate)."""
    return Subscription.select().where(_HN & (Subscription.enabled == True)).exists()  # noqa: E712


def channel_max_message_id(channel_id: int) -> int:
    """Highest stored message id for a channel (0 if none) — a watermark for new-message diffs."""
    cur = tdb.db.execute_sql('SELECT MAX(id) FROM messages WHERE channel_id = ?', (channel_id,))
    return cur.fetchone()[0] or 0


def channel_min_message_id(channel_id: int) -> int:
    """Lowest stored message id for a channel (0 if none) — the page-back anchor for older fetches."""
    cur = tdb.db.execute_sql('SELECT MIN(id) FROM messages WHERE channel_id = ?', (channel_id,))
    return cur.fetchone()[0] or 0


def delete_channel_messages(channel_id: int) -> int:
    """Wipe a channel's cached messages, comments, read markers and search documents;
    returns messages deleted.

    Saved records (``saved_items``) and keyword filters are intentionally preserved —
    they are user assets / config, not re-syncable source cache. The search index is
    *not* in that group: it is derived from the text being deleted here, so leaving
    it would make a hit open onto a message that no longer exists.
    """
    deleted = tdb.get_message_count(channel_id)
    with tdb.db.atomic():
        ReadItem.delete().where((ReadItem.source == 'telegram') & (ReadItem.ref1 == channel_id)).execute()
        search.delete_telegram_channel(channel_id)
        tdb.db.execute_sql('DELETE FROM comments WHERE parent_channel_id = ?', (channel_id,))
        tdb.db.execute_sql('DELETE FROM messages WHERE channel_id = ?', (channel_id,))
    return deleted


def count_messages_after(channel_id: int, after_id: int) -> int:
    """Count stored messages with id above ``after_id`` (Telegram ids are monotonic per channel)."""
    cur = tdb.db.execute_sql('SELECT COUNT(*) FROM messages WHERE channel_id = ? AND id > ?', (channel_id, after_id))
    return cur.fetchone()[0]


# --- keyword filters --------------------------------------------------------


def list_all_filters() -> list[KeywordFilter]:
    """All filters across every channel, plus global rules (channel_id IS NULL)."""
    return list(KeywordFilter.select().order_by(KeywordFilter.channel_id.asc(nulls='FIRST'), KeywordFilter.created_at))


def add_filter(channel_id: Optional[int], pattern: str) -> KeywordFilter:
    return KeywordFilter.create(channel_id=channel_id, pattern=pattern, created_at=_now())


def get_filter(filter_id: int) -> Optional[KeywordFilter]:
    return KeywordFilter.get_or_none(KeywordFilter.id == filter_id)


def delete_filter(filter_id: int) -> None:
    KeywordFilter.delete().where(KeywordFilter.id == filter_id).execute()


# --- read markers -----------------------------------------------------------


def _expand_album_siblings(channel_id: int, message_id: int) -> list[int]:
    """All raw message ids belonging to the same display unit as (channel_id, message_id).

    A display unit collapses an album (rows sharing ``grouped_id``) under its primary id,
    but unread counts and the unread filter operate per raw row — so marking a unit read
    must touch every sibling, not just the primary. Falls back to the id itself when the
    message is not (or no longer) in telememo's cache.
    """
    cur = tdb.db.execute_sql(
        'SELECT sib.id FROM messages tgt '
        'JOIN messages sib ON sib.channel_id = tgt.channel_id '
        '  AND (sib.id = tgt.id OR (tgt.grouped_id IS NOT NULL AND sib.grouped_id = tgt.grouped_id)) '
        'WHERE tgt.channel_id = ? AND tgt.id = ?',
        (channel_id, message_id),
    )
    sibs = [row[0] for row in cur.fetchall()]
    return sibs or [message_id]


def mark_read(items: list[ItemKey]) -> int:
    """Mark item keys as read; idempotent. Returns count of rows touched.

    Telegram keys are expanded to their album siblings so an album clears its
    unread count fully; other sources are written as-is.
    """
    if not items:
        return 0
    triples: set[tuple[str, int, int]] = set()
    for k in items:
        if k.source == 'telegram':
            triples.update(('telegram', k.ref1, sib) for sib in _expand_album_siblings(k.ref1, k.ref2))
        else:
            triples.add(k.triple)
    rows = [{'source': s, 'ref1': r1, 'ref2': r2, 'read_at': _now()} for s, r1, r2 in triples]
    with tdb.db.atomic():
        ReadItem.insert_many(rows).on_conflict_ignore().execute()
    return len(rows)


def mark_read_bulk(
    channel_id: Optional[int],
    before_date: Optional[str],
    source: Optional[str] = None,
    feed: Optional[str] = None,
) -> None:
    """Mark every subscribed, unfiltered item before a date (optionally one TG channel) as read.

    The aggregate form (no channel_id) covers every source: HN stories are included
    when an enabled HN subscription exists (all archived rows — hidden ranks don't
    affect visible counts and marking them keeps a later display-mode widening quiet).
    `source` narrows the sweep to one source (the source-scoped timeline views),
    `feed` narrows it further within a multi-feed source (X feed key / RSS feed
    URL); `channel_id` already implies telegram. X's For You only joins the sweep
    when the caller is X-scoped — it is invisible in the aggregate view, so
    clearing it from there would silently burn a feed the user never saw.
    """
    if source is None or source == 'telegram':
        where = ['m.is_filtered IS NOT 1']
        params: list = []
        if channel_id is not None:
            where.append('m.channel_id = ?')
            params.append(channel_id)
        if before_date:
            where.append('substr(m.date, 1, 10) < ?')
            params.append(before_date)
        sql = (
            'INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) '
            "SELECT 'telegram', m.channel_id, m.id, ? FROM messages m "
            "JOIN subscriptions s ON s.source = 'telegram' AND s.channel_id = m.channel_id AND s.enabled = 1 "
            'WHERE ' + ' AND '.join(where)
        )
        tdb.db.execute_sql(sql, (_now().isoformat(sep=' '), *params))

    if channel_id is None and source in (None, 'hn') and hn_sampling_active():
        # Admitted stories only (v14). Before the admission stamp this swept the
        # whole archive, on the grounds that a below-cut story was invisible anyway
        # and marking it kept a later display-mode widening quiet. That inverts
        # under one-way admission: an unadmitted story is not below a cut, it is
        # *not here yet*, and burning it now would land it at the head of the
        # timeline already read — exactly the arrival the stamp exists to make
        # visible. Same rule as X's bulk_read_scope: burn what the view showed.
        hn_where = ['h.is_dead = 0', 'h.qualified_at IS NOT NULL']
        hn_params: list = []
        if before_date:
            hn_where.append('substr(h.qualified_at, 1, 10) < ?')
            hn_params.append(before_date)
        tdb.db.execute_sql(
            'INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) '
            "SELECT 'hn', h.id, 0, ? FROM hn_stories h WHERE " + ' AND '.join(hn_where),
            (_now().isoformat(sep=' '), *hn_params),
        )

    if channel_id is None and source in (None, 'x'):
        _mark_x_read_bulk(before_date, feed, include_foryou=source == 'x')

    if channel_id is None and source in (None, 'rss'):
        _mark_rss_read_bulk(before_date, feed if source == 'rss' else None)


def _mark_rss_read_bulk(before_date: Optional[str], feed: Optional[str]) -> None:
    # deferred, for the same reason as X's: the sort key and the "what did the view
    # show" rule live with the provider, so the sweep burns exactly those rows.
    from .sources.rss import bulk_read_scope

    where, params = bulk_read_scope(before_date)
    if feed:
        where += ' AND e.feed_url = ?'
        params.append(feed)
    tdb.db.execute_sql(
        "INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) SELECT 'rss', e.id, 0, ? "
        'FROM rss_entries e JOIN subscriptions s ON s.channel_id = e.feed_url WHERE ' + where,
        (_now().isoformat(sep=' '), *params),
    )


def _mark_x_read_bulk(before_date: Optional[str], feed: Optional[str], include_foryou: bool) -> None:
    # deferred: condenser.sources.x imports this module (the scope, the admission
    # rule and the SQL sort key all live with the provider, so the sweep burns
    # exactly the rows the timeline showed — and no others)
    from .sources.x import SORT_AT_SQL, bulk_read_scope

    feeds, params, where = bulk_read_scope(feed, include_foryou)
    if not feeds:
        return
    if before_date:
        where.append(f'substr({SORT_AT_SQL}, 1, 10) < ?')
        params.append(before_date)
    tdb.db.execute_sql(
        "INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) SELECT 'x', f.tweet_id, 0, ? "
        'FROM x_feed_items f JOIN x_tweets t ON t.id = f.tweet_id WHERE ' + ' AND '.join(where),
        (_now().isoformat(sep=' '), *params),
    )


def is_item_read(source: str, ref1: int, ref2: int = 0) -> bool:
    return (
        ReadItem.select()
        .where((ReadItem.source == source) & (ReadItem.ref1 == ref1) & (ReadItem.ref2 == ref2))
        .exists()
    )


# --- hidden items -------------------------------------------------------------


def _hide_triples(k: ItemKey) -> list[tuple[str, int, int]]:
    """A key's stored triples: Telegram expands to the album's raw sibling rows so
    hide/unhide always cover the whole display unit (mirrors mark_read)."""
    if k.source == 'telegram':
        return [('telegram', k.ref1, sib) for sib in _expand_album_siblings(k.ref1, k.ref2)]
    return [k.triple]


def hide_item(k: ItemKey) -> int:
    """Hide one item from every timeline surface; idempotent. Returns rows written."""
    rows = [{'source': s, 'ref1': r1, 'ref2': r2, 'hidden_at': _now()} for s, r1, r2 in _hide_triples(k)]
    with tdb.db.atomic():
        HiddenItem.insert_many(rows).on_conflict_ignore().execute()
    return len(rows)


def unhide_item(k: ItemKey) -> None:
    for s, r1, r2 in _hide_triples(k):
        HiddenItem.delete().where(
            (HiddenItem.source == s) & (HiddenItem.ref1 == r1) & (HiddenItem.ref2 == r2)
        ).execute()


# --- item feedback (explicit up/down; Phase 4's training signal) --------------

FEEDBACK_VERDICTS = ('up', 'down')

# The down-chip taxonomy (v9). Each value is aimed at a different channel of the
# planned multi-channel model: 'topic' at the dense-kNN neighbourhood, 'promo' /
# 'ai_slop' / 'engagement_farming' at the style/wording channels, 'author' at the
# author prior. Closed on purpose — free text could not be used as a feature
# without another labeling pass.
#
# 'engagement_farming' (2026-07-27) is X's own platform-manipulation term for the
# influencer-thread pattern: a hook, some FOMO, "save this 🔖", and the payoff
# parked in the replies so an outbound link does not cost reach. It is deliberately
# NOT folded into 'promo': promo is about selling a thing (intent), this is about
# baiting interaction (largely lexical, so the cheap n-gram channel can learn it
# outright). Folding them together would make a tweet that sells nothing but games
# everything indistinguishable from an advertisement, and the reader would have to
# hesitate over which chip to press — a taxonomy you hesitate over yields noisy
# labels, which is the one thing a training set cannot recover from.
FEEDBACK_REASONS = ('topic', 'promo', 'ai_slop', 'engagement_farming', 'author')


def set_feedback(k: ItemKey, verdict: str, reason: Optional[str] = None) -> None:
    """Label an item up or down; one row per item, so switching sides is a correction.

    A call states the **whole** label, reason included: the chip arrives as a second
    call right after the thumb, and an omitted reason means "no reason", not "keep
    the old one". That is what makes a down→up correction drop the stale attribute
    instead of carrying 'ai_slop' over onto a positive.

    Source-generic by table design (X in v1, HN whenever its UI grows buttons).
    Unlike read/hide markers this is NOT album-expanded: a label belongs to the
    display unit the user actually judged, and only X — which has no albums —
    writes it today.
    """
    now = _now()
    ItemFeedback.insert(
        source=k.source, ref1=k.ref1, ref2=k.ref2, verdict=verdict, reason=reason, created_at=now
    ).on_conflict(
        conflict_target=[ItemFeedback.source, ItemFeedback.ref1, ItemFeedback.ref2],
        update={ItemFeedback.verdict: verdict, ItemFeedback.reason: reason, ItemFeedback.created_at: now},
    ).execute()


def clear_feedback(k: ItemKey) -> None:
    """Remove an item's label (the undo click); idempotent."""
    ItemFeedback.delete().where(
        (ItemFeedback.source == k.source) & (ItemFeedback.ref1 == k.ref1) & (ItemFeedback.ref2 == k.ref2)
    ).execute()


def get_feedback(source: str, ref1: int, ref2: int = 0) -> tuple[Optional[str], Optional[str]]:
    """The item's label as the pair it is since v9: ``(verdict, reason)``.

    Returns both halves rather than the verdict alone so a caller cannot silently
    read a label that has lost its attribution.
    """
    row = ItemFeedback.get_or_none(
        (ItemFeedback.source == source) & (ItemFeedback.ref1 == ref1) & (ItemFeedback.ref2 == ref2)
    )
    return (row.verdict, row.reason) if row else (None, None)


# --- saved items (user assets, source-decoupled) -----------------------------


def add_saved_item(source: str, ref1: int, ref2: int, raw_data: dict) -> None:
    SavedItem.insert(
        source=source, ref1=ref1, ref2=ref2, raw_data=json.dumps(raw_data), created_at=_now()
    ).on_conflict_ignore().execute()


def delete_saved_item(source: str, ref1: int, ref2: int = 0) -> None:
    SavedItem.delete().where(
        (SavedItem.source == source) & (SavedItem.ref1 == ref1) & (SavedItem.ref2 == ref2)
    ).execute()


def list_saved_items() -> list[SavedItem]:
    return list(SavedItem.select().order_by(SavedItem.created_at.desc()))


# --- devices (client bearer tokens) ------------------------------------------

# Skip the last_seen_at write when the previous one is this recent, so the hot
# request path doesn't hit SQLite on every call.
DEVICE_SEEN_THROTTLE_SECONDS = 3600


def create_device(name: str, token_hash: str) -> Device:
    return Device.create(name=name, token_hash=token_hash, created_at=_now_naive())


def get_device_by_token_hash(token_hash: str) -> Optional[Device]:
    return Device.get_or_none(Device.token_hash == token_hash)


def list_devices() -> list[Device]:
    return list(Device.select().order_by(Device.created_at.desc()))


def delete_device(device_id: int) -> int:
    """Revoke a device; returns rows deleted (0 = unknown id)."""
    return Device.delete().where(Device.id == device_id).execute()


def touch_device_last_seen(device: Device) -> None:
    now = _now_naive()
    last = device.last_seen_at
    if last is not None and (now - last).total_seconds() < DEVICE_SEEN_THROTTLE_SECONDS:
        return
    Device.update(last_seen_at=now).where(Device.id == device.id).execute()


# --- app_meta ---------------------------------------------------------------


def get_meta(key: str) -> Optional[str]:
    row = AppMeta.get_or_none(AppMeta.key == key)
    return row.value if row else None


def set_meta(key: str, value: str) -> None:
    AppMeta.insert(key=key, value=value).on_conflict(
        conflict_target=[AppMeta.key], update={AppMeta.value: value}
    ).execute()


def effective_backfill_days(env_default: int) -> int:
    """Resolve the backfill window: an app_meta runtime override wins over the env default.

    ``CONDENSER_BACKFILL_DAYS`` sets the baseline, but the value can be tuned at runtime
    (via ``PATCH /api/app/meta``) without a restart. A malformed/absent override falls
    back to the env default.
    """
    raw = get_meta('backfill_days')
    if raw is None:
        return env_default
    try:
        days = int(raw)
    except ValueError:
        return env_default
    return days if days > 0 else env_default


def get_languages() -> list[str]:
    """The global language whitelist (app_meta ``languages``, a JSON array).

    Deliberately a generic key with no ``x_`` prefix: it is the reader's language
    preference, not an X setting — today only the For You ingest filter reads it,
    but any source can. Empty/missing/malformed all mean "not set", which every
    consumer must treat as "do not filter" (fail-open).
    """
    raw = get_meta('languages')
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return [code for code in parsed if isinstance(code, str)] if isinstance(parsed, list) else []


# --- hn stories (front-page archive) -----------------------------------------


def get_hn_story(story_id: int) -> Optional[HNStory]:
    return HNStory.get_or_none(HNStory.id == story_id)


def existing_hn_story_ids(story_ids: list[int]) -> set[int]:
    if not story_ids:
        return set()
    return {s.id for s in HNStory.select(HNStory.id).where(HNStory.id.in_(story_ids))}


def insert_hn_story(**fields) -> None:
    """Insert a story if unseen; an existing row is left untouched (first_seen_at is sticky)."""
    HNStory.insert(**fields).on_conflict_ignore().execute()


def update_hn_snapshot(story_id: int, score: int, comments_count: int, updated_at: datetime) -> None:
    HNStory.update(score=score, comments_count=comments_count, score_updated_at=updated_at).where(
        HNStory.id == story_id
    ).execute()


def update_hn_peak_rank(story_id: int, rank: int) -> None:
    """Keep the best (lowest) observed front-page position."""
    HNStory.update(peak_rank=rank).where(
        (HNStory.id == story_id) & ((HNStory.peak_rank.is_null()) | (HNStory.peak_rank > rank))
    ).execute()


def mark_hn_story_dead(story_id: int) -> None:
    """Flag a story HN itself killed. The row stays (the archive is append-only),
    but its search document goes: the timeline's ranking excludes dead stories, so
    leaving it findable would make search the one surface that still offers it."""
    HNStory.update(is_dead=True).where(HNStory.id == story_id).execute()
    search.delete_item('hn', story_id)


def hn_stories_to_refresh(first_seen_after: datetime) -> list[HNStory]:
    """Live stories still inside the snapshot-refresh window."""
    return list(
        HNStory.select().where(
            (HNStory.first_seen_at >= first_seen_after) & (HNStory.is_dead == False)  # noqa: E712
        )
    )


def hn_stories_needing_preview(limit: int, max_attempts: int) -> list[HNStory]:
    """Linkable live stories without a stored preview, newest first (the prefetch queue)."""
    return list(
        HNStory.select()
        .where(
            HNStory.url.is_null(False)
            & (HNStory.is_dead == False)  # noqa: E712
            & HNStory.preview.is_null()
            & (HNStory.preview_attempts < max_attempts)
        )
        .order_by(HNStory.first_seen_at.desc())
        .limit(limit)
    )


def set_hn_preview(story_id: int, preview_json: str) -> None:
    HNStory.update(preview=preview_json).where(HNStory.id == story_id).execute()


def bump_hn_preview_attempts(story_id: int) -> None:
    HNStory.update(preview_attempts=HNStory.preview_attempts + 1).where(HNStory.id == story_id).execute()


def hn_story_counts(today: str) -> tuple[int, int]:
    """(total archived stories, stories first seen on ``today``)."""
    total = HNStory.select().count()
    today_count = HNStory.select().where(HNStory.day == today).count()
    return total, today_count


# --- hn admission (v14): the polling-time judge's SQL -------------------------
#
# Everything below writes or reads ``qualified_at`` / ``qualified_rank``. The
# *policy* (which floors, how big today's budget is) lives in sources/hn.py with
# the config it reads; this is only the storage side, per the module's convention
# that all SQL lives here.


def hn_qualified_count(day: str) -> int:
    """How many stories have been admitted on ``day`` (a UTC date string).

    Counts by *admission* day, not archive day: a story first seen at 23:50 and
    admitted at 02:00 spends the second day's budget, which is what keeps the
    budget line monotone (plan §5.4a).
    """
    cur = tdb.db.execute_sql('SELECT COUNT(*) FROM hn_stories WHERE substr(qualified_at, 1, 10) = ?', (day,))
    return cur.fetchone()[0]


def hn_qualification_candidates(
    min_score: int,
    max_peak_rank: int,
    first_seen_after: datetime,
    limit: Optional[int],
) -> list[HNStory]:
    """Unadmitted stories eligible for a stamp, best score first.

    ``first_seen_after`` is the refresh window's own cutoff, deliberately the same
    constant: past it we stop pulling scores, so a story can no longer *earn* its
    way in — only a freed-up slot could let it in, and stamping a three-day-old
    story with today's timestamp would drop it at the top of the timeline
    (plan §5.4b).
    """
    where = HNStory.qualified_at.is_null() & (HNStory.is_dead == False) & (HNStory.first_seen_at >= first_seen_after)  # noqa: E712
    if min_score > 0:
        where &= HNStory.score >= min_score
    if max_peak_rank > 0:
        where &= HNStory.peak_rank.is_null() | (HNStory.peak_rank <= max_peak_rank)
    query = HNStory.select().where(where).order_by(HNStory.score.desc(), HNStory.id.asc())
    if limit is not None:
        query = query.limit(limit)
    return list(query)


def stamp_hn_qualified(story_id: int, at: datetime, rank: int) -> None:
    """Admit one story. Guarded by ``qualified_at IS NULL`` because admission is
    one-way — a second stamp would move an item the reader may already have read."""
    HNStory.update(qualified_at=at, qualified_rank=rank).where(
        (HNStory.id == story_id) & HNStory.qualified_at.is_null()
    ).execute()


def hn_daily_archive_counts(days: int, before_day: str) -> list[int]:
    """Archived-story counts for the ``days`` most recent complete days before
    ``before_day`` — the population 'half' mode takes its rate from."""
    cur = tdb.db.execute_sql(
        'SELECT COUNT(*) FROM hn_stories WHERE day < ? GROUP BY day ORDER BY day DESC LIMIT ?',
        (before_day, days),
    )
    return [row[0] for row in cur.fetchall()]


# The pre-v14 read rule, kept for one purpose: replaying what the timeline *did*
# show, so history can be stamped where it already sat. Not a general ranking
# helper — see the warning on _migrate_hn_qualified_v14.
_LEGACY_RANKED = """
    SELECT h.id, h.day, h.first_seen_at, h.score, h.peak_rank, h.qualified_at,
           ROW_NUMBER() OVER (PARTITION BY h.day ORDER BY h.score DESC, h.id ASC) AS day_rank,
           COUNT(*) OVER (PARTITION BY h.day) AS day_total
    FROM hn_stories h
    WHERE h.is_dead = 0
"""


def stamp_hn_history(cfg, quota: Optional[int], day: Optional[str] = None) -> int:
    """Stamp a historical day (or the whole archive) at each story's own ``first_seen_at``.

    Two callers, one meaning — *these stories belong where they already are*: the
    v14 backfill, and the hckrnews import, which hands us days that closed before
    we were watching. A live round never uses this; it stamps at ``now``, so a
    newly admitted story lands at the head of the timeline.

    ``quota`` is the day's fixed capacity (None for 'all'/'half', whose own rank
    predicate already caps them). Already-stamped rows are skipped *and* count
    against it, so re-importing a day the sampler was already watching — which
    happens to every new subscriber on their third day — tops the day up instead
    of doubling it. Returns the number stamped.
    """
    where = ['r.qualified_at IS NULL', _legacy_mode_where(cfg.mode, quota)[0]]
    params = list(_legacy_mode_where(cfg.mode, quota)[1])
    if cfg.min_score > 0:
        where.append('r.score >= ?')
        params.append(cfg.min_score)
    if cfg.max_peak_rank > 0:
        where.append('(r.peak_rank IS NULL OR r.peak_rank <= ?)')
        params.append(cfg.max_peak_rank)
    if day is not None:
        where.append('r.day = ?')
        params.append(day)
    cur = tdb.db.execute_sql(
        f'SELECT r.id, r.day, r.first_seen_at, r.day_rank FROM ({_LEGACY_RANKED}) r '
        f'WHERE {" AND ".join(where)} ORDER BY r.day, r.day_rank',
        tuple(params),
    )
    taken: dict[str, int] = {}
    stamped = 0
    for story_id, story_day, first_seen_at, day_rank in cur.fetchall():
        if quota is not None:
            if story_day not in taken:
                taken[story_day] = hn_qualified_count(story_day)
            if taken[story_day] >= quota:
                continue
            taken[story_day] += 1
        stamp_hn_qualified(story_id, first_seen_at, day_rank)
        stamped += 1
    return stamped


def _legacy_mode_where(mode: str, quota: Optional[int]) -> tuple[str, list]:
    if mode == 'half':
        return 'r.day_rank * 2 <= r.day_total + 1', []
    if quota is None:  # 'all'
        return '1 = 1', []
    return 'r.day_rank <= ?', [quota]


# --- subscriptions (x / twitter) ---------------------------------------------

_X = Subscription.source == 'x'


def list_x_subscriptions() -> list[Subscription]:
    return list(Subscription.select().where(_X).order_by(Subscription.added_at.desc()))


def get_x_subscription(channel_id: str) -> Optional[Subscription]:
    return Subscription.get_or_none(_X & (Subscription.channel_id == channel_id))


def add_x_subscription(channel_id: str, name: Optional[str], config: dict) -> tuple[Subscription, bool]:
    """Subscribe-and-enable; a paused row is re-enabled (POST semantics, same as HN).
    Returns ``(sub, created)``."""
    sub, created = Subscription.get_or_create(
        source='x',
        channel_id=channel_id,
        defaults={
            'enabled': True,
            'backfill_done': False,
            'added_at': _now(),
            'name': name,
            'config': json.dumps(config),
        },
    )
    if not created and not sub.enabled:
        Subscription.update(enabled=True).where(_X & (Subscription.channel_id == channel_id)).execute()
        sub.enabled = True
    return sub, created


def update_x_subscription(
    channel_id: str,
    enabled: Optional[bool] = None,
    config: Optional[dict] = None,
    name: Optional[str] = None,
) -> None:
    fields = {}
    if enabled is not None:
        fields[Subscription.enabled] = enabled
    if config is not None:
        fields[Subscription.config] = json.dumps(config)
    if name is not None:
        fields[Subscription.name] = name
    if fields:
        Subscription.update(fields).where(_X & (Subscription.channel_id == channel_id)).execute()


def delete_x_subscription(channel_id: str) -> None:
    Subscription.delete().where(_X & (Subscription.channel_id == channel_id)).execute()


def enabled_x_subscriptions() -> list[Subscription]:
    return list(
        Subscription.select().where(_X & (Subscription.enabled == True)).order_by(Subscription.added_at)  # noqa: E712
    )


def enabled_x_feeds(feed: Optional[str] = None) -> list[str]:
    """Enabled X feed keys, optionally narrowed to one (empty = nothing to read).

    Which of them the *aggregate* timeline admits is a per-feed setting the user
    can change, so that rule lives with the provider (``sources/x.py:scope``) and
    not here — this used to hardcode "everything except For You".
    """
    ids = [s.channel_id for s in enabled_x_subscriptions()]
    if feed is not None:
        return [c for c in ids if c == feed]
    return ids


# --- x tweets + feed items ----------------------------------------------------


def get_x_tweet(tweet_id: int) -> Optional[XTweet]:
    return XTweet.get_or_none(XTweet.id == tweet_id)


def existing_x_tweet_ids(tweet_ids: list[int]) -> set[int]:
    if not tweet_ids:
        return set()
    return {t.id for t in XTweet.select(XTweet.id).where(XTweet.id.in_(tweet_ids))}


def upsert_x_tweet(fields: dict) -> None:
    """Store a tweet from a full feed entry, refreshing an existing row (metrics move)."""
    XTweet.insert(**fields).on_conflict(
        conflict_target=[XTweet.id],
        update={getattr(XTweet, k): v for k, v in fields.items() if k != 'id'},
    ).execute()


def insert_x_tweet_if_absent(fields: dict) -> None:
    """Store a tweet seen only as an embedded payload (a quoted tweet).

    Embedded copies are depth-limited and can be poorer than a row we already have
    from the feed itself, so an existing row is never overwritten.
    """
    XTweet.insert(**fields).on_conflict_ignore().execute()


def existing_x_feed_item_ids(channel_id: str, tweet_ids: list[int]) -> set[int]:
    if not tweet_ids:
        return set()
    return {
        i.tweet_id
        for i in XFeedItem.select(XFeedItem.tweet_id).where(
            (XFeedItem.channel_id == channel_id) & (XFeedItem.tweet_id.in_(tweet_ids))
        )
    }


def insert_x_feed_items(rows: list[dict]) -> None:
    """Register tweets in a feed; existing rows keep their (sticky) first_seen_at."""
    if not rows:
        return
    with tdb.db.atomic():
        XFeedItem.insert_many(rows).on_conflict_ignore().execute()


def x_counts() -> tuple[int, int]:
    """(archived tweets, feed appearances)."""
    return XTweet.select().count(), XFeedItem.select().count()


def x_feed_item_count(channel_id: str) -> int:
    return XFeedItem.select().where(XFeedItem.channel_id == channel_id).count()


# --- x followed accounts (v11) ------------------------------------------------

# When the last follow-list sync happened. Deliberately *not* derived from
# max(synced_at): a sync that produced zero rows is still a sync, and reading the
# rows would make an empty list look permanently stale and re-crawl every round.
FOLLOWING_SYNCED_META_KEY = 'x_following_synced_at'


def replace_x_following(rows: list[dict], synced_at: datetime) -> int:
    """Swap the whole follow list for this one, in one transaction.

    Full replacement rather than a merge because the point of the list is who you
    follow *now* — an account you unfollowed has to disappear, and no incremental
    update can express a deletion the probe never mentions.
    """
    with tdb.db.atomic():
        XFollowing.delete().execute()
        if rows:
            XFollowing.insert_many([{**r, 'synced_at': synced_at} for r in rows]).execute()
        set_meta(FOLLOWING_SYNCED_META_KEY, synced_at.isoformat(sep=' ', timespec='seconds'))
    return len(rows)


def x_following_handles() -> set[str]:
    return {row.handle for row in XFollowing.select(XFollowing.handle)}


def x_following_user(handle: str) -> Optional[XFollowing]:
    return XFollowing.get_or_none(XFollowing.handle == handle)


def x_following_count() -> int:
    return XFollowing.select().count()


def x_following_synced_at() -> Optional[datetime]:
    raw = get_meta(FOLLOWING_SYNCED_META_KEY)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# --- x embeddings + verdicts (v8) --------------------------------------------


def x_labeled_samples() -> dict[int, str]:
    """The training set: tweet_id -> 'up' | 'down' | 'save'.

    Read live from the label tables rather than copied anywhere, so un-saving or
    undoing a thumb removes the sample with no synchronization code. A save
    outranks an up on the same tweet (it is the stronger positive); a tweet that
    is both saved and downvoted is contradictory and teaches nothing, so it is
    dropped from both sides instead of letting a tie-break pick a direction.
    """
    labels = {row.ref1: row.verdict for row in ItemFeedback.select().where(ItemFeedback.source == 'x')}
    saved = {row.ref1 for row in SavedItem.select(SavedItem.ref1).where(SavedItem.source == 'x')}
    samples = {tid: verdict for tid, verdict in labels.items() if not (verdict == 'down' and tid in saved)}
    samples.update({tid: 'save' for tid in saved if labels.get(tid) != 'down'})
    return samples


def x_down_reasons() -> dict[int, str]:
    """tweet_id -> the down's chip, for downs that carry one.

    Channel C's routing input: the chip says *which attribute* earned the down,
    and ``attributes.fit_flags`` charges that attribute instead of the whole bag.
    Pre-chip downs (before 2026-07-26) are absent, which is the honest reading —
    they were bag-level labels and stay that way.
    """
    query = ItemFeedback.select(ItemFeedback.ref1, ItemFeedback.reason).where(
        (ItemFeedback.source == 'x') & (ItemFeedback.verdict == 'down') & ItemFeedback.reason.is_null(False)
    )
    return {row.ref1: row.reason for row in query}


def x_embedding_ids(tweet_ids: Optional[set[int]] = None, model: Optional[str] = None) -> set[int]:
    """Which of these tweets already have a stored vector (optionally: for this model)."""
    query = XEmbedding.select(XEmbedding.tweet_id)
    if tweet_ids is not None:
        if not tweet_ids:
            return set()
        query = query.where(XEmbedding.tweet_id.in_(list(tweet_ids)))
    if model is not None:
        query = query.where(XEmbedding.model == model)
    return {row.tweet_id for row in query}


def x_author_handles(tweet_ids: set[int]) -> dict[int, str]:
    """tweet_id -> author handle, for rendering verdict evidence readably."""
    if not tweet_ids:
        return {}
    rows = XTweet.select(XTweet.id, XTweet.author_handle).where(XTweet.id.in_(list(tweet_ids)))
    return {row.id: row.author_handle for row in rows if row.author_handle}


def x_embedding_vectors(tweet_ids: set[int], model: str) -> dict[int, bytes]:
    if not tweet_ids:
        return {}
    rows = XEmbedding.select().where((XEmbedding.tweet_id.in_(list(tweet_ids))) & (XEmbedding.model == model))
    return {row.tweet_id: row.vector for row in rows}


def upsert_x_embedding(tweet_id: int, vector: bytes, model: str, created_at: datetime) -> None:
    XEmbedding.insert(tweet_id=tweet_id, vector=vector, model=model, created_at=created_at).on_conflict(
        conflict_target=[XEmbedding.tweet_id],
        update={XEmbedding.vector: vector, XEmbedding.model: model, XEmbedding.created_at: created_at},
    ).execute()


def prune_x_embeddings(before: datetime, keep_ids: set[int]) -> int:
    """Drop unlabeled vectors older than ``before``; the training set is exempt."""
    query = XEmbedding.delete().where(XEmbedding.created_at < before.strftime('%Y-%m-%d %H:%M:%S'))
    if keep_ids:
        query = query.where(XEmbedding.tweet_id.not_in(list(keep_ids)))
    return query.execute()


# The columns the judge needs to build a tweet's text: the body, plus what bird
# flattened away (a retweet's prefix, an article's title/preview, a quoted tweet).
_JUDGE_COLS = (
    'SELECT t.id AS tweet_id, t.text AS text, t.rt_of_handle AS rt_of_handle, '
    't.article AS article, q.text AS quote_text '
    'FROM x_tweets t LEFT JOIN x_tweets q ON q.id = t.quote_of '
)


def _rows(cur) -> list[dict]:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def x_tweet_judge_rows(tweet_ids: list[int]) -> list[dict]:
    """Judge-text columns for specific tweets (used to embed labeled tweets)."""
    if not tweet_ids:
        return []
    placeholders = ','.join('?' for _ in tweet_ids)
    return _rows(tdb.db.execute_sql(f'{_JUDGE_COLS} WHERE t.id IN ({placeholders})', tuple(tweet_ids)))


def x_pending_verdict_rows(since: datetime, limit: int) -> list[dict]:
    """Unjudged, unlabeled For You appearances inside the judging window, newest first.

    Only For You: a followed account is a choice you already made, and an algorithm
    second-guessing it would just add noise.

    Already-labeled tweets are excluded as well. They are in the KNN index, so they
    would match themselves at distance 0 and the "verdict" would just be the label
    read back — a circular answer on the one item that needs no answer at all.
    """
    return _rows(
        tdb.db.execute_sql(
            'SELECT f.channel_id AS channel_id, f.tweet_id AS tweet_id, t.text AS text, '
            't.author_handle AS author_handle, '
            't.rt_of_handle AS rt_of_handle, t.article AS article, q.text AS quote_text '
            'FROM x_feed_items f JOIN x_tweets t ON t.id = f.tweet_id '
            'LEFT JOIN x_tweets q ON q.id = t.quote_of '
            'WHERE f.channel_id = ? AND f.verdict IS NULL AND f.first_seen_at >= ? '
            "AND NOT EXISTS (SELECT 1 FROM item_feedback fb WHERE fb.source = 'x' AND fb.ref1 = f.tweet_id) "
            "AND NOT EXISTS (SELECT 1 FROM saved_items si WHERE si.source = 'x' AND si.ref1 = f.tweet_id) "
            'ORDER BY f.first_seen_at DESC LIMIT ?',
            (FORYOU_FEED, since.strftime('%Y-%m-%d %H:%M:%S'), limit),
        )
    )


def set_x_verdict(channel_id: str, tweet_id: int, verdict: str, meta: dict) -> None:
    XFeedItem.update(verdict=verdict, verdict_meta=json.dumps(meta, ensure_ascii=False)).where(
        (XFeedItem.channel_id == channel_id) & (XFeedItem.tweet_id == tweet_id)
    ).execute()


# --- x attributes (v10) -------------------------------------------------------


def x_attribute_ids(model: str) -> set[int]:
    """Tweets already described under this model@taxonomy (others need re-reading)."""
    return {row.tweet_id for row in XAttribute.select(XAttribute.tweet_id).where(XAttribute.model == model)}


def x_attributes_for(tweet_ids: set[int], model: str) -> dict[int, list[str]]:
    """tweet_id -> style flags, for the tweets described under this model@taxonomy."""
    if not tweet_ids:
        return {}
    rows = XAttribute.select().where((XAttribute.tweet_id.in_(list(tweet_ids))) & (XAttribute.model == model))
    return {row.tweet_id: json.loads(row.style_flags) for row in rows}


def x_attribute_count(model: Optional[str] = None) -> int:
    query = XAttribute.select()
    return (query.where(XAttribute.model == model) if model else query).count()


def upsert_x_attributes(tweet_id: int, topics: list, style_flags: list, model: str, created_at: datetime) -> None:
    fields = {
        'topics': json.dumps(topics, ensure_ascii=False),
        'style_flags': json.dumps(style_flags),
        'model': model,
        'created_at': created_at,
    }
    XAttribute.insert(tweet_id=tweet_id, **fields).on_conflict(
        conflict_target=[XAttribute.tweet_id],
        update={getattr(XAttribute, key): value for key, value in fields.items()},
    ).execute()


def x_describable_rows(since: datetime, limit: int, model: str) -> list[dict]:
    """Tweets worth describing, labeled ones first.

    A labeled tweet is training data for the attribute channel, so it is worth
    paying for before any unlabeled one — and there is a fixed backlog of them,
    while unlabeled For You tweets arrive forever. Inside each group, newest first.
    """
    return _rows(
        tdb.db.execute_sql(
            f'{_JUDGE_COLS} '
            'LEFT JOIN x_attributes a ON a.tweet_id = t.id AND a.model = ? '
            "LEFT JOIN item_feedback fb ON fb.source = 'x' AND fb.ref1 = t.id "
            "LEFT JOIN saved_items si ON si.source = 'x' AND si.ref1 = t.id "
            'LEFT JOIN x_feed_items f ON f.tweet_id = t.id AND f.channel_id = ? '
            'WHERE a.tweet_id IS NULL AND t.text IS NOT NULL '
            '  AND (fb.ref1 IS NOT NULL OR si.ref1 IS NOT NULL OR f.first_seen_at >= ?) '
            'ORDER BY (fb.ref1 IS NOT NULL OR si.ref1 IS NOT NULL) DESC, '
            '  COALESCE(f.first_seen_at, t.created_at) DESC LIMIT ?',
            (model, FORYOU_FEED, since.strftime('%Y-%m-%d %H:%M:%S'), limit),
        )
    )


def x_verdict_counts() -> dict[str, int]:
    cur = tdb.db.execute_sql('SELECT verdict, COUNT(*) FROM x_feed_items WHERE verdict IS NOT NULL GROUP BY verdict')
    counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    counts.update({row[0]: row[1] for row in cur.fetchall()})
    return counts


def x_prospective_rows() -> list[dict]:
    """For You rows carrying both a verdict and a label — the out-of-sample set.

    No timestamp comparison, because none is needed: ``x_pending_verdict_rows``
    never judges an already-labeled tweet, so a row with both was judged first and
    labeled afterwards. That structural fact is why there is no ``verdict_at``
    column and why these pairs are free of the leave-one-out backtest's selection
    bias — the reader labeled them without being asked to grade anything.
    """
    return _rows(
        tdb.db.execute_sql(
            'SELECT f.tweet_id AS tweet_id, f.verdict AS verdict, f.verdict_meta AS verdict_meta, '
            'f.first_seen_at AS first_seen_at, t.author_handle AS author_handle, t.text AS text, '
            'fb.verdict AS feedback, fb.reason AS reason, fb.created_at AS labeled_at, '
            'si.created_at AS saved_at '
            'FROM x_feed_items f '
            'LEFT JOIN x_tweets t ON t.id = f.tweet_id '
            "LEFT JOIN item_feedback fb ON fb.source = 'x' AND fb.ref1 = f.tweet_id "
            "LEFT JOIN saved_items si ON si.source = 'x' AND si.ref1 = f.tweet_id "
            'WHERE f.channel_id = ? AND f.verdict IS NOT NULL '
            'AND (fb.ref1 IS NOT NULL OR si.ref1 IS NOT NULL) '
            'ORDER BY f.first_seen_at',
            (FORYOU_FEED,),
        )
    )


def x_verdict_label_coverage() -> list[dict]:
    """Per verdict: how many were judged, read, and labeled at all.

    The denominator behind every prospective precision figure — a badge nobody
    ever read produces no evidence, and a channel is not being validated just
    because it has been running.
    """
    return _rows(
        tdb.db.execute_sql(
            'SELECT f.verdict AS verdict, COUNT(*) AS judged, '
            "SUM(EXISTS (SELECT 1 FROM read_items r WHERE r.source = 'x' AND r.ref1 = f.tweet_id)) AS read, "
            "SUM(EXISTS (SELECT 1 FROM item_feedback fb WHERE fb.source = 'x' AND fb.ref1 = f.tweet_id) "
            "  OR EXISTS (SELECT 1 FROM saved_items si WHERE si.source = 'x' AND si.ref1 = f.tweet_id)) AS labeled "
            'FROM x_feed_items f WHERE f.channel_id = ? AND f.verdict IS NOT NULL '
            'GROUP BY f.verdict ORDER BY f.verdict',
            (FORYOU_FEED,),
        )
    )


# --- subscriptions (rss) ------------------------------------------------------

_RSS = Subscription.source == 'rss'


def list_rss_subscriptions() -> list[Subscription]:
    return list(Subscription.select().where(_RSS).order_by(Subscription.added_at.desc()))


def get_rss_subscription(url: str) -> Optional[Subscription]:
    return Subscription.get_or_none(_RSS & (Subscription.channel_id == url))


def add_rss_subscription(
    url: str, name: Optional[str] = None, update_existing: bool = True
) -> tuple[Subscription, bool]:
    """Subscribe-and-enable, plus the feed's fetch-state row.

    On an existing row, ``update_existing`` decides whose gesture this is. A
    manual re-add (True) re-enables a paused feed and — since PATCH carries no
    ``name`` — a name sent with it is the rename path, and sticks
    (``_learn_feed_name`` never overwrites a non-NULL name). An OPML import
    (False) leaves existing rows entirely alone: a re-import must not reverse
    pause decisions or relabel feeds, it only picks up additions (2026-08-22).

    The two rows are created together because a subscription with no ``rss_feeds``
    row would poll with no validators and no place to record a failure. Returns
    ``(sub, created)`` — HN/X's POST semantics.
    """
    with tdb.db.atomic():
        sub, created = Subscription.get_or_create(
            source='rss',
            channel_id=url,
            defaults={'enabled': True, 'backfill_done': False, 'added_at': _now(), 'name': name},
        )
        if not created and update_existing:
            fields = {}
            if not sub.enabled:
                fields[Subscription.enabled] = True
                sub.enabled = True
            if name is not None and name != sub.name:
                fields[Subscription.name] = name
                sub.name = name
            if fields:
                Subscription.update(fields).where(_RSS & (Subscription.channel_id == url)).execute()
        RssFeed.insert(url=url).on_conflict_ignore().execute()
    return sub, created


def update_rss_subscription(
    url: str,
    enabled: Optional[bool] = None,
    config: Optional[dict] = None,
    name: Optional[str] = None,
) -> None:
    fields = {}
    if enabled is not None:
        fields[Subscription.enabled] = enabled
    if config is not None:
        fields[Subscription.config] = json.dumps(config)
    if name is not None:
        fields[Subscription.name] = name
    if fields:
        Subscription.update(fields).where(_RSS & (Subscription.channel_id == url)).execute()


def delete_rss_subscription(url: str) -> None:
    """Unsubscribe. Archived entries **and** the feed's fetch state are intentionally
    preserved (``delete_channel_messages``'s convention of naming what survives):
    the entries are the reader's history, and keeping the validators means a
    re-subscribe resumes instead of re-downloading a window it already has."""
    Subscription.delete().where(_RSS & (Subscription.channel_id == url)).execute()


def enabled_rss_subscriptions() -> list[Subscription]:
    return list(
        Subscription.select().where(_RSS & (Subscription.enabled == True)).order_by(Subscription.added_at)  # noqa: E712
    )


def rss_polling_active() -> bool:
    """Whether any enabled RSS subscription exists (the polling gate)."""
    return Subscription.select().where(_RSS & (Subscription.enabled == True)).exists()  # noqa: E712


# --- rss feeds + entries ------------------------------------------------------


def get_rss_feed(url: str) -> Optional[RssFeed]:
    return RssFeed.get_or_none(RssFeed.url == url)


def ensure_rss_feed(url: str) -> RssFeed:
    """The feed's fetch-state row, created if it is somehow missing.

    ``add_rss_subscription`` creates the pair atomically, so this only fires for a
    row deleted underneath us — but a poll round that cannot record its failure
    fails silently forever, which is the one outcome this source must not have.
    """
    RssFeed.insert(url=url).on_conflict_ignore().execute()
    return RssFeed.get(RssFeed.url == url)


def list_rss_feeds() -> list[RssFeed]:
    return list(RssFeed.select())


def record_rss_feed_success(
    url: str,
    at: datetime,
    title: Optional[str] = None,
    site_url: Optional[str] = None,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Record a round that reached the feed (200 or 304): validators, timestamp, and
    a cleared failure streak.

    ``note`` is a non-fatal complaint (malformed XML we still recovered entries
    from) — it lands in ``last_error`` so the row can show a warning badge, while
    ``error_count`` stays 0 because nothing needs retrying. NULL fields are left
    alone: a 304 carries no title and must not erase the one we learned.

    ``last_error`` obeys that same rule, which is why clearing it takes the empty
    string rather than None. The two are different statements: ``''`` is "I parsed
    a document and it was clean", None is "I have no opinion" — which is exactly a
    304, where there is no document to complain about. Writing None through erased
    the previous round's warning on every 304 and made the badge blink (2026-08-22).
    """
    fields: dict = {RssFeed.fetched_at: at, RssFeed.error_count: 0}
    for column, value in (
        (RssFeed.title, title),
        (RssFeed.site_url, site_url),
        (RssFeed.etag, etag),
        (RssFeed.last_modified, last_modified),
    ):
        if value is not None:
            fields[column] = value
    if note is not None:
        fields[RssFeed.last_error] = note or None  # '' clears; stored as NULL, not ''
    RssFeed.update(fields).where(RssFeed.url == url).execute()


def migrate_rss_feed_url(old: str, new: str) -> bool:
    """Move a feed to the URL it permanently redirects to. Returns whether it moved.

    The URL is this source's key in three places, so one transaction moves all three:
    ``rss_feeds.url`` (the PK), ``subscriptions.channel_id`` (half of a composite PK)
    and every archived entry's ``feed_url`` — the timeline joins entries to the
    subscription on exactly that, so a partial move would empty the feed's view. Read
    state, saved items and search documents key on the entry id and are untouched;
    a saved snapshot keeps the old URL it was taken with, which is what a snapshot is.

    Refuses when the target key is already taken — by a subscription, or by a feed row
    alone, which is what an unsubscribed-but-archived feed leaves behind (the archive
    outlives the subscription on purpose). Merging two archives is a decision, not a
    mechanic, and the reader is the one who should retire whichever copy they do not
    want. The refusal is written to ``last_error`` so it is visible on the row — a
    silent no-op would re-attempt every round with nothing to see — but not to
    ``error_count``: the fetch itself worked.
    """
    if old == new:
        return False
    with tdb.db.atomic():
        taken = RssFeed.select().where(RssFeed.url == new).exists() or (
            Subscription.select().where(_RSS & (Subscription.channel_id == new)).exists()
        )
        if taken:
            RssFeed.update(
                last_error=f'permanently redirects to {new}, which already has an archive here — retire one of the two'
            ).where(RssFeed.url == old).execute()
            return False
        RssFeed.update(url=new).where(RssFeed.url == old).execute()
        Subscription.update(channel_id=new).where(_RSS & (Subscription.channel_id == old)).execute()
        RssEntry.update(feed_url=new).where(RssEntry.feed_url == old).execute()
    return True


def record_rss_feed_error(url: str, error: str, at: datetime) -> None:
    """Count one failed round. ``fetched_at`` is deliberately not touched — it means
    "last time we actually saw this feed", which is what makes a stale feed visible."""
    RssFeed.update(last_error=error, error_count=RssFeed.error_count + 1).where(RssFeed.url == url).execute()


def existing_rss_guids(feed_url: str, guids: list[str]) -> set[str]:
    if not guids:
        return set()
    known: set[str] = set()
    for i in range(0, len(guids), 500):  # SQLite's bound-variable limit
        chunk = guids[i : i + 500]
        rows = RssEntry.select(RssEntry.guid).where((RssEntry.feed_url == feed_url) & (RssEntry.guid.in_(chunk)))
        known.update(row.guid for row in rows)
    return known


def insert_rss_entries(rows: list[dict], read_before: Optional[datetime], now: datetime) -> int:
    """Archive new entries and, in the same transaction, mark the old ones read.

    Callers pre-filter against ``existing_rss_guids``, so the return is the number
    archived; the unique index on ``(feed_url, guid)`` is the backstop and makes a
    re-run a no-op rather than a duplicate.

    ``read_before`` is the unread window's cutoff (None = mark nothing). Marking
    happens here rather than in a later pass because the two writes have to be one
    fact: an entry that is archived without its read marker is unread backlog on
    the reader's screen the moment the transaction commits.

    An entry with no ``published_at`` falls back to ``first_seen_at`` (= now),
    which is never before the cutoff — so a dateless feed's first fetch arrives
    entirely unread, window or no window. Accepted fail-open (2026-08-22): such
    feeds are rare, and the exposure is bounded by one feed document.
    """
    if not rows:
        return 0
    with tdb.db.atomic():
        # Chunked: one INSERT binds a parameter per column per row, and a first
        # fetch of an archive-style feed can carry hundreds of entries at once.
        for i in range(0, len(rows), 200):
            RssEntry.insert_many(rows[i : i + 200]).on_conflict_ignore().execute()
        if read_before is not None:
            by_feed: dict[str, list[str]] = {}
            for row in rows:
                if (row.get('published_at') or row['first_seen_at']) < read_before:
                    by_feed.setdefault(row['feed_url'], []).append(row['guid'])
            for feed_url, guids in by_feed.items():
                _mark_rss_read_by_guid(feed_url, guids, now)
    return len(rows)


def _mark_rss_read_by_guid(feed_url: str, guids: list[str], now: datetime) -> None:
    """Read markers for entries identified by guid — the ids were just assigned by
    the INSERT, so they are read back rather than round-tripped through Python."""
    stamp = now.isoformat(sep=' ', timespec='seconds')
    for i in range(0, len(guids), 500):
        chunk = guids[i : i + 500]
        placeholders = ','.join('?' for _ in chunk)
        tdb.db.execute_sql(
            'INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) '
            "SELECT 'rss', id, 0, ? FROM rss_entries WHERE feed_url = ? AND guid IN "
            f'({placeholders})',
            (stamp, feed_url, *chunk),
        )


def rss_entry_ids(feed_url: str, guids: list[str]) -> list[int]:
    """The surrogate ids behind a feed's guids, in insertion order.

    ``insert_rss_entries`` cannot return them — ``INSERT OR IGNORE`` reports no
    rowids — and the ingest hook needs them to index the new entries for search.
    """
    if not guids:
        return []
    ids: list[int] = []
    for i in range(0, len(guids), 500):
        chunk = guids[i : i + 500]
        rows = (
            RssEntry.select(RssEntry.id)
            .where((RssEntry.feed_url == feed_url) & (RssEntry.guid.in_(chunk)))
            .order_by(RssEntry.id)
        )
        ids.extend(row.id for row in rows)
    return ids


def rss_entry_count() -> int:
    return RssEntry.select().count()


def rss_feed_error_count() -> int:
    """Subscribed feeds whose last round failed — the "something is broken" number
    on status. Scoped to subscriptions on purpose: unsubscribing keeps the fetch
    state (see ``delete_rss_subscription``), and a stale error on a feed the reader
    dropped is not a problem they have."""
    cur = tdb.db.execute_sql(
        "SELECT COUNT(*) FROM rss_feeds f JOIN subscriptions s ON s.source = 'rss' AND s.channel_id = f.url "
        'WHERE f.error_count > 0'
    )
    return cur.fetchone()[0]


# --- rss summaries (condenser/summary.py) -------------------------------------

# "Waiting for a summary", as SQL. One copy, shared by the pipeline's candidate
# query and the status count, so the number the reader is shown and the work that
# gets done cannot drift apart.
#
# Three of the four conditions are about not spending: an **enabled** feed (pausing
# a feed stops it reaching the reader, so its backlog stops being something they
# might read), **unread** (an OPML import marks everything older than a week read —
# that backlog is archived, not offered), and a **length floor**. The floor here is
# on the raw HTML, which is a cheap upper bound on the text: a body shorter than the
# gate before stripping is certainly shorter after it. The exact test runs on the
# stripped text in ``summary.run_round``, which records its answer so a
# markup-heavy one-liner is only measured once.
_RSS_SUMMARY_FROM = """
    FROM rss_entries e
    JOIN subscriptions s ON s.source = 'rss' AND s.channel_id = e.feed_url AND s.enabled = 1
    LEFT JOIN read_items ri ON ri.source = 'rss' AND ri.ref1 = e.id AND ri.ref2 = 0
"""
# summary_model IS NULL covers both "never looked at" and, by its absence, every
# decided state: a written summary, and the `skip:short` sentinel.
_RSS_SUMMARY_WHERE = (
    'e.summary_model IS NULL AND e.summary_attempts < ? AND ri.ref1 IS NULL '
    'AND e.content IS NOT NULL AND LENGTH(e.content) > ?'
)


def rss_entries_needing_summary(limit: int, max_attempts: int, min_content_chars: int) -> list[dict]:
    """The next entries to summarize, newest first.

    Ordered by the *timeline's* position rather than by insertion, because a
    backlog drains over hours and the order decides what the reader finds
    summarized when they next open the app — which is the top of the list.
    """
    from .sources.rss import SORT_AT_SQL

    cur = tdb.db.execute_sql(
        f'SELECT e.id, e.title, e.content {_RSS_SUMMARY_FROM} WHERE {_RSS_SUMMARY_WHERE} '
        f'ORDER BY {SORT_AT_SQL} DESC, e.id DESC LIMIT ?',
        (max_attempts, min_content_chars, limit),
    )
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def rss_summary_counts(max_attempts: int, min_content_chars: int) -> dict[str, int]:
    """What ``/api/rss/status`` reports: the backlog, the spend, and the give-ups."""
    pending = tdb.db.execute_sql(
        f'SELECT COUNT(*) {_RSS_SUMMARY_FROM} WHERE {_RSS_SUMMARY_WHERE}', (max_attempts, min_content_chars)
    ).fetchone()[0]
    done = tdb.db.execute_sql('SELECT COUNT(*) FROM rss_entries WHERE summary IS NOT NULL').fetchone()[0]
    failed = tdb.db.execute_sql(
        'SELECT COUNT(*) FROM rss_entries WHERE summary IS NULL AND summary_attempts >= ?', (max_attempts,)
    ).fetchone()[0]
    return {'pending': pending, 'done': done, 'failed': failed}


def set_rss_summary(entry_id: int, summary: str, model: str) -> None:
    """Store a summary and what wrote it. The two are one fact — a summary whose
    provenance is unknown cannot be told from one written by a prompt we retired."""
    RssEntry.update(summary=summary, summary_model=model).where(RssEntry.id == entry_id).execute()


def set_rss_summary_decision(entry_id: int, decision: str) -> None:
    """Record a decision *not* to summarize (``summary.SKIP_SHORT``).

    ``summary`` stays NULL, so the card keeps rendering the feed's own text; only
    the pipeline is told to stop reconsidering this entry.
    """
    RssEntry.update(summary_model=decision).where(RssEntry.id == entry_id).execute()


def bump_rss_summary_attempts(entry_id: int) -> None:
    """Charge one failed attempt to this entry (``hn.bump_hn_preview_attempts``)."""
    RssEntry.update(summary_attempts=RssEntry.summary_attempts + 1).where(RssEntry.id == entry_id).execute()


# --- daily cleanup (condenser/cleanup.py) -------------------------------------


def _x_untouched(tweet_id_column: str) -> str:
    """The "the reader never did anything with this" test, as SQL.

    Four markers, all triple-keyed with ``ref2 = 0`` for X, so matching ``ref1``
    alone is both sufficient and index-friendly. Every one of them is a user
    asset or a user decision, and this schema has no foreign keys anywhere — so
    a missed exemption does not raise, it silently destroys something.
    """
    return ' '.join(
        f"AND NOT EXISTS (SELECT 1 FROM {table} m WHERE m.source = 'x' AND m.ref1 = {tweet_id_column})"
        for table in ('read_items', 'hidden_items', 'item_feedback', 'saved_items')
    )


# `first_seen_at`, not the timeline's sort key: the question is how long the row
# has sat in the reader's backlog, not what date the card shows. The two differ
# for a followed account, whose backfill can hand us months-old tweets -- sorting
# those into history is right, deleting them the next morning is not.
#
# The second clause keeps a row whose tweet the probe is *still pushing*
# (`fetched_at` is refreshed by every `upsert_x_tweet`). Without it, deleting the
# appearance only invites `insert_x_feed_items` to recreate it on the next push
# with a fresh `first_seen_at` -- i.e. a long-ignored tweet would resurface at the
# top of the unread list. Measured on production it costs nothing: at the 15-day
# default it spares 0 rows, and 1-3% at windows short enough to bite (the widest
# observed gap between the two timestamps is 11.9 days, on For You).
_DELETE_X_FEED_ITEMS = (
    'DELETE FROM x_feed_items WHERE first_seen_at < ? '
    'AND NOT EXISTS (SELECT 1 FROM x_tweets t WHERE t.id = x_feed_items.tweet_id AND t.fetched_at >= ?) '
    f'{_x_untouched("x_feed_items.tweet_id")}'
)

# `fetched_at` means *last* seen, not first archived -- `upsert_x_tweet` refreshes
# it on every re-push so metrics can move. Gating the body on it is deliberate
# rather than incidental: a tweet the probe still hands us is still live in some
# feed window, and reclaiming its body would only have it re-ingested. The clock
# on a body therefore starts when the probe stops seeing it, which is exactly
# when it becomes garbage.
_DELETE_X_TWEETS = (
    'DELETE FROM x_tweets WHERE fetched_at < ? '
    'AND NOT EXISTS (SELECT 1 FROM x_feed_items f WHERE f.tweet_id = x_tweets.id) '
    'AND NOT EXISTS (SELECT 1 FROM x_tweets q WHERE q.quote_of = x_tweets.id) '
    f'{_x_untouched("x_tweets.id")}'
)


def sweep_x_retention(feed_cutoff: datetime, embedding_cutoff: Optional[datetime]) -> dict[str, int]:
    """The X archive's daily prune, in one transaction. Returns rows per table.

    Reads backwards on purpose, so state it plainly: an **unread** old row is
    what gets deleted and a **read** one is kept forever, exactly like Telegram
    messages and HN stories never expire. This is not cache eviction — it
    reclaims a firehose backlog nobody will ever scroll back to (measured on
    production: 92% of archived tweets were never opened).

    Intentionally preserved, in the spirit of ``delete_channel_messages``:
    everything the reader read, hid, labeled or saved, plus every tweet body a
    surviving tweet still quotes. The labels are the verdict's training set and
    channels A and D re-read ``author_handle`` / ``text`` on *every* round, so a
    deleted labeled body would not error — it would quietly stop teaching.

    Step order matters: feed rows first, so the body sweep can ask the simple
    question "is anything still showing this?". The body sweep then repeats
    until it comes up empty, because one ``DELETE`` evaluates its ``WHERE``
    against the pre-statement state: in a chain where A quotes B quotes C, B
    still sees A and survives the pass that removes A. One pass a day would
    drain such a chain one link at a time — measured on a production snapshot,
    it left 17.5% of the deletable bodies behind. The loop terminates because a
    quote always points at an older tweet, so the graph is acyclic, and because
    every iteration but the last strictly shrinks the table.
    """
    stamp = feed_cutoff.strftime('%Y-%m-%d %H:%M:%S')
    counts = {
        'feed_items': 0,
        'tweets': 0,
        'embeddings_orphaned': 0,
        'embeddings_expired': 0,
        'attributes_orphaned': 0,
        'search_orphaned': 0,
    }
    with tdb.db.atomic():
        counts['feed_items'] = tdb.db.execute_sql(_DELETE_X_FEED_ITEMS, (stamp, stamp)).rowcount
        while True:
            removed = tdb.db.execute_sql(_DELETE_X_TWEETS, (stamp,)).rowcount
            if not removed:
                break
            counts['tweets'] += removed
        # An anti-join rather than the ids just deleted, so the sweep also heals
        # whatever went orphaned before this rule existed. Both tables are caches
        # keyed by tweet id (the `messages.is_filtered` contract) and neither can
        # be rebuilt once the text is gone. `x_vec_labeled` needs no equivalent:
        # it holds only labeled tweets, and those are exempt above.
        counts['embeddings_orphaned'] = tdb.db.execute_sql(
            'DELETE FROM x_embeddings WHERE tweet_id NOT IN (SELECT id FROM x_tweets)'
        ).rowcount
        counts['attributes_orphaned'] = tdb.db.execute_sql(
            'DELETE FROM x_attributes WHERE tweet_id NOT IN (SELECT id FROM x_tweets)'
        ).rowcount
        # Same anti-join, one table further out: search documents exist per *feed
        # appearance*, so this one keys off x_feed_items rather than x_tweets — a
        # body that survives as somebody's quote is no longer a timeline item.
        counts['search_orphaned'] = search.sweep_x_orphans()
        if embedding_cutoff is not None:
            # A living tweet's vector expires on its own, longer clock: it is read
            # once (at judge time) and re-derivable from the text that is still here.
            counts['embeddings_expired'] = prune_x_embeddings(embedding_cutoff, set(x_labeled_samples()))
    return counts


_DELETE_RSS_ENTRIES = 'DELETE FROM rss_entries WHERE first_seen_at < ? ' + ' '.join(
    f"AND NOT EXISTS (SELECT 1 FROM {table} m WHERE m.source = 'rss' AND m.ref1 = rss_entries.id)"
    for table in ('read_items', 'hidden_items', 'item_feedback', 'saved_items')
)


def sweep_rss_retention(cutoff: datetime) -> dict[str, int]:
    """Delete archived entries older than ``cutoff`` that the reader never touched.

    X's rule, unchanged in substance and stated the same way round: an **unread**
    old entry is deleted and a **read** one is kept forever. What is intentionally
    preserved is everything the reader read, hid, labeled or saved.

    Two consequences worth knowing rather than rediscovering. The clock is
    ``first_seen_at``, not the timeline's clamped sort key: the question is how long
    a row has sat in the backlog, and an archive-style feed hands us years-old
    entries that should sort into history without being deleted the next morning.
    And the unread window (plan §0.3) marks an import's back-catalogue *read* on
    arrival, so those rows are exempt and accumulate — accepted at plan time, since
    they are kilobytes of text each and ``/api/cleanup/status`` makes the total
    visible.

    No feed row is dropped: ``rss_feeds`` is per-feed fetch state (100 rows at the
    design target) and its validators are what make a re-subscribe resume.
    """
    counts = {'entries': 0, 'search_orphaned': 0}
    with tdb.db.atomic():
        counts['entries'] = tdb.db.execute_sql(_DELETE_RSS_ENTRIES, (cutoff.strftime('%Y-%m-%d %H:%M:%S'),)).rowcount
        # Anti-join rather than the ids just deleted, so the sweep also heals
        # documents orphaned before this rule existed (the X precedent).
        counts['search_orphaned'] = search.sweep_rss_orphans()
    return counts


def sqlite_freelist_ratio() -> float:
    """Fraction of the file's pages that VACUUM could hand back to the OS.

    Reads correctly through the WAL — verified, rather than assumed: a fresh
    connection sees the same number immediately after a delete, and a passive
    checkpoint does not change it by a single page.
    """
    pages = tdb.db.execute_sql('PRAGMA page_count').fetchone()[0]
    if not pages:
        return 0.0
    return tdb.db.execute_sql('PRAGMA freelist_count').fetchone()[0] / pages


def vacuum() -> None:
    """Rewrite the file to reclaim freed pages.

    Production runs ``auto_vacuum=0``, so nothing returns pages to the OS on its
    own and ``PRAGMA incremental_vacuum`` is unavailable without a full rewrite
    first. Takes an exclusive lock, and SQLite refuses outright to run it inside
    a transaction — so callers must be outside any ``atomic()`` block.
    """
    tdb.db.execute_sql('VACUUM')


# --- link preview cache -----------------------------------------------------


def get_cached_preview(url_key: str) -> Optional[LinkPreviewCache]:
    return LinkPreviewCache.get_or_none(LinkPreviewCache.url == url_key)


def upsert_preview(
    url_key: str,
    *,
    ok: bool,
    title: Optional[str] = None,
    description: Optional[str] = None,
    image: Optional[str] = None,
    site_name: Optional[str] = None,
    canonical_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Insert/replace a cached preview keyed by the normalized URL."""
    fields = {
        'ok': ok,
        'title': title,
        'description': description,
        'image': image,
        'site_name': site_name,
        'canonical_url': canonical_url,
        'error': error,
        'fetched_at': _now_naive(),
    }
    LinkPreviewCache.insert(url=url_key, **fields).on_conflict(
        conflict_target=[LinkPreviewCache.url],
        update={getattr(LinkPreviewCache, k): v for k, v in fields.items()},
    ).execute()
