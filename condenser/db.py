"""Condenser data layer (spec Part B).

Condenser shares telememo's single SQLite file. telememo tables (channels,
messages, comments) are owned by telememo's Peewee models and the ``is_filtered``
extension column; the app-state tables below are condenser's own, bound to the
same Peewee database object so everything lives on one connection.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from peewee import (
    SQL,
    AutoField,
    BareField,
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

from .items import ItemKey

# The condenser is_filtered overlay column declared on telememo's messages table.
MESSAGES_OPTIONAL_FIELDS = {
    'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}],
}

# Bumped when condenser's own table shapes change; recorded in app_meta on init so a
# future startup can detect an upgrade and run a migration. Telememo manages its own
# table migrations separately (init_db optional_fields / ALTER TABLE).
SCHEMA_VERSION = 4


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

    class Meta:
        table_name = 'hn_stories'
        indexes = ((('day', 'score'), False),)


CONDENSER_TABLES = [
    Subscription,
    KeywordFilter,
    ReadItem,
    SavedItem,
    TgSession,
    AppMeta,
    LinkPreviewCache,
    Device,
    HNStory,
]


def init_db(db_path: str) -> None:
    """Initialize the shared SQLite file: telememo tables (+ is_filtered) then condenser tables."""
    tdb.init_db(db_path, optional_fields=MESSAGES_OPTIONAL_FIELDS)
    _migrate_subscriptions_v3()
    tdb.db.create_tables(CONDENSER_TABLES)
    _migrate_read_saved_v4()
    _enable_wal(db_path)
    set_meta('schema_version', str(SCHEMA_VERSION))


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
    """Wipe a channel's cached messages, comments, and read markers; returns messages deleted.

    Saved records (``saved_items``) and keyword filters are intentionally preserved —
    they are user assets / config, not re-syncable source cache.
    """
    deleted = tdb.get_message_count(channel_id)
    with tdb.db.atomic():
        ReadItem.delete().where((ReadItem.source == 'telegram') & (ReadItem.ref1 == channel_id)).execute()
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


def mark_read_bulk(channel_id: Optional[int], before_date: Optional[str], source: Optional[str] = None) -> None:
    """Mark every subscribed, unfiltered item before a date (optionally one TG channel) as read.

    The aggregate form (no channel_id) covers every source: HN stories are included
    when an enabled HN subscription exists (all archived rows — hidden ranks don't
    affect visible counts and marking them keeps a later display-mode widening quiet).
    `source` narrows the sweep to one source (the source-scoped timeline views);
    `channel_id` already implies telegram.
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
        hn_where = ['h.is_dead = 0']
        hn_params: list = []
        if before_date:
            hn_where.append('h.day < ?')
            hn_params.append(before_date)
        tdb.db.execute_sql(
            'INSERT OR IGNORE INTO read_items (source, ref1, ref2, read_at) '
            "SELECT 'hn', h.id, 0, ? FROM hn_stories h WHERE " + ' AND '.join(hn_where),
            (_now().isoformat(sep=' '), *hn_params),
        )


def is_item_read(source: str, ref1: int, ref2: int = 0) -> bool:
    return (
        ReadItem.select()
        .where((ReadItem.source == source) & (ReadItem.ref1 == ref1) & (ReadItem.ref2 == ref2))
        .exists()
    )


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
    HNStory.update(is_dead=True).where(HNStory.id == story_id).execute()


def hn_stories_to_refresh(first_seen_after: datetime) -> list[HNStory]:
    """Live stories still inside the snapshot-refresh window."""
    return list(
        HNStory.select().where(
            (HNStory.first_seen_at >= first_seen_after) & (HNStory.is_dead == False)  # noqa: E712
        )
    )


def hn_story_counts(today: str) -> tuple[int, int]:
    """(total archived stories, stories first seen on ``today``)."""
    total = HNStory.select().count()
    today_count = HNStory.select().where(HNStory.day == today).count()
    return total, today_count


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
